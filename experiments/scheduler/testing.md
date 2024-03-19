# Testing

We are primarily doing this testing to develop our applications, and see what is possible (vs. not) and establish "truth" meaning knowledge of what will run where.

```bash
kind create cluster --config ./crd/kind-config.yaml
```
Install the flux operator - this was a wget of the main dist/flux-operator.yaml with the digest added on March 17, 2024.

```bash
kubectl apply -f ./crd/flux-operator.yaml
```

One thing I'm not sure about is if an x86 operator can schedule to ARM nodes (or across node pools) I've never tried this before. We will need to try this when we deploy the GKE cluster. To add note to that - I'm thinking of creating node pools that have selector labels, and then I can assign specific MiniCluster to specific nodes (at least I hope)!

## Testing

### Cluster

I first created a local kind cluster. It would have compspec (go) installed and rainbow-python (not used yet) and jobspec (python) to translate a jobspec to flux.

```bash
kubectl apply -f ./crd/clusters/amd-ubuntu-jammy-go120.yaml 
```

And then shell inside and test the jobspec. I wrote the [jobspecs/fractal-amd-jobspec.yaml](jobspecs/fractal-amd-jobspec.yaml) to file manually to test after connecting to the broker and checking the workers.

```bash
. /mnt/flux/flux-view.sh
flux proxy $fluxsocket /bin/bash
flux resource list
```

I want to point out that the "transform" section doesn't need to be directly in the jobspec - we could write it into a separate file that the jobspec library knows how to read. Then from Python, I tried running it per [this example](https://github.com/compspec/jobspec/blob/main/examples/flux/receive-job.py)

```python
from jobspec.plugin import get_transformer_registry
registry = get_transformer_registry()
plugin = registry.get_plugin("flux")()
plugin.run("jobspec.yaml")
```

That seems to be a good way to define and test jobspecs. Now we can assume that rainbow will send them. 
I'll have to design different clusters (container bases) and node metadata, but it is what it is.

### Rainbow

I wonder if we can just run this as a service? It didn't like ghcr.io so I had to pull and re-push.
See the image in [docker/rainbow](docker/rainbow) where I customized the entrypoint.

```bash
docker pull ghcr.io/converged-computing/rainbow-scheduler:latest
docker tag ghcr.io/converged-computing/rainbow-scheduler:latest vanessa/rainbow-scheduler:latest
docker push vanessa/rainbow-scheduler:latest
```
```bash
gcloud run deploy rainbow-service --region us-central1 \
    --image docker.io/vanessa/rainbow-scheduler:latest \
    --max-instances 1 \
    --port 8080 \
    --allow-unauthenticated \
    --use-http2
```
It will give you a URL - then you can interact. E.g., from a testing cluster, e.g., I used [jobspecs/generate-cluster-nodes.yaml](generate-cluster-nodes.yaml)
You can also just run it for one node and then copy N times.

Let's try registering with the rainbow client now.

```
wget https://raw.githubusercontent.com/converged-computing/rainbow/main/python/v1/examples/flux/register.py
python3 register.py --help
python3 register.py --cluster $CLUSTER_NAME --host https://rainbow-service-a5cie3jtja-uc.a.run.app --secret chocolate-cookies --config-path ./rainbow-config.yaml --cluster-nodes /root/rainbow/cluster-nodes.json
```

That didn't work - I am going to just deploy to one of the clusters and use ingress, which I know has worked before.s
