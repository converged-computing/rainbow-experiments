#!/usr/bin/env python3

import argparse
import json
import os

from itertools import product, combinations

import matplotlib.colors as mcolors
from jinja2 import Template

import pandas
import copy
import yaml
import re
import random

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)

# cluster template
cluster_template = os.path.join(here, "templates", "cluster-nodes.json")
subsystem_template = os.path.join(here, "templates", "subsystem.json")

# Nice selection of colors for cluster names (rainbow...)
colors = list(mcolors.CSS4_COLORS)
random.shuffle(colors)


def recursive_find(base, pattern="^(compspec[.]json)$"):
    """
    Recursively find lammps output files.
    """
    for root, _, filenames in os.walk(base):
        for filename in filenames:
            if re.search(pattern, filename):
                yield os.path.join(root, filename)


def read_json(filename):
    """
    Read json from file
    """
    return json.loads(read_file(filename))


def write_file(content, filename):
    """
    Write json to file
    """
    with open(filename, "w") as outfile:
        outfile.write(content)


def write_json(obj, filename):
    """
    Write json to file
    """
    with open(filename, "w") as outfile:
        outfile.write(json.dumps(obj, indent=4))


def read_file(filename):
    """
    Read content from file
    """
    with open(filename, "r") as fd:
        content = fd.read()
    return content

template = Template(read_file(cluster_template))
subsys_template = Template(read_file(subsystem_template))


def load_yaml(filename):
    """
    Read yaml from file.
    """
    with open(filename, "r") as stream:
        content = yaml.safe_load(stream)
    return content


def write_yaml(data, filename):
    """
    Write yaml to file
    """
    with open(filename, "w") as outfile:
        yaml.dump(data, outfile)


def get_parser():
    parser = argparse.ArgumentParser(description="cluster generator")
    parser.add_argument(
        "--indir",
        # MPI variant is one past descriptive and has full metadata
        default=os.path.join(root, "jobspecs", "mpi"),
        help="input directory with jobspecs",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(root, "clusters"),
        help="output directory for clusters",
    )
    return parser


# Cluster names to use


def compspec_file_to_jobspec_file(filename):
    """
    Convert the compspec.json to a jobspec yaml name
    """
    basename = os.path.basename(filename)
    return basename.replace("-compspec.json", "-jobspec.yaml")


def to_uid(name):
    """
    Get the column uid of a jobspec from the full flattened name
    """
    return (
        os.path.basename(name)
        .replace("-jobspec.yaml", "")
        .replace("ghcr.io-rse-ops-lammps-matrix-", "")
    )


