#!/usr/bin/env bash
# Builds a Linux release variant in Docker, the same way the "Build Linux release" workflow does.
# Usage: tools/docker_build_linux.sh base|cpu|gpu [release-tag]      -> release files in release_files/
# The gpu variant compiles llama.cpp with CUDA inside the image: no GPU and no CUDA toolkit are needed on this computer.
set -euo pipefail
cd "$(dirname "$0")/.."
VARIANT="${1:?usage: tools/docker_build_linux.sh base|cpu|gpu [release-tag]}"
TAG="${2:-}"
case "$VARIANT" in
  base|cpu) BASE_IMAGE=ubuntu:22.04 ;;
  gpu) BASE_IMAGE=nvidia/cuda:12.8.1-devel-ubuntu22.04 ;;
  *) echo "variant must be base, cpu or gpu"; exit 1 ;;
esac
IMAGE="diplomachecker-build-$VARIANT"
docker build -f docker/linux-build.Dockerfile --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$IMAGE" docker
mkdir -p release_files .docker-home
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
  -v "$PWD":/src -v "$PWD/.docker-home":/tmp/home \
  "$IMAGE" "$VARIANT" $TAG
