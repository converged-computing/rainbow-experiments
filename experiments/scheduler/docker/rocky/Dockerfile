ARG tag=8
FROM rockylinux:${tag}
ARG arch=amd64
ENV arch=$arch

# docker build -t ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-8 .
# docker build --build-arg tag=9-t ghcr.io/converged-computing/rainbow-experiments/scheduler-v1:rocky-9 .

# Basic dependencies for flux operator
RUN dnf update -y && \
    dnf groupinstall -y 'Development Tools' && \
    dnf install -y wget python3-pip git \
    autoconf libtool pkg-config mpich vim python3-cffi \
    openssl-devel \
    libuuid-devel \
    libseccomp-devel \
    squashfs-tools \
    cryptsetup \
    cmake \
    glib2-devel \
    fuse3-libs \
    fuse3-devel

# Install Go
RUN wget https://go.dev/dl/go1.20.14.linux-${arch}.tar.gz && \
    tar -C /usr/local -xzf go1.20.14.linux-${arch}.tar.gz

ENV PATH=/opt/spack/bin:/opt/ramble/bin:/usr/local/go/bin:$PATH

# Install compspec and fractal
RUN git clone --depth 1 https://github.com/compspec/compspec-go /opt/compspec-go && \ 
    cd /opt/compspec-go && \
    make build && cp ./bin/compspec* /usr/local/bin/ && \
    rm -rf /opt/compspec-go

RUN git clone https://github.com/converged-computing/distributed-fractal /tmp/df && \
    cd /tmp/df && make build && cp ./bin/fractal /usr/local/bin/fractal  && \
    rm -rf /tmp/df

# install lammps with pixi
RUN /bin/bash -c "curl -fsSL https://pixi.sh/install.sh | bash" && \
   . /root/.bash_profile && pixi global install lammps
ENV PATH=/root/.pixi/bin:$PATH
    
# Let's throw singularity into the mix! This will be our singularity cluster
ENV PATH=/usr/local/go/bin:$PATH
RUN git clone --recurse-submodules https://github.com/sylabs/singularity.git && \
    cd singularity && \
    ./mconfig && make -C builddir && make -C builddir install
