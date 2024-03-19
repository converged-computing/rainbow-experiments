# Descriptive Expression + Scheduler Experiment

This experiment will be testing compatibility metadata in the context of a scheduler. Specifically we will be creating node pools on a single cluster, each with ARM and X86 nodes, and then scheduling different MiniClusters to each, and this will mirror having multiple clusters. I'm realizing (somewhat after doing a lot of work) that we could just simulate this - setting compatibility metadata for fake clusters we tell rainbow about, and then see where they get assigned just locally. I'm wondering if that would be good to do, but in parallel with this one. I might test this out first.

## System (MiniCluster) Variation

In terms of what we want to vary:

 - architectures (arm64 and amd64) as an example of system compatiility
 - Software version (go) as an example of software compatibility (akin to MPI version or variant)
 - GPU (or not - we won't have any GPU)
 - Cluster with really small amount of memory (and application that needs more)
 - Really small (2 node) cluster and we ask for more
 - Disk space not sufficient
 
For the above, this maps to the following clusters (each will be small):

- ARM and x86 at some reasonable size
- Different installs (versions) of Go (1.20 and 1.15 to mirror our clusters)
- Same sets as above, but memory constrained (resource limits _and_ requests set for cluster)
- Nodes with artificially small disks and IOR runs that write larger files

In practice, we will likely see (without descriptive):

- A memory intensive workload mapped to resources too small, OOM (dominant subsystem compatibility)
- A workload that needs N nodes on an N-M cluster will not be able to run (dominant subsystem compatibility)
- Something to compile with go, either for too-old version or wrong architecture (software compatibility)
- Disk space too small (subsystem compatibility)
- Missing GPU (driver subsystem compatibility)

For the GPU case, it should be that rainbow rejects the job, we won't have any GPU clusters.
I believe these variables are more interesting than just LAMMPS with MPI because Google Cloud isn't good for MPI anyway.
I don't have a ton of credits on Google Cloud, so each cluster size will be relatively smal.

## Workflows

For the above, I'll design workflows that are across a matrix. Note that since we are running these directly on existing MiniCluster, we will either need to do a build -> run step directly when we hit the cluster, or we will need to expect the cluster to have the software that we need. This could eventually map to a ramble use case, which also does build, but also note that (at least for cloud resources we are paying for) the build should not take that long. I am thinking I generally want to use:

- [ior](https://github.com/hpc/ior) because I can ask to do a test to write a file that is too big (hopefully won't break the cluster)
- [fractale-distributed](https://github.com/converged-computing/fractale-distributed): provides interesting metrics for resource usage (from Go) and can be run distributed across multiple nodes (so I can ask for different sizes). Cross compiling also means that I can build for different arches.
- [ramble](https://github.com/LLNL/benchpark/blob/develop/.github/workflows/run.yml#L14)
- [lammps](jobspecs/lammps-amd-jobspec.yaml): in the simplest way (1 node) possible. I'm burnt out on MPI, I'm sorry. If it runs for one that's what we care about now, and maybe for the HPC experiment equivalent it can run across nodes.
- [hwloc](jobspecs/hwloc-amd-jobspec): I thought it would be interesting to get this diagram, just for fun.
- [salad](jobspecs/salad-amd-jobspec): This is just to demonstrate the singularity container use case.

## Base Images

I'm going to test the following base images, which are provided in [docker](docker).
Testing notes are in [testing](testing.md). This (so far) is a total of 5 clusters.

### ubuntu amd (2 clusters)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:ubuntu-jammy](./docker/ubuntu/Dockerfile.jammy)
- Tested (working) workflows include:
 - jobspecs/fractal-amd-jobspec.yaml (4 nodes)
 - jobspecs/io-amd-jobspec.yaml (1 node)
 - jobspecs/hwloc-amd-jobspec.yaml (1 node)
 - jobspecs/lammps-amd-jobspec.yaml (1 node)
 - jobspecs/ramble-amd-jobspec.yaml (1 node, MPI) [saxpy](https://github.com/LLNL/benchpark/blob/develop/.github/workflows/run.yml#L14)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:ubuntu-focal](./docker/ubuntu/Dockerfile.focal)
- Tested (working) workflows include:
 - jobspecs/fractal-amd-jobspec.yaml (4 nodes)
 - jobspecs/hwloc-amd-jobspec.yaml (1 node)
 - jobspecs/io-amd-jobspec.yaml (1 node)
 - jobspecs/lammps-amd-jobspec.yaml (1 node)

Note that ramble will only work on the ubuntu jammy amd image - the reason is because it took manual tweaking for `--allow-run-as-root`.
Let's just make one ARM cluster node.

### ubuntu arm (1 cluster)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:ubuntu-focal-arm](./docker/ubuntu/Dockerfile.focal)
- Workflows include:
 - jobspecs/fractal-amd-jobspec.yaml (4 nodes)
 - jobspecs/hwloc-amd-jobspec.yaml (1 node)
 - jobspecs/io-amd-jobspec.yaml (1 node)
 - jobspecs/lammps-amd-jobspec.yaml (1 node)


### rocky amd (2 clusters)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-8](./docker/rocky/Dockerfile)
- Not tested yet - will include singularity supported workflows

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-9](./docker/rocky/Dockerfile)
- Not tested yet - will include singularity supported workflows

I tried to mix it up by adding singularity here. These will need to be run with privileged. 

### rocky arm (2 clusters)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-8-arm](./docker/rocky/Dockerfile)
- Does not include lammps (no arm binary from pixi)

- Builds to: [ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-9-arm](./docker/rocky/Dockerfile)
- Does not include lammps (no arm binary from pixi)

## Experiment

I haven't done this yet, but this is what needs to be done.

1. Create a large cluster with enough nodes to support sub-clusters (and take into account node types). Different node types should be separate node pools.
2. On each cluster, deploy several instances of interactive MiniCluster, which will vary in architecture, base operating system and version.  Conceptually, you can think of this as several different clusters. These are the bases described above.
3. Deploy rainbow as a service to the cluster, and it needs to be exposed via ingress.
4. Deploy the flux operator (theoretically x86 should still be able to schedule to arm nodes?)
5. Deploy each cluster and register with rainbow.
6. Generate jobspecs that vary across compatibility metadata.
7. Generate subsystem metadata for each cluster, also register with rainbow.
8. Submit jobs from local machine to rainbow, at each compatibility level

For the last step, we either can have a service running to automatically receive, or have a script that receives and runs. Although it's more work, I'd rather shell in and run the script, and ensure that I save the jobspecs / job metadata in completion for each. It's a bit pedantic, but this will be a more controlled experiment than hoping that full automation will work. It eventually should, but I'm not comfortable doing that yet and then having something go wrong.

I haven't done anything beyond this.
