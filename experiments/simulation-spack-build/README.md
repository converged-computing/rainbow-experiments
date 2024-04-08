# Descriptive Expression + Scheduler Simulation

> using spack build metadata

From the models in [data](data) we can see that memory (mean and max) is correlated with duration. We can thus view memory as a compatibility feature that is indicative of performance.

## Notes

We are going to generate [clusters](data/clusters) based on actual jobpsecs (with features across arch, memory, compiler,and version) and build package-specific KNN models to predict runtime from a memory. Some notes:

- more memory provided to jobs means more performant (faster) runs
- we can thus treat runtime (duration) as a performance metric, and memory as the compatibility metadata that influences it.
- we have one gradient of metadata, and a divider in the middle (I will make visuals of this):
  - **compatibility metadata**: is the minimum metadata represented in subsystems, compared to jobspecs, required to maximize build success
  - **optimization**: is any combination of algorithm or metadata on top of that to optimize the build (e.g., in this experiment, it will come down to lower cost)
- we can still include basic compatibility metadata (e.g., arch) to demonstrate the basic needs of compatibility metadata
- we can then vary memory on clusters (and use real memory values from jobspecs) to generate different runtimes
- we can generate clusters based on values of memory across real spack builds
- we can define the most performant case per package as the memory value where it ran most quickly
- we can then use the spack builds to generate real jobspecs, each defined in all the dimensions above
- Then do the following runs:
 - No compatibility metadata, totally random
 - Gradually add levels (each subsystem on its own), we might get fewer matches, but more successful builds
 - Add memory and cost as the final selection algorithm, do we do better?
 
I hypothesize we will see a tradeoff between matching and build success, and there might be an ideal place to operate in that dimension. For costs, I did my best to generate (what I think is) a reasonable mapping between memory and node cost per hour, which is something you might see for a real cloud. And it's reasonable I think to use the best *real* build time (fastest that is successful) as something to aspire to. We will see! I will be generating plots, slides, etc. to help synthesize the results when they are available.

## Design

### Base Experiments

We start with base experiments. For these experiments we are using a "random" selection algorithm and not providing any additional subsystem metadata. To assess compatibility:

- A mismatch for arch or compiler is considered a failure. We record it.
- A mismatch for compiler version is a failure only if the compiler needed is newer than the one found.
- For each failure / success above, we give points of 0/1.
- We then calculate memory and cost. We use a KNN model (specific to the package) previously derived to get an estimated runtime for the package build. We compare this to a fastest runtime for the build and calculate a difference in time and cost. KNN can overfit, but I think it's appropriate here because we want as close to a real runtime value in the dataset for a given memory.

At the end we should accumulate, for each analysis, a number of build failures / successes (and reasons why). For the successes, we should assess performance in terms of cost - the total extra time/cost as a result of scheduling inefficiency.
Note that this experiment has no constraints - we assume each cluster can take an infinite number of jobs.

### Subsystem Experiments

Once we have base experiments, we want to assess the relative value of adding subsytems. We do the following subsystems (in this order) and using the algorithm for each:

- **arch** The architecture is matched, exactly to a value.
- **compiler**: Is just the compiler name. This dataset has two, gcc and oneapi.
- **compiler-version**: Is modeled as a separate subsystem (so we see how it influences the space) but in practice is part of the compiler subsystem. Both the compiler and compiler-version nodes are checked, although it would probably just work with the version given that the subsystems don't have two compilers with overlapping versions.
- **memory** is the one subsystem that doesn't use an exact equality match, but looks for the value in the jobspec to be a minimum the cluster has.

Note that this experiment has no constraints - we assume each cluster can take an infinite number of jobs. We aren't moving into constraints yet because we still aren't getting compatible matches (meaning the build will have the environment it needs for a successful outcome).


### Expanding Subsystem Experiments

The expanding experiments take the above, but add on subsystems (in that order) incrementally. The idea is that we should see matches go down and build successes go up as we add more stringent requirements. This experiment also doesn't do any constraint checking.

### Constraint Checking

Now we can start with what we consider the most compatible setup (the set of jobs that will work on the clusters with all compatibility metadata) and try to optimize, namely, given there is more than one match for a jobspec, choose the best cluster based on the minimum price. While ideally we might have some strategy to serve the models for rainbow to use, since this is a demo we are going to have rainbow return all the clusters assigned instead, and use our same (local) KNN models to determine the final assignment. The same scoring rules will apply, but we must apply the logic for the final selection, namely:

- filter: nodes_free > 0 (this is done in the select step of rainbow)
- use KNN for the package build type to calculate the estimated runtime based on memory of each cluster
- calculate the build cost for the cluster based on the runtime
- sort the build costs
- choose the lowest cost

And at the end, we update the cluster to have N-2 nodes available.

#### 1. Rainbow

First, let's run rainbow. The server is currently lenient to allow us to change the selection algorithm one off for a job, so we can run it with one config.

```bash
git clone https://github.com/converged-computing/rainbow
cd rainbow
go mod vendor

# See what you can do
go run cmd/server/server.go --help

# Run rainbow using our experiment config and verbose logging (good for testing)
go run cmd/server/server.go --loglevel 6 --global-token rainbow --config ../rainbow-config.yaml --testing

# The actual experiment
go run cmd/server/server.go --global-token rainbow --config ../rainbow-config.yaml
```

And then run:

```bash
python run_experiments.py
```

## Results

Parse the results (currently running for 31K+ jobspecs, coming soon)

```bash
python plot-results.py
```

For experiment results, you can see them in [img](img) and I wrote them up [here](here).
