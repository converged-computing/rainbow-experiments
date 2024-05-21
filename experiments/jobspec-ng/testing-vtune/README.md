# Descriptive Expression + Scheduler Brainstorm

> Testing vtune on Kubernetes

I found [this article](https://stackoverflow.com/questions/69395912/pmu-x86-64-performance-counters-not-showing-in-perf-under-aws) helpful to figuring out the instance type that this would be possible on, and how to check that. I first got working on c5.9xlarge, but then realized for efa I would need to intersect with [this list](https://github.com/eksctl-io/eksctl/blob/fa79d2e0b1af108b714da8020809bec218908288/pkg/addons/assets/efa-device-plugin.yaml#L43-L95).  These are the ones that support vPMU.


```console
i3.metal
c5.9xlarge
c5.18xlarge
m4.16xlarge
m5.12xlarge
m5.24xlarge
r5.12xlarge
r5.24xlarge
f1.16xlarge
h1.16xlarge
i3.16xlarge
p2.16xlarge
p3.16xlarge
r4.16xlarge
x1.32xlarge
c5d.9xlarge
c5d.18xlarge
m5d.12xlarge
m5d.24xlarge
r5d.12xlarge
r5d.24xlarge
x1e.32xlarge
```

Note that I didn't find overlap - but that list is old.

**Update** [This instance type, c5n.9xlarge](https://instances.vantage.sh/aws/ec2/c5n.9xlarge) seems to be in the efa list and have the `arch_perfmon` feature, so I'll try it out next. We will need to find "full T-shirt sizes" for Nitro and then shell in and look at /proc/cpuinfo. Let's continue with this setup for learning about vtune and with lammps examples.


```bash
eksctl create cluster -f crd/eks-config.yaml
```

Install the flux operator.

```bash
kubectl apply -f https://raw.githubusercontent.com/flux-framework/flux-operator/main/examples/dist/flux-operator.yaml
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

Check for vPMU support:

```bash
cat /proc/cpuinfo | grep arch_perfmon
```

Try running lammps without flux:

```bash
lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

Wrap vtune.

```bash
vtune -collect hpc-performance -data-limit=0 -r hpc-performance lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

YES! It worked! Holy hell I tried this like 8 different times. There is something to say for being a stubborn idiot.
Pull the arm image to both nodes:

Note that it's not going to work with flux without efa, or at least I don't want to debug how to get it working without efa.
Let's first test doing the same with a container. Install Singularity (for the future base we will have it installed).
Yes, being lazy with flux exec.

```
flux exec apt-get update
flux exec apt-get install -y \
   autoconf \
   automake \
   cryptsetup \
   git \
   libfuse-dev \
   libglib2.0-dev \
   libseccomp-dev \
   libtool \
   pkg-config \
   runc \
   squashfs-tools \
   squashfs-tools-ng \
   uidmap \
   wget \
   zlib1g-dev
```

I had to run these separately on the nodes (this will be built into the containers)

```
wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz && \
  tar -C /usr/local -xzvf go1.21.0.linux-amd64.tar.gz

echo 'export PATH=/usr/local/go/bin:$PATH' >> ~/.bashrc 

export VERSION=4.1.0 && \
wget https://github.com/sylabs/singularity/releases/download/v${VERSION}/singularity-ce-${VERSION}.tar.gz && \
tar -xzf singularity-ce-${VERSION}.tar.gz && \
cd singularity-ce-${VERSION}

./mconfig && \
    make -C builddir && \
    make -C builddir install
```

```bash
flux exec --dir /home singularity pull docker://ghcr.io/rse-ops/lammps-matrix:mpich-ubuntu-22.04-amd64 
```

Let's try singularity. I also needed to do:

```
apt-get install -y locales
locale > /etc/localtime
```

This worked:

```
singularity exec --pwd /opt/lammps/examples/reaxff/HNS/ /home/lammps-matrix_mpich-ubuntu-22.04-amd64.sif lmp -v x 1 -v y 1 -v z 1 -in in.reaxc.hns -nocite
```

Let's add vtune

```bash
vtune -collect hpc-performance -data-limit=0 -r hpc-performance-singularity singularity exec --pwd /opt/lammps/examples/reaxff/HNS/ /home/lammps-matrix_mpich-ubuntu-22.04-amd64.sif lmp -v x 2 -v y 2 -v z 2 -in in.reaxc.hns -nocite
```

## Exploring Examples

We are going to do this off of the cloud, since we have the container.


## Looking at a result

That's wicked! Let's copy a report over to our local machine so we can try the gui.

```bash
kubectl cp flux-sample-0-xxx:/opt/lammps/examples/reaxff/HNS/hpc-performance-singularity ./report
```

That will generate [report](report) for us to open in the vtune-gui. I'll work on this in the next experiment setup.

When you are done:

```bash
eksctl delete cluster -f crd/eks-config.yaml
```
