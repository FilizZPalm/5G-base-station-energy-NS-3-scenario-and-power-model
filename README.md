# 5G base station energy: NS-3 scenario and power model

How much energy can a 5G base station save by switching off parts of itself, and at what cost in
quality of service? An NS-3 + 5G-LENA scenario produces load and QoS; Python turns them into watts
with the AAU power model of Piovesan et al. (2022).

    NS-3 (C++) -> CSV per slot and per flow -> Python: metrics -> watts -> comparisons and figures

This page gives the scenario, the main results and how to set up. The full record of the work, step by
step, is in [docs/STEPS.md](docs/STEPS.md); every command to rerun it is in [docs/RUN.md](docs/RUN.md).

## Results at a glance

| Question | Answer (10 seeds, 95% CI where shown) |
|---|---|
| Saving over a day, symbol + channel shutdown | **-27.3 ± 0.4%** (16.83 -> 12.24 kWh) |
| ... adding a 0.5 ms sleep mode, simulated in NS-3 | **-32.9 ± 0.6%** (11.30 kWh) |
| Best setting per traffic level | night and day: 16 of 64 chains + symbol shutdown; peak: 64 chains + symbol |
| QoS cost | none at night and by day; at peak, fewer chains fail the QoS criterion |
| A rule that picks the chains from the load measured every 5 min | **-24.0%** with QoS unacceptable 0.04% of the time (oracle -27.6%) |
| Same traffic, 3GPP power model (TR 38.864) | symbol + channel **-48%**; with light sleep at night (SSB every 160 ms) **-55.5%** |
| Energy efficiency over a day | 53.3 -> 73.3 kbit/J (+37%) |
| TDMA instead of OFDMA scheduling | about 1% less energy over a day, and fewer users over 20 ms at peak (8 -> 4 of 70) |

