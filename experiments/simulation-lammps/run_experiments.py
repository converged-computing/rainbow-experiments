#!/usr/bin/env python3

import argparse
import copy
import json
import os
import subprocess
import shutil
import random
import sys
import re
import tempfile
import yaml
import pandas
from datetime import datetime

from rainbow.protos import rainbow_pb2
from rainbow.client import RainbowClient
import rainbow.config as config
import jobspec.core as js

from jinja2 import Template

here = os.path.dirname(os.path.abspath(__file__))

# I'm putting variables up here so you see them, that you might want to change

# These are subsystem files we will add, in this order
# Each should be in clusters/<cluster-name>/<filename>
# After we do the "empty" subsystem (not adding one)
subsystems = {
    "io.archspec": "io.archspec-subsystem.json",
    "os": "os-subsystem.json",
    "hardware": "hardware-subsystem.json",
    "mpi": "mpi-subsystem.json",
}

# This is the order of subsystems (keys above) we want to adhere to
order = ["io.archspec", "os", "mpi", "hardware"]

# Resources will be added programatically here
# Note that this is the format I'm prototyping.
jobspec_template = """
version: 1
resources:
- count: 2
  type: node
  with:
  - count: 4
    type: core
      
# No slot here implies the top level resource has the slot
# This isn't allowed by the jobspec validation so we add it in rainbow
# I think it's a good idea, and I'm trying really hard to not simplify
# the entire jobspec...
task:
  command: [lmp, -v, x, '2', -v, y, '2', -v, z, '2', -in, ./in.reaxff.hns, -nocite]
  count:
    per_slot: 1
  resources: {}
"""

# Create a jinja2 template to render this (add the name
template = Template(jobspec_template)

# Response types for successful subsystem (main graph nodes or subsystem)
register_success = [
    rainbow_pb2.RegisterResponse.ResultType.REGISTER_EXISTS,
    rainbow_pb2.RegisterResponse.ResultType.REGISTER_SUCCESS,
]

# share client across functions
cli = None


def write_json(content, filename):
    """
    Write json to file
    """
    with open(filename, "w") as fd:
        fd.write(json.dumps(content, indent=4))


def write_file(content, filename):
    """
    Write content to file.
    """
    with open(filename, "w") as fd:
        fd.write(content)


def read_file(filename):
    """
    Read content from file
    """
    with open(filename, "r") as fd:
        content = fd.read()
    return content


def load_yaml(filename):
    """
    Read yaml from file.
    """
    with open(filename, "r") as stream:
        content = yaml.safe_load(stream)
    return content


def recursive_find(base, pattern="^(compspec[.]json)$"):
    """
    Recursively find lammps output files.
    """
    for root, _, filenames in os.walk(base):
        for filename in filenames:
            if re.search(pattern, filename):
                yield os.path.join(root, filename)


def run_base_experiment(iters, jobspec_listing):
    """
    The base experiment does not have any subsystems registered.
    It's basically just random selection. It will be terrible.
    """
    # First submission, 20x, without any subsystem metadata
    assignments = {}
    for i in range(iters):
        for spec in jobspec_listing["jobspecs"]:
            render = template.render(name=spec["name"])
            loaded = yaml.load(render, Loader=yaml.SafeLoader)
            submit_job(loaded, assignments, spec)
    return assignments


def submit_job(loaded, assignments, spec):
    """
    Submit a job, update assignments given.
    """
    # Load into a rainbow jobspec object (validates, etc)
    jobspec = js.Jobspec(loaded)
    response = cli.submit_jobspec(jobspec)
    try:
        assigned_to = response.cluster
    except:
        assigned_to = "unmatched"
    if assigned_to not in assignments:
        assignments[assigned_to] = []
    assignments[assigned_to].append(spec["name"])