def find_match(df, idxs):
    """
    Find matching cluster name (color) for a set of attributes
    """
    perfect_match = df[df.loc[:, idxs].sum(axis=1) == 4]
    assert perfect_match.shape[0] == 1
    perfect_match = perfect_match.index[0]
    return perfect_match


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
    """
    Main script. Warning, this is 🍝️
    """
    parser = get_parser()
    args, _ = parser.parse_known_args()

    # Also organize results by mode
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    # Show parameters to the user
    print(f"▶️  Output directory: {args.outdir}")
    print(f"▶️   Input directory: {args.indir}")

    # CLUSTERS ---------------------
    # Create every possible combination cluster.
    # We will take combinations across, but just keep the last group with one from each
    # that are size 4 (that we want) there should be 48.
    attributes = [
        {"hardware|hardware.gpu.available=no", "hardware|hardware.gpu.available=yes"},
        {"io.archspec|cpu.target=amd64", "io.archspec|cpu.target=arm64"},
        {
            "mpi|mpi.implementation=mpich",
            "mpi|mpi.implementation=openmpi",
            "mpi|mpi.implementation=intel-mpi",
        },
        {
            "os|os.full=ubuntu20.04",
            "os|os.full=ubuntu22.04",
            "os|os.full=rocky8",
            "os|os.full=rocky9",
        },
    ]
    sets = []
    for size in range(1, len(attributes) + 1):
        for combination in combinations(attributes, r=size):
            sets.extend(set(p) for p in product(*combination))

    # Keep those only the size we care about (4)
    sets = [x for x in sets if len(x) == 4]
    assert len(sets) == 48

    # Write into a data frame, clusters by feature
    columns = set()
    for attset in sets:
        for attribute in attset:
            parts = attribute.split("|")
            columns.add(parts[1])

    df = pandas.DataFrame(columns=list(columns))
    for attset in sets:
        # Choose a new cluster name, a color
        cluster_name = colors.pop(0)
        idxs = [x.split("|")[1] for x in attset]
        df.loc[cluster_name, idxs] = 1

    # This is a 0/1 matrix that shows features for each cluster.
    # We will use this to generate the subsystems too.
    df = df.fillna(0)
    df.to_csv("rainbow-clusters.csv")

    # MATCHES ----------------------
    # Now read in the jobspecs and determine the perfect cluster, and the others that are compatible
    # Perfect == 1
    # Compatible (but not perfect) = 0.5
    # Will not work = 0
    inputs = list(recursive_find(args.indir, ".+jobspec[.]yaml"))
    columns = [to_uid(x) for x in inputs]
    matchdf = pandas.DataFrame(columns=columns, index=df.index)

    for input_file in inputs:
        js = load_yaml(input_file)
        task = js["tasks"][0]["resources"]

        # This is the name of the jobspec in the match dataframe
        js_label = to_uid(input_file)

        # First find perfect compatibility... being lazy
        gpu_label = "=".join(list(task["hardware"].items())[0])
        os_label = task["os"]["os.vendor"]

        # Don't bother with the point version
        os_label += task["os"]["os.release"].rsplit(".", 1)[0]
        os_label = f"os.full={os_label}"
        mpi_label = "mpi.implementation=" + task["mpi"]["mpi.implementation"].lower()
        cpu_label = "cpu.target=" + task["io.archspec"]["cpu.target"]
        idxs = [os_label, gpu_label, mpi_label, cpu_label]

        # Find the perfect match cluster (should be only one) and set to 1
        perfect_match = find_match(df, idxs)
        matchdf.loc[perfect_match, js_label] = 1

        # Less than perfect but compatible (0.5)
        # 1. If it doesn't need a gpu, assume can still run on gpu cluster
        variant = set(copy.deepcopy(idxs))
        if "hardware.gpu.available=no" in variant:
            variant.remove("hardware.gpu.available=no")
            variant.add("hardware.gpu.available=yes")
            perfect_match = find_match(df, list(variant))
            matchdf.loc[perfect_match, js_label] = 0.5

    # The rest get a value of 0, not compatible
    matchdf = matchdf.fillna(0)
    matchdf.to_csv("jobspec-to-cluster-matches.csv")

    # Now let's generate the cluster files
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    for color in df.index:
        render = template.render(name=f"cluster-{color}")
        cluster_outdir = os.path.join(args.outdir, f"cluster-{color}")
        if not os.path.exists(cluster_outdir):
            os.makedirs(cluster_outdir)
        outfile = os.path.join(cluster_outdir, "nodes.json")
        write_file(render, outfile)

    # SUBSYSTEMS ----------------------
    # Generate a subsystem for each cluster.
    for row in df.iterrows():
        # This is a pretty limited set, so each cluster
        # in practice has just one subsystem attribute
        features = row[1][row[1] == 1].index
        for feature in features:
            subsystem = feature.split(".")[0]

            # The one weirdo
            if "target" in feature:
                subsystem = "io.archspec"

            # Only one node per subsystem, rofl
            # index 0 is the root, so we start at 1
            node = Node(1, feature, 0)
            render = subsys_template.render(nodes=[node], name=subsystem)
            cluster_outdir = os.path.join(args.outdir, f"cluster-{row[0]}")
            outfile = os.path.join(cluster_outdir, f"{subsystem}-subsystem.json")
            write_file(render, outfile)


if __name__ == "__main__":
    main()
