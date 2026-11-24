#!/bin/bash
# Runs the NS-3 load grid inside the ns3-5g container. Resumable: finished runs are skipped.
set -euo pipefail
OUT=bs-results
JOBS=${JOBS:-7}
docker start ns3-5g >/dev/null
docker exec -w /ns3 ns3-5g ./ns3 build bs-energy >/dev/null
docker exec -w /ns3 ns3-5g mkdir -p $OUT
for run in 1 2 3 4; do for ant in 64 32 16; do for load in 0 1 2 5 10 20 30 45 60 80 100 120; do
  echo "$ant $load $run"
done; done; done | docker exec -i -w /ns3 ns3-5g xargs -P "$JOBS" -L1 bash -c '
  o='$OUT'/a$0_l$1_r$2
  [ -f ${o}_flows.csv ] && exit 0
  LD_LIBRARY_PATH=build/lib build/scratch/ns3.46.1-bs-energy-default \
    --antennas=$0 --loadMbps=$1 --run=$2 --duration=1.5 --out=${o}.part &&
  mv ${o}.part_slots.csv ${o}_slots.csv && mv ${o}.part_flows.csv ${o}_flows.csv'
echo done
