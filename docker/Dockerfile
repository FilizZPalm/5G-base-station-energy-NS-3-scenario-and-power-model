# Build and run environment for NS-3 3.46.1 + 5G-LENA v4.1.1.
# The NS-3 sources are not copied: they are mounted at /ns3 when the container is created (setup.sh).
FROM ubuntu:24.04@sha256:2198e4c65076e9cb0b3d695219df667c0e3b0072da64ca3c2648aca17dcecaf5

# libeigen3-dev is required by SU-MIMO: without it the runs abort
# ("MIMO channel normalization requires Eigen").
RUN apt-get update \
 && apt-get install -y \
      g++ cmake ninja-build git python3 pkg-config \
      libsqlite3-dev libgsl-dev libxml2-dev libeigen3-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /ns3
# Keeps the container alive so that the run scripts can use "docker exec".
CMD ["sleep", "infinity"]
