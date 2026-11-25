#!/bin/bash
# Wake-up campaign: sleep settings x profiles x seeds (chains fixed per profile by the main campaign).
# Resumable: finished runs are skipped. Output: <profile>_a<chains>_t<Tw ms>_s<SSB ms>_r<seed>.
set -euo pipefail
OUT=${OUT:-bs-results-wake}
JOBS=${JOBS:-6}
SEEDS=${SEEDS:-10}
DURATION=${DURATION:-10}
# profile chains Tw[ms] SSB[ms]; 5 ms is left out at peak, where it almost never sleeps
CASES=${CASES:-"peak100 64 0.5 20
day 16 0.5 20
day 16 5 20
day 16 5 160
night 16 0.5 20
night 16 5 20
night 16 5 160"}
TOTAL=$((SEEDS * $(wc -l <<< "$CASES")))
docker start ns3-5g >/dev/null
docker exec -w /ns3 ns3-5g ninja -C cmake-cache-opt scratch_bs-energy >/dev/null
docker exec -w /ns3 ns3-5g mkdir -p "$OUT"
for run in $(seq "$SEEDS"); do while read -r c; do echo "$c $run"; done <<< "$CASES"; done |
  docker exec -i -w /ns3 -e OUT="$OUT" -e DURATION="$DURATION" ns3-5g xargs -P "$JOBS" -L1 bash -c '
  o=$OUT/$0_a$1_t$2_s$3_r$4
  [ -f ${o}_flows.csv ] && { echo "skip $0 $1 Tw=$2 SSB=$3 seed $4"; exit 0; }
  p="--profile=$0"
  case $0 in
    peak*) n=${0#peak}; p="--profile=peak --loadMbps=$((n - 53))";;
    night?*) p="--profile=night --loadMbps=${0#night}";;
  esac
  LD_LIBRARY_PATH=build-opt/lib build-opt/scratch/ns3.46.1-bs-energy-optimized $p \
    --antennas=$1 --run=$4 --sleepTwMs=$2 --sleepSsbMs=$3 --duration=$DURATION --drain=0.5 \
    --out=${o}.part > ${o}.log 2>&1 || { echo "FAILED $0 $1 $2 $3 $4"; exit 1; }
  for k in slots segments sleep flows; do
    [ -f ${o}.part_$k.csv ] && mv ${o}.part_$k.csv ${o}_$k.csv
  done
  echo "done $0 $1 Tw=$2 SSB=$3 seed $4"' |
  awk -v t="$TOTAL" '/^(done|skip)/ {print ++n "/" t, $0; fflush(); next} {print; fflush()}'
echo campaign finished
