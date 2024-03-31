#!/usr/bin/env python3

# Warning: this code is really janky. I thought I had a good idea at the beginning,
# but I don't like it now. Room for improvement I guess.

import argparse
import json
import os
import random
import sys
import re
import yaml
import numpy

import packaging.version as version
from rainbow.protos import rainbow_pb2
from rainbow.client import RainbowClient
import rainbow.config as config
import jobspec.core as js

from jinja2 import Template

here = os.path.dirname(os.path.abspath(__file__))

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
task:
  command: ["{{package}}"]
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


def read_json(filename):
    """
    Read json from file
    """
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


def run_base_experiment(jobspec_files):
    """
    The base experiment does not have any subsystems registered.
    It's basically just random selection.
    """
    assignments = {}
    for jobspec_file in jobspec_files:
        specs = load_yaml(jobspec_file)
        for spec in specs:
            render = template.render(package=spec["package"])
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
    # Return this so we can stop at unmatched
    return assigned_to


def run_single_subsystem_experiment(subsystem, jobspecs):
    """
    A single subsystem experiment adds subsystem metadata to resource.

    This is assessing the value of a single subsystem.
    """
    # First submission, 20x, without any subsystem metadata
    assignments = {}
    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # Don't submit if the subsystem isn't relevant for the spec
        if subsystem not in spec["resources"]:
            continue

        # {"max": x, "min": x}
        ranges = spec["resources"][subsystem]
        ranges["field"] = "version"
        loaded["task"]["resources"][subsystem] = {"range": [ranges]}
        print(loaded)
        submit_job(loaded, assignments, spec)
    return assignments


def run_expanding_subystem_experiment(subsystems, jobspec_listing):
    """
    Run expanding subsystem experiment
    """
    # Generate a lookup key for each order
    ids = {}
    unmatched_at = {}

    assignments = {}
    for jobid, spec in jobspec_listing.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # Add subsystems, one at a time
        for s, subsystem in enumerate(subsystems):
            included_set = subsystems[: s + 1]
            ids[s] = included_set

            # Don't submit if the subsystem isn't relevant for the spec
            if subsystem not in spec["resources"]:
                continue

            # {"max": x, "min": x}
            ranges = spec["resources"][subsystem]
            ranges["field"] = "version"
            loaded["task"]["resources"][subsystem] = {"range": [ranges]}

            # A key for the combined subsystems
            print(loaded)
            if s not in assignments:
                assignments[s] = {}
            assigned_to = submit_job(loaded, assignments[s], spec)
            if assigned_to == "unmatched":
                print("Stopping adding metadata, no cluster match.")
                unmatched_at[jobid] = s
                break

    return assignments, ids, unmatched_at


