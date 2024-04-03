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
from jinja2 import Template

from sklearn import linear_model
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder
from sklearn import model_selection


here = os.path.abspath(os.path.dirname(__file__))
root = os.path.dirname(here)

# Nice selection of colors for cluster names (rainbow...)
import matplotlib.colors as mcolors


db_file = os.path.join(root, "raw", "db")
if not os.path.exists(db_file):
    raise ValueError(f"Database {db_file} does not exist.")

labels_file = os.path.join(root, "raw", "query_result_2024-04-02T02_48_24.138231Z.csv")
if not os.path.exists(labels_file):
    raise ValueError(f"Labels {labels_file} does not exist.")

# cluster template
cluster_template = os.path.join(root, "templates", "cluster-nodes.json")
subsystem_template = os.path.join(root, "templates", "subsystem.json")


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

    # Keep these columns as is
    columns = ["cpu_mean", "cpu_max", "cpu_min", "mem_mean", "mem_max", "mem_min"]

    # Let's save CV scores, alphas, and feature weights
    data = {}

    # Markdown file to preview all
    content = "# Lasso Regression Models for Package Build Times\n\n"
    for package in packages:
        subset = success[success.pkg_name == package]

        df = subset[columns]
        df.index = subset.job_id

        if df.shape[0] < 100:
            continue

        if not colors:
            colors = list(mcolors.CSS4_COLORS)

        # Let's try a linear model that predicts build time from features
        encoder_one_hot = OneHotEncoder(sparse_output=False)
        for column in [
            "job_size",
            "compiler_name",
            "compiler_version",
            "arch",
            "pkg_version",
        ]:
            encoded_x = pandas.DataFrame(
                encoder_one_hot.fit_transform(subset[[column]])
            )
            encoded_x.columns = [
                f"{column}_{x}" for x in list(encoder_one_hot.categories_[0])
            ]
            encoded_x.index = df.index
            df = pandas.merge(df, encoded_x, right_index=True, left_index=True)

        # Note that this cross validation is for alpha, not for assessing model
        # We are going to first do all features, then again with just
        # features that are important. I want to see that alpha goes down
        clf = linear_model.LassoCV(cv=10)
        y = subset.duration.tolist()
        clf.fit(df.values, y)
        scores = model_selection.cross_val_score(
            clf, df.values, y, scoring="neg_mean_squared_error", cv=df.shape[0]
        )

        # https://en.wikipedia.org/wiki/Coefficient_of_variation
        score = numpy.sqrt(-1 * numpy.mean(scores)) / numpy.mean(y)
        print(f"{package}: pre-selection {score}, standardized-mse: {score}")
        weights = {}
        selected_features = list(df.columns[clf.coef_ != 0])
        for i, value in enumerate(clf.coef_):
            weights[df.columns[i]] = value
        data[package] = {
            "pre-selection": {
                "features_with_weights": weights,
                "standardized_mse": score,
                "selected_features": selected_features,
            }
        }

        # print(json.dumps(data[package]))
        print(selected_features)

    write_json(data, "loo-cv.json")


if __name__ == "__main__":
    main()
