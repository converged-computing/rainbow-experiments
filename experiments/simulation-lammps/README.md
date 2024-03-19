# Descriptive Expression + Scheduler Simulation

I couldn't get the lammps containers running on a single MiniCluster (it was too much debugging and I hit a level of anguish that I could not tolerate) but I had a cool idea - we still know where jobs should go, so why not create a simulation? And in fact since none of it is real, we can extend beyond the actual reality of what these lammps runs offered.

This experiment will simulate clusters, meaning we will deploy rainbow, and it can even be locally, and then create several faux clusters locally, and receive jobs to them (and assuming we have a lookup of correct assignment, determine which are correct and which are not). It's a bit artificial, but that's probably OK. I'll try this in unison with actual clusters. For all clusters we will assume the same size (4 nodes) and jobs won't go beyond that, but we will vary the subsystem metadata. Once this is working we will add additional subsystem metadata and do a larger simulation.

## Experiment

I haven't done this yet, but this is what needs to be done.

1. Deploy rainbow locally.
2. Create separate faux-clusters, nodes are under [clusters](clusters). I generated these by way of running compspec in different environments.

3. Deploy rainbow as a service to the cluster, and it needs to be exposed via ingress.
4. Deploy the flux operator (theoretically x86 should still be able to schedule to arm nodes?)
5. Deploy each cluster and register with rainbow.
6. Generate jobspecs that vary across compatibility metadata.
7. Generate subsystem metadata for each cluster, also register with rainbow.
8. Submit jobs from local machine to rainbow, at each compatibility level

For the last step, we either can have a service running to automatically receive, or have a script that receives and runs. Although it's more work, I'd rather shell in and run the script, and ensure that I save the jobspecs / job metadata in completion for each. It's a bit pedantic, but this will be a more controlled experiment than hoping that full automation will work. It eventually should, but I'm not comfortable doing that yet and then having something go wrong.

## 1. Generate Jobspecs

We previously used compatibility artifacts to determine compatibility, but now we are representing this same metadata as part of a job, so we are going to include the attributes within jobspecs. Specifically, we will define them each as subsystems with requirements on the level of a job. E.g., "task A to run lammps requires X" and then X will be part of a subsystem graph. This means that we can generate the same dimension of compatibility by (step-wise) registering our different subsystems. 

```bash
# pip install rainbow-scheduler
cd ./compspec
python generate_jobspecs.py
```

For the above, we use [this function](https://github.com/converged-computing/rainbow/blob/8a8db39196d64536983ca6aaa6defdf229ea8b6a/python/v1/rainbow/jobspec/converter.py#L4-L47) from rainbow-scheduler (the Python rainbow library) and the [schema attributes](https://github.com/compspec/schemas) for each of mpi, io.archspec, hardware, and os as different subsystems. The resulting data is in [jobspecs](jobspecs) where each yaml is a jobspec we will submit to rainbow, and a cluster will be selected. When we receive the work on the clusters we will want to record which ones are sent where, etc.

## 2. Subsystems

We will have subsystems for:

- archspec 
- operating system (name and version)
- MPI variants
- hardware

And we need a script that can generate these on the fly for some specification of a node graph. For these experiments we have all the metadata on the level of a node, and for all nodes in a cluster, so it should be simple to write a script to do that. While this will be generated on the fly for the cluster, for now I'll prototype something in [subsystems](subsystems) assuming a faux cluster nodes graph.


## 1. Deploy Clusters

Let's create the ARM and X86 clusters.

```bash
GOOGLE_PROJECT=myproject
gcloud container clusters create test-cluster \
    --threads-per-core=1 \
    --placement-type=COMPACT \
    --num-nodes=5 \
    --region=us-central1-a \
    --project=${GOOGLE_PROJECT} \
    --machine-type=c2d-standard-8
```

Note that I stopped here - the LAMMPS containers were not running, just about anywhere, and I chose not to handle the task of debugging 18 different lammps installs. If someone else wants to do it, please do! It would be nice to reproduce the image selection experiments in a different context.


