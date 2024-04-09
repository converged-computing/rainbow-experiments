#!/usr/bin/env python3

import argparse
import os
import re

from matplotlib.ticker import FormatStrFormatter
import matplotlib.pyplot as plt
import pandas
import seaborn as sns
import json

plt.style.use("bmh")
here = os.path.dirname(os.path.abspath(__file__))

skips = ["unmatched_at", "unmatched", "reasons_for_failure"]


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
    ideal_costs = read_json(os.path.join(indir, "cluster-package-ideal-costs.json"))

    # This does the actual parsing of data into a formatted variant
    # Has keys results, iters, and columns
    dfs = parse_data(jobspecs, scores, unmatched)
    for uid, df in dfs.items():
        df.to_csv(os.path.join(outdir, f"{uid}.csv"))
    plot_results(dfs, outdir)
    plot_histograms(scores, ideal_costs, outdir)


def plot_histograms(scores, ideal_costs, outdir):
    # Additional runtime by cluster
    fig, axes = plt.subplots(11)
    fig.set_figheight(50)
    fig.set_figwidth(12)

    i = 0
    for experiment, data in scores.items():
        cluster_costs = []
        if experiment in skips:
            continue
        for _, costlist in data["additional_costs"]["additional_costs"].items():
            cluster_costs += costlist

        axes[i].hist(cluster_costs, bins=100)
        plt.title(f"Additional Runtime For {experiment}", fontsize=14)
        axes[i].set_xticklabels(axes[i].get_xmajorticklabels(), fontsize=14)
        axes[i].set_yticklabels(axes[i].get_yticks(), fontsize=14)
        axes[i].set_xlabel(
            f"Runtime (seconds) for Experiment {experiment}", fontsize=14
        )
        i += 1

    fig.suptitle("Additional Runtime Across Clusters and Experiments")
    plt.savefig(os.path.join(outdir, "additional-runtime-experiments-hists.png"))
    plt.clf()

    # Additional costs per cluster
    fig, axes = plt.subplots(11)
    fig.set_figheight(50)
    fig.set_figwidth(12)

    i = 0
    for experiment, data in scores.items():
        cluster_costs = []
        if experiment in skips:
            continue
        for _, costlist in data["additional_costs"]["additional_costs"].items():
            cluster_costs += costlist

        axes[i].hist(cluster_costs, bins=100)
        plt.title(f"Additional Cost For Experiment {experiment}", fontsize=14)
        axes[i].set_xticklabels(axes[i].get_xmajorticklabels(), fontsize=14)
        axes[i].set_yticklabels(axes[i].get_yticks(), fontsize=14)
        axes[i].set_xlabel(f"Cost ($) for Experiment {experiment}", fontsize=14)
        i += 1

    fig.suptitle("Additional Cost Across Clusters and Experiments")
    plt.savefig(os.path.join(outdir, "additional-costs-experiments-hists.png"))
    plt.clf()

    # Plot reasons for failure
    rdf = pandas.DataFrame(columns=["experiment", "reason_for_failure", "count"])
    idx = 0

    for experiment, data in scores.items():
        if experiment == "unmatched_at":
            continue
        reasons = data["reasons_for_failure"]
        for reason, count in reasons.items():
            rdf.loc[idx] = [experiment, reason, count]
            idx += 1

    # Also calculate percentage for each
    total_counts = {}
    for experiment in rdf.experiment.unique():
        total_counts[experiment] = rdf[rdf.experiment == experiment]["count"].sum()
    rdf.loc[:, "total_count"] = 0
    for experiment, count in total_counts.items():
        rdf.loc[rdf.experiment == experiment, "total_count"] = count
    rdf["percentage"] = rdf["count"] / rdf.total_count

    # That makes some nans
    rdf = rdf.fillna(0)

    rdf.to_csv(os.path.join(outdir, "reasons-for-failure.csv"))

    # Remove reasons for failure with values of 0.
    # rdf = rdf[rdf['count'] != 0]

    # make labels more human friendly to read
    rdf.reason_for_failure[
        rdf.reason_for_failure == "compiler_too_old"
    ] = "compiler too old"
    rdf.reason_for_failure[rdf.reason_for_failure == "wrong_arch"] = "wrong arch"
    rdf.reason_for_failure[
        rdf.reason_for_failure == "missing_compiler"
    ] = "missing compiler"

    plt.figure(figsize=(12, 8))
    ax = sns.barplot(x="experiment", y="count", hue="reason_for_failure", data=rdf)
    plt.title("Reasons for Failure Across Experiments")
    ax.set_xlabel("Experiment", fontsize=16)
    ax.set_ylabel("Count", fontsize=16)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.tick_params(axis="x", labelrotation=90)
    plt.savefig(os.path.join(outdir, "reasons-for-failure.png"), bbox_inches="tight")
    plt.clf()

    # Also plot as percentage
    ax = sns.barplot(x="experiment", y="percentage", hue="reason_for_failure", data=rdf)
    plt.title("Reasons for Failure (Percentages) Across Experiments")
    ax.set_xlabel("Experiment", fontsize=16)
    ax.set_ylabel("Percent of Total", fontsize=16)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.tick_params(axis="x", labelrotation=90)
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    plt.savefig(
        os.path.join(outdir, "reasons-for-failure-percentage.png"), bbox_inches="tight"
    )
    plt.clf()

    # Try plotting by package
    df = pandas.DataFrame(columns=["package", "runtime", "cost"])
    idx = 0

    for experiment, data in scores.items():
        if experiment in skips:
            continue
        print(f"Processing experiment {experiment}")
        for package, costlist in data["additional_costs"]["additional_costs"].items():
            for i, c in enumerate(costlist):
                cc = data["additional_runtime"]["additional_runtimes"][package][i]
                df.loc[idx] = [package, cc, c]
                idx += 1

    plt.figure(figsize=(20, 12))
    sns.set_style("dark")
    ax = sns.boxplot(x="package", y="runtime", hue="package", data=df, whis=[5, 95])
    plt.title("Runtime by Package")
    ax.set_xlabel("Package", fontsize=16)
    ax.set_ylabel("Runtime", fontsize=16)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=10)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.tick_params(axis="x", labelrotation=45)
    plt.savefig(os.path.join(outdir, "runtimes-by-package.png"))
    plt.clf()

    plt.figure(figsize=(20, 12))
    sns.set_style("dark")
    ax = sns.boxplot(x="package", y="cost", hue="package", data=df, whis=[5, 95])
    plt.title("Cost by Package")
    ax.set_xlabel("Package", fontsize=16)
    ax.set_ylabel("Cost", fontsize=16)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=10)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.tick_params(axis="x", labelrotation=45)
    plt.savefig(os.path.join(outdir, "costs-by-package.png"))
    plt.clf()


