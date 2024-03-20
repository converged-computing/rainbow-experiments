# Descriptive Expression + Scheduler Simulation

> Algorithm: direct match

I had a cool idea - the perfect experiment would have a perfect cluster for every jobspec, so why not create a simulation? Then we can add each subsystem (the compatibiliity levels), assign to clusters, see how well we did, and create a gradient of compatibility (the percentage of jobs that are compatible at each level). We can start simple with a direct match, meaning that if you look at the subsystem nodes, they are literally just exact keys and values. We can expand upon this, along with allow "compatible but imperfect" matches based on the value in the matches data frame. Since none of it is real, we can extend beyond the actual reality of what the original lammps runs offered.

This experiment will simulate clusters, meaning we will deploy rainbow, and it can even be locally, and then create several (48) faux clusters locally, and receive jobs to them (and assuming we have a lookup of correct assignment, determine which are correct and which are not). It's a bit artificial, but that's probably OK. I'll try this in unison with actual clusters. For all clusters we will assume the same size (4 nodes) and jobs won't go beyond that, but we will vary the subsystem metadata. Once this is working we will add additional subsystem metadata and do a larger simulation.

## Experiment

I haven't done this yet, but this is what needs to be done.

1. Deploy rainbow locally.
2. Create separate faux-clusters, nodes and subsystems are under [clusters](clusters). These are generated so every jobspec has a perfect cluster.
3. Deploy rainbow as a service to the cluster, and it needs to be exposed via ingress.
4. Deploy each faux cluster and register with rainbow.
5. Generate jobspecs that vary across compatibility metadata (this I already did, see [jobspecs](jobspecs))
6. For each compatibility level, from platform to descriptive:
  - Submit 20x each job to rainbow. Capture jobids (uids) assigned to each cluster.
  - Calculate some metric(s) of accuracy

I'm going to try this once, and I might allow for more of a gradient if the results are weird (meaning, it's not realistic that a job would actually only work on 1/48 clusters).

## 1. Generate Jobspecs

We previously used compatibility artifacts to determine compatibility, but now we are representing this same metadata as part of a job, so we are going to include the attributes within jobspecs. Specifically, we will define them each as subsystems with requirements on the level of a job. E.g., "task A to run lammps requires X" and then X will be part of a subsystem graph. This means that we can generate the same dimension of compatibility by (step-wise) registering our different subsystems. 

```bash
# pip install rainbow-scheduler
cd ./compspec
python generate_jobspecs.py
```

For the above, we use [this function](https://github.com/converged-computing/rainbow/blob/8a8db39196d64536983ca6aaa6defdf229ea8b6a/python/v1/rainbow/jobspec/converter.py#L4-L47) from rainbow-scheduler (the Python rainbow library) and the [schema attributes](https://github.com/compspec/schemas) for each of mpi, io.archspec, hardware, and os as different subsystems. The resulting data is in [jobspecs](jobspecs) where each yaml is a jobspec we will submit to rainbow, and a cluster will be selected. When we receive the work on the clusters we will want to record which ones are sent where, etc.

## 2. Generate Clusters and Subsystems

See [clusters](clusters) for all of that!
