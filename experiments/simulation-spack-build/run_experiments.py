#!/usr/bin/env python3

import argparse
import math
import json
import os
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

# Nodes per simulated job
nodes_per_job = 2

# Rainbow config with constraint select algorithm
config_file = os.path.join(here, "rainbow-config.yaml")
if not os.path.exists(config_file):
    sys.exit("Rainbow config {config_file} does not exist")

# Make cluster truth global because we are lazy
clusters = {}
cluster_truth_file = os.path.join(here, "data", "cluster-features.json")
if not os.path.exists(cluster_truth_file):
    sys.exit(f"{cluster_truth_file} does not exist.")

# Load models
models = {}

# Select algorithm options - we now we just filter down by nodes free
# and the script here handles calculating the build cost via knn
priorities = """- priority: 1 
  steps:
  - filter: "nodes_free > 0"
"""

select_options = {"priorities": priorities}


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
jobspec_template = (
    """
version: 1
resources:
- count: %s
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
    % nodes_per_job
)

# Create a jinja2 template to render this (add the name
template = Template(jobspec_template)

# Response types for successful subsystem (main graph nodes or subsystem)
register_success = [
    rainbow_pb2.RegisterResponse.ResultType.REGISTER_EXISTS,
    rainbow_pb2.RegisterResponse.ResultType.REGISTER_SUCCESS,
]

update_state_success = [
    rainbow_pb2.UpdateStateResponse.ResultType.UPDATE_STATE_SUCCESS,
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


cluster_truth = read_json(cluster_truth_file)


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

    If rainbow is running with constraints we take cluster state
    into account.
    """
    assignments = {}
    stats = []
    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)
        response, assigned_to = submit_job(
            loaded, assignments, spec, select_algo="random", with_constraints=False
        )
        stats.append(
            {
                "total_clusters": response.total_clusters,
                "total_matches": response.total_matches,
                "total_mismatches": response.total_mismatches,
            }
        )
    return assignments, stats


def submit_job(
    loaded, assignments, spec, match_algo=None, select_algo=None, with_constraints=False
):
    """
    Submit a job, update assignments given.

    If with constraints is True, we update a cluster to indicate it has fewer
    available cores to run further jobs. This will better distribute jobs.
    """
    global clusters

    # Load into a rainbow jobspec object (validates, etc)
    jobspec = js.Jobspec(loaded)

    # If we are adding constraints, we want a satisfy only, which will return a list of clusters
    response = cli.submit_jobspec(
        jobspec, match_algo=None, select_algo=None, satisfy_only=with_constraints
    )

    # with constraints (satisfy only) returns list of all clusters
    try:
        if with_constraints:
            assigned_to = response.clusters
        else:
            assigned_to = response.cluster
    except:
        assigned_to = "unmatched"

    # Only add to assigned to if we have an actual assignment!
    if not with_constraints:
        if assigned_to not in assignments:
            assignments[assigned_to] = []
        assignments[assigned_to].append(spec["name"])

    # Return this so we can stop at unmatched
    return response, assigned_to


def run_single_subsystem_experiment(subsystem, jobspecs):
    """
    A single subsystem experiment adds subsystem metadata to resource.

    This is assessing the value of a single subsystem. If with constraints is
    True, we add constraint metadata needed for the selection algorithm.
    """
    assignments = {}
    count = 1
    stats = []
    total = len(jobspecs)
    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # We represent all of these resources as value = <X>
        # resources:
        #  io:
        #     match:
        #     - field: type
        #       value: shm
        match = []
        ranges = []
        field = "value"
        if subsystem == "compiler-version":
            for _, v in spec["resources"]["compiler"].items():
                match.append({"field": field, "value": v})
            loaded["task"]["resources"]["compiler"] = {"match": match}
            print(f"{subsystem} ===>  {count}/{total}: {loaded}")

        # Memory must be provided in a range (with min value)
        elif subsystem == "memory":
            value = list(spec["resources"][subsystem].values())[0]
            ranges.append({"field": field, "min": str(int(value))})
            loaded["task"]["resources"][subsystem] = {"range": ranges}
            print(f"{subsystem} ===>  {count}/{total}: {loaded}")

        else:
            value = list(spec["resources"][subsystem].values())[0]
            match.append({"field": field, "value": value})
            loaded["task"]["resources"][subsystem] = {"match": match}
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


