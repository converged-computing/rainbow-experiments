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

here = os.path.abspath(os.path.dirname(__file__))

# Nice selection of colors for cluster names (rainbow...)
import matplotlib.colors as mcolors


db_file = os.path.join(here, "raw", "db")
if not os.path.exists(db_file):
    raise ValueError(f"Database {db_file} does not exist.")

labels_file = os.path.join(here, "raw", "query_result_2024-04-02T02_48_24.138231Z.csv")
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
    data = {}
    for package in packages:
        subset = success[success.pkg_name == package]
        data[package] = {
            "build_count": subset.shape[0],
            "compilers": list(subset.compiler_name.unique()),
            "job_size": list(subset.job_size.unique()),
            "arch": list(subset.arch.unique()),
            "compiler_versions": list(subset.compiler_version.unique()),
            "durations": {
                "min": subset.duration.min(),
                "max": subset.duration.max(),
                "mean": success.duration.mean(),
            },
        }

    write_json(data, "package-summaries.json")

    # Keep these columns as is
    columns = ["cpu_mean", "cpu_max", "cpu_min", "mem_mean", "mem_max", "mem_min"]

    # Markdown file to preview all
    content = "# Linear Models for Package Build Times\n\n"
    log_content = "# Log Linear Models for Package Build Times\n\n"
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

        regr = linear_model.LinearRegression()
        y = subset.duration.tolist()
        regr.fit(df.values, y)
        pred = regr.predict(df.values)

        plt.scatter(pred, y, color=colors.pop(0))
        plt.title(f"Linear model: build times for {package} with {df.shape[0]} builds")
        plt.xlabel("Actual build time (seconds)", fontsize=14)
        plt.ylabel("Predicted build time (seconds)", fontsize=14)
        path = os.path.join(here, "img", f"{package}-build-time-linear-regression.png")
        plt.savefig(path)
        relpath = os.path.basename(path)
        content += f"\n## {package}\n\n![img/{relpath}](img/{relpath})\n"
        plt.close()

        # Do the same, but take log
        regr = linear_model.LinearRegression()

        # We shouldn't have any zeros
        y = numpy.log(subset.duration.tolist())
        regr.fit(df.values, y)
        pred = [numpy.exp(x) for x in regr.predict(df.values)]

        plt.scatter(pred, subset.duration.tolist(), color=colors.pop(0))
        plt.title(
            f"Log linear model: build times for {package} with {df.shape[0]} builds"
        )
        plt.xlabel("Actual build time (seconds)", fontsize=14)
        plt.ylabel("Predicted build time (seconds)", fontsize=14)
        path = os.path.join(
            here, "img", f"{package}-build-time-log-linear-regression.png"
        )
        plt.savefig(path)
        relpath = os.path.basename(path)
        log_content += f"\n## {package}\n\n![img/{relpath}](img/{relpath})\n"
        plt.close()

    write_file(content, "regression-model.md")
    write_file(log_content, "regression-log-model.md")


if __name__ == "__main__":
    main()