def plot_results(dfs, outdir):
    """
    Plot results
    """
    score_df = dfs["scores"]
    unmatched = dfs["unmatched_at"]

    ax = sns.countplot(x="unmatched_at", data=unmatched)
    sns.set_style("dark")
    plt.title("Subsystem Incremental Count When Job Became Unmatched", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=14)
    ax.set_xlabel("Count at Unmatch", fontsize=14)
    plt.savefig(os.path.join(outdir, "count-unmatched.png"))
    plt.clf()

    # score_df['lower_bound'] = score_df['build_success_mean'] - score_df['build_success_std']
    # score_df['upper_bound'] = score_df['build_success_mean'] + score_df['build_success_std']

    # First make simple boxplot that shows build success and std
    # linedf = pandas.DataFrame({
    #    'experiment': score_df['experiment'],
    #    'build_success': score_df['build_success_mean'],
    #    'lower_bound': score_df['lower_bound'],
    #    'upper_bound': score_df['upper_bound']})

    # Calculate percent matches from means
    score_df["matched_clusters_percent_mean"] = (
        score_df["matched_clusters_per_job_mean"] / 100
    )

    order = [
        "none",
        "compiler-version-subsystem",
        "compiler-subsystem",
        "arch-subsystem",
        "memory-subsystem",
        "arch",
        "arch-compiler",
        "arch-compiler-compiler-version",
        "arch-compiler-compiler-version-memory",
        "constraint-with-replacement",
        "constraint-without-replacement",
    ]
    score_df["experiment"] = pandas.Categorical(score_df["experiment"], order)

    # Build Success vs. Points - note I checked, this is exactly the same
    # (as it should be) - the lines overlap
    score_df["percent_points_earned"] = (
        score_df["points_scored_correct"] / score_df["points_scored_possible"]
    )

    # Build Success vs. Number matches
    # TODO how to order these?
    fig, ax = plt.subplots()
    fig.set_figheight(12)
    fig.set_figwidth(12)
    sns.pointplot(
        x="experiment",
        y="build_success_mean",
        data=score_df,
        label="build success",
        color="blue",
    )
    sns.pointplot(
        x="experiment",
        y="matched_clusters_percent_mean",
        data=score_df,
        label="clusters matched",
        color="green",
    )
    sns.set_style("dark")
    plt.title("Tradeoff Between Build Success and Cluster Matches", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Percentage builds successful", fontsize=14)
    ax.tick_params(axis="x", labelrotation=45)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    fig.tight_layout()
    ax.legend()
    plt.savefig(os.path.join(outdir, "build-success.png"))
    plt.clf()

    # Matched vs. Mismatched clusters
    fig, ax = plt.subplots()
    fig.set_figheight(12)
    fig.set_figwidth(12)
    sns.pointplot(
        x="experiment",
        y="matched_clusters_per_job_mean",
        data=score_df,
        label="matched clusters",
        color="green",
    )
    sns.pointplot(
        x="experiment",
        y="mismatched_clusters_per_job_mean",
        data=score_df,
        label="mismatched clusters",
        color="darkorange",
    )
    sns.set_style("dark")
    plt.title("Matched vs. Mismatched Clusters by Experiment (mean)", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Percent Clusters Matched", fontsize=14)
    ax.tick_params(axis="x", labelrotation=45)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    fig.tight_layout()
    ax.legend()
    plt.savefig(os.path.join(outdir, "clusters-matched.png"))
    plt.clf()

    # Total Additional Runtime
    fig, ax = plt.subplots()
    fig.set_figheight(12)
    fig.set_figwidth(12)
    sns.pointplot(
        x="experiment",
        y="total_additional_runtime_seconds",
        data=score_df,
        label="additional runtime",
        color="darkorange",
    )
    sns.set_style("dark")
    plt.title("Additional Runtime by Experiment (mean)", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Additional Runtime (seconds)", fontsize=14)
    ax.tick_params(axis="x", labelrotation=45)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    fig.tight_layout()
    ax.legend()
    plt.savefig(os.path.join(outdir, "additional-runtime.png"))
    plt.clf()

    # Total Additional Cost
    fig, ax = plt.subplots()
    fig.set_figheight(12)
    fig.set_figwidth(12)
    sns.pointplot(
        x="experiment",
        y="total_additional_cost",
        data=score_df,
        label="additional cost",
        color="darkgreen",
    )
    sns.set_style("dark")
    plt.title("Additional Cost by Experiment", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Additional Cost ($) for simulated jobs", fontsize=14)
    ax.tick_params(axis="x", labelrotation=45)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    fig.tight_layout()
    ax.legend()
    plt.savefig(os.path.join(outdir, "additional-cost.png"))
    plt.clf()

    # Try to calculate additional cost per job
    score_df["additional_cost_per_job"] = (
        score_df["total_additional_cost"] / score_df["total_jobs"]
    )

    # Total Additional Cost by job (there are three sizes so above is not right)
    fig, ax = plt.subplots()
    fig.set_figheight(12)
    fig.set_figwidth(12)
    sns.pointplot(
        x="experiment",
        y="additional_cost_per_job",
        data=score_df,
        label="additional cost per job",
        color="darkgreen",
    )
    sns.set_style("dark")
    plt.title("Additional Cost per Job by Experiment (mean)", fontsize=14)
    ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=14)
    ax.set_yticklabels(ax.get_yticks(), fontsize=10)
    ax.set_xlabel("Experiment", fontsize=14)
    ax.set_ylabel("Additional Cost ($) simulated jobs", fontsize=14)
    ax.tick_params(axis="x", labelrotation=45)
    ylabels = ["{:,.2f}".format(x) for x in ax.get_yticks()]
    ax.set_yticklabels(ylabels)
    fig.tight_layout()
    ax.legend()
    plt.savefig(os.path.join(outdir, "additional-cost-per-job.png"))
    plt.clf()


def parse_data(jobspecs, scores, unmatched):
    """
    Parse data to answer questions!
    """
    df = pandas.DataFrame(
        columns=[
            "experiment",
            "total_additional_runtime_seconds",
            "total_additional_cost",
            "unmatched_percent",
            "unmatched_count",
            "build_success_mean",
            "build_success_std",
            # 1 point == successful build
            "points_scored_correct",
            "points_scored_incorrect",
            "points_scored_possible",
            "matched_clusters_per_job_mean",
            "matched_clusters_per_job_std",
            "mismatched_clusters_per_job_mean",
            "mismatched_clusters_per_job_std",
            "total_jobs",
            "total_clusters",
        ]
    )

    idx = 0
    for experiment, data in scores.items():
        if experiment in skips:
            continue
        df.loc[idx, :] = [
            experiment,
            # These second values were incorrectly named in originally runs, but data correct
            data["additional_runtime"]["total_additional_runtime"],
            data["additional_costs"]["total_additional_cost"],
            data["unmatched_percent"]["value"],
            data["unmatched"]["value"],
            data["build_success"]["mean"],
            data["build_success"]["std"],
            data["points_scored"]["total_correct"],
            data["points_scored"]["total_incorrect"],
            data["points_scored"]["total_possible"],
            data["matched_clusters_per_job"]["mean"],
            data["matched_clusters_per_job"]["std"],
            data["mismatched_clusters_per_job"]["mean"],
            data["mismatched_clusters_per_job"]["std"],
            data["total_jobs"]["value"],
            100,
        ]
        idx += 1

    # Now look at unmatched
    print(scores["unmatched_at"])
    udf = pandas.DataFrame(unmatched)
    return {"unmatched_at": udf, "scores": df}


if __name__ == "__main__":
    main()
