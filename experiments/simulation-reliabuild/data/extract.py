#!/usr/bin/env python3

import pickle
import os
from glob import glob
import pandas
import shutil
import numpy
import joblib
import yaml
import json
import copy
import random
from jinja2 import Template

here = os.path.abspath(os.path.dirname(__file__))

# Nice selection of colors for cluster names (rainbow...)
import matplotlib.colors as mcolors

colors = list(mcolors.CSS4_COLORS)
random.shuffle(colors)

# cluster template
cluster_template = os.path.join(here, "templates", "cluster-nodes.json")
subsystem_template = os.path.join(here, "templates", "subsystem.json")

# We need to encode categorical variables as numerical
from sklearn.preprocessing import OrdinalEncoder
from sklearn.naive_bayes import CategoricalNB
from sklearn.model_selection import KFold


def read_pickle(path):
    with open(path, "rb") as f:
        content = pickle.load(f)
    return content


def load_yaml(filename):
    with open(filename, "r") as file:
        data = yaml.safe_load(file)
    return data


def write_file(content, filename):
    """
    Write json to file
    """
    with open(filename, "w") as outfile:
        outfile.write(content)


def write_json(obj, filename):
    with open(filename, "w") as fd:
        fd.write(json.dumps(obj, indent=4))


def read_json(filename):
    with open(filename, "r") as fd:
        content = json.loads(fd.read())
    return content


def read_file(filename):
    """
    Read content from file
    """
    with open(filename, "r") as fd:
        content = fd.read()
    return content


template = Template(read_file(cluster_template))
subsys_template = Template(read_file(subsystem_template))


class Node:
    """
    A node! This could (should) be a dataclass

    This is used for subsystem definitions (nodes and edges)
    """

    def __init__(self, index, typ, type_count):
        self.type = typ
        self.index = index
        self.type_count = type_count