def run_expanding_subystem_experiment(subsystems, jobspecs):
    """
    Run expanding subsystem experiment
    """
    unmatched_at = {}
    count = 0
    total = len(jobspecs)
    stats = {}
    assignments = {}

    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # Add subsystems, one at a time
        uid = ""
        for s, subsystem in enumerate(subsystems):
            if uid == "":
                uid = subsystem
            else:
                uid = f"{uid}-{subsystem}"
            match = []
            ranges = []
            field = "value"
            if subsystem == "compiler-version":
                for _, v in spec["resources"]["compiler"].items():
                    match.append({"field": field, "value": v})
                loaded["task"]["resources"]["compiler"] = {"match": match}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

            elif subsystem == "memory":
                value = list(spec["resources"][subsystem].values())[0]
                ranges.append({"field": field, "min": str(int(value))})
                loaded["task"]["resources"][subsystem] = {"range": ranges}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

            else:
                value = list(spec["resources"][subsystem].values())[0]
                match.append({"field": field, "value": value})
                loaded["task"]["resources"][subsystem] = {"match": match}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

            # A key for the combined subsystems
            if uid not in assignments:
                assignments[uid] = {}
            if uid not in stats:
                stats[uid] = []

            print(f"{count}/{total}:      {loaded}")
            response, assigned_to = submit_job(loaded, assignments[uid], spec)
            stats[uid].append(
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


def run_constraint_experiment(subsystems, jobspecs, with_replacement=True):
    """
    Run constraint experiment, with and without replacement.
    """
    count = 0
    total = len(jobspecs)
    stats = []
    assignments = {}
    unmatched_at = {}

    # For the constraint experiment, we add all the attributes at the getgo
    for jobid, spec in jobspecs.items():
        render = template.render(package=spec["package"])
        loaded = yaml.load(render, Loader=yaml.SafeLoader)

        # Add subsystems, one at a time
        for s, subsystem in enumerate(subsystems):
            match = []
            ranges = []
            field = "value"
            if subsystem == "compiler-version":
                for _, v in spec["resources"]["compiler"].items():
                    match.append({"field": field, "value": v})
                loaded["task"]["resources"]["compiler"] = {"match": match}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

            elif subsystem == "memory":
                value = list(spec["resources"][subsystem].values())[0]
                ranges.append({"field": field, "min": str(int(value))})
                loaded["task"]["resources"][subsystem] = {"range": ranges}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

            else:
                value = list(spec["resources"][subsystem].values())[0]
                match.append({"field": field, "value": value})
                loaded["task"]["resources"][subsystem] = {"match": match}
                print(f"{subsystem} ===>  {count}/{total}: {loaded}")

        print(f"{count}/{total}:      {loaded}")
        # Here we need to submit the job and get back ALL the clusters that work
        # We need to do this because we are running our ML model locally
        response, assigned_to = submit_job(
            loaded, assignments, spec, with_constraints=True
        )
        stats.append(
            {
                "total_clusters": response.total_clusters,
                "total_matches": response.total_matches,
                "total_mismatches": response.total_mismatches,
            }
        )

        # If we only have one cluster (string), it is added to assignments in submit func
        if len(assigned_to) == 1:
            assigned_to = assigned_to[0]

        # This does the final selection taking into account the cost, so we use the package
        # specific model and the memory that produced the best runtime for the package
        elif len(assigned_to) > 1:
            assigned_to = do_final_selection(
                assigned_to,
                spec["package"],
                spec["attributes"]["memory_global_best_runtime"],
            )

        # Either way, we set the assignment because submit_job does not
        if assigned_to not in assignments:
            assignments[assigned_to] = []
        assignments[assigned_to].append(jobid)

        # Mimic final selection here, we have to choose a cluster based on the model
        # and then update its metadata to have one less slot
        if not with_replacement and "unmatched" not in assigned_to:
            nodes_free = clusters[assigned_to]["nodes_free"]
            clusters[assigned_to]["nodes_free"] = max(0, nodes_free - nodes_per_job)
            update_cluster_state(assigned_to, metadata={"nodes_free": nodes_free})

        if "unmatched" in assigned_to:
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


def run(args):
    """
    Run the experiments.
    """
    global clusters

    # Make a config that allows authenticating to each cluster
    # This is the hostname, cluster name (defaults to rainbow) and register secret
    cfg = config.RainbowConfig(config_file)

    # In practice, all of the tokens are "rainbow"
    for cluster, meta in clusters.items():
        cfg.add_cluster(cluster, meta["token"])

    # Just manually set the config on the client, being lazy
    cli.cfg = cfg

    # Set selection to be random for basic case for first set of experiments
    # we won't add constraints until we get an optimal scoring, then we will
    # try to optimize cost/memory
    cli.cfg.set_selection_algorithm("random")

    # Read in jobspec files and save based on name
    jobspec_files = [os.path.join(args.jobspecs, x) for x in os.listdir(args.jobspecs)]

    # Remove repeated ones.
    jobspecs, repeated = get_unique_jobspecs_from_file(jobspec_files)
    subset = {}

    # Testing mode
    if args.testing:
        count = 0
        for key, rest in jobspecs.items():
            if count >= 100:
                break
            subset[key] = rest
            count += 1
        jobspecs = subset

    # Now that we know the number of jobspecs, we can calculate the
    # number of nodes free per cluster (jobspecs / clusters) * job size
    nodes_free = math.ceil(len(jobspecs) / len(clusters) * nodes_per_job)

    # Set the cluster starting state. This would mimic a response
    # that a cluster sends back to rainbow after accepting jobs
    for cluster_name, cluster_meta in clusters.items():
        # Keep state synced here to update, simulating the cluster
        clusters[cluster_name]["nodes_free"] = nodes_free
        update_cluster_state(
            cluster_name, metadata={"nodes_free": nodes_free}, init=True
        )

    print(f"Total jobspecs: {len(jobspecs)}")
    print(f"Repeated jobspecs: {repeated}")
    metadata = {"jobspecs": jobspecs, "removed_repeated": repeated}
    write_json(metadata, os.path.join(args.outdir, "jobspecs.json"))
    scores = {}

    # CASE 1: no subsystem knowledge
    print("\n\n === BASE EXPERIMENTS START ===\n\n")
    assignments, stats = run_base_experiment(jobspecs)
    print("\n\n === BASE EXPERIMENTS DONE ===\n\n")

    # See how well we did! A score of 0 means it wouldn't be compatible
    scores["none"] = calculate_scores(assignments, jobspecs, cluster_truth, stats)

    # Save data as we go
    write_json(scores, os.path.join(args.outdir, "scores.json"))

    # Register all subsystems at once - every cluster has the same set
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

    # Reset assignments
    assignments = {}

    # CASE 2..2+ subsystems: add subsystems (a la carte)
    # Note that if this gets too large, we can retrieve the job assignments
    # from rainbow and that clears them up in the remote database.
    print("\n\n === SINGLE SUBSYSTEM EXPERIMENTS START ===\n\n")

    # compiler-version is the same subsytem as compiler, but we add more metadata
    # Note that memory won't function well without a range setting.
    order = ["arch", "compiler", "compiler-version", "memory"]
    for subsystem in order:
        new_assignments, stats = run_single_subsystem_experiment(subsystem, jobspecs)
        assignments[subsystem] = new_assignments
        scores[f"{subsystem}-subsystem"] = calculate_scores(
            assignments[subsystem], jobspecs, cluster_truth, stats
        )

    # print("\n\n === SINGLE SUBSYSTEM EXPERIMENTS DONE ===\n\n")
    write_json(assignments, os.path.join(args.outdir, "subsystem-assignments.json"))

    # Save scores as we go
    write_json(scores, os.path.join(args.outdir, "scores.json"))

    # CASE 3...N subsystems added in order
    print("\n\n === EXPANDING SUBSYSTEM EXPERIMENTS START ===\n\n")
    assignments, unmatched_at, stats = run_expanding_subystem_experiment(
        order, jobspecs
    )
    print("\n\n === EXPANDING SUBSYSTEM EXPERIMENTS DONE ===\n\n")

    # Calculate scores for each subsystem combination
    for uid, st in stats.items():
        scores[uid] = calculate_scores(assignments[uid], jobspecs, cluster_truth, st)

    # unmatched at is the level of compatibility metadata that we added where there was no longer any match
    scores["unmatched_at"] = calculate_unmatched_scoring(unmatched_at)

    # Save raw unmatched at distribution, along with the total number of feature (package deps)
    # as a percentage of unmatched
    summary_unmatched = calculate_summary_unmatched(unmatched_at, jobspecs)
    write_json(summary_unmatched, os.path.join(args.outdir, "unmatched-summary.json"))
    write_json(unmatched_at, os.path.join(args.outdir, "unmatched-at-raw.json"))

    # Finally, we are going to take each job, and remove clusters that didn't match with all the data
    # With the remaining set we are going to add the constraint and have rainbow return ALL the matches
    # and we will calculate our algorithm locally. I'm doing this because otherwise we'd need to serve
    # the same models alongside rainbow -something we can do but needs some thought.
    matching = {k: v for k, v in jobspecs.items() if k not in unmatched_at}

    print("\n\n === CONSTRAINT EXPERIMENTS START ===\n\n")
    cli.cfg.set_selection_algorithm("constraint", select_options)
    assignments, unmatched_at, stats = run_constraint_experiment(
        order, matching, with_replacement=True
    )

    # Same scoring
    scores["constraint-with-replacement"] = calculate_scores(
        assignments, jobspecs, cluster_truth, stats
    )

    # Now don't allow clusters to be used twice
    assignments, unmatched_at, stats = run_constraint_experiment(
        order, matching, with_replacement=False
    )
    scores["constraint-without-replacement"] = calculate_scores(
        assignments, jobspecs, cluster_truth, stats
    )

    import IPython

    IPython.embed()
    sys.exit()

    print("\n\n === CONSTRAINT EXPERIMENTS FINISHED ===\n\n")
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


def do_final_selection(contenders, package, memory_best_runtime):
    """
    Given a selection with >1 cluster, do final assignment.

    We want to minimize the build cost, regardless of all else.
    """
    # Assume minimum cost is the first
    min_cost_cluster = None
    smallest_cost = None
    for contender in contenders:
        cluster_name = contender.replace("cluster-", "")
        cluster_features = cluster_truth[cluster_name]
        shaped = numpy.array(cluster_features["memory"]).reshape(-1, 1)
        predicted_duration = models[package].predict(shaped)[0]

        # Calculate total cost
        hours_runtime = predicted_duration / 60 / 60
        total_cost = hours_runtime * cluster_features["cost_per_node_hour"]
        print(f"Cluster {contender} has a total cost of {total_cost}")
        if smallest_cost is None or total_cost < smallest_cost:
            smallest_cost = total_cost
            min_cost_cluster = contender

    print(f"The lowest cost cluster is {min_cost_cluster}")
    return min_cost_cluster


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
        "--testing",
        action="store_true",
        help="testing mode (only 100 jobspecs)",
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


def update_cluster_state(cluster_name, metadata, init=False):
    """
    get cluster state returns cluster state metadata.
    If no metadata is provided, we are assuming an init
    and also set unchanging variables like cost and memory
    per node.
    """
    # If we are init-ing, also set memory and cost
    cluster_color = cluster_name.replace("cluster-", "")
    truth = cluster_truth[cluster_color]
    cluster_meta = clusters[cluster_name]
    if init:
        metadata["cost_per_node_hour"] = truth["cost_per_node_hour"]
        metadata["memory_per_node"] = truth["memory"]
    update_state(cluster_name, cluster_meta["secret"], metadata)


def update_state(cluster_name, secret, metadata):
    """
    Update state for a cluster.
    """
    response = cli.update_state(cluster_name, secret=secret, state_data=metadata)
    if response.status not in update_state_success:
        raise ValueError(f"Issue updating state of cluster {cluster_name}: {response}")

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
    global clusters

    parser = get_parser()
    args, _ = parser.parse_known_args()
    outdir = os.path.abspath(args.outdir)

    # Create the client
    cli = RainbowClient(host=args.host)

    # Also organize results by mode
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)
    cluster_nodes = list(recursive_find(args.clusters, "nodes.json"))

    # Show parameters to the user
    print(f"▶️  Output directory: {outdir}")
    print(f"▶️          Jobspecs: {args.jobspecs}")
    print(f"▶️          Clusters: {len(cluster_nodes)}")
    print(f"▶️           Testing: {args.testing}")

    if not args.force and not confirm_action("Would you like to continue?"):
        sys.exit("Cancelled!")

    # Find cluster nodes and register
    # Here we are also updating their state. Each has equal resources.
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

    try:
        run(args)
    except Exception as e:
        print(e)
        raise


if __name__ == "__main__":
    main()
