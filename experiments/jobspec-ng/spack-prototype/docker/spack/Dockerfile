FROM spack/ubuntu-jammy:latest

# docker build -t vanessa/rainbow-spack-experiment:prototype .

ENV DEBIAN_FRONTEND=noninteractive
ENV GO_VERSION=1.20.14

# Install extra buildrequires for flux-sched:
RUN apt-get update && \
    apt-get -qq install -y --no-install-recommends \
        wget \
        curl \
        less \
        git \
        vim \
        build-essential \
        iputils-ping \
        python3-pip \
        ca-certificates \
        unzip && \
    apt-get clean -y && apt -y autoremove

# To compile compspec go
RUN wget https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz  && tar -xvf go${GO_VERSION}.linux-amd64.tar.gz && \
    mv go /usr/local && rm go${GO_VERSION}.linux-amd64.tar.gz

ENV PATH=/usr/local/go/bin:$PATH

# Install jobspec nextgen and rainbow
RUN git clone https://github.com/compspec/jobspec && \
    cd jobspec && \
    pip install -e .

RUN git clone https://github.com/converged-computing/rainbow && \
    cd rainbow/python/v1 && \
    pip install -e .

ENV PATH=/opt/spack/bin:/opt/ramble/bin:/usr/local/go/bin:$PATH

# Install compspec and fractal
RUN git clone --depth 1 https://github.com/compspec/compspec-go /opt/compspec-go && \ 
    cd /opt/compspec-go && \
    make build && cp ./bin/compspec* /usr/local/bin/ && \
    rm -rf /opt/compspec-go
    
WORKDIR /code
COPY ./jobspec-spack.yaml ./jobspec-spack.yaml
