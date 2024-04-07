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
import joblib
import numpy
import hashlib

import packaging.version as version
from rainbow.protos import rainbow_pb2
from rainbow.client import RainbowClient
import rainbow.config as config
import jobspec.core as js

from jinja2 import Template

here = os.path.dirname(os.path.abspath(__file__))

config_file = os.path.join(here, "rainbow-config.yaml")
if not os.path.exists(config_file):
    sys.exit("Rainbow config {config_file} does not exist")

# Load models
models = {}


def load_models():
    """
    Load dumped models, organized by package
    """
    global models
    models_dir = os.path.join(here, "data", "models", "knn")
    if not os.path.exists(models_dir):
        sys.exit(f"Models directory {models_dir} does not exist.")
    for model_file in os.listdir(models_dir):
        model_outfile = os.path.join(models_dir, model_file)
        package = os.path.basename(model_outfile).replace(".joblib", "")
        models[package] = joblib.load(model_outfile)


load_models()

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
attributes:
  parameter: {}
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


def run_base_experiment(jobspecs):
    """
    The base experiment does not have any subsystems registered.
    It's basically just random selection. This is the base case
    with no compatibility metadata and we run it once, so
    obviously there is repeated-ness here.
    """
    assignments = {}
    stats = []
    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)
        response, assigned_to = submit_job(
            loaded, assignments, spec, select_algo="random"
        )
        stats.append(
            {
                "total_clusters": response.total_clusters,
                "total_matches": response.total_matches,
                "total_mismatches": response.total_mismatches,
            }
        )
    return assignments, stats


def submit_job(loaded, assignments, spec, match_algo=None, select_algo=None):
    """
    Submit a job, update assignments given.
    """
    # Load into a rainbow jobspec object (validates, etc)
    jobspec = js.Jobspec(loaded)
    response = cli.submit_jobspec(jobspec, match_algo=None, select_algo=None)
    try:
        assigned_to = response.cluster
    except:
        assigned_to = "unmatched"
    if assigned_to not in assignments:
        assignments[assigned_to] = []
    assignments[assigned_to].append(spec["name"])
    # Return this so we can stop at unmatched
    return response, assigned_to


def run_single_subsystem_experiment(subsystem, jobspecs):
    """
    A single subsystem experiment adds subsystem metadata to resource.

    This is assessing the value of a single subsystem.
    """
    # First assemble unique jobs for subsystem
    uniques = {}
    stats = []
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
        uniques[jobid] = loaded

    jobspec_set, _ = get_unique_jobspecs(uniques)

    # First submission, 20x, without any subsystem metadata
    assignments = {}
    count = 1
    total = len(jobspec_set)
    for jobid, loaded in jobspec_set.items():
        print(f"{subsystem} ===>  {count}/{total}: {loaded}")
        response, assigned_to = submit_job(loaded, assignments, spec)
        stats.append(
            {
                "total_clusters": response.total_clusters,
                "total_matches": response.total_matches,
                "total_mismatches": response.total_mismatches,
            }
        )
        count += 1
    return assignments, stats


def run_expanding_subystem_experiment(subsystems, jobspec_listing):
    """
    Run expanding subsystem experiment
    """
    # Generate a lookup key for each order
    unmatched_at = {}
    seen = set()
    count = 0
    total = len(jobspec_listing)
    stats = []
    assignments = {}

    for jobid, spec in jobspec_listing.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)
        count += 1
        # Add subsystems, one at a time
        for s, subsystem in enumerate(subsystems):
            # Don't submit if the subsystem isn't relevant for the spec
            if subsystem not in spec["resources"]:
                continue

            # {"max": x, "min": x}
            ranges = spec["resources"][subsystem]
            ranges["field"] = "version"
            loaded["task"]["resources"][subsystem] = {"range": [ranges]}

            uid = get_content_hash(loaded["task"]["resources"])
            if uid in seen:
                continue
            seen.add(uid)

            # A key for the combined subsystems
            if s not in assignments:
                assignments[s] = {}
            print(f"{count}/{total}:      {loaded}")
            response, assigned_to = submit_job(loaded, assignments[s], spec)
            stats.append(
                {
                    "total_clusters": response.total_clusters,
                    "total_matches": response.total_matches,
                    "total_mismatches": response.total_mismatches,
                }
            )
            if assigned_to == "unmatched":
                print("Stopping adding metadata, no cluster match.")
                # This is the number of subsystems where we failed
                unmatched_at[jobid] = len(loaded["task"]["resources"])
                break
        count += 1

    return assignments, unmatched_at, stats