def run_single_subsystem_experiment(iters, subsystem, jobspec_listing):
    """
    A single subsystem experiment adds subsystem metadata to resource.

    This is assessing the value of a single subsystem.
    """
    # First submission, 20x, without any subsystem metadata
    assignments = {}
    for i in range(iters):
        for spec in jobspec_listing["jobspecs"]:
            render = template.render(name=spec["name"])
            loaded = yaml.load(render, Loader=yaml.SafeLoader)
            # Add the resources for the subsystem type
            # We assume each spec has a definition, if this
            # isn't the case, do a check here
            resources = []
            for key, value in spec["resources"][subsystem].items():
                resources.append({"type": f"{key}={value}"})
            loaded["task"]["resources"][subsystem] = {"match": resources}
            print(loaded)
            submit_job(loaded, assignments, spec)
    return assignments


def run_expanding_subystem_experiment(iters, subsystems, jobspec_listing, assignments):
    """
    Run expanding subsystem experiment
    """
    for spec in jobspec_listing["jobspecs"]:
        render = template.render(name=spec["name"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # Add subsystems, one at a time
        for s, subsystem in enumerate(order):
            included_set = order[: s + 1]
            resources = []
            for key, value in spec["resources"][subsystem].items():
                resources.append({"type": f"{key}={value}"})
            loaded["task"]["resources"][subsystem] = {"match": resources}

            for i in range(iters):
                # We already ran single subsystem experiments
                if s == 0:
                    continue

                # A key for the combined subsystems
                key = "+".join(included_set)
                print(loaded)
                if key not in assignments:
                    assignments[key] = {}
                submit_job(loaded, assignments[key], spec)

    return assignments


def run(args, clusters):
    """
    Run the experiments. This means:

    1. Submitting 20x each jobspec to rainbow.
    2. Iterating through clusters and getting assignment.
    3. Saving job assignments
    """
    # Read in jobspecs listing
    jobspec_listing = load_yaml(args.jobspecs)

    # Make a config that allows authenticating to each cluster
    # This is the hostname, cluster name (defaults to rainbow) and register secret
    cfg = config.new_rainbow_config(args.host, "rainbow", args.secret)

    # In practice, all of the tokens are "rainbow"
    for cluster, meta in clusters.items():
        cfg.add_cluster(cluster, meta["token"])

    # Just manually set the config on the client, being lazy
    cli.cfg = cfg
    assignments = {}

    # CASE 1: no subsystem knowledge
    assignments["none"] = run_base_experiment(args.iters, jobspec_listing)

    # Add all subsystems at once
    for subsystem in order:
        subsystem_file = subsystems[subsystem]

        # Register the subsystem file for each cluster
        for cluster, meta in clusters.items():
            print(f"Registering subsystem {subsystem} for cluster {cluster}")

            # This is the cluster-specific subsystem to register
            subsystem_nodes = os.path.join(args.clusters, cluster, subsystem_file)
            register_subsystem(cluster, subsystem, subsystem_nodes, meta["secret"])

    # CASE 2..2+subsystems: add subsystems (a la carte)
    for subsystem in order:
        assignments[subsystem] = run_single_subsystem_experiment(
            args.iters, subsystem, jobspec_listing
        )

    # CASE 3...N subsystems added in order
    assignments = run_expanding_subystem_experiment(
        args.iters, subsystems, jobspec_listing, assignments
    )

    # Lookup of clusters (rows) by jobs (columns)
    df = pandas.read_csv(args.match, index_col=0)

    # Calculate how well we did.
    # This data frame has a point system
    scores = {}
    for experiment, assigns in assignments.items():
        total = 0
        correct = 0
        for cname, jobids in assigns.items():
            for jobid in jobids:
                total += 1
                cname = cname.replace("cluster-", "")
                correct += df.loc[cname, jobid]
        scores[experiment] = {
            "total": total,
            "correct": correct,
            "accuracy": correct / total,
        }

    print(json.dumps(scores, indent=4))
    print(f"🧪️ Experiments are finished. See output in {args.outdir}")
    write_json(scores, os.path.join(args.outdir, "scores.json"))


def confirm_action(question):
    """
    Ask for confirmation of an action
    """
    response = input(question + " (yes/no)? ")
    while len(response) < 1 or response[0].lower().strip() not in "ynyesno":
        response = input("Please answer yes or no: ")
    if response[0].lower().strip() in "no":
        return False
    return True


def get_parser():
    parser = argparse.ArgumentParser(description="Run LAMMPS Simulations")
    parser.add_argument(
        "--iters",
        type=int,
        default=20,
        help="iterations to run per jobspec (defaults to 20)",
    )
    parser.add_argument(
        "--host", help="host of rainbow cluster", default="localhost:50051"
    )
    parser.add_argument(
        "--secret", help="registration secret", default="chocolate-cookies"
    )
    parser.add_argument(
        "--clusters",
        help="path to look for clusters (nodes.json)",
        default=os.path.join(here, "clusters"),
    )
    parser.add_argument(
        "--jobspecs",
        help="path to jobspec.yaml (jobspecs to simulate)",
        default=os.path.join(here, "jobspecs.yaml"),
    )
    parser.add_argument(
        "--match-csv",
        dest="match",
        help="path match csv lookup (to load with pandas)",
        default=os.path.join(here, "clusters", "jobspec-to-cluster-matches.csv"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="do not ask for confirmation",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(here, "results"),
        help="output directory for results",
    )
    return parser


def register(cluster_name, cluster_node, secret):
    """
    Register a cluster node path.
    """
    response = cli.register(cluster_name, secret=secret, cluster_nodes=cluster_node)
    if response.status not in register_success:
        raise ValueError(f"Issue registering cluster {cluster_name}: {response}")

    # In the response:
    # secret is for the cluster to receive jobs
    # token is to submit to it
    # Note that the server should be started so response.token is always "rainbow"
    return response


def register_subsystem(cluster, subsystem, subsystem_nodes, secret):
    """
    Helper to register a subsystem and check for successful response

    cluster: name of the cluster
    subsystem: name of the subsystem
    subsystem_file: file with nodes
    secret: the secret specific to the cluster
    """
    response = cli.register_subsystem(
        cluster, subsystem=subsystem, secret=secret, nodes=subsystem_nodes
    )
    if response.status not in register_success:
        raise ValueError(f"Issue registering cluster {cluster_name}: {response}")
    return response


def get_cluster_name(cluster_node):
    """
    Get a cluster name from a nodes file.
    """
    return os.path.basename(os.path.dirname(cluster_node))


def main():
    global cli

    parser = get_parser()
    args, _ = parser.parse_known_args()
    outdir = os.path.abspath(args.outdir)

    # Create the client
    cli = RainbowClient(host=args.host)

    # Also organize results by mode
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    # Save cluster tokens and secrets - we need these to retrieve assigned jobs
    clusters = {}

    # Find cluster nodes and register
    cluster_nodes = list(recursive_find(args.clusters, "nodes.json"))
    for i, cluster_node in enumerate(cluster_nodes):
        # Skip templates!
        if "templates" in cluster_node:
            continue

        cluster_name = get_cluster_name(cluster_node)
        # Registration
        response = register(cluster_name, cluster_node, args.secret)
        if response.token and response.secret:
            clusters[cluster_name] = {
                "secret": response.secret,
                "token": response.token,
            }

    # Show parameters to the user
    print(f"▶️  Output directory: {outdir}")
    print(f"▶️          Jobspecs: {args.jobspecs}")
    print(f"▶️          Clusters: {len(clusters)}")
    print(f"▶️        Iterations: {args.iters}")

    if not args.force and not confirm_action("Would you like to continue?"):
        sys.exit("Cancelled!")

    try:
        run(args, clusters)
    except Exception as e:
        print(e)
        raise


if __name__ == "__main__":
    main()
