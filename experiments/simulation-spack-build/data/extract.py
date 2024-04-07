#!/usr/bin/env python3

import dataset

# import pickle
import os

# from glob import glob
import pandas
import yaml
import json
import random
import numpy
import joblib
from scipy.stats import pearsonr
from jinja2 import Template
from sklearn import linear_model
import matplotlib.pyplot as plt
from sklearn import model_selection
from sklearn import neighbors

here = os.path.abspath(os.path.dirname(__file__))
root = os.path.dirname(here)

# Nice selection of colors for cluster names (rainbow...)
import matplotlib.colors as mcolors

db_file = os.path.join(root, "data", "raw", "db")
if not os.path.exists(db_file):
    raise ValueError(f"Database {db_file} does not exist.")

labels_file = os.path.join(
    root, "data", "raw", "query_result_2024-04-02T02_48_24.138231Z.csv"
)
if not os.path.exists(labels_file):
    raise ValueError(f"Labels {labels_file} does not exist.")

# cluster template
cluster_template = os.path.join(here, "templates", "cluster-nodes.json")
subsystem_template = os.path.join(here, "templates", "subsystem.json")


def load_yaml(filename):
    with open(filename, "r") as file:
        data = yaml.safe_load(file)
    return data


def get_db(filename: str) -> dataset.Database:
    return dataset.connect(
        url=f"sqlite:///{filename}", on_connect_statements=["PRAGMA foreign_keys = ON;"]
    )


def write_file(content, filename):
    """
    Write json to file
    """
    with open(filename, "w") as outfile:
        outfile.write(content)


def write_yaml(obj, filename):
    with open(filename, "w") as file:
        yaml.dump(obj, file)


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

    def __init__(self, index, typ, type_count, value):
        self.type = typ
        self.index = index
        self.type_count = type_count
        self.value = value


