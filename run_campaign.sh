#!/bin/bash
# Runs profiles x chains x seeds inside the ns3-5g container (optimized build).
# Profiles: night, day, peakNNN (NNN Mbit/s offered: 53 of video, the rest bursts).
# Resumable: finished runs are skipped. Runs go seed by seed, so partial results stay balanced.
set -euo pipefail
OUT=${OUT:-bs-results-seg}
JOBS=${JOBS:-6}
SEEDS=${SEEDS:-10}
DURATION=${DURATION:-10}
VIDEO=${VIDEO:-segments}
PROFILES=${PROFILES:-peak150 day night}
CHAINS=${CHAINS:-64 32 16}
docker start ns3-5g >/dev/null
docker exec -w /ns3 ns3-5g ninja -C cmake-cache-opt scratch_bs-energy >/dev/null
docker exec -w /ns3 ns3-5g mkdir -p "$OUT"
for run in $(seq "$SEEDS"); do for prof in $PROFILES; do for ant in $CHAINS; do
  echo "$prof $ant $run"
done; done; done | docker exec -i -w /ns3 -e OUT="$OUT" -e DURATION="$DURATION" -e VIDEO="$VIDEO" \
  ns3-5g xargs -P "$JOBS" -L1 bash -c '
  o=$OUT/$0_a$1_r$2
  [ -f ${o}_flows.csv ] && exit 0
  p="--profile=$0"
  case $0 in peak*) n=${0#peak}; p="--profile=peak --loadMbps=$((n - 53))";; esac
  LD_LIBRARY_PATH=build-opt/lib build-opt/scratch/ns3.46.1-bs-energy-optimized $p \
    --antennas=$1 --run=$2 --video=$VIDEO --duration=$DURATION --drain=0.5 --out=${o}.part \
    > ${o}.log 2>&1 || { echo "FAILED $0 $1 $2"; exit 1; }
  for k in slots segments flows; do
    [ -f ${o}.part_$k.csv ] && mv ${o}.part_$k.csv ${o}_$k.csv
  done
  echo "done $0 $1 $2"'
echo campaign finished
