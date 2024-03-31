# Descriptive Expression + Scheduler Simulation

> Algorithm: direct match with reliabuild metadata

- [publication](https://www.osti.gov/biblio/2223030)
- [build spec generator](https://github.com/buildsi/spack-buildspace-exploration)

We started with a base simulation in [simulation-lammps](../simulation-lammps) and this experiment aims to improve upon that by using actual data and extending compatibility to the case of software version ranges. We are going to do the following:

1. For the real dataset (spack specs) filter down to those that were successful. We know they build.
1. The package dependency versions are the features. This means rainbow needed an algorithm addition to match a version range.
1. Create cluster environments that have a randomly selected version (from the set in the experiment)
1. One level of compatibility metadata is a dependency version. Submit jobs to rainbow, first with no metadata, and then adding version *ranges* for specific packages. E.g., "Does this build environment have a version that is within this range?" 
1. When we finish submitting all jobspecs (spack build specs) we have a set assigned to every cluster.
1. Calculate a score (versions that correctly overlap over total)

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
go run cmd/server/server.go --global-token rainbow --match-algorithm range
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

1. register 100 randomly generated clusters, each with varying ranges of dependency versions (subsystems)
1. register ~113 subsystems across 100 clusters
1. run the experiment with ~10K jobspecs without any subsystem metadata
1. run the expemiments adding each subsystem in isolation
1. for each subsystem (randomly sorted):
 - submit each jobspec with added subsystem metadata, adding subsystem metadata until no match (then stopping)
 - for each cluster, get assigned jobs:
  - give a point for each package build dependency version in the right range
  - keep track of unmatched jobs, etc.
  - save scores across cluster

We would want to see that as we add compatibility metadata (package dependencies), we get more matches. But I suspect with these versions, we are going to see the original set is fairly good (there aren't that many versions) and then it might go up slightly, but then go down. I hypothesize this experiment will be an example of the over fitting case, where when we ask too much from a limited set of clusters (that is not generated perfectly for our needs) we get fewer matches if we ask for too many things. 

We will see!

```bash
python run_experiments.py
```
