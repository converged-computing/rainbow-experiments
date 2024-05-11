# Descriptive Expression + Scheduler Experiment

> Using Jobspec Next Generation and spack

This experiment will be testing compatibility metadata in the context of a scheduler. Specifically we will be creating node pools on a single cluster, and then scheduling different MiniClusters to each, and this will mirror having multiple clusters. This prototype will test:

1. Creating the rainbow service2
2. Creating a Flux MiniCluster with spack installed (jobspec and rainbow sdk libraries)
3. Registering the cluster
4. Submitting the job to it.

If that works we can easily deploy a second MiniCluster to test submitting jobs to, and then we will have a setup we can scale out (and add requires or compatibility metadata for).

## 1. Create the Kubernetes cluster

```bash
kind create cluster --config ./crd/kind-config.yaml
```

## Base Images

I've built testing images, provided in [docker](docker), that has jobspec nextgen, the rainbow client, and spack.

```bash
# This builds an image with development rainbow
cd ./docker/rainbow
docker build -t vanessa/rainbow-scheduler:latest .

# And the minicluster image (with spack and compspec)
cd ./docker/spack
docker build -t vanessa/rainbow-spack-experiment:prototype .
```

Load into kind

```bash
kind load docker-image vanessa/rainbow-scheduler:latest 
kind load docker-image vanessa/rainbow-spack-experiment:prototype
```

## Experiment

### Setup

Create the scheduler, the service, and ingress.

```bash
kubectl apply -f ./crd/rainbow/scheduler.yaml
kubectl apply -f ./crd/rainbow/service.yaml
kubectl apply -f ./crd/rainbow/ingress.yaml
```

Sanity check logs.

```console
$ kubectl logs scheduler-584df6b5d4-qlnfs 
2024/05/11 08:15:15 creating 🌈️ server...
2024/05/11 08:15:15 🧩️ selection algorithm: random
2024/05/11 08:15:15 🧩️ graph database: memory
2024/05/11 08:15:15 ✨️ creating rainbow.db...
2024/05/11 08:15:15    rainbow.db file created
2024/05/11 08:15:15    🏓️ creating tables...
2024/05/11 08:15:15    🏓️ tables created
2024/05/11 08:15:15 ⚠️ WARNING: global-token is set, use with caution.
2024/05/11 08:15:15 starting scheduler server: rainbow v0.1.1-draft
2024/05/11 08:15:15 🧠️ Registering memory graph database...
2024/05/11 08:15:15 server listening: [::]:8080
```

Install the flux-operator.

```bash
kubectl apply -f https://raw.githubusercontent.com/flux-framework/flux-operator/main/examples/dist/flux-operator.yaml
```

Now create the single Minicluster.

```bash
kubectl apply -f ./crd/minicluster-blue.yaml
```

This is just testing, so we are allowing multiple pods per node. We won't do this in a real experiment.
Note that the Minicluster creation will also use compspec to generate the nodes (to register) when it is coming up.
You can find those in `/code`.

```bash
/code
├── cluster
│   ├── node-1.json
│   ├── node-2.json
│   ├── node-3.json
│   └── node-4.json
├── cluster-nodes.json
└── jobspec-spack.yaml
```


### Interact with Flux

Shell into the lead broker, source the view, and connect via proxy.

```bash
kubectl exec -it flux-sample-0-xxxx bash
. /mnt/flux/flux-view.sh
flux proxy $fluxsocket bash
```
```console
root@flux-sample-0:~# flux resource list
     STATE NNODES   NCORES    NGPUS NODELIST
      free      2       20        0 blue-[0-1]
 allocated      0        0        0 
      down      0        0        0 
```

Now run the jobspec.

```bash
jobspec run ./jobspec-spack.yaml
```

This will install ior and then submit a second job that waits for it to be loadable and runs it. In the future we will have the depends_on working and not need to do that.

### Register to Rainbow

Now that we know our jobspec is working, let's have it submit through rainbow. We can do this on our local machine, or in the cluster - we just need to be able to hit the rainbow endpoint that is running. First we need to get the ip address of rainbow.

```bash
kubectl get pods -o wide
```
```console
$ kubectl get pods -o wide
NAME                         READY   STATUS    RESTARTS   AGE     IP            NODE                 NOMINATED NODE   READINESS GATES
flux-sample-0-ndnkg          1/1     Running   0          5h45m   10.244.0.13   kind-control-plane   <none>           <none>
flux-sample-1-hkr6f          1/1     Running   0          5h45m   10.244.0.15   kind-control-plane   <none>           <none>
flux-sample-2-kw68b          1/1     Running   0          5h45m   10.244.0.14   kind-control-plane   <none>           <none>
flux-sample-3-t5bwq          1/1     Running   0          5h45m   10.244.0.16   kind-control-plane   <none>           <none>
scheduler-584df6b5d4-rczmd   1/1     Running   0          6h14m   10.244.0.5    kind-control-plane   <none>           <none>
```

In the above, we care about `10.244.0.5` and we know the service is running on port 8080.
And then here is how to use the script (already in the container) to register your cluster. The secret for the cluster will be saved to the `rainbow-config.yaml` you speciy (that does not exist). Here is the full command - we are providing the nodes json we generated, and the secret is in the scheduler.yaml that we used to create the deployment.

```bash
script=/root/rainbow/python/v1/examples/flux
python3 $script/register.py --cluster blue --host 10.244.0.5:8080 --secret peanutbutta --cluster-nodes /code/cluster-nodes.json --config-path /code/rainbow-config.yaml
```
```console
Saving rainbow config to /code/rainbow-config.yaml
🤫️ The token you will need to submit jobs to this cluster is jellaytime
🔐️ The secret you will need to accept jobs is 409ece99-0f91-4816-9113-e62458afdfe1
```

### Submit to Rainbow

Now let's submit the job. First let's submit a dummy job (command line without jobspec).

```bash
python3 $script/submit-job.py --config-path /code/rainbow-config.yaml --nodes 1 echo hostname
```

Now we can submit the jobspec.

```bash
python3 $script/submit-jobspec.py --config-path /code/rainbow-config.yaml /code/jobspec-spack.yaml 
```
```console
resources:
  spack-resources:
    count: 1
    type: node
    with:
    - count: 10
      type: core
tasks:
- command:
  - spack
  - install
  - ior
  name: build
  resources: spack-resources
- command:
  - bash
  - -c
  - 'spack load ior

    ior -b 10g -O summaryFormat=json

    '
  depends_on:
  - build
  name: ior
  resources: spack-resources
version: 1

SatisfyResponse(clusters=[], cluster='flux-sample', total_matches=1, total_mismatches=0, total_clusters=1, status=1)
```

Now let's receive the job (down to the same cluster). This won't submit.

```bash
python3 $script/receive-jobs.py --config-path /code/rainbow-config.yaml
```

To receive jobs _and_ submit to flux via the Jobspec next generation transformer, do:

```bash
python3 $script/receive-jobs-and-submit.py --config-path /code/rainbow-config.yaml
```

### Fully Automated Case

We will add this case when depends on works and we have a larger plan (that we can test on a cloud). It will basically come down to having all of the commands above run when the cluster starts up.

