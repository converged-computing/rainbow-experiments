#!/usr/bin/env python3

import argparse
import os
import re

import matplotlib.pyplot as plt
import pandas
import seaborn as sns
import json

plt.style.use("bmh")
here = os.path.dirname(os.path.abspath(__file__))


def get_parser():
    parser = argparse.ArgumentParser(
        description="Plot Version Matching Descriptive Results",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--results",
        help="directory with raw results data",
        default=os.path.join(here, "results"),
    )
    parser.add_argument(
        "--out",
        help="directory to save parsed results",
        default=os.path.join(here, "img"),
    )
    return parser


def recursive_find(base, pattern="specs.json"):
    """
    Recursively find and yield files matching a glob pattern.
    """
    for root, _, filenames in os.walk(base):
        for filename in filenames:
            if re.search(pattern, filename):
                yield os.path.join(root, filename)


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


def main():
    parser = get_parser()
    args, _ = parser.parse_known_args()

    # Output images and data
    outdir = os.path.abspath(args.out)
    indir = os.path.abspath(args.results)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    # Read in input files
    jobspecs = read_json(os.path.join(indir, "jobspecs.json"))
    scores = read_json(os.path.join(indir, "scores.json"))
    unmatched = read_json(os.path.join(indir, "unmatched-summary.json"))
    subsys = read_json(os.path.join(indir, "subsystem-scores.json"))

    # This does the actual parsing of data into a formatted variant
    # Has keys results, iters, and columns
    dfs = parse_data(jobspecs, scores, unmatched, subsys)
    for uid, df in dfs.items():
        df.to_csv(os.path.join(outdir, f"{uid}.csv"))
    plot_results(dfs, outdir)


def plot_results(dfs, outdir):
    """
    Plot results
    """
    score_df = dfs["scores"]
    unmatched = dfs["unmatched_at"]
    # subsys = dfs["subsys"]

    plt.figure(figsize=(12, 8))

    # score_df['lower_bound'] = score_df['build_success_mean'] - score_df['build_success_std']
    # score_df['upper_bound'] = score_df['build_success_mean'] + score_df['build_success_std']

    # First make simple boxplot that shows build success and std
    # linedf = pandas.DataFrame({
    #    'experiment': score_df['experiment'],
    #    'build_success': score_df['build_success_mean'],
    #    'lower_bound': score_df['lower_bound'],
    #    'upper_bound': score_df['upper_bound']})

    # melted = pandas.melt(linedf, ['experiment'])
    # melted.columns = ['experiment', '', 'build_success']
    # sns.lineplot(x='experiment', y='build_success', hue='', data=melted)
    ax = sns.lineplot(x="experiment", y="build_success_mean", data=score_df)

    sns.set_style("dark")
    plt.title("Mean Build Success Adding Version Subsystems", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Percentage builds successful", fontsize=14)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    plt.savefig(os.path.join(outdir, "build-success.png"))
    plt.clf()

    ax = sns.lineplot(x="experiment", y="marginal_score_mean", data=score_df)

    sns.set_style("dark")
    plt.title("Marginal Score Adding Version Subsystems", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Score (percentage version ranges correct)", fontsize=14)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    plt.savefig(os.path.join(outdir, "marginal-score.png"))
    plt.clf()

    ax = sns.histplot(x="max_percent_matched", data=unmatched)
    sns.set_style("dark")
    plt.title("Max % Subsystems Matched Before Rainbow Could not Match", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.set_xlabel("Percent of Subsystems Matched", fontsize=14)
    plt.savefig(os.path.join(outdir, "percent-matched.png"))
    plt.clf()

    ax = sns.histplot(x="unmatched_at", data=unmatched)
    sns.set_style("dark")
    plt.title("Subsystem Incremental Count When Job Became Unmatched", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.set_xlabel("Count at Unmatch", fontsize=14)
    plt.savefig(os.path.join(outdir, "count-unmatched.png"))
    plt.clf()


def parse_data(jobspecs, scores, unmatched, subsys):
    """
    Parse data to answer questions!
    """
    df = pandas.DataFrame(
        columns=[
            "experiment",
            "build_success_mean",
            "build_success_std",
            "marginal_score_mean",
            "marginal_score_std",
            "versions_in_range_correct",
            "versions_in_range_possible",
            "matched_clusters_per_job_mean",
            "matched_clusters_per_job_std",
            "mismatched_clusters_per_job_mean",
            "mismatched_clusters_per_job_std",
            "total_clusters",
        ]
    )

    idx = 0
    for experiment, data in scores.items():
        if experiment == "unmatched_at":
            continue
        df.loc[idx, :] = [
            experiment,
            data["build_success"]["mean"],
            data["build_success"]["std"],
            data["marginal_score"]["mean"],
            data["marginal_score"]["std"],
            data["versions_in_range"]["total_correct"],
            data["versions_in_range"]["total_possible"],
            data["matched_clusters_per_job"]["mean"],
            data["matched_clusters_per_job"]["std"],
            data["mismatched_clusters_per_job"]["mean"],
            data["mismatched_clusters_per_job"]["std"],
            100,
        ]
        idx += 1

    df["percent_versions_correct"] = (
        df.versions_in_range_correct / df.versions_in_range_possible
    )

    # Look at breakdown of by subsystem (not a lot of jobs per subsystem)
    sdf = pandas.DataFrame(
        columns=[
            "subsystem",
            "build_success_mean",
            "build_success_std",
            "marginal_score_mean",
            "marginal_score_std",
            "total_jobs",
        ]
    )

    # Note that the total jobs / subsystem is too small to make use of
    idx = 0
    for s, data in subsys.items():
        if data["total_jobs"]["value"] == 0:
            continue
        sdf.loc[idx, :] = [
            s,
            data["build_success"]["mean"],
            data["build_success"]["std"],
            data["marginal_score"]["mean"],
            data["marginal_score"]["std"],
            data["total_jobs"]["value"],
        ]
        idx += 1

    # Now look at unmatched
    print(scores["unmatched_at"])
    udf = pandas.DataFrame(unmatched)
    return {"unmatched_at": udf, "scores": df, "subsys": sdf}


# 1. How many builds would be successful based on having all dependencies in the matched ranges
# 1. The change in matching clusters as we add compatibility metadata (more dependency version constaints)
# 1. The marginal points (number of version ranges that were right, even if the build might fail) for each.
# 1. Patterns of the above across cases of providing no compatibility metadata, metadata for one subsystem (package dependency) and then increasing numbers of subsystems
# 1. The incremental addition (number of subsystems) that deemed rainbow could not match the job anywhere.


if __name__ == "__main__":
    main()