def get_unique_jobspecs_from_file(jobspec_files):
    """
    Get unique jobspecs based on content hash of resources
    This function reads from files.
    """
    jobspecs = {}
    seen = set()
    repeated = 0
    for jobspec_file in jobspec_files:
        try:
            specs = load_yaml(jobspec_file)
        except:
            print(f"Issue loading {jobspec_file}")
            continue
        for spec in specs:
            # Skip those with empty / no resources (saw this for papi)
            if not spec["resources"]:
                continue
            uid = get_content_hash(spec["resources"])
            if uid not in seen:
                jobspecs[spec["name"]] = spec
                seen.add(uid)
            else:
                repeated += 1
    return jobspecs, repeated


def get_content_hash(item):
    content = json.dumps(sorted(item.items()))
    hasher = hashlib.md5()
    hasher.update(content.encode("utf-8"))
    return hasher.hexdigest()


def get_unique_jobspecs(contenders):
    """
    Get unique jobspecs based on content hash of resources
    This variant assumes they are already loaded
    """
    jobspecs = {}
    seen = set()
    repeated = 0
    for jobid, spec in contenders.items():
        uid = get_content_hash(spec["task"]["resources"])
        if uid not in seen:
            jobspecs[jobid] = spec
            seen.add(uid)
        else:
            repeated += 1
    return jobspecs, repeated


def combine_assignments(assignments):
    """
    Combine assignments across job groups into single result.

    We do this because each is too small to consider in isolation.
    """
    combined_assignments = {}
    for _, listing in assignments.items():
        for cluster_name, jobids in listing.items():
            if cluster_name not in combined_assignments:
                combined_assignments[cluster_name] = []
            combined_assignments[cluster_name] += jobids
    return combined_assignments


def run(args, clusters):
    """
    Run the experiments.
    """
    # Make a config that allows authenticating to each cluster
    # This is the hostname, cluster name (defaults to rainbow) and register secret
    cfg = config.RainbowConfig(config_file)

    # In practice, all of the tokens are "rainbow"
    for cluster, meta in clusters.items():
        cfg.add_cluster(cluster, meta["token"])

    # Just manually set the config on the client, being lazy
    cli.cfg = cfg

    # Set selection to be random for basic case
    cli.cfg.set_selection_algorithm("random")

    # Read in jobspec files and save based on name
    jobspec_files = [os.path.join(args.jobspecs, x) for x in os.listdir(args.jobspecs)]

    # Remove repeated ones.
    jobspecs, repeated = get_unique_jobspecs_from_file(jobspec_files)
    subset = {}
    count = 0
    for key, rest in jobspecs.items():
        if count >= 1000:
            break
        subset[key] = rest
        count += 1
    jobspecs = subset

    print(f"Total jobspecs: {len(jobspecs)}")
    print(f"Repeated jobspecs: {repeated}")
    metadata = {"jobspecs": jobspecs, "removed_repeated": repeated}
    write_json(metadata, os.path.join(args.outdir, "jobspecs.json"))

    # Read in compatibility files and clusters
    cluster_truth = read_json(os.path.join(here, "data", "cluster-features.json"))

    # CASE 1: no subsystem knowledge
    print("\n\n === BASE EXPERIMENTS START ===\n\n")
    assignments, stats = run_base_experiment(jobspecs)
    print("\n\n === BASE EXPERIMENTS DONE ===\n\n")

    # See how well we did! A score of 0 means it wouldn't be compatible
    scores = {}

    import IPython

    IPython.embed()
    sys.exit()
    scores["none"] = calculate_scores(assignments, jobspecs, cluster_truth, stats)

    # Save data as we go
    write_json(scores, os.path.join(args.outdir, "scores.json"))

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

    # Reset assignments
    assignments = {}

    # CASE 2..2+ subsystems: add subsystems (a la carte)
    # Note that if this gets too large, we can retrieve the job assignments
    # from rainbow and that clears them up in the remote database.
    print("\n\n === SINGLE SUBSYSTEM EXPERIMENTS START ===\n\n")
    for subsystem in order:
        new_assignments, stats = run_single_subsystem_experiment(subsystem, jobspecs)
        assignments[subsystem] = new_assignments
    print("\n\n === SINGLE SUBSYSTEM EXPERIMENTS DONE ===\n\n")

    # Combine assignments into one lookup
    # I'm doing this because we only have a few runs per subsystem
    combined_assignments = combine_assignments(assignments)
    scores["single-subsystem"] = calculate_scores(
        combined_assignments, jobspecs, cluster_truth, stats
    )

    # Save scores as we go
    write_json(scores, os.path.join(args.outdir, "scores.json"))

    # Save on level of subsystem
    write_json(assignments, os.path.join(args.outdir, "subsystem-assignments.json"))
    subsys_scores = {}
    for subsystem, assign in assignments.items():
        subsys_scores[subsystem] = calculate_scores(
            assign, jobspecs, cluster_truth, stats
        )
    write_json(subsys_scores, os.path.join(args.outdir, "subsystem-scores.json"))

    # CASE 3...N subsystems added in order
    # Note we reset assignments here
    print("\n\n === EXPANDING SUBSYSTEM EXPERIMENTS START ===\n\n")
    assignments, unmatched_at, stats = run_expanding_subystem_experiment(
        order, jobspecs
    )
    print("\n\n === EXPANDING SUBSYSTEM EXPERIMENTS DONE ===\n\n")

    expanding_assignments = combine_assignments(assignments)
    scores["expanded-subsystems"] = calculate_scores(
        expanding_assignments, jobspecs, cluster_truth, stats
    )

    # unmatched at is the level of compatibility metadata that we added where there was no longer any match
    scores["unmatched_at"] = calculate_unmatched_scoring(unmatched_at)

    # Save raw unmatched at distribution, along with the total number of feature (package deps)
    # as a percentage of unmatched
    summary_unmatched = calculate_summary_unmatched(unmatched_at, jobspecs)
    write_json(summary_unmatched, os.path.join(args.outdir, "unmatched-summary.json"))

    # TODO also save the compat size set so we can do percentage of features where became too many
    write_json(unmatched_at, os.path.join(args.outdir, "unmatched-at-raw.json"))

    print(f"🧪️ Experiments are finished. See output in {args.outdir}")
    write_json(scores, os.path.join(args.outdir, "scores.json"))


