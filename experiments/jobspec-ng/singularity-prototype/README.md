# Descriptive Expression + Scheduler Brainstorm

> Testing ARM cluster with Singularity (to run an app)

I was chewing on how to create an interesting experiment that would be about software compatibility, and (since we want to be championing using containers) I thought I'd try the idea of using a Singularity container as a unit of operation,
and then being able to run it on different clusters that don't need the apps installed explicitly, but rather the resources
needed for the specific container apps. I first need to test if this idea will work, period, to pull and run the Singularity container with flux.

This first setup will test just bringing up the cluster, installing singularity, etc.

```bash
eksctl create cluster -f crd/eks-config.yaml
```

Install the flux operator.

```bash
kubectl apply -f https://raw.githubusercontent.com/flux-framework/flux-operator/main/examples/dist/flux-operator-arm.yaml
```

Try creating the interactive minicluser.

```bash
kubectl apply -f crd/minicluster.yaml
```

Shell in.

```bash
kubectl exec -it flux-sample-0-xxx bash
. /mnt/flux/flux-view.sh 
flux proxy $fluxsocket bash
flux resource list
```

Pull the arm image to both nodes:

```bash
flux exec --dir /home/ubuntu singularity pull docker://ghcr.io/rse-ops/lammps-matrix:mpich-ubuntu-22.04-arm64  
```

Try shelling into the container. We will test lammps manually first.

```bash
singularity shell /home/ubuntu/lammps-matrix_mpich-ubuntu-22.04-arm64.sif 
```
```bash
cd /opt/lammps/examples/reaxff/HNS/
lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

Success! Let's try from outside the container next...

```bash
singularity exec --pwd /opt/lammps/examples/reaxff/HNS/ /home/ubuntu/lammps-matrix_mpich-ubuntu-22.04-arm64.sif lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

That worked too. Now with flux.

```bash
flux run -N 1 -n 64 singularity exec --pwd /opt/lammps/examples/reaxff/HNS/ /home/ubuntu/lammps-matrix_mpich-ubuntu-22.04-arm64.sif lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

That worked too! Now two nodes?

```bash
flux run -N 2 -n 128 -o cpu-affinity=per-task singularity exec --pwd /opt/lammps/examples/reaxff/HNS/ /home/ubuntu/lammps-matrix_mpich-ubuntu-22.04-arm64.sif lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

What I'm not sure about here is if we would be better of binding the MPI in the container to the host, or (if by way of flux) that is handled indirectly?

What I'm trying to think about is if there is an experiment we can do that isn't about "build a million different clusters where the cluster is different" but rather "assume we have two generic clusters, ARM and X86, and allow the compatibility metadata to inform _how_ to run the application, either by way of:

- parameters specified to the app directly
- topology provided to flux
- binding specific libraries to the container
- pre-loading something before running the container.

I think we will be empowered to do a lot more experiments if it doesn't require building a gazillion different environments (the MiniCluster container bases, each with a separate application) OR a single chonker one with a bunch of apps. By running two cluster types and testing application configurations, we can still test compatibility without that.

High level ideas of what we can vary:

- The highest level will be arch - if we create two MiniCluster (arm/x86)
- If we don't do the singularity approach (and everything is native) we might care about if a cluster has an executable, etc.
- The specific build of the container (vary by the mpi, operating system)
- flags to flux to determine topology
- in the case of needing binds to the host (for example, to use some exact MPI library) 
- we could likely do an entire set of experiments with the different example apps provided by lammps already. In this case we could have the compatibility be about how we provide the parameters, and choosing the best parameters for example, regardless of the cluster.

Will do more thinking on this. When you are done:

```bash
eksctl delete cluster -f crd/eks-config.yaml
```

### TODO

This is what I need to do next.

- Test out some "out of the box" profiling cluster tools that use eBPF, possibly to just look at basic metrics to go along with an application runtime.
- Test deploying rainbow on [arm](https://github.com/converged-computing/rainbow/pull/38) because we might need/want it.
- Look into different lammps apps in the [examples](https://github.com/lammps/lammps/tree/develop/examples) directory and determine if we can describe different ways to run them as some kind of compatibility metadata. Either the custom configs are linked to software / environment needs, OR we can just build different Singularity images, run them in different ways, and see which is best.

I think likely I'm going to want to do the first bullet, and figure out a way to determine my ground truth - the profiling. Then I'll try (in one setup) running different lammps apps. When I know how to do that, I can build different variants and test them in that profile setup. And then I'll be able to say "this one runs better when we have this container base, or this command line flag that required this container build" 

The "perfect" experiment would be having the "same" container URI for lammps, but with different variants (each with an artifact) that are described via the attributes discovered above. And then when we ask to run a specific lammps example, one for which we know what the "best" way is, the degree to which we choose the right container to do it depends on the compatibility metadata.