def main():
    db = get_db(db_file)

    # Read in labels
    builds = pandas.DataFrame(db["builds"])
    labels = pandas.read_csv(labels_file)

    colors = list(mcolors.CSS4_COLORS)
    random.shuffle(colors)

    # Filter to successful builds, and try to create distribution of build durations
    success_labels = labels[labels.status == "success"]
    success = builds[builds.job_id.isin(success_labels.job_id)]
    packages = success.pkg_name.unique()

    # outdir
    outdir = os.path.join(here, "img")
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    models_dir = os.path.join(here, "models", "knn")
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)

    # Use mean memory for now
    columns = ["mem_mean"]

    # We already looking at scoring, etc. for models.
    # We are just going to save the intercept and slope for each
    # This will allow us to take some memory value for a cluster
    models = {}

    # Markdown file to preview all
    for package in packages:
        subset = success[success.pkg_name == package]
        df = subset[columns]
        df.index = subset.job_id
        if df.shape[0] < 100:
            continue

        # Build a linear model just with mean memory
        memory_df = df[columns[0]]
        regr = linear_model.LinearRegression(fit_intercept=False)
        y = subset.duration.tolist()
        # The -1 is the new axis
        shaped = memory_df.values.reshape(df.shape[0], -1)
        regr.fit(shaped, y)
        pred = regr.predict(shaped)

        # Calulate basic correlation between mean mem and duration -
        # we will use this to filter down models (don't keep < 0.5) "noble" correlation
        # corr = pearsonr(pred, y)
        # if corr.statistic < 0.50:
        #    continue
        # print(f"Correlation for {package} is {corr}")

        # I think knn will be better to give an estimate for a point.
        # But we will need to save the model
        clf = neighbors.KNeighborsRegressor()
        clf.fit(shaped, y)
        model_outfile = os.path.join(models_dir, f"{package}.joblib")
        joblib.dump(clf, model_outfile)

        # For the optimal runtime (duration) calculate from the top 10% of runtimes
        # for the package
        memory_best_runtime = subset[
            subset.duration == subset.duration.min()
        ].mem_mean.tolist()[0]
        top_ten_percent = subset.sort_values("duration")
        idx = top_ten_percent.index[0 : int(top_ten_percent.shape[0] * 0.1)]
        top_ten_percent = top_ten_percent.loc[idx, :]
        top_ten_percent = subset[0 : int(subset.shape[0] * 0.1)]
        memory_top_ten_percent_runtime = top_ten_percent.mem_mean.mean()
        models[package] = {
            #            "corr": corr.statistic,
            #            "corr_p_value": corr.pvalue,
            #            "slope": regr.coef_[0],
            "memory_global_best_runtime": memory_best_runtime,
            "memory_of_top_ten_percent_runtime": memory_top_ten_percent_runtime,
        }
    write_json(models, "linear-model-params.json")

    # Filter down to packages we have >100 for
    filt = success[success.pkg_name.isin(list(models.keys()))]

    # We first need the entire range of memories across actual builds
    # This will determine the range that we can choose from to generate clusters
    min_memory = filt[filt.mem_min != 0].mem_min.min()
    max_memory = filt.mem_max.max()

    # We also need the other unique values to select from for clusterf features
    arches = filt.arch.unique().tolist()

    compilers = filt.compiler_name.unique().tolist()

    # Version lookup by compiler
    compiler_versions = {}
    for compiler in compilers:
        compiler_versions[compiler] = (
            filt[filt.compiler_name == compiler].compiler_version.unique().tolist()
        )

    # Save unique features
    features = {
        "compiler": compilers,
        "compiler_versions": compiler_versions,
        "arch": arches,
        "min_memory": min_memory,
        "max_memory": max_memory,
    }
    write_json(features, "unique-features.json")

    # Now let's generate 100 clusters
    clusters = {}

    # We need to get a cost for each one, based on memory
    # This is janky, but will do
    distance = max_memory - min_memory
    middle = distance / 2
    first_quarter = 0.25 * max_memory
    third_quarter = 0.75 * max_memory

    # Generate 100 clusters (could eventually do more)
    for i in range(100):
        cluster_name = colors.pop(0)

        # Select the memory value for the cluster
        # We will first use this as a min requirement, then loosen that a bit
        memory = random.randint(min_memory, max_memory)

        # This is cost per node hour
        # The rate of increase isn't consistent because I don't think cloud makes sense either
        if memory < first_quarter:
            cost = 0.8
        elif memory < middle:
            cost = 1.6
        elif memory < third_quarter:
            cost = 3.2
        else:
            cost = 4.2
        compiler = random.choice(compilers)
        compiler_version = random.choice(compiler_versions[compiler])
        clusters[cluster_name] = {
            "memory": memory,
            "cost_per_node_hour": cost,
            "arch": random.choice(arches),
            "compiler": compiler,
            "compiler_version": compiler_version,
        }

    write_json(clusters, os.path.join(here, "cluster-features.json"))

    # Generate the jobspecs from our successful builds
    # These are partal jobspecs - just what we need for resources and attributes
    jobspec_outdir = os.path.join(here, "jobspecs")
    if not os.path.exists(jobspec_outdir):
        os.makedirs(jobspec_outdir)

    # Fields to keep for each resource group
    groups = {
        "memory": ["mem_min", "mem_max", "mem_mean"],
        "arch": ["arch"],
        # Let's assume newer compilers can handle older builds
        # But builds using old compilers won't work with new ones
        "compiler": ["compiler_name", "compiler_version"],
    }

    # Create a jobspec for each of our jobspecs
    # We need to match this to a version range
    count = 0
    jobspecs = []
    total = filt.shape[0]
    for row in filt.iterrows():
        print(f"Parsing spack build {count}/{total}", end="\r")

        # This is the package to build, how we choose the model
        js = {"name": row[1].id, "resources": {}, "attributes": {}}
        for group_name, feats in groups.items():
            resources = {}
            for field in feats:
                if field in row[1].index:
                    resources[field] = row[1][field]
            js["resources"][group_name] = resources

        # Ensure we provide the slope and memory metadata
        js["attributes"]["duration"] = row[1].duration
        js["attributes"]["memory_global_best_runtime"] = float(
            models[row[1].pkg_name]["memory_global_best_runtime"]
        )
        js["attributes"]["memory_of_top_ten_percent_runtime"] = float(
            models[row[1].pkg_name]["memory_of_top_ten_percent_runtime"]
        )

        js["package"] = row[1].pkg_name
        jobspecs.append(js)

        # Save every 1000
        count += 1
        if len(jobspecs) >= 1000:
            outfile = os.path.join(
                jobspec_outdir, os.path.join(jobspec_outdir, f"jobspecs-{count}.yaml")
            )
            write_yaml(jobspecs, outfile)
            jobspecs = []

    # One final save
    outfile = os.path.join(
        jobspec_outdir, os.path.join(jobspec_outdir, f"jobspecs-{count}.yaml")
    )
    write_yaml(jobspecs, outfile)

    # Next, generate the clusters themselves, and subsystems
    clusters_dir = os.path.join(here, "clusters")
    if not os.path.exists(clusters_dir):
        os.makedirs(clusters_dir)

    # Now generate the cluster JGF
    for color in clusters:
        render = template.render(name=f"cluster-{color}")
        cluster_outdir = os.path.join(clusters_dir, f"cluster-{color}")
        if not os.path.exists(cluster_outdir):
            os.makedirs(cluster_outdir)
        outfile = os.path.join(cluster_outdir, "nodes.json")
        write_file(render, outfile)

    # SUBSYSTEMS ----------------------
    subsystem_names = ["memory", "arch", "compiler"]
    for cluster, features in clusters.items():
        cluster_outdir = os.path.join(clusters_dir, f"cluster-{cluster}")

        # Assemble package "subsystems"
        for subsystem in subsystem_names:
            nodes = [Node(1, subsystem, 0, features[subsystem])]
            if subsystem == "compiler":
                nodes.append(
                    Node(2, "compiler-version", 0, features["compiler_version"])
                )
            render = subsys_template.render(nodes=nodes, name=subsystem)
            outfile = os.path.join(cluster_outdir, f"{subsystem}-subsystem.json")
            write_file(render, outfile)


if __name__ == "__main__":
    main()
