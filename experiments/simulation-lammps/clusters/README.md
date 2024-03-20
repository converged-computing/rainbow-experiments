# Clusters

> To go with rainbow, these are the crayon clusters! (simulations)!

These are fake clusters we will generate nodes for, register to rainbow, and then assign work to.
We will have variation across variants of MPI, etc. To make life simple, the dominant subsystems
(nodes, cores, etc) are largely going to be the same, and all jobs will ask for 2 nodes.
Since this is a simulation, it means that we can generate the *perfect* cluster for each
job, and then set rules for what is compatible vs. not. We will need:

```console
4 os variants x 3 mpi variants x (gpu or not, 2) x 2 arch = 48 clusters!
```
For rules we make the assumptions that:

- MPI must match, because if it doesn't, we provide the wrong command
- Operating system version must match (to match image selection experiments) 
- A non-gpu `lmp` can run on a gpu node, and this assumes the main command was built too (e.g., `lmp` and `lmp_gpu`
  - This was not the case for the original experiments
- Versions of MPI don't matter (for this experiment simulation)

And we can tweak these if needed.
This will be encoded in the script that generates the clusters and "correct" answers.

## Inventory

These are shared across clusters:

| Cluster | Attribute | Value      |
|---------|-----------|------------|
| all     | nodes     | 4          |
| all     | racks     | 1          |
| all     | cores     | 8 (2/node) |


To generate the 48 clusters and associated subsystems:

```bash
python generate_clusters.py
```
Note that since rainbow currently has a simple algorithm for subsystems, doing an _exact_ match on a type:

```yaml
version: 1
resources:
- count: 2
  type: node
  with:
  - count: 1
    label: default
    type: slot
    with:
    - count: 2
      type: core
tasks:
- command:
  - ior
  slot: default
  count:
    per_slot: 1
  resources:
    io:
      match:
      - type: shm
```

We are going to flatten attributes into types, and make it easy. Note that we can do future simulations and slowly modify the algorithm to have a type then child that needs to be looked at, e.g., something like:

```yaml
tasks:
- command:
  - ior
  slot: default
  count:
    per_slot: 1
  resources:
    io.archspec:
      match:
      - type: cpu
        name: target
        value: arm64 
```

E.g., "For the io.archspec subsystem, find a node with type cpu, and check that the value of the attribute target is arm64"
I'll do that next, want to do this simple approach first.

Note that since colors are shuffled, if you re-run this you'll get a different set each time. Be careful.
