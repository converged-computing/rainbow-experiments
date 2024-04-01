#!/usr/bin/env python3

import pickle
import os
from glob import glob
import pandas
import shutil
import yaml
import json
import copy
import random
from jinja2 import Template
from packaging import version

here = os.path.abspath(os.path.dirname(__file__))

# Nice selection of colors for cluster names (rainbow...)
import matplotlib.colors as mcolors

from semantic_version import Version

colors = list(mcolors.CSS4_COLORS)
random.shuffle(colors)

# cluster template
cluster_template = os.path.join(here, "templates", "cluster-nodes.json")
subsystem_template = os.path.join(here, "templates", "subsystem.json")


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

    def __init__(self, index, typ, type_count, version):
        self.type = typ
        self.index = index
        self.type_count = type_count
        self.version = version


def update_versions(versions, package, v):
    """
    Update version strings
    """
    package = package.replace("-version", "")
    v = version.parse(v)
    if package not in versions:
        versions[package] = set()
    versions[package].add(str(v))


def sort_versions(vs):
    """
    Break each version into a tuple
    and sort, reassemble. Geez.
    """
    cleaned = [clean_version(x) for x in vs]
    updated = []

    # Skip versions that are weird/do not parse
    for x in cleaned:
        try:
            updated.append(Version(x))
        except:
            continue

    tuples = [(x.major, x.minor, x.patch) for x in updated]
    return [".".join([str(x) for x in tup]) for tup in sorted(tuples)]


def get_next_version(sortedv):
    v = sortedv.pop(0)
    if v.count(".") == 1:
        v = f"{v}.0"
    if v.count(".") == 3:
        v = ".".join(v.split(".")[0:3])
    v = v.replace("rc", "")
    return Version(v)


def get_indexed_version(sortedv, idx):
    v = sortedv[idx]
    if v.count(".") == 1:
        v = f"{v}.0"
    if v.count(".") == 3:
        v = ".".join(v.split(".")[0:3])
    v = v.replace("0rc", "")
    return Version(v)


def clean_version(vclean):
    """
    clean a version for the cluster
    """
    if vclean.count(".") == 1:
        vclean = f"{vclean}.0"
    if vclean.count(".") == 3:
        vclean = ".".join(vclean.split(".")[0:3])
    vclean = vclean.replace("0rc", "")
    # This ensures it parses
    Version(vclean)
    return vclean


class VersionMatcher:
    def __init__(self, vs):
        """
        A VersionMatcher can return the correct group (min and max)
        A version is assigned to.
        """
        self.vs = vs

    def match(self, toMatch):
        """
        Given a version to match, return the right range
        """
        vmatch = version.parse(toMatch)
        for vset in self.vs:
            vmin = version.parse(vset["min"])
            vmax = version.parse(vset["max"])
            if vmatch >= vmin and vmatch <= vmax:
                return vset


