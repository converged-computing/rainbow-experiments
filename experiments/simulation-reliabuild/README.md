# Descriptive Expression + Scheduler Simulation

> Algorithm: direct match with reliabuild metadata

- [publication](https://www.osti.gov/biblio/2223030)
- [build spec generator](https://github.com/buildsi/spack-buildspace-exploration)

We started with a base simulation in [simulation-lammps](../simulation-lammps) and this experiment aims to improve upon that by using actual data and some modeling. Specifically, what I've scoped out. We impressive dataset, about 25K spack specs. For each spack spec I have a data frame of if the build was a success, failure, and given failure, why. I'm thinking what we might want to do is:

1. For each spec that failed filter down to those that have a root failure (meaning it wasn't a spack child/dependency that failed it, but something about building the core package)
1. All successes can be included. We know they build.
1. Decide on core features from the specs we want to model (e.g., platform, os, target, compiler and version and a subset of features, stuff from the core package). We likely can choose most of them.
1. Remove features that are consistent (e.g., it says in the paper they were run on the same os, so this is irrelevant)
1. Each spack spec becomes a vector of features!
1. Break the specs down by the package (this is a combination of the ECP / proxy app stuffs).
1. For each package, build a bayesian model that predicts success or failure based on the actual features
1. We then create cluster environments, akin to the first experiment, that have every combination of features (or close to that if the number is astronomically large, I think even 1K+ clusters would be OK).
1. For each level of compatibility metadata, submit the job to rainbow, again get a cluster assignment. Each cluster is also a vector of those same features.
1. When we finish submitting all jobspecs (spack build specs) we have a set assigned to every cluster.
For each cluster set, use the package model to calculate the probably of success given the feature vector of the cluster (P success | cluster environment)
1. This gives us a set of probability scores for each cluster
1. Across clusters, the simplest thing we can then do is the sum of scores / total points possible

High level, the above allows us to derive a probability from a model that is specific to the package (this is important I think) of success given an assigned environment. This feels similar to what we probably would eventually do, because I think the way we understand compatibility is going to vary on the app level (here that is spack package builds). It's based on real data, will be a large scale, and will be super cool!

## Setup

First prepare data in [data](data) (see README.md there for instructions). At the end we have:

- 119 unique features (that are package metadata, there can be >1 per subsystem, e.g., `<package>-version` and `<package>-compiler-version`
- 113 unique package subsytems
- 1000 clusters with randomly selected compatibility features
- Over 25K jobspecs (split into groups of 1K so the files aren't too huge)
- 50 models for 50 packages represented in the jobspecs that we want to build

Note that in parsing the data I discovered that we have variability with respect primarily to package versions (dependencies). Thus, a subsystem is actually going to be a package dependency, with typically 1-2 features for each. This also means our experiment design is going to be huge (won't need to run iterations).

### Experiment

#### 1. Rainbow

First, let's run rainbow. We will keep this really simple - running locally, and that way you could, for example, add in a new algorithm and re-deploy the cluster with just a control-C and `make server`. 

```bash
git clone https://github.com/converged-computing/rainbow
cd rainbow
go mod vendor

# See what you can do
go run cmd/server/server.go --help

# We can use all the defaults, and set a global token. Run it:
go run cmd/server/server.go --global-token rainbow
```
```console
2024/03/20 00:27:55 creating 🌈️ server...
2024/03/20 00:27:55 🧩️ selection algorithm: random
2024/03/20 00:27:55 🧩️ graph database: memory
2024/03/20 00:27:55 ✨️ creating rainbow.db...
2024/03/20 00:27:55    rainbow.db file created
2024/03/20 00:27:55    🏓️ creating tables...
2024/03/20 00:27:55    🏓️ tables created
2024/03/20 00:27:55 ⚠️ WARNING: global-token is set, use with caution.
2024/03/20 00:27:55 starting scheduler server: rainbow v0.1.1-draft
2024/03/20 00:27:55 🧠️ Registering memory graph database...
2024/03/20 00:27:55 server listening: [::]:50051
```

#### 2. Python

Since we have everything locally, we can actually do the entire thing in Python! We will (in one script, I know):

For each cluster:

1. register cluster
2. register 113 subsystems
3. run the experiment with 25K jobspecs without any subsystem metadata
4. for each subsytem (randomly sorted, N=113):
 - submit each jobspec (25k+) with added subsystem metadata
 - for each cluster, get assigned jobs:
  - use build package specific model to get P(success|features)
  - save scores across cluster

Calculate overall scores for each subsytem group (incrementally added)
We would want to see that as we add compatibility metadata (package dependencies), we get more matches. Since the jobspecs don't have perfect clusters, note that there might not be a perfect match. This means as we add more constraints, jobs won't even be allowed to be submit if there is not a matching cluster.

```bash
python run_experiments.py
```

Note that we might try this again building a model that doesn't use categorical version features, but numerical.
