# Descriptive Expression + Scheduler Simulation

> Algorithm: direct match

I had a cool idea - the perfect experiment would have a perfect cluster for every jobspec, so why not create a simulation? Then we can add each subsystem (the compatibiliity levels), assign to clusters, see how well we did, and create a gradient of compatibility (the percentage of jobs that are compatible at each level). We can start simple with a direct match, meaning that if you look at the subsystem nodes, they are literally just exact keys and values. We can expand upon this, along with allow "compatible but imperfect" matches based on the value in the matches data frame. Since none of it is real, we can extend beyond the actual reality of what the original lammps runs offered.

This experiment will simulate clusters, meaning we will deploy rainbow, and it can even be locally, and then create several (48) faux clusters locally, and receive jobs to them (and assuming we have a lookup of correct assignment, determine which are correct and which are not). It's a bit artificial, but that's probably OK. I'll try this in unison with actual clusters. For all clusters we will assume the same size (4 nodes) and jobs won't go beyond that, but we will vary the subsystem metadata. Once this is working we will add additional subsystem metadata and do a larger simulation.

**Simulations I want to do**

- Assess utility of each subsystem in isolation 
- Assess utility of adding them (one at a time) in an order

That is what the experiments here do.

#### Notes

Note that I mangled the jobspec quite a bit, and honestly I'm not happy with it (meaning, the current v1) and I'm holding off changing more in fear of people being angry. To start, it should be allowed to not define a slot explicitly, and then it be assumed that the slot is the top level at the node (meaning, our task block is asking for subsystem resources at the level of the node, which is reasonable to do). Secondly, it doesn't make sense to have a list of tasks OR resources if the limit is 1 or 2 items. I think this was designed with extendability in mind? For this prototype, I changed tasks to just "Task" but left the resource list as is. I'm getting rather ornery about the design and probably need to stop and just let someone else figure it out, because I feel strongly about things and am likely to disagree and make people dislike me more. We will eventually want models that can assess the value of subsystem features, but I think this is a good start.

## Usage

This is the general outline of running a simulation. Each step will be provided in more detail, but with setup first.

1. Deploy rainbow locally.
2. Create separate faux-clusters, nodes and subsystems are under [clusters](clusters). These are generated so every jobspec has a perfect cluster.
3. Deploy rainbow as a service to the cluster, and it needs to be exposed via ingress.
4. Deploy each faux cluster and register with rainbow.
5. Generate jobspecs that vary across compatibility metadata (this I already did, see [jobspecs](jobspecs))
6. For each compatibility level, from platform to descriptive:
  - Submit 20x each job to rainbow. Capture jobids (uids) assigned to each cluster.
  - Calculate some metric(s) of accuracy

I'm going to try this once, and I might allow for more of a gradient if the results are weird (meaning, it's not realistic that a job would actually only work on 1/48 clusters).

### Setup

#### 1. Generate Jobspecs

We previously used compatibility artifacts to determine compatibility, but now we are representing this same metadata as part of a job, so we are going to include the attributes within jobspecs. Specifically, we will define them each as subsystems with requirements on the level of a job. E.g., "task A to run lammps requires X" and then X will be part of a subsystem graph. This means that we can generate the same dimension of compatibility by (step-wise) registering our different subsystems. 

```bash
# pip install rainbow-scheduler
cd ./compspec
python generate_jobspecs.py
```

For the above, we use [this function](https://github.com/converged-computing/rainbow/blob/8a8db39196d64536983ca6aaa6defdf229ea8b6a/python/v1/rainbow/jobspec/converter.py#L4-L47) from rainbow-scheduler (the Python rainbow library) and the [schema attributes](https://github.com/compspec/schemas) for each of mpi, io.archspec, hardware, and os as different subsystems. The resulting data is in [jobspecs](jobspecs) where each yaml is a jobspec we will submit to rainbow, and a cluster will be selected. When we receive the work on the clusters we will want to record which ones are sent where, etc.

#### 2. Generate Clusters and Subsystems

See [clusters](clusters) for all of that! Output includes:

##### clusters

In [clusters](clusters) there are (appropriately named) rainbow clusters, and each has a JGF for nodes, and a set of subsystems. For example:

```console
cluster-deeppink
├── hardware-subsystem.json
├── io.archspec-subsystem.json
├── mpi-subsystem.json
├── nodes.json
└── os-subsystem.json

0 directories, 5 files
```

The metadata, primarily what features each cluster has (matched to the subsystems) are in [rainbow-clusters.csv](clusters/rainbow-clusters.csv).

##### matches

The matching table (jobspecs in [jobspecs](jobspecs)) to each of the clusters above, where each _does_ have a perfect match, is in
[jobspec-to-cluster-matches.csv](clusters/jobspec-to-cluster-matches.csv). Right now I am being very stringent, meaning that the only wiggle room I allow is to say that a job intended for non-gpu can also run on a gpu cluster, and this assumes the software has been installed for the cpu variant too (for my image selection experiment this wasn't the case, but here I am relaxing a bit). This means in the matrix we can set these values to 0.5, a "not perfect but not mismatch." In particulate:

- 1: indicates a perfect match
- 0.5: indicates compatible, but not perfect
- 0: indicates not compatible

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

I hope you like the emojis. They are one of life's simple pleasures. 🤌️
And That's it. Rainbow is running. Let's use it.

#### 2. Python

Since we have everything locally, we can actually do the entire thing in Python! We will (in one script, I know):

1. Create each cluster (registering to rainbow) and saving the secret we get back to receive jobs.
2. Read in each jobspec, associate with a unique id (generated from the filename that reflects the metadata)
3. For each subsystem (starting with no subsystem, the empty set)
  - Apply the subsystem (or not for the empty set)
  - For each of 20x, submit all the jobs to rainbow, with the UID plus an index
  - For each cluster (meaning, a loop) get jobs assigned to it.
  - Determine how well we did (what percentage of assigned jobs are correct?)

We would want to see that as we add compatibility metadata, we get more matches. Once this experiment is done,
we can tweak it, and I think likely we will add another algorithm that better honors a graph structure, and 
either allow for more gradients of compatibility (e.g., call a match of the same OS but different version OK to do)
or more subsystems, etc. I'm hoping with this simple setup others can see all the pieces and work independently.
So basically, just do:

```bash
python run_experiments.py
```

**warning** the output is noisy! I haven't made levels of logging for rainbow yet.  And you'll see the scores:

```console
{
    "none": {
        "total": 360,
        "correct": 14.0,
        "accuracy": 0.03888888888888889
    },
    "io.archspec": {
        "total": 360,
        "correct": 24.5,
        "accuracy": 0.06805555555555555
    },
    "os": {
        "total": 360,
        "correct": 31.5,
        "accuracy": 0.0875
    },
    "mpi": {
        "total": 360,
        "correct": 22.0,
        "accuracy": 0.06111111111111111
    },
    "hardware": {
        "total": 360,
        "correct": 17.0,
        "accuracy": 0.04722222222222222
    },
    "io.archspec+os": {
        "total": 360,
        "correct": 76.0,
        "accuracy": 0.2111111111111111
    },
    "io.archspec+os+mpi": {
        "total": 360,
        "correct": 239.5,
        "accuracy": 0.6652777777777777
    },
    "io.archspec+os+mpi+hardware": {
        "total": 360,
        "correct": 360.0,
        "accuracy": 1.0
    }
}
🧪️ Experiments are finished. See output in /home/vanessa/Desktop/Code/rainbow-experiments/experiments/simulation-lammps/results
```

And that's it. Cheers.