def main():
    files = glob(os.path.join(here, "dinos-runs", "*", "*.pkl"))

    # This is the complete list of specs, working and errored
    # We care about both! Note that heffe seems to be entirely missing?
    specs = glob(os.path.join(here, "specs", "*", "*.yaml"))

    # Keep all scores
    all_scores = {}

    # Create a lookup based on hash
    # Note that a spec can appear twice if it has failures/successes
    lookup = {}
    for spec in specs:
        digest = os.path.basename(spec).replace(".yaml", "")
        if digest not in lookup:
            lookup[digest] = spec

    # We want to capture the unique features and values ACROSS packages!
    cluster_features = {}

    # Create a directory of parsed data
    compats_outdir = os.path.join(here, "prepared", "compats")
    outdir = os.path.join(here, "prepared", "labels")
    specs_outdir = os.path.join(here, "prepared", "specs")
    models_outdir = os.path.join(here, "prepared", "models")
    for dirname in [outdir, specs_outdir, compats_outdir, models_outdir]:
        if not os.path.exists(dirname):
            os.makedirs(dirname)

    scores_file = os.path.join(here, "10-fold-scores.json")
    if os.path.exists(scores_file):
        all_scores = read_json(scores_file)

    for filename in files:
        # The pkl file is in a directory named by the package
        package = os.path.basename(os.path.dirname(filename))

        model_outfile = os.path.join(models_outdir, f"{package}.joblib")
        # if os.path.exists(model_outfile):
        #    print(f"Model for {package} already exists, skipping.")
        #    continue

        # Note this is a pandas data frame
        data = pandas.read_pickle(filename)

        # Split apart success and failure. We can keep all successes
        success = data[data.Status == "SUCCESS"]
        success = success[success.name == package]
        failure = data[data.Status == "FAILED"]

        # The field "Root Failed" indicates that a root package failed, so we need to filter to that
        # along with the package name we found. These two combined means "Package X failed during its main
        # build." and that is the subset we want.
        subset = failure[failure.Reason == "Root Failure"]
        subset = subset[subset.name == package]

        # Combine back into one
        df = pandas.concat([success, subset])
        print(f"Package {package} has {df.shape[0]} records of failure or success")

        # Now we need to filter down the specs to those that we have.
        package_specs = set()
        to_remove = set()
        for digest in df.index:
            # I remember from earlier that we were missing a handful
            if digest not in lookup:
                to_remove.add(digest)
                continue
            spec_path = lookup[digest]
            new_path = os.path.join(specs_outdir, f"{digest}.yaml")
            if not os.path.exists(new_path):
                shutil.copyfile(spec_path, new_path)
            package_specs.add(new_path)

        # Remove small set of missing
        if to_remove:
            df = df.drop(list(to_remove))

        if (df.shape[0] == 0) or df.shape[0] < 5:
            print(
                f"Warning: package {package} is missing / does not have enough specs."
            )
            continue

        # Save the data frame to file
        df.to_csv(os.path.join(outdir, f"{package}.csv"))

        print(f"Creating data frame of compatibility information for package {package}")

        # Create unique features for each spec
        package_features = {}
        unique_features = set()
        for specfile in package_specs:
            spec = load_yaml(specfile)
            digest = os.path.basename(specfile).replace(".yaml", "")
            feats = parse_spec_row(spec)
            for k in feats:
                unique_features.add(k)
            package_features[digest] = feats

        # Now create a data frame from them!
        # For each spec, load into feature matrix and get compatibility metadata
        # for the spec and package. This means we have one compatibility matrix
        # per spack package, each with the complete set of specs and features
        compats = pandas.DataFrame(index=df.index, columns=list(unique_features))
        for digest, package_feat in package_features.items():
            values = list(package_feat.values())
            keys = list(package_feat.keys())
            compats.loc[digest, keys] = values

        # Filter out features that are uniform across specs
        to_remove = set()
        for column in compats.columns:
            uniques = set([x for x in compats[column].tolist() if not pandas.isna(x)])
            if len(uniques) <= 1:
                to_remove.add(column)

        # From this we learn most of the unique-ness comes from the package versions
        compats = compats.drop(list(to_remove), axis=1)
        compats = compats.fillna("absent")
        compats.to_csv(os.path.join(compats_outdir, f"{package}.csv"))
        enc = OrdinalEncoder()
        enc.fit(compats)

        # Add to unique features
        for column in compats.columns:
            if column not in cluster_features:
                cluster_features[column] = set()
            for value in compats[column].unique():
                cluster_features[column].add(value)

        # Now create the features in ordinal
        compats_ordinal = enc.transform(compats)
        ord_df = pandas.DataFrame(compats_ordinal)
        ord_df.index = compats.index
        ord_df.columns = compats.columns
        ord_df.to_csv(os.path.join(compats_outdir, f"{package}-ordinal.csv"))

        # Prepare the vector of Y, SUCCESS (1) or failure (0)
        predict = df.loc[compats.index].Status.tolist()

        def get_binary_outcome(x):
            if x == "SUCCESS":
                return 1
            return 0

        Y = [get_binary_outcome(x) for x in predict]

        # Note that this gives the probabilty of each class
        # print(clf.predict_log_proba(compats_ordinal[0:1]))
        # [[0.00437222 0.99562778]]
        # And the greater one wins
        # print(clf.predict(compats_ordinal[0:1]))
        # [1]

        # Avoid weird data type issues
        Y = numpy.array(Y)

        # but we need to do cross validation to validate
        print(f"Scoring package {package}")

        # If it's too small to split, just run once. Yeah bad practice.
        try:
            all_scores[package] = run_cross_validation(compats_ordinal, Y)
        except:
            all_scores[package] = run_score(compats_ordinal, Y)

        # Build and save the final model
        clf = CategoricalNB()
        clf.fit(compats_ordinal, Y)
        joblib.dump(clf, model_outfile)

        # Save scores as we go
        write_json(all_scores, scores_file)

    # Save cluster features, convert to list
    for k, v in cluster_features.items():
        cluster_features[k] = list(v)
    write_json(cluster_features, os.path.join(here, "cluster-features.json"))

    # There are too many sets to make every cluster!
    # https://en.wikipedia.org/wiki/Latin_hypercube_sampling
    # Let's create 1000 clusters, with a random sample from each feature set
    # We will sample without replacement (until we run out) and then start again
    select_from = copy.deepcopy(cluster_features)

    # Create clusters data frame! This will have clusters in the index, features in the column
    clusters = pandas.DataFrame(columns=list(cluster_features))

    # The colors palette has 149 colors, so multiply by 7
    colorset = (
        [f"{c}-circle" for c in colors]
        + [f"{c}-square" for c in colors]
        + [f"{c}-triangle" for c in colors]
        + [f"{c}-rectangle" for c in colors]
        + [f"{c}-rhombus" for c in colors]
        + [f"{c}-star" for c in colors]
        + [f"{c}-heart" for c in colors]
        + [f"{c}-kite" for c in colors]
    )
    random.shuffle(colorset)

    # Generate 1000 clusters!
    for i in range(1000):
        cluster_name = colorset.pop(0)

        # Randomly select a value for each feature
        row = []
        for column in clusters.columns:
            # If we selected them all, restore!
            if not select_from[column]:
                select_from[column] = copy.deepcopy(cluster_features[column])

            random.shuffle(select_from[column])
            row.append(select_from[column].pop(0))

        clusters.loc[cluster_name, :] = row

    # Save clusters to file
    clusters.to_csv(os.path.join(here, "clusters.csv"))

    # We don't need to pre-calculate scores because for each cluster
    # We can generate the probability on the fly by:
    # 1. filtering down to the set of features that the jobspec has
    # 2. using those features to get P(SUCCESS|features) for the package model

    # Next, generate the clusters themselves, and subsystems
    clusters_dir = os.path.join(here, "clusters")
    if not os.path.exists(clusters_dir):
        os.makedirs(clusters_dir)

    # Now generate the cluster JGH
    for color in clusters.index:
        render = template.render(name=f"cluster-{color}")
        cluster_outdir = os.path.join(clusters_dir, f"cluster-{color}")
        if not os.path.exists(cluster_outdir):
            os.makedirs(cluster_outdir)
        outfile = os.path.join(cluster_outdir, "nodes.json")
        write_file(render, outfile)

    # SUBSYSTEMS ----------------------
    # Generate package dependency subsystems for each cluster
    for row in clusters.iterrows():
        # This is a pretty limited set, so each cluster
        # in practice has just one subsystem attribute
        features = list(row[1].index)
        values = list(row[1].values)

        cluster_outdir = os.path.join(clusters_dir, f"cluster-{row[0]}")

        # Assemble package "subsystems"
        subsystems = {}
        for i, feature in enumerate(features):
            # We treat the package as the subsystem
            subsystem = feature.split("-")[0]
            if subsystem not in subsystems:
                subsystems[subsystem] = {}

            # just include the entire feature
            subsystems[subsystem][feature] = values[i]

        # Now generate nodes for each
        for subsystem, features in subsystems.items():
            # Index 0 is the subsystem node
            nodes = []
            count = 1
            for key, value in features.items():
                # The type is the feature
                nodes.append(Node(count, f"{key}={value}", count - 1))
                count += 1

            render = subsys_template.render(nodes=nodes, name=subsystem)
            outfile = os.path.join(cluster_outdir, f"{subsystem}-subsystem.json")
            write_file(render, outfile)


