FROM intel/oneapi-vtune:2024.1.0-devel-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive

# docker build -t ghcr.io/converged-computing/rainbow-experiments:vtune-singularity .

RUN apt-get update && \
    apt-get install -y fftw3-dev fftw3 pdsh libfabric-dev libfabric1 \
        dnsutils telnet strace cmake git g++ python3-pip \
        openmpi-bin openmpi-doc libopenmpi-dev \
        build-essential wget curl unzip libnss3-dev libgtk2.0-dev ffmpeg \
        libblas-dev liblapack-dev \
        libnetcdf-dev libnetcdff-dev

RUN apt-get update && \
    apt-get install -y \
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
       zlib1g-dev \
       libzstd-dev \
       libcurl4-openssl-dev \
       libgsl-dev \
       libvtk9-dev \
       qtbase5-dev \
       libatk-bridge2.0-0

RUN python3 -m pip install clang-format
RUN git clone https://github.com/ornladios/ADIOS2.git /opt/ADIOS2 && \
    cd /opt/ADIOS2 && \
    mkdir adios2-build && cd adios2-build && \
    cmake ../ && make && make install

WORKDIR /opt/
RUN apt-get install -y xxd && \
    git clone --depth 1 --branch stable https://github.com/lammps/lammps.git /opt/lammps && \
    cd /opt/lammps && \
    mkdir build && \
    cd build && \
    . /etc/profile && \ 
    # I am leaving out -DPKG_GPU=yes  -DPKG_INTEL=yes -DPKG_ELECTRON=yes
    # https://docs.lammps.org/Packages_list.html
    cmake ../cmake \
    -DCMAKE_INSTALL_PREFIX:PATH=/usr \
    -DCMAKE_PREFIX_PATH=/usr/lib/mpich \ 
    -DCMAKE_PREFIX_PATH=/usr/lib/x86_64-linux-gnu \
    -DBUILD_MPI=yes \ 
    -DFFT=FFTW3 \
    -DPKG_ADIOS=yes \
    -DPKG_AMOEBA=yes \
    -DPKG_ASPHERE=yes \
    -DPKG_ATC=yes \
    -DPKG_AWPMD=yes \
    -DPKG_BOCS=yes \
    -DPKG_BODY=yes \
    -DPKG_BPM=yes \
    -DPKG_BROWNIAN=yes \
    -DPKG_CG-DNA=yes \
    -DPKG_CG-SPICA=yes \
    -DPKG_CLASS2=yes \
    -DPKG_COLLOID=yes \
    -DPKG_COLVARS=yes \
    -DPKG_COMPRESS=yes \
    -DPKG_CORESHELL=yes \
    -DPKG_DIELECTRIC=yes \
    -DPKG_DIFFRACTION=yes \ 
    -DPKG_DIPOLE=yes \
    -DPKG_DPD-BASIC=yes \
    -DPKG_DPD-MESO=yes \
    -DPKG_DPD-REACT=yes \
    -DPKG_DPD-SMOOTH=yes \ 
    -DPKG_DRUDE=yes \
    -DPKG_EFF=yes \
    -DPKG_ELECTRODE=yes \
    -DPKG_EXTRA-COMPUTE=yes \
    -DPKG_EXTRA-DUMP=yes \
    -DPKG_EXTRA-FIX=yes \ 
    -DPKG_EXTRA-MOLECULE=yes \ 
    -DPKG_EXTRA-PAIR=yes \
    -DPKG_FEP=yes \
    -DPKG_GRANULAR=yes \
    -DPKG_H5MD=yes \
    -DPKG_INTEL=yes \
    -DPKG_INTERLAYER=yes \ 
    -DPKG_KIM=yes \
    -DPKG_KOKKOS=yes \
    -DPKG_KSPACE=yes \
    -DPKG_LATBOLTZ=yes \
    -DPKG_LEPTON=yes \
    -DPKG_MACHDYN=yes \
    -DPKG_MANIFOLD=yes \
    -DPKG_MANYBODY=yes \
    -DPKG_MC=yes \
    -DPKG_MDI=yes \
    -DPKG_MEAM=yes \
    -DPKG_MESONT=yes \
    -DPKG_MGPT=yes \
    -DPKG_MISC=yes \
    -DPKG_ML-HDNNP=yes \
    -DPKG_ML-IAP=yes \
    -DPKG_ML-PACE=yes  \
    -DPKG_ML-POD=yes \
    -DPKG_ML-QUIP=yes \
    -DPKG_ML-RANN=yes \
    -DPKG_ML-SNAP=yes \
    -DPKG_MOFFF=yes \
    -DPKG_MOLECULE=yes \
    -DPKG_MOLFILE=yes \
    -DPKG_NETCDF=yes \
    -DPKG_OMP=yes \
    -DPKG_OPENMP=yes \
    -DPKG_OPT=yes \
    -DPKG_OPT=yes \
    -DPKG_ORIENT=yes \
    -DPKG_PERI=yes \
    -DPKG_PHONON=yes \
    -DPKG_PLUGIN=yes \
    -DPKG_PLUMED=yes \
    -DPKG_POEMS=yes \
    -DPKG_PYTHON=yes \
    -DPKG_QEQ=yes \
    -DPKG_QMMM=yes \
    -DPKG_QTB=yes \
    -DPKG_REACTION=yes \
    -DPKG_REAXFF=yes \
    -DPKG_REPLICA=yes \
    -DPKG_RIGID=yes \
    -DPKG_SCAFACOS=yes \
    -DPKG_SHOCK=yes \
    -DPKG_SMTBQ=yes \
    -DPKG_SPH=yes \
    -DPKG_SPIN=yes \
    -DPKG_SRD=yes \
    -DPKG_TALLY=yes \
    -DPKG_UEF=yes \
    -DPKG_VORONOI=yes \
    -DPKG_VTK=yes \
    -DPKG_YAFF=yes && \
    make && \
    make install


