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

from sklearn import linear_model
import matplotlib.pyplot as plt
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
    data = {}

    # outdir
    outdir = os.path.join(here, "img")
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    # Plot runtime against each of these
    columns = ["mem_mean", "mem_max", "mem_min"]

    # Markdown file to preview all
    content = "# Linear Models for Package Build Times\n\n"
    for package in packages:
        subset = success[success.pkg_name == package]
        df = subset[columns]
        df.index = subset.job_id

        if df.shape[0] < 100:
            continue

        # We will save metrics / scores for each memory attribute
        data[package] = {}

        # First just plot memory against duration
        fig, axes = plt.subplots(len(columns), figsize=(12, 8))
        fig.suptitle(f"Memory vs. build time for {package} with {df.shape[0]} builds")
        fig.tight_layout(pad=3.0)
        for i, column in enumerate(columns):
            memory_df = df[column]
            times = subset.duration.tolist()
            # The -1 is the new axis
            shaped = memory_df.values.reshape(df.shape[0], -1)
            if not colors:
                colors = list(mcolors.CSS4_COLORS)
            axes[i].scatter(shaped, times, color=colors.pop(0))
            axes[i].set_title(f"Using Feature '{column}'")
            axes[i].set_xlabel(f"Memory feature {column}", fontsize=10)
            axes[i].set_ylabel("Build time (seconds)", fontsize=10)

        path = os.path.join(here, "img", f"{package}-build-times-vs-memory.png")
        plt.savefig(path)
        relpath = os.path.basename(path)
        content += f"\n## {package}\n\n![img/{relpath}](img/{relpath})\n"
        plt.close()

        fig, axes = plt.subplots(len(columns), figsize=(12, 8))
        fig.suptitle(
            f"Linear models to predict build time for {package} with {df.shape[0]} builds"
        )
        fig.tight_layout(pad=3.0)
        for i, column in enumerate(columns):
            memory_df = df[column]
            regr = linear_model.LinearRegression()
            y = subset.duration.tolist()
            # The -1 is the new axis
            shaped = memory_df.values.reshape(df.shape[0], -1)
            regr.fit(shaped, y)
            pred = regr.predict(shaped)

            # Cross validated scores
            # scores = cross_val_score(regr, df.values, y, scoring="r2")
            scores = model_selection.cross_val_score(
                regr, shaped, y, scoring="neg_mean_squared_error", cv=memory_df.shape[0]
            )
            score = numpy.sqrt(-1 * numpy.mean(scores)) / numpy.mean(y)
            if not colors:
                colors = list(mcolors.CSS4_COLORS)

            data[package][column] = {"standardized_mse": score}
            axes[i].scatter(pred, y, color=colors.pop(0))
            axes[i].set_title(f"Using Feature '{column}'")
            axes[i].set_xlabel("Actual build time (seconds)", fontsize=10)
            axes[i].set_ylabel("Predicted build time (seconds)", fontsize=10)

        path = os.path.join(here, "img", f"{package}-build-time-linear-regression.png")
        plt.savefig(path)
        relpath = os.path.basename(path)
        content += f"\n### Linear Models\n![img/{relpath}](img/{relpath})\n"
        plt.close()

    write_file(content, "regression-model.md")
    write_json(data, "package-scores.json")


if __name__ == "__main__":
    main()