def main():
    files = glob(os.path.join(here, "dinos-runs", "*", "*.pkl"))

    # This is the complete list of specs, working and errored
    # We care about both! Note that heffe seems to be entirely missing?
    specs = glob(os.path.join(here, "specs", "*", "*.yaml"))

    # Create a lookup based on hash
    # Note that a spec can appear twice if it has failures/successes
    lookup = {}
    for spec in specs:
        digest = os.path.basename(spec).replace(".yaml", "")
        if digest not in lookup:
            lookup[digest] = spec

    # Create a directory of parsed data
    outdir = os.path.join(here, "prepared", "labels")
    specs_outdir = os.path.join(here, "prepared", "specs")
    for dirname in [outdir, specs_outdir]:
        if not os.path.exists(dirname):
            os.makedirs(dirname)

    # Also keep track of full range of versions across jobspecs
    versions = {}

    # Keep track of invalid seen so we don't mention it again
    invalid_versions = set()

    # Keep track of all jobspec files
    jobspec_files = []
    for filename in files:
        # The pkl file is in a directory named by the package
        package = os.path.basename(os.path.dirname(filename))

        # Note this is a pandas data frame
        data = pandas.read_pickle(filename)

        # Only keep successful builds
        data = data[data.Status == "SUCCESS"]
        data = data[data.name == package]
        print(f"Package {package} has {data.shape[0]} records of success")

        # Now we need to filter down the specs to those that we have.
        package_specs = set()
        to_remove = set()
        for digest in data.index:
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
            data = data.drop(list(to_remove))

        if data.shape[0] < 5:
            print(
                f"Warning: package {package} is missing / does not have enough specs."
            )
            continue

        # Save the data frame to file (not sure if we need this)
        data.to_csv(os.path.join(outdir, f"{package}.csv"))

        # Get complete versions for each
        for specfile in package_specs:
            spec = load_yaml(specfile)
            feats = parse_spec_row(spec)
            for k in feats:
                if k.endswith("-version"):
                    # Not going to bother with invalid version strings
                    try:
                        update_versions(versions, k, feats[k])
                    except:
                        if feats[k] not in invalid_versions:
                            package = k.replace("-version", "")
                            print(
                                f"Version for package {package} {feats[k]} is invalid"
                            )
                        invalid_versions.add(feats[k])
            jobspec_files.append(specfile)

    # Create ranges for each, along with min/max to 0 or infinity :)
    # We will do this dumbly, by taking the current sorted versions,
    # splitting into groups, and then creating bounds around the edges
    ranges = {}
    for package, vs in versions.items():
        try:
            sortedv = sort_versions(vs)
        except:
            continue

        # No versions to parse
        if not sortedv:
            continue

        # If we only have one version, just be all inclusive
        if len(vs) == 1:
            try:
                v = get_next_version(sortedv)
                ranges[package] = [{"min": "0.0.0", "max": str(v.next_major())}]
            except:
                print(f"Cannot parse versions for package {package}")
                print(vs)
            continue
        try:
            smallest = get_next_version(sortedv)
            smallest = smallest.next_patch()
        except:
            print(f"Cannot parse versions for package {package}")
            print(vs)
            continue

        # This range will be from 0 to the smallest  + one patch
        ranges[package] = [{"min": "0.0.0", "max": str(smallest)}]
        approxMiddle = len(sortedv) // 2

        # Then two patches up to the middle and one over
        middle = get_indexed_version(sortedv, approxMiddle)
        middle = middle.next_patch()
        ranges[package].append({"min": str(smallest.next_patch()), "max": str(middle)})

        # Last group...
        highest = get_indexed_version(sortedv, -1)
        ranges[package].append({"min": str(middle.next_patch()), "max": str(highest)})

        # To infinity and beyond! (stuff we haven't seen yet)
        next_patch = highest.next_patch()
        for _ in range(10):
            highest = highest.next_patch()
        ranges[package].append({"min": str(next_patch), "max": str(highest)})

    # This is excessive, but I want every jobspec to be given an actual range for
    # the package it needs, so we are making a class to do that.
    # The clusters will be given a random version, but the jobspec can
    # fit a range. I want the range to reflect the truth of what actually built.
    matchers = {}
    for package, vs in ranges.items():
        matchers[package] = VersionMatcher(vs)

    # Now generate clusters, randomly selecting a specific version from the actual list
    select_from = copy.deepcopy(versions)

    # Create clusters data frame! This will have clusters in the index, features in the column
    clusters = {}

    # Generate 100 clusters (could eventually do more)
    for i in range(100):
        cluster_name = colors.pop(0)

        # Randomly select a value for each package
        selected = {}
        for package in ranges:
            # If we selected them all, restore!
            if not select_from[package]:
                select_from[package] = copy.deepcopy(list(versions[package]))
            select_from[package] = list(select_from[package])
            random.shuffle(list(select_from[package]))
            cluster_version = clean_version(select_from[package].pop(0))
            selected[package] = cluster_version
        clusters[cluster_name] = selected

    write_json(clusters, os.path.join(here, "cluster-features.json"))

    # Generate the jobspecs from our jobspec files
    jobspec_outdir = os.path.join(here, "jobspecs")
    if not os.path.exists(jobspec_outdir):
        os.makedirs(jobspec_outdir)

    # Create a jobspec for each of our jobspecs
    # We need to match this to a version range
    count = 0
    jobspecs = []
    total = len(jobspec_files)
    for s, specfile in enumerate(jobspec_files):
        print(f"Parsing jobspec {s}/{total}", end="\r")
        digest = os.path.basename(specfile).replace(".yaml", "")

        # This is the package to build, how we choose the model
        js = {"name": digest, "resources": {}}
        spec = load_yaml(specfile)

        # Note that the first spec is the one we are trying to build
        package = spec["spec"]["nodes"][0]["name"]
        package_version = spec["spec"]["nodes"][0]["version"]

        # Find the right range for the main package
        matcher = matchers[package]
        js["package_version"] = package_version

        try:
            m = matcher.match(package_version)
            # The package subsystem (for itself) should have the min and match
            # This is stored here as is, but parsed into a jobspec in the run experiment script
            js["resources"][package] = m
        except:
            pass
        feats = parse_spec_row(spec)
        js["package"] = package

        # Break into faux package subsystems
        for feat, value in feats.items():
            if "-version" not in feat:
                continue
            # This is the subsystem name.
            # We should only see it once per jobspec
            dependency = feat.replace("-version", "")

            # We can't include ones we could not parse
            if dependency not in matchers:
                continue
            matcher = matchers[dependency]
            try:
                value = clean_version(value)
                m = matcher.match(value)
            except:
                continue
            if not m:
                continue
            js["resources"][dependency] = m

        jobspecs.append(js)

        # Save every 1000
        if len(jobspecs) >= 1000:
            outfile = os.path.join(
                jobspec_outdir, os.path.join(jobspec_outdir, f"jobspecs-{count}.yaml")
            )
            count += 1
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

    # Now generate the cluster JGH
    for color in clusters:
        render = template.render(name=f"cluster-{color}")
        cluster_outdir = os.path.join(clusters_dir, f"cluster-{color}")
        if not os.path.exists(cluster_outdir):
            os.makedirs(cluster_outdir)
        outfile = os.path.join(cluster_outdir, "nodes.json")
        write_file(render, outfile)

    # SUBSYSTEMS ----------------------
    # Generate package dependency subsystems for each cluster
    # features are the package RANGE of versions
    for cluster, features in clusters.items():
        cluster_outdir = os.path.join(clusters_dir, f"cluster-{cluster}")

        # Assemble package "subsystems"
        for subsystem, pkg_version in features.items():
            node = Node(1, "package", 0, pkg_version)
            render = subsys_template.render(nodes=[node], name=subsystem)
            outfile = os.path.join(cluster_outdir, f"{subsystem}-subsystem.json")
            write_file(render, outfile)


def parse_spec_row(spec):
    """
    Parse main package features from a spack spec

    I was originally going for everything, but for this experiment
    I am just caring about dependency versions
    """
    feats = {}
    for i, spec in enumerate(spec["spec"]["nodes"]):
        name = spec["name"]
        attrs = {"version": spec["version"]}
        feats.update({f"{name}-{x}": feat for x, feat in attrs.items()})
    return feats


if __name__ == "__main__":
    main()
