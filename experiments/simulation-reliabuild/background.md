# Notes

We started with an impressive dataset, about 25K spack specs. For each spack spec I have a data frame of if the build was a success, failure, and given failure, why. I'm thinking what we might want to do is:

1. For each spec filter down to those that were successful. We will assume all others not in that set would fail.
1. The package dependencies are the features
1. Remove features that are consistent (e.g., it says in the paper they were run on the same os, so this is irrelevant)
1. Each spack spec becomes a vector of features!
1. Create cluster environments, akin to the first experiment, that have every combination of features (or close to that if the number is astronomically large, I think even 1K+ clusters would be OK).
1. For each level of compatibility metadata, submit the job to rainbow, again get a cluster assignment. Each cluster is also a vector of those same features.
1. When we finish submitting all jobspecs (spack build specs) we have a set assigned to every cluster.
1. For each cluster set, determine features needed vs. present, and for those present, calculate a difference between the found version and actual version. Newer versions are not compatible with older ones (assuming new features) but older versions we can calculate some diff to say distance to working.
1. Calculate an overall score for each cluster (total points/total possible)

High level, the above allows us to derive a probability from a model that is specific to the package (this is important I think) of success given an assigned environment. This feels similar to what we probably would eventually do, because I think the way we understand compatibility is going to vary on the app level (here that is spack package builds). It's based on real data, will be a large scale, and will be super cool!

# TODO check length of jobspecs.yaml
# we should have a scoring algorithm for a jobspec assignment:
# if version is newer, assume not compatible (or distance?)
# use puython version parsing to calculate distance
# weighted features = cosine distance of two? 1 == perfect, 0 == totally wrong
# score of assignment = (weighted features / total features needed)


## Setup

First prepare data in [data](data) (see README.md there for instructions). At the end we have:

- 119 unique features (that are package metadata, there can be >1 per subsystem, e.g., `<package>-version` and `<package>-compiler-version`
- 113 unique package subssytems
- 1000 clusters with randomly selected compatibility features
- Over 25K jobspecs (split into groups of 1K so the files aren't too huge)
- 50 models for 50 packages represented in the jobspecs that we want to build

Note that in parsing the data I discovered that we have variability with respect primarily to package versions (dependencies). Thus, a subsystem is actually going to be a package dependency, with typically 1-2 features for each. This also means our experiment design is going to be huge (won't need to run iterations).

