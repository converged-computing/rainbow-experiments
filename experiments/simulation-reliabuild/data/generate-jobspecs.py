#!/usr/bin/env python3

import os
from glob import glob
import pandas
import yaml
import sys

here = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, here)

from extract import parse_spec_row


def load_yaml(filename):
    with open(filename, "r") as file:
        data = yaml.safe_load(file)
    return data


def write_yaml(obj, filename):
    with open(filename, "w") as file:
        yaml.dump(obj, file)


def chunkize(l, n):
    for i in range(0, len(l), n):
        yield l[i : i + n]


def main():
    # We will generate jobspecs again from the original data.
    # The models are trained on this, but we will be giving them
    # to totally randomly generated clusters (unlikely to have
    # perfect matches)
    specs = glob(os.path.join(here, "specs", "*", "*.yaml"))

    jobspec_outdir = os.path.join(here, "jobspecs")
    if not os.path.exists(jobspec_outdir):
        os.makedirs(jobspec_outdir)

    # load in cluster features so we filter down to common set
    cluster_features = pandas.read_csv("clusters.csv", index_col=0)

    # Break into 25 groups, 1K per group
    # Create a jobspec for each
    for i, group in enumerate(chunkize(specs, 1000)):
        jobspecs = []
        print(f"Creating jobspec for group {i}")
        outfile = os.path.join(jobspec_outdir, os.path.join(jobspec_outdir, f"jobspecs-{i}.yaml"))

        total = len(group)
        for s, specfile in enumerate(group):
            print(f"Parsing jobspec {s}/{total}", end="\r")
            digest = os.path.basename(specfile).replace(".yaml", "")

            # This is the package to build, how we choose the model
            js = {"name": digest, "resources": {}}
            spec = load_yaml(specfile)
            feats = parse_spec_row(spec)

            # Note that the first spec is the one we are trying to build
            package = spec["spec"]["nodes"][0]['name']
            package_version = spec["spec"]["nodes"][0]['version']
            js["package"] = package
            js["package_version"] = package_version
            overlap = {k: v for k, v in feats.items() if k in cluster_features.columns}

            # Break into faux package subsystems
            for k, v in overlap.items():
                subsystem = k.split("-")[0]
                if subsystem not in js["resources"]:
                    js["resources"][subsystem] = {}
                js["resources"][subsystem][k] = v
            jobspecs.append(js)

        # Save to outdir
        print()
        write_yaml(jobspecs, outfile)


if __name__ == "__main__":
    main()
