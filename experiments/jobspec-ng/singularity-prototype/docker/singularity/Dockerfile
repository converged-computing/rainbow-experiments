FROM ubuntu

# docker build -t ghcr.io/converged-computing/rainbow-experiments:singularity-mamba .
RUN apt-get update && apt-get install -y wget curl vim
RUN /bin/bash -c "curl -L https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh > mambaforge.sh && \
    bash mambaforge.sh -b -p /opt/conda && \
    rm mambaforge.sh"
ENV PATH=/opt/conda/bin:$PATH
RUN mamba install singularity
