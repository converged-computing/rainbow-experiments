#!/usr/bin/env python3

import dataset

import os

import pandas
import yaml
import json

here = os.path.abspath(os.path.dirname(__file__))
root = os.path.dirname(here)

db_file = os.path.join(root, "data", "raw", "db")
if not os.path.exists(db_file):
    raise ValueError(f"Database {db_file} does not exist.")

labels_file = os.path.join(
    root, "data", "raw", "query_result_2024-04-02T02_48_24.138231Z.csv"
)
if not os.path.exists(labels_file):
    raise ValueError(f"Labels {labels_file} does not exist.")


def load_yaml(filename):
    with open(filename, "r") as file:
        data = yaml.safe_load(file)
    return data


def get_db(filename: str) -> dataset.Database:
    return dataset.connect(
        url=f"sqlite:///{filename}", on_connect_statements=["PRAGMA foreign_keys = ON;"]
    )


def main():
    db = get_db(db_file)

    # Read in labels
    builds = pandas.DataFrame(db["builds"])
    labels = pandas.read_csv(labels_file)

    # Filter to successful builds, and try to create distribution of build durations
    success_labels = labels[labels.status == "success"]
    success = builds[builds.job_id.isin(success_labels.job_id)]
    packages = success.pkg_name.unique()

    print(f"Total builds {builds.shape[0]}")
    print(f"Successful builds {success.shape[0]}")

    # Get package counts
    counts = {}

    # Markdown file to preview all
    for package in packages:
        subset = success[success.pkg_name == package]
        if subset.shape[0] >= 100:
            counts[package] = subset.shape[0]

    print(json.dumps(counts, indent=4))
    print(f"Filtered packages > 100: {len(counts)}")

    counts = {
        k: v for k, v in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    }
    df = pandas.DataFrame(columns=["package", "builds"])
    idx = 0
    for package, count in counts.items():
        df.loc[idx] = [package, count]
        idx += 1
    df.to_csv(os.path.join(here, "package-counts-greater-100.csv"))


if __name__ == "__main__":
    main()
