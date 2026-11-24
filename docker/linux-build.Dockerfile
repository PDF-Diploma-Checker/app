# Build environment of the Linux release variants. Same image for CI and for a local build:
#   tools/docker_build_linux.sh base|cpu|gpu
# ubuntu 22.04 on purpose: its glibc is old, so the build runs on older distributions too. The gpu variant needs the
# CUDA toolkit to compile llama.cpp, so it starts from NVIDIA's devel image of the same Ubuntu (no GPU is needed to build).
ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
# build tools for llama.cpp and the libraries Qt needs at run time (the build ends with a smoke test of the application)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 build-essential cmake ninja-build pkg-config \
        libgl1 libegl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libxkbcommon0 libxkbcommon-x11-0 libx11-6 libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# A build machine has no NVIDIA driver, so libcuda.so.1 does not exist, but llama.cpp's tools and libggml-cuda.so are
# linked against it. CUDA's stub library stands in for it while building and in the smoke test; it is not packed into
# the application (PyInstaller never bundles libcuda), the driver of the user's computer is used there.
RUN if [ -d /usr/local/cuda/lib64/stubs ]; then ln -sf libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1; fi
ENV LIBRARY_PATH=/usr/local/cuda/lib64/stubs \
    LDFLAGS=-Wl,-rpath-link=/usr/local/cuda/lib64/stubs

WORKDIR /src
ENTRYPOINT ["/src/docker/build_in_container.sh"]
