#!/bin/bash
# Creates the ns3-5g container from docker/Dockerfile and compiles bs-energy (optimized build).
# Never touches an existing container. NS-3 + 5G-LENA must already be in ns-3.46.1/ (see README.md).
set -euo pipefail
NAME=${NAME:-ns3-5g}
IMAGE=${IMAGE:-ns3-5g-env}
JOBS=${JOBS:-6}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
NS3="$ROOT/ns-3.46.1"
[ -d "$NS3/contrib/nr" ] || { echo "missing $NS3/contrib/nr (5G-LENA)"; exit 1; }
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "container $NAME already exists: remove it yourself or use NAME=other"; exit 1
fi
docker build -t "$IMAGE" "$ROOT/docker"
docker run -d --init --name "$NAME" -v "$NS3":/ns3 "$IMAGE"
# Configure only if needed. cmake overwrites the NS-3 lock file: restore it.
docker exec "$NAME" bash -c '
  set -e
  [ -f cmake-cache-opt/build.ninja ] && exit 0
  lock=.lock-ns3_linux_build; [ -f $lock ] && cp -p $lock /tmp/lock.bak
  cmake -S . -B cmake-cache-opt -G Ninja -DCMAKE_BUILD_TYPE=release -DNS3_ASSERT=OFF -DNS3_LOG=OFF \
    -DNS3_WARNINGS_AS_ERRORS=OFF -DNS3_NATIVE_OPTIMIZATIONS=ON -DNS3_EXAMPLES=OFF -DNS3_TESTS=OFF \
    -DNS3_OUTPUT_DIRECTORY=build-opt
  [ -f /tmp/lock.bak ] && cp -p /tmp/lock.bak $lock || true
  grep -q "NS3_EIGEN:BOOL=ON" cmake-cache-opt/CMakeCache.txt'
docker exec "$NAME" ninja -C cmake-cache-opt -j"$JOBS" scratch_bs-energy
echo "ready: $NAME"
