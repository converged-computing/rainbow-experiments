# Docker builds

Along with applications we will eventually run, we need two variants here for base images, one for ARM and one for x86.
I want a simple image for each that has singularity and a modern python maybe. We can add stuff to it as needed.

```
cd singularity/
docker build -t ghcr.io/converged-computing/rainbow-experiments:singularity-mamba .
docker push -t ghcr.io/converged-computing/rainbow-experiments:singularity-mamba 

docker buildx build -f Dockerfile.arm --platform linux/arm64 --tag ghcr.io/converged-computing/rainbow-experiments:singularity-mamba-arm .
docker push -t ghcr.io/converged-computing/rainbow-experiments:singularity-mamba-arm
```
