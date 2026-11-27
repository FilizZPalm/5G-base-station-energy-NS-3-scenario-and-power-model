# Running the simulations and the analysis

Setup is in the [README](../README.md#setup). Each campaign below feeds one or more steps of [STEPS.md](STEPS.md).

## Simulations

A single run (night profile, 16 active chains, 10 s, seed 1):

```bash
docker exec -e LD_LIBRARY_PATH=build-opt/lib ns3-5g \
  build-opt/scratch/ns3.46.1-bs-energy-optimized \
  --profile=night --antennas=16 --duration=10 --drain=0.5 --run=1 --out=test
```

Use `--help` instead of these options for the full list. Campaigns are resumable: finished runs are
skipped. Times are for an Apple M2 with 6 runs in parallel.

```bash
OUT=bs-results-main ./run_campaign.sh     # night, day and 100 Mbit/s peak x 64/32/16 chains x 10 seeds (~1 h)
./run_wakeup.sh                           # sleep modes with a wake-up time (70 runs)
OUT=bs-results-load PROFILES="peak80 peak100 peak120" CHAINS=64 ./run_campaign.sh   # peak load search
OUT=bs-results-night PROFILES="night5 night10 night15" ./run_campaign.sh            # busier nights
OUT=bs-results-night-wake CASES="night5 16 0.5 20
night5 16 5 160
night10 16 0.5 20
night10 16 5 160
night15 16 0.5 20
night15 16 5 160" ./run_wakeup.sh                                                    # sleep in busier nights
SCHEDULER=tdma OUT=bs-results-tdma ./run_campaign.sh                                # TDMA in all sites (~1 h)
for c in ofdma tdma; do for n in ofdma tdma; do                                     # scheduler mix (~1 h 40)
  SCHEDULER=$c NEIGHBOR=$n TB_TRACE=true PROFILES=peak100 OUT=bs-results-mix/$c-$n ./run_campaign.sh
done; done
OUT=bs-results-wake3gpp CASES="night 16 3 20
night 16 3 160
night 16 25 160
day 16 3 20
peak100 64 3 20" ./run_wakeup.sh                                                     # 3GPP light and deep sleep
OUT=bs-results-grid PROFILES="day5 day10 day20 day30 day50 day60 day70 day80 day90 day100" \
  ./run_campaign.sh                                                                 # load grid, 64/32/16 chains
OUT=bs-results-grid PROFILES="night day5 day10 day20 day30 day40 day50 day60 day70 day80 day90 day100 peak100" \
  CHAINS="48 24" ./run_campaign.sh                                                  # load grid, 48/24 chains
OUT=bs-results-allsites NEIGHBOR_CHAINS=same CHAINS="32 16" ./run_campaign.sh  # all sites with fewer chains (~45 min)
```

Final study (step 13): every neighbour picks its chains for its own load (`NEIGHBOR_CHAINS=rule`, rule in `RULE`),
neighbour load as a multiple of the load of cell 0 (`NEIGHBOR_LOAD`, at most 150 Mbit/s). 1890 runs, about 21 h:

```bash
ALL="night day5 day10 day20 day30 day40 day50 day60 day70 day80 day90 day100 day110 day120 day130 day140 day150"
SOME="day10 day20 day40 day60 day80 day100 day120 day150"
HIGH="day80 day90 day100 day110 day120 day130 day140 day150"
export NEIGHBOR_CHAINS=rule CHAINS="64 48 32 24 16"
OUT=bs-results-indep/x1 NEIGHBOR_LOAD=1 PROFILES="$ALL" ./run_campaign.sh
OUT=bs-results-indep/x0.5 NEIGHBOR_LOAD=0.5 PROFILES="$SOME" ./run_campaign.sh
OUT=bs-results-indep/x2 NEIGHBOR_LOAD=2 PROFILES="$SOME" ./run_campaign.sh
OUT=bs-results-indep/x1 NEIGHBOR_LOAD=1 SEEDS=20 PROFILES="$HIGH" CHAINS="64 48 32" ./run_campaign.sh  # seeds 11-20
```

The two grid campaigns are 560 runs, about 4 h 30.

## Analysis

Always from `analysis/`, as modules:

```bash
cd analysis
../.venv/bin/python -m tests.test_power
../.venv/bin/python -m lib.campaign        # first: writes results/campaign.csv
../.venv/bin/python -m studies.plots       # main figures
```

| Script | Result | Needs |
|---|---|---|
| `studies.scenario` | Map of the scenario (sites, users, array, carriers, TDD frame) | nothing |
| `studies.schedulers` | Sketch of how OFDMA and TDMA fill a downlink slot | nothing |
| `studies.plots` | Power, delay and QoS figures | main campaign |
| `studies.daily` | Energy of one day per sleep policy | main campaign |
| `studies.efficiency` | Bit per Joule | main campaign |
| `studies.models` | Piovesan against EARTH and Björnson | main campaign |
| `studies.wakeup` | Wake-up time, estimate on the traces | main campaign |
| `studies.wakeup_ns3` | Wake-up time, simulated in NS-3 | main and wake-up campaigns |
| `studies.load_search` | Peak load that 64 chains sustain | load search |
| `studies.night` | Busier nights, with and without sleep | main, wake-up and both night campaigns |
| `studies.tdma` | TDMA against OFDMA | main and TDMA campaigns |
| `studies.mix` | Scheduler of cell 0 and of the neighbours, per-block errors | mix campaign |
| `studies.threegpp` | 3GPP TR 38.864 power model, with its light and deep sleep | main and 3GPP sleep campaigns |
| `studies.policy` | A rule that picks the chains from the measured load (`--peak`: 100 Mbit/s with video) | main and grid campaigns |
| `studies.allsites` | All sites with the same chains as cell 0 | main, mix and all-sites campaigns |
| `studies.final` | Final study: limits per chains and neighbour load, one day (Piovesan and 3GPP) | final, main, grid and 3GPP sleep campaigns; run `studies.policy` first (it prints its limits) |
| `studies.policy --final` | The rule of step 11 on the final configuration (run `studies.final` first) | final campaign |