All of this rests on the assumptions listed [at the end](#main-assumptions-and-limits): the traffic
levels, the hours per level, the 20 ms delay limit and the pairing of sleep times with sleep powers.

## Method

![The simulated scenario](analysis/figures/scenario.png)

**Scenario** (`ns-3.46.1/scratch/bs-energy.cc`). Three sites 500 m apart (cell radius 250 m), 10 users per site, urban
macro channel (3GPP UMa) with shadowing. Each site is one active antenna unit (AAU) with two contiguous
30 MHz carriers at 3.5 GHz (n78), TDD pattern DDDSU and a 64-element array. Only cell 0 is measured; its
neighbours use 64 chains. Scheduling is proportional fair. SU-MIMO with two layers is on;
MU-MIMO is not available in 5G-LENA for the downlink. Each user is attached to its strongest site.

**Traffic.** Three levels, each simulated for 10 s after a 0.3 s warm-up, with 10 random seeds. A day is
8 h of night, 12 h of day and 4 h of peak.

| Level | Offered traffic | Users |
|---|---|---|
| Night | 1 Mbit/s | 2 per site, rare Poisson bursts of 25 kB |
| Day | 40 Mbit/s | 10 per site, Poisson bursts |
| Peak | 100 Mbit/s | 3 video users (3, 10, 40 Mbit/s, as 2 s segments) + 7 burst users |

**Power model** (`analysis/lib/power.py`). Piovesan et al. (2022), normalised to a 930 W peak:

$$
P_{\mathrm{AAU}} = P_0 + P_{\mathrm{BB}} + M_{\mathrm{av}}\,D_{\mathrm{Tran}} + M_{\mathrm{ac}}\,D_{\mathrm{PA}} + \frac{1}{\eta}\sum_{c=1}^{C} P_{\mathrm{TX},c}
$$

where $P_0$ is the static power, $P_{\mathrm{BB}}$ the baseband, $M_{\mathrm{av}}$ and $M_{\mathrm{ac}}$ the available
and active transceiver chains, $D_{\mathrm{Tran}}$ and $D_{\mathrm{PA}}$ the power of one transceiver and of one
power amplifier (PA), $\eta$ the PA efficiency and $P_{\mathrm{TX},c}$ the transmitted power of carrier $c$
($C = 2$). $P_{\mathrm{TX},c}$ follows the simulated resource-block (PRB) load. The savings act on these terms:

- **Symbol shutdown**: the PAs sleep in downlink symbols that carry no data on either carrier, minus
  two transition symbols. One control symbol per slot always stays on.
- **Channel shutdown**: only 48, 32, 24 or 16 of the 64 transceiver chains stay active ($M_{\mathrm{ac}}$); the
  array shrinks in NS-3 too, so the loss of beamforming gain is simulated.
- **Sleep modes**: the whole AAU sleeps between bursts and needs a wake-up time; simulated in NS-3.

**QoS.** Per burst user, the 95th percentile (p95) of the packet delay, against a 20 ms limit. A
setting is acceptable if, compared to 64 chains on the same seeds, at most 5 more users in 100 exceed
the limit, no extra video segment arrives late (a segment needs 99% of its packets within 2 s) and
losses stay under 1%.

## Main results

**Fewer chains save most when the cell is quiet** ([step 2](docs/STEPS.md#2-main-campaign-power-and-qos)).
At night and by day 16 of 64 chains with symbol shutdown cut the power by about 32% at no QoS cost. At peak,
32 and 16 chains leave 24 and 33 of 70 burst users over 20 ms (8 with 64), so 64 chains stay on.

![AAU power by traffic level and number of chains](analysis/figures/power_by_profile.png)

**Over a day: -27.3%, and -32.9% with a sleep mode** ([steps 3](docs/STEPS.md#3-one-day-and-the-deeper-sleep-modes)
and [6](docs/STEPS.md#6-sleep-with-a-wake-up-time)). Sleeping between bursts with a 0.5 ms wake-up time adds 18% at
night, for about 1 ms more delay. What moves the daily saving most is the number of peak hours.

![Energy of one day per sleep policy](analysis/figures/daily_power.png)

**A simple rule gets most of it without knowing the traffic**
([step 11](docs/STEPS.md#11-a-policy-that-picks-the-chains-by-itself)). Every 5 minutes it measures the load,
adds a 50% margin and keeps the fewest chains that sustain it: -24.0% against -27.6% for an oracle, with
the QoS unacceptable 0.04% of the time. Deciding every hour is too slow. 48 chains sustain the whole peak.

![Saving against time with QoS not acceptable](analysis/figures/policy_tradeoff.png)

**The power model matters as much as the technique** ([step 10](docs/STEPS.md#10-the-3gpp-power-model)). With
the 3GPP TR 38.864 model (Category 1) the same traffic saves 48%, and 55.5% with light sleep at night, because
an empty symbol costs 20% of full load there against 47% in Piovesan. The report does not say which of its two
categories of values applies to real equipment.

![One day with Piovesan and the 3GPP model](analysis/figures/threegpp.png)

Also in [STEPS.md](docs/STEPS.md): calibrating the peak load (1), energy efficiency in bit/J (4), the EARTH
and Björnson power models (5), busier nights (7), TDMA against OFDMA and why TDMA serves the peak better
(8, 9), all sites with fewer chains (12).

## Main assumptions and limits

- Only the AAU and the downlink are modelled. No MU-MIMO: 5G-LENA is limited to SU-MIMO in downlink, so
  64 chains lose their main advantage and the QoS cost of fewer chains is probably underestimated.
- Each run simulates 10 s of a traffic level, not hours. The traffic levels, the 8/12/4 h day, the 20 ms
  delay limit and the QoS criterion, and the video segments are assumptions.
- With Piovesan, sleep times come from a survey and sleep powers from Piovesan. The 3GPP model gives both
  from one source but leaves open which of its two categories applies.
- In the main results the neighbour sites keep 64 chains while cell 0 saves. With all sites at the same
  chains the QoS at peak improves but the best settings do not change ([step 12](docs/STEPS.md#12-all-sites-with-fewer-chains)).
- Sleep with a wake-up time is implemented on the OFDMA scheduler only, so TDMA was not combined with it.
- With OFDMA, 18-25% of the blocks at peak fail their first transmission, above the usual 10% target:
  5G-LENA has no outer loop link adaptation. A simple one is available (`--ollaStep`, off) but made delay,
  losses and power much worse in a trial; all results are without it.
- The policy study takes a change of chains as instantaneous and free.
- With 10 seeds the QoS differences have wide intervals.

## Contents

| Path | What it is |
|---|---|
| `ns-3.46.1/scratch/bs-energy.cc` | The NS-3 scenario (the rest of NS-3 is not in this repository) |
| `docker/` | Environment: `Dockerfile` and `setup.sh` |
| `run_campaign.sh`, `run_wakeup.sh` | Campaigns: traffic levels x chains x seeds; sleep with a wake-up time |
| `analysis/lib/` | Shared code: paths, figure style, NS-3 metrics, power models, campaign loading |
| `analysis/studies/` | One script per result |
| `analysis/tests/` | Checks of the power models against numbers stated in the papers |
| `analysis/figures/` | The figures, generated by the studies |
| `docs/` | The full record of the steps, and how to rerun everything |

Raw NS-3 outputs and generated CSV files are not in the repository.

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

2. Build the image, create the `ns3-5g` container and compile (about 10 minutes; the image includes Eigen,
   which SU-MIMO needs):

   ```bash
   docker/setup.sh
   ```

3. Python environment:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install numpy==2.5.5 pandas==3.1.1 matplotlib==3.11.2
   ```

4. Main campaign (90 runs, about 1 hour) and main figures:

   ```bash
   OUT=bs-results-main ./run_campaign.sh
   cd analysis
   ../.venv/bin/python -m lib.campaign
   ../.venv/bin/python -m studies.plots
   ```

All other campaigns and studies: [docs/RUN.md](docs/RUN.md).