def calculate_unmatched_scoring(unmatched_at):
    """
    Determine what level of adding compatibility metadata we had zero matches
    """
    mean_unmatched_at = numpy.mean(list(unmatched_at.values()))
    std_unmatched_at = numpy.std(list(unmatched_at.values()))
    return {
        "mean": mean_unmatched_at,
        "std": std_unmatched_at,
        "description": "The number of subsystem metadata attributes (package dependency version ranges) that were added when rainbow rejected entirely (no match)",
    }


def calculate_summary_unmatched(unmatched_at, jobspecs):
    """
    Calculate the unmatched at level in proportion to total attributes.
    """
    summary = []
    for jobid, score in unmatched_at.items():
        js = jobspecs[jobid]
        total_subs = len(js["resources"])
        percent_of_total = score / total_subs
        summary.append(
            {
                "jobid": jobid,
                "unmatched_at": score,
                "total_subsystems": total_subs,
                "max_percent_matched": percent_of_total,
            }
        )
    return summary


def calculate_scores(assignment, jobspecs, cluster_truth, stats):
    """
    Calculate scores for an assignment.

    If a jobspec is not compatible (meaning wrong arch, etc) it won't work.
    """
    # Stats has overall percentages for matches, etc.
    mean_total_matches = numpy.mean([x["total_matches"] for x in stats])
    mean_total_mismatches = numpy.mean([x["total_mismatches"] for x in stats])
    mean_total_matches_std = numpy.std([x["total_matches"] for x in stats])
    mean_total_mismatches_std = numpy.std([x["total_mismatches"] for x in stats])

    total_count = 0
    scoreset = []
    unmatched = 0
    total_points_possible = 0
    total_points_earned = 0
    total_points_lost = 0

    # Keep track of additional runtime minutes total and by package
    total_additional_runtime = 0
    runtimes = {}
    # Keep track of additional costs total and by packages
    total_additional_cost = 0
    costs = {}

    # Keep track of reasons for failure
    # compiler too old == software needs newer version, found old one
    reasons_for_failure = {
        "wrong_arch": 0,
        "missing_compiler": 0,
        "compiler_too_old": 0,
    }

    for cname, jobids in assignment.items():
        for jobid in jobids:
            total_count += 1
            points = 0

            if cname == "unmatched":
                unmatched += 1
                continue

            # Compare the assigned cluster features to the jobspec needs
            cluster_name = cname.replace("cluster-", "")
            cluster_features = cluster_truth[cluster_name]
            js = jobspecs[jobid]

            # These are conditions for failure
            failed = False
            if js["resources"]["arch"]["arch"] != cluster_features["arch"]:
                reasons_for_failure["wrong_arch"] += 1
                failed = True
            elif (
                js["resources"]["compiler"]["compiler_name"]
                != cluster_features["compiler"]
            ):
                reasons_for_failure["missing_compiler"] += 1
                failed = True

            # Here we assume we haven't failed from missing compiler
            found_version = version.parse(
                js["resources"]["compiler"]["compiler_version"]
            )
            needs_version = version.parse(cluster_features["compiler_version"])

            # We fail if the compiler is too old
            if not failed and found_version < needs_version:
                reasons_for_failure["compiler_too_old"] += 1
                failed = True

            # Now give points (or not)
            total_points_possible += 1
            points += 1
            if not failed:
                points += 1
                total_points_earned += 1
                scoreset.append(1)
            else:
                scoreset.append(0)
                total_points_lost += 1

            # Only calculate cost metrics if not failed etc
            # Estimate the predicted duration from the knn model
            package = js["package"]
            shaped = numpy.array(cluster_features["memory"]).reshape(-1, 1)
            predicted_duration = models[package].predict(shaped)[0]

            # calculate the optimal runtime, assuming this is the maximum potential for build!
            shaped = numpy.array(
                js["attributes"]["memory_global_best_runtime"]
            ).reshape(-1, 1)
            optimal_duration = models[package].predict(shaped)[0]

            # of accumulated time and cost differences, globally and for each package (seconds)
            additional_runtime = predicted_duration - optimal_duration
            if package not in runtimes:
                runtimes[package] = []
            runtimes[package].append(additional_runtime)

            # Calculate the additional cost
            # Assume we can spend OR save money here
            hours_runtime = additional_runtime / 60 / 60
            additional_cost = hours_runtime * cluster_features["cost_per_node_hour"]
            if package not in costs:
                costs[package] = []
            costs[package].append(additional_cost)
            total_additional_cost += additional_cost
            total_additional_runtime += additional_runtime

    # Calculate the overall score - the sum / total number
    return {
        "additional_runtime": {
            "total_additional_cost": total_additional_runtime,
            "additional_costs": runtimes,
            "description": "Additional runtime calculated as difference between actual and optimal runimes, where actual is based on KNN prediction of runtime with cluster memory and optimal runtime is the actual, optimal value",
        },
        "additional_costs": {
            "total_additional_cost": total_additional_cost,
            "additional_costs": costs,
            "description": "additional cost calculated from additional runtime converged to hours multiplied by node cost per hour.",
        },
        "total_jobs": {
            "value": total_count,
            "description": "total number of jobs run for group",
        },
        "unmatched_percent": {
            "value": unmatched / total_count,
            "description": "total unmatched divided by total count",
        },
        "unmatched": {
            "value": unmatched,
            "description": "number of unmatched jobs that could not be assigned a cluster by rainbow",
        },
        # This reflects if the package had exactly what it needed for
        # a successful build
        "build_success": {
            "mean": numpy.mean(scoreset),
            "std": numpy.std(scoreset),
            "description": "reflects if the package had exactly what it needed for a successful build",
        },
        "points_scored": {
            "total_correct": total_points_earned,
            "total_possible": total_points_possible,
            "total_incorrect": total_points_lost,
            "description": "total points earned vs. total points possible, where 1 point means a a successful build",
        },
        "matched_clusters_per_job": {
            "mean": mean_total_matches,
            "std": mean_total_matches_std,
            "description": "number of clusters rainbow deemed a match based on version ranges and compatibility metadata provided",
        },
        "mismatched_clusters_per_job": {
            "mean": mean_total_mismatches,
            "std": mean_total_mismatches_std,
            "description": "number of clusters rainbow deemed a mismatch based on version ranges and compatibility metadata provided",
        },
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