def run_cross_validation(compats_ordinal, Y, splits=10):
    """
    Run K fold cross validation
    """
    scores = []
    kFold = KFold(n_splits=splits, shuffle=True)
    for train_index, test_index in kFold.split(compats_ordinal):
        X_train = compats_ordinal[train_index]
        X_test = compats_ordinal[test_index]
        y_train = Y[train_index]
        y_test = Y[test_index]
        clf = CategoricalNB()
        clf.fit(X_train, y_train)
        scores.append(clf.score(X_test, y_test))
    return {"scores": scores, "mean_score": numpy.mean(scores), "splits": splits}


def run_score(compats_ordinal, Y):
    """
    Run K fold cross validation
    """
    clf = CategoricalNB()
    clf.fit(compats_ordinal, Y)
    score = clf.score(compats_ordinal, Y)
    return {"score": score, "splits": 1}


def parse_spec_row(spec):
    """
    Parse main package features from a spack spec
    """
    feats = {}
    for spec in spec["spec"]["nodes"]:
        # This is the main spec
        name = spec["name"]
        attrs = {
            "version": spec["version"],
            "platform": spec["arch"]["platform"],
            "platform_os": spec["arch"]["platform_os"],
            "target": spec["arch"]["target"]["name"],
            "vendor": spec["arch"]["target"]["vendor"],
            "generation": spec["arch"]["target"]["generation"],
            "compiler": spec["compiler"]["name"],
            "compiler_version": spec["compiler"]["version"],
        }
        for param_name, param_value in spec["parameters"].items():
            attrs[param_name] = True
        features = spec["arch"]["target"]["features"]
        features.sort()
        attrs["features"] = ",".join(features)
        feats.update({f"{name}-{x}": feat for x, feat in attrs.items()})
    return feats


if __name__ == "__main__":
    main()
