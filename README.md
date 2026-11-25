# 5G base station energy: NS-3 scenario and power model

How much energy can a 5G base station save by switching off parts of itself, and at what cost in
quality of service? An NS-3 + 5G-LENA scenario produces load and QoS; Python turns them into watts
with the AAU power model of Piovesan et al. (2022).

    NS-3 (C++) -> CSV per slot and per flow -> Python: metrics -> watts -> comparisons and figures

## Contents

| Path | What it is |
|---|---|
| `ns-3.46.1/scratch/bs-energy.cc` | The NS-3 scenario (the rest of NS-3 is not in this repository) |
| `docker/` | Environment: `Dockerfile` and `setup.sh` |
| `run_campaign.sh`, `run_wakeup.sh` | Main campaign (90 runs) and wake-up campaign (70 runs) |
| `analysis/lib/` | Shared code: paths, figure style, NS-3 metrics, power models, campaign loading |
| `analysis/studies/` | One script per result |
| `analysis/tests/` | Checks of the power models against numbers stated in the papers |

Raw NS-3 outputs, generated CSV files and figures are not in the repository.

## Setup

Requirements: Docker, git, Python 3.12, about 5 GB of free disk. Tested on an Apple M2 (arm64).

1. Get this repository, NS-3 3.46.1 and 5G-LENA v4.1.1 (the sources are unmodified):

   ```bash
   git clone https://github.com/FilizZPalm/5G-base-station-energy-NS-3-scenario-and-power-model.git
   cd 5G-base-station-energy-NS-3-scenario-and-power-model
   curl -LO https://www.nsnam.org/releases/ns-3.46.1.tar.bz2
   tar xjf ns-3.46.1.tar.bz2 -C ns-3.46.1 --strip-components=1
   git clone --branch v4.1.1 https://gitlab.com/cttc-lena/nr.git ns-3.46.1/contrib/nr
   ```

2. Build the image, create the `ns3-5g` container and compile (about 10 minutes):

   ```bash
   docker/setup.sh
   ```

   The image includes Eigen, which SU-MIMO needs.

3. Python environment:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install numpy==2.5.5 pandas==3.1.1 matplotlib==3.11.2
   ```

## Run

A single run (night profile, 16 active chains, 10 s, seed 1):

```bash
docker exec -e LD_LIBRARY_PATH=build-opt/lib ns3-5g \
  build-opt/scratch/ns3.46.1-bs-energy-optimized \
  --profile=night --antennas=16 --duration=10 --drain=0.5 --run=1 --out=test
```

Use `--help` instead of these options for the full list. Campaigns (resumable: finished runs are
skipped; the main one took about one hour on an M2):

```bash
OUT=bs-results-main ./run_campaign.sh     # night, day and 100 Mbit/s peak x 64/32/16 chains x 10 seeds
./run_wakeup.sh                           # sleep modes with a wake-up time
OUT=bs-results-load PROFILES="peak80 peak100 peak120" CHAINS=64 ./run_campaign.sh   # peak load search
```

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
| `studies.plots` | Power, delay and QoS figures | main campaign |
| `studies.daily` | Energy of one day per sleep policy | main campaign |
| `studies.efficiency` | Bit per Joule | main campaign |
| `studies.models` | Piovesan against EARTH and Björnson | main campaign |
| `studies.wakeup` | Wake-up time, estimate on the traces | main campaign |
| `studies.wakeup_ns3` | Wake-up time, simulated in NS-3 | main and wake-up campaigns |
| `studies.load_search` | Peak load that 64 chains sustain | load search |

## Main assumptions and limits

- Only the AAU and the downlink are modelled. No MU-MIMO: 5G-LENA is limited to SU-MIMO in downlink.
- Each run simulates 10 s of a traffic level (night, day, peak), not hours. A day is 8 h of night,
  12 h of day and 4 h of peak.
- The traffic levels, the 20 ms delay limit, the video segments (2 s, sent at 100 Mbit/s) and the
  pairing of sleep times (from a survey) with sleep powers (from Piovesan) are assumptions.
- Carrier shutdown and deep dormancy come from the power formula only, with no wake-up time or 4G QoS.