# Install intel compilers
# Don't do this at home kids!
RUN wget https://registrationcenter-download.intel.com/akdlm/IRC_NAS/2e562b6e-5d0f-4001-8121-350a828332fb/l_dpcpp-cpp-compiler_p_2024.1.0.468_offline.sh && \
    chmod +x ./l_dpcpp-cpp-compiler_p_2024.1.0.468_offline.sh && \
    ./l_dpcpp-cpp-compiler_p_2024.1.0.468_offline.sh -a -s --eula accept

# Make another lammps with intel?
# ENV PATH=$PATH:/opt/intel/oneapi/compiler/latest/bin/compiler:/opt/intel/oneapi/compiler/latest/bin
# RUN git clone --depth 1 --branch stable https://github.com/lammps/lammps.git /opt/lammps-intel && \  
#    cd /opt/lammps-intel

COPY ./common /opt/lammps/examples/common

# Not sure we will need to use singularity
# ENV PATH=/usr/local/go/bin:$PATH
# RUN wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz && \
#  tar -C /usr/local -xzvf go1.21.0.linux-amd64.tar.gz && \
#  export VERSION=4.1.0 && \
#  wget https://github.com/sylabs/singularity/releases/download/v${VERSION}/singularity-ce-${VERSION}.tar.gz && \
#  tar -xzf singularity-ce-${VERSION}.tar.gz && \
#  cd singularity-ce-${VERSION} && \
#  ./mconfig && \
#    make -C builddir && \
#    make -C builddir install

# Running examples
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/lammps/build/build

# The following are working (testing on my single machine)
# I think we want to create experiments based on:
# https://www.hpc-carpentry.org/tuning_lammps/05-accelerating-lammps/index.html
# Add -nocite to all of them to remove citation
# cd /opt/lammps/examples/airebo
# lmp -in in.airebo      # 53 seconds
# lmp -in in.airebo-m    # 56 seconds
# lmp -in in.airebo-0-0  # 4 seconds
# lmp -in in.rebo2       # 4 seconds
# cd /opt/lammps/examples/atm
# lmp -in in.atm         # 15 seconds
# cd /opt/lammps/examples/balance
# lmp -in in.balance             # instant
# lmp -in in.balance.bond.slow   #
# lmp in.


WORKDIR /opt/lammps/examples/reaxff/HNS