def run(args, clusters):
    """
    Run the experiments.
    """
    # Make a config that allows authenticating to each cluster
    # This is the hostname, cluster name (defaults to rainbow) and register secret
    cfg = config.new_rainbow_config(args.host, "rainbow", args.secret)
    cfg.set_match_algorithm("range")

    # In practice, all of the tokens are "rainbow"
    for cluster, meta in clusters.items():
        cfg.add_cluster(cluster, meta["token"])

    # Just manually set the config on the client, being lazy
    cli.cfg = cfg
    assignments = {}

    # Save means / std as we go, and order of subsystems added
    scores = {}

    # Read in jobspec files and save based on name
    jobspec_files = [os.path.join(args.jobspecs, x) for x in os.listdir(args.jobspecs)]

    # Testing mode
    jobspec_files = [jobspec_files[0]]

    jobspecs = {}
    for jobspec_file in jobspec_files:
        specs = load_yaml(jobspec_file)
        for spec in specs:
            jobspecs[spec["name"]] = spec

    # Read in compatibility files and clusters
    cluster_truth = read_json(os.path.join(here, "data", "cluster-features.json"))

    # output directory for assignment
    outdir_assign = os.path.join(args.outdir, "assignments")
    if not os.path.exists(outdir_assign):
        os.makedirs(outdir_assign)

    # CASE 1: no subsystem knowledge
    assignments["none"] = run_base_experiment(jobspec_files)

    # Save data as we go
    write_json(assignments, os.path.join(outdir_assign, "none.json"))

    # Calculate the overall score - the sum / total number
    scores["none"] = calculate_scores(assignments["none"], jobspecs, cluster_truth)

    # Save data as we go
    write_json(scores, os.path.join(outdir_assign, "scores.json"))

    # We will randomize how we add subsystems (package dependencies)
    order = []

    # Add all subsystems at once - every cluster has the same set
    for subsystem_file in os.listdir(os.path.join(args.clusters, cluster)):
        if "-subsystem.json" not in subsystem_file:
            continue

        # Register the subsystem file for each cluster
        for cluster, meta in clusters.items():
            # This is a package dependency
            subsystem = subsystem_file.replace("-subsystem", "").replace(".json", "")
            print(f"Registering subsystem {subsystem} for cluster {cluster}")

            # This is the cluster-specific subsystem to register
            subsystem_nodes = os.path.join(args.clusters, cluster, subsystem_file)
            register_subsystem(cluster, subsystem, subsystem_nodes, meta["secret"])
            order.append(subsystem)

    random.shuffle(order)

    # CASE 2..2+ subsystems: add subsystems (a la carte)
    # Note that if this gets too large, we can retrieve the job assignments
    # from rainbow and that clears them up in the remote database.
    for subsystem in order:
        assignments[subsystem] = run_single_subsystem_experiment(subsystem, jobspecs)
        scores[subsystem] = calculate_scores(
            assignments[subsystem], jobspecs, cluster_truth
        )

    # CASE 3...N subsystems added in order
    # Note we reset assignments here
    assignments, ids, unmatched_at = run_expanding_subystem_experiment(order, jobspecs)

    for group_id, assign in assignments.items():
        scores[group_id] = calculate_scores(
            assignments[group_id], jobspecs, cluster_truth
        )

    print(f"🧪️ Experiments are finished. See output in {args.outdir}")
    write_json(scores, os.path.join(args.outdir, "scores.json"))
    ids = {"ids": ids, "unmatched_at": unmatched_at}
    write_json(ids, os.path.join(args.outdir, "ids_unmatched_at.json"))


def calculate_scores(assignment, jobspecs, cluster_truth):
    """
    Calculate scores for an assignment.

    We assume that if a cluster range is within what the jobspec allows,
    it gets credit for that feature. Otherwise, no.
    """
    # This is annoying, and I don't like the design of having categories for
    # versions (the model will fail if we haven't seen it) but it is what it is
    total_count = 0
    scoreset = []
    unmatched = 0
    for cname, jobids in assignment.items():
        for jobid in jobids:
            total_features = 0
            total_count += 1
            points = 0

            if cname == "unmatched":
                unmatched += 1
                continue

            # Compare the assigned cluster features to the jobspec needs
            cluster_name = cname.replace("cluster-", "")
            cluster_features = cluster_truth[cluster_name]
            js = jobspecs[jobid]

            # For each jobspec range that we need, give a point
            # if the cluster is in the range
            for dep, vs in js["resources"].items():
                total_features += 1
                vmin = version.parse(vs["min"])
                vmax = version.parse(vs["max"])
                clusterv = version.parse(cluster_features[dep])
                if clusterv > vmin and clusterv < vmax:
                    points += 1
            scoreset.append(points / total_features)

    # Calculate the overall score - the sum / total number
    return {
        "total_jobs": total_count,
        "unmatched_percent": unmatched / total_count,
        "unmatched": unmatched,
        "mean": numpy.mean(scoreset),
        "std": numpy.std(scoreset),
    }


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
    parser = argparse.ArgumentParser(description="Run Reliabuild Simulation")
    parser.add_argument(
        "--host", help="host of rainbow cluster", default="localhost:50051"
    )
    parser.add_argument(
        "--secret", help="registration secret", default="chocolate-cookies"
    )
    parser.add_argument(
        "--clusters",
        help="path to look for clusters (nodes.json)",
        default=os.path.join(here, "data", "clusters"),
    )
    parser.add_argument(
        "--labels",
        help="path to look for labels (*.csv)",
        default=os.path.join(here, "data", "prepared", "labels"),
    )
    parser.add_argument(
        "--jobspecs",
        help="path to jobspec*.yaml files (jobspecs to simulate)",
        default=os.path.join(here, "data", "jobspecs"),
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
        raise ValueError(f"Issue registering cluster {cluster}: {response}")
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
    print(f"Found {len(cluster_nodes)} clusters to register.")
    for i, cluster_node in enumerate(cluster_nodes):
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

    if not args.force and not confirm_action("Would you like to continue?"):
        sys.exit("Cancelled!")

    try:
        run(args, clusters)
    except Exception as e:
        print(e)
        raise


if __name__ == "__main__":
    main()
