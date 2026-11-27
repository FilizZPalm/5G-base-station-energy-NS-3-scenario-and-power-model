#!/bin/bash
# Runs profiles x chains x seeds inside the ns3-5g container (optimized build).
# Profiles: night, nightNN (NN Mbit/s), day, dayNN (NN Mbit/s), peakNNN (NNN Mbit/s offered: 53 of video, the rest bursts).
# Resumable: finished runs are skipped. Runs go seed by seed, so partial results stay balanced.
set -euo pipefail
OUT=${OUT:-bs-results-main}
JOBS=${JOBS:-6}
SEEDS=${SEEDS:-10}
DURATION=${DURATION:-10}
VIDEO=${VIDEO:-segments}
SCHEDULER=${SCHEDULER:-ofdma}
NEIGHBOR=${NEIGHBOR:-$SCHEDULER}  # scheduler of the other sites
NEIGHBOR_CHAINS=${NEIGHBOR_CHAINS:-64}  # chains of the other sites; "same" = as cell 0; "rule" = from RULE and their load
NEIGHBOR_LOAD=${NEIGHBOR_LOAD:-1}       # burst load of the other sites, as a multiple of the burst load of cell 0
RULE=${RULE:-"40:16 50:24 100:48 1000:64"}  # up to load:chains, the fewest chains with acceptable QoS (policy study)
TB_TRACE=${TB_TRACE:-false}       # write every transport block received in cell 0
PROFILES=${PROFILES:-peak100 day night}
CHAINS=${CHAINS:-64 32 16}
TOTAL=$((SEEDS * $(echo $PROFILES | wc -w) * $(echo $CHAINS | wc -w)))
docker start ns3-5g >/dev/null
docker exec -w /ns3 ns3-5g ninja -C cmake-cache-opt scratch_bs-energy >/dev/null
docker exec -w /ns3 ns3-5g mkdir -p "$OUT"
for run in $(seq "$SEEDS"); do for prof in $PROFILES; do for ant in $CHAINS; do
  echo "$prof $ant $run"
done; done; done | docker exec -i -w /ns3 -e OUT="$OUT" -e DURATION="$DURATION" -e VIDEO="$VIDEO" -e SCHEDULER="$SCHEDULER" -e NEIGHBOR="$NEIGHBOR" -e TB_TRACE="$TB_TRACE" -e NEIGHBOR_CHAINS="$NEIGHBOR_CHAINS" -e NEIGHBOR_LOAD="$NEIGHBOR_LOAD" -e RULE="$RULE" \
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
  case $0 in                                          # burst load of cell 0 [Mbit/s]
    night) l=1;; night*) l=${0#night};; day) l=40;; day*) l=${0#day};; peak) l=47;; peak*) l=$((${0#peak} - 53));;
  esac
  nl=$(awk -v l=$l -v f=$NEIGHBOR_LOAD "BEGIN {x = l * f; print (x > 150 ? 150 : x)}")   # capped at the highest grid load
  nb=$NEIGHBOR_CHAINS; [ "$nb" = same ] && nb=$1
  [ "$nb" = rule ] && nb=$(echo $RULE | tr " " "\n" | awk -F: -v l=$nl "l <= \$1 {print \$2; exit}")
  LD_LIBRARY_PATH=build-opt/lib build-opt/scratch/ns3.46.1-bs-energy-optimized $p \
    --antennas=$1 --run=$2 --video=$VIDEO --scheduler=$SCHEDULER --neighborScheduler=$NEIGHBOR --neighborAntennas=$nb --neighborLoadMbps=$nl --tbTrace=$TB_TRACE --duration=$DURATION --drain=0.5 --out=${o}.part \
    > ${o}.log 2>&1 || { echo "FAILED $0 $1 $2"; exit 1; }
  for k in slots segments cells rx tb flows; do
    [ -f ${o}.part_$k.csv ] && mv ${o}.part_$k.csv ${o}_$k.csv
  done
  echo "done $0 $1 $2"' | awk -v t="$TOTAL" '/^(done|skip)/ {print ++n "/" t, $0; fflush(); next} {print; fflush()}'
echo campaign finished
