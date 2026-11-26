#!/bin/bash
# Runs profiles x chains x seeds inside the ns3-5g container (optimized build).
# Profiles: night, nightNN (NN Mbit/s), day, dayNN (NN Mbit/s), peakNNN (NNN Mbit/s offered: 53 of video, the rest bursts).
# Resumable: finished runs are skipped. Runs go seed by seed, so partial results stay balanced.
set -euo pipefail
OUT=${OUT:-bs-results-seg}
JOBS=${JOBS:-6}
SEEDS=${SEEDS:-10}
DURATION=${DURATION:-10}
VIDEO=${VIDEO:-segments}
SCHEDULER=${SCHEDULER:-ofdma}
NEIGHBOR=${NEIGHBOR:-$SCHEDULER}  # scheduler of the other sites
NEIGHBOR_CHAINS=${NEIGHBOR_CHAINS:-64}  # chains of the other sites; "same" = as cell 0
TB_TRACE=${TB_TRACE:-false}       # write every transport block received in cell 0
PROFILES=${PROFILES:-peak100 day night}
CHAINS=${CHAINS:-64 32 16}
TOTAL=$((SEEDS * $(echo $PROFILES | wc -w) * $(echo $CHAINS | wc -w)))
docker start ns3-5g >/dev/null
docker exec -w /ns3 ns3-5g ninja -C cmake-cache-opt scratch_bs-energy >/dev/null
docker exec -w /ns3 ns3-5g mkdir -p "$OUT"
for run in $(seq "$SEEDS"); do for prof in $PROFILES; do for ant in $CHAINS; do
  echo "$prof $ant $run"
done; done; done | docker exec -i -w /ns3 -e OUT="$OUT" -e DURATION="$DURATION" -e VIDEO="$VIDEO" -e SCHEDULER="$SCHEDULER" -e NEIGHBOR="$NEIGHBOR" -e TB_TRACE="$TB_TRACE" -e NEIGHBOR_CHAINS="$NEIGHBOR_CHAINS" \
  ns3-5g xargs -P "$JOBS" -L1 bash -c '
  o=$OUT/$0_a$1_r$2
  [ -f ${o}_flows.csv ] && { echo "skip $0 $1 $2"; exit 0; }
  echo "start $0 $1 $2"
  p="--profile=$0"
  case $0 in
    peak*) n=${0#peak}; p="--profile=peak --loadMbps=$((n - 53))";;
    night?*) p="--profile=night --loadMbps=${0#night}";;
    day?*) p="--profile=day --loadMbps=${0#day}";;
  esac
  nb=$NEIGHBOR_CHAINS; [ "$nb" = same ] && nb=$1
  LD_LIBRARY_PATH=build-opt/lib build-opt/scratch/ns3.46.1-bs-energy-optimized $p \
    --antennas=$1 --run=$2 --video=$VIDEO --scheduler=$SCHEDULER --neighborScheduler=$NEIGHBOR --neighborAntennas=$nb --tbTrace=$TB_TRACE --duration=$DURATION --drain=0.5 --out=${o}.part \
    > ${o}.log 2>&1 || { echo "FAILED $0 $1 $2"; exit 1; }
  for k in slots segments cells rx tb flows; do
    [ -f ${o}.part_$k.csv ] && mv ${o}.part_$k.csv ${o}_$k.csv
  done
  echo "done $0 $1 $2"' | awk -v t="$TOTAL" '/^(done|skip)/ {print ++n "/" t, $0; fflush(); next} {print; fflush()}'
echo campaign finished
