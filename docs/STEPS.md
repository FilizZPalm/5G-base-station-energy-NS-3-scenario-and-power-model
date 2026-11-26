# How we got there: every step

The full record behind the [README](../README.md), in the order the work was done: what each step tried, what it
found, and the fixes and dead ends along the way. Scenario, traffic, power model and QoS criterion are described in
the README ([Method](../README.md#method)); the commands to rerun each campaign and study are in [RUN.md](RUN.md).

## 1. Calibrating the peak

At 150 Mbit/s the cell was overloaded in most seeds (losses 5-28%); the first trials had used a lucky
seed. A search at 64 chains over 80, 100 and 120 Mbit/s (`studies.load_search`) chose 100 Mbit/s: losses
below 0.1% on average, 8 of 70 burst users over 20 ms. Two model fixes came out of that search:
users attach to the strongest site instead of the one they were dropped around, and both carriers share
the same shadowing and line-of-sight state.

## 2. Main campaign: power and QoS

90 runs: 3 levels x 64/32/16 chains x 10 seeds (`run_campaign.sh`).

![AAU power by traffic level and number of chains](../analysis/figures/power_by_profile.png)

Fewer chains save more than symbol shutdown when the cell is quiet. At peak, symbol shutdown saves little
(713 against 767 W): there are few empty symbols.

![p95 delay of the burst users at peak](../analysis/figures/peak_p95_per_user.png)

At peak, 32 and 16 chains leave 24 and 33 of 70 burst users over 20 ms, against 8 with 64 chains. At
night no user exceeds the limit; by day 2, 2 and 4 of 100. So the best setting is 16 chains + symbol at
night (-32.1% against 64 chains always on) and by day (-31.6%), and 64 chains + symbol at peak (-7.1%).

![Power against QoS](../analysis/figures/power_vs_qos.png)

## 3. One day and the deeper sleep modes

![Energy of one day per sleep policy](../analysis/figures/daily_power.png)

Switching off all carriers or putting the AAU in deep dormancy at night would reach -32% and -39%, but
these come from the formula only: there is no wake-up time and the traffic moved to 4G is not
simulated. Symbol + channel gives -27.3% with 6, 8 or 10 hours of night; what moves it is the number
of peak hours, from -29.5% with 2 h to -25.1% with 6 h.

![Night power by sleep mode](../analysis/figures/night_sleep_modes.png)

## 4. Energy efficiency

![Energy efficiency in kbit/J](../analysis/figures/efficiency.png)

Delivered bits per joule rise most at night and by day (+46% to +47%). At peak, 32 and 16 chains look
more efficient but fail the QoS criterion. Over a day: 53.3 -> 73.3 kbit/J (+37.4 ± 0.8%).

## 5. Other power models: EARTH and Björnson

![Piovesan, EARTH and Björnson on the same traffic](../analysis/figures/models.png)

The same NS-3 load in the EARTH model (Auer et al. 2011, an LTE sector) and in the massive-MIMO model of
Björnson et al. (2015). Idle power as a share of full load: Piovesan 72%, EARTH 58-60%, Björnson 24%
with our transmit power or 84% with the paper's 0.1 W per antenna. The 2.5x overestimate of Björnson
mentioned by Piovesan is not reproduced with the parameters in Björnson's Table II: here it gives 4-8
times fewer watts. Which model is "most load-proportional" depends on that transmit-power choice.

## 6. Sleep with a wake-up time

A first estimate replayed the slot traces of the main campaign with an ideal sleep controller
(`studies.wakeup`):

![Sleep estimate on the traces](../analysis/figures/wakeup.png)

It was then simulated in NS-3 (`run_wakeup.sh`, 70 runs): a sleep controller holds new data while the AAU
sleeps, wakes it up after Tw, waits for pending HARQ feedback and keeps the SSB (synchronisation block)
schedule. No data was ever sent while asleep (0 violations).

![Sleep simulated in NS-3](../analysis/figures/wakeup_ns3.png)

With Tw = 0.5 ms the AAU sleeps 82% of the night and saves another 18% on top of symbol + channel, at
the cost of about 1 ms of p95 delay. With Tw = 5 ms it barely sleeps unless the SSB comes every 160 ms.
The trace estimate was optimistic (it ignored the wait for HARQ feedback): 11.01 against 11.30 kWh.

## 7. Busier nights

Our night carries 1% of the peak traffic; EARTH's daily minimum of active users is 14% of its maximum.
Nights at 5, 10 and 15 Mbit/s were simulated (150 runs, `studies.night`).

![Sleep saving as the night gets busier](../analysis/figures/night_load.png)

Symbol + channel keeps its -32% at all four loads. The extra saving of sleep falls from 18% to 11%
(Tw 0.5 ms) and from 17% to 4% (Tw 5 ms). Over a day: -31.2% at 1 Mbit/s, -29.7% at 15 Mbit/s.

## 8. TDMA against OFDMA

OFDMA shares the band of a slot among users in frequency and fills almost every symbol, even for small
data. TDMA gives each user whole symbols over the full band and stops when the data fits, which leaves
more empty symbols for the PAs. The same 90 runs were repeated with TDMA in all sites (`studies.tdma`).

![How OFDMA and TDMA fill a downlink slot](../analysis/figures/schedulers.png)

![Peak: OFDMA against TDMA](../analysis/figures/tdma.png)

At peak, TDMA lowers the power with symbol shutdown by 21 W at 64 chains and halves the users over
20 ms (8 -> 4, 24 -> 12, 33 -> 19). By day and at night it changes little, since the saving there comes
from slots that are empty with either scheduler. Over a day: -28.0% instead of -27.3%. The best setting
does not change.

## 9. Why TDMA serves the peak better

A 2 x 2 campaign (`studies.mix`, 120 runs) set the scheduler of cell 0 and of its neighbours
independently and traced every transport block received in cell 0.

![Errors and SINR spread in the four combinations](../analysis/figures/mix.png)

The mean SINR and the chosen MCS barely change. What changes is the share of blocks received in error at
the first transmission (10-25%), and the error model of 5G-LENA predicts these rates exactly. Two
separate effects, averaged over the other factor:

- **TDMA in the neighbours** makes their interference flat across frequency. The gap between the mean
  SINR of a block and its worst resource block shrinks by about 3 dB, and errors drop by 2.7-5.3 points.
- **TDMA in cell 0** lowers errors by 3.9-4.7 points although that gap grows slightly, so the cause is
  different and is **not verified**. It is not a choice of sub-bands: with the default wideband MCS,
  OFDMA assigns resource blocks in order. A candidate is that the MCS is computed on the whole band, which
  a TDMA block uses and an OFDMA block does not; TDMA blocks are also shorter (9.4 against 12.5 symbols).

Fewer retransmissions mean shorter queues. The power saving comes mostly from cell 0 (-15.9 W at 64
chains, against -4.8 W from the neighbours).

## 10. The 3GPP power model

Steps 3 and 6 pair sleep times from a survey with sleep powers from Piovesan. 3GPP TR 38.864 (V18.1.0,
clause 5.1), the study on network energy saving for NR, gives both in one model, for a reference
configuration close to ours (TDD, 100 MHz at 30 kHz, 64 transmit chains). Powers are relative to deep
sleep (= 1). The report gives two alternative sets of values, Category 1 and Category 2, without saying
which equipment they stand for:

| State | Category 1 | Category 2 | Total transition time (down + up), Cat. 1 / Cat. 2 |
|---|---|---|---|
| Active DL, full load | 280 | 32 | - |
| Active UL | 110 | 6.5 | - |
| Micro sleep | 55 | 5.5 | immediate |
| Light sleep | 25 | 2.1 | 6 ms / 640 ms |
| Deep sleep | 1 | 1 | 50 ms / 10 s |

While transmitting, the power of a symbol is

$$
P_{\mathrm{DL}} = P_{\mathrm{micro}} + s_a\,A\,(P_{\mathrm{DL,max}} - P_{\mathrm{micro}}) + s_f\,(1-A)\,(P_{\mathrm{DL,max}} - P_{\mathrm{micro}}),
\qquad A = 0.4
$$

with $s_a$ the share of active chains and $s_f$ the share of the 100 MHz band in use. A second contiguous
carrier costs 0.7 times the first, and each light or deep sleep adds a transition energy. `studies.threegpp`
builds this power symbol by symbol from the same NS-3 traces. Empty symbols drop to micro sleep with symbol
shutdown. Assumptions: the control symbol uses the whole carrier, UL symbols are always receiving, and
the 0.7 factor also applies to sleep states.

![One day with Piovesan and the 3GPP model](../analysis/figures/threegpp.png)

The savings nearly double: an empty symbol costs 20% of full load in the 3GPP model against 47% in
Piovesan, which was fitted on today's commercial hardware. Light and deep sleep were first estimated on the
traces, then simulated in NS-3 for Category 1 (50 runs, wake-up time = half of the transition time):

- light sleep at night adds 30.0% with an SSB every 20 ms and 52.2% with one every 160 ms, with no user
  over 20 ms; by day it adds 4.4% and at peak 1.4%, within the QoS criterion;
- deep sleep at night adds 49.5%, less than light sleep, and puts every night burst user over 20 ms;
- deep sleep needs 50 ms, which does not fit between SSBs 20 ms apart. Category 2 transitions (640 ms
  and 10 s) fit only without any SSB, and its deep sleep is longer than the simulated window.

## 11. A policy that picks the chains by itself

The best settings of step 2 assume someone knows the traffic level. Here a simple rule decides alone:
every 5, 15 or 60 minutes it looks at the load just measured, adds a safety margin (0, 25, 50 or 100%) and
keeps the fewest chains that sustain that load for the next interval. Two arrays were added to the scenario,
48 (6 x 8) and 24 (4 x 6) chains, and the day profile was simulated from 5 to 100 Mbit/s every 10 Mbit/s
at all five chain counts (560 runs, `bs-results-grid`).

| Chains | QoS acceptable up to | Power at 100 Mbit/s with symbol shutdown |
|---|---|---|
| 16 | 40 Mbit/s | 526 W (fails) |
| 24 | 50 Mbit/s | 563 W (fails) |
| 32 | 50 Mbit/s | 599 W (fails) |
| 48 | 100 Mbit/s | 662 W |
| 64 | 100 Mbit/s | 723 W |

48 chains sustain the whole peak, so 64 are almost never needed; 32 are never chosen, since 24 sustain the
same load for less. The rule was tested on 300 simulated days of 5-minute loads: our 8/12/4 h levels with
one-hour ramps, times a random log-normal fluctuation (σ = 0.25, correlated between steps). Each step uses
the power and QoS of the 10 s runs at its load, and switching chains is taken as instantaneous.

![One simulated day and the chains the rule picks](../analysis/figures/policy_day.png)

![Saving against time with QoS not acceptable](../analysis/figures/policy_tradeoff.png)

| Policy | Saving, Piovesan | Saving, 3GPP Cat. 1 | Time with QoS not acceptable |
|---|---|---|---|
| 64 chains + symbol, no decision | 18.9% | 39.1% | 0 |
| Oracle (knows the load of each step) | 27.6% | 48.5% | 0 |
| Every 5 min, margin 50% | 24.0% | 45.3% | 0.04% |
| Every 5 min, margin 100% | 22.8% | 44.1% | 0 |
| Every 15 min, margin 100% | 22.8% | 44.1% | 0.05% |
| Every 60 min, margin 100% | 23.1% | 44.2% | 1.2% |

Without a margin the rule saves as much as the oracle but leaves the QoS unacceptable 7-16% of the time,
every day: the load rises within the interval. Deciding every 5-15 minutes with a wide margin keeps about
23-24% with almost no violation; deciding every hour is too slow. The intermediate arrays add 2-3 points
compared with a choice among 64, 32 and 16 only (oracle 24.2%, 5 min with 50% margin 21.4%). Taking the
100 Mbit/s point from the peak profile with video instead of the day profile (`--peak`) changes no
acceptable load and no saving by more than 0.1 points.

## 12. All sites with fewer chains

Until here only cell 0 saved energy and its neighbours kept 64 chains. In a real network all sites would switch
off chains together, and with fewer chains each neighbour transmits less power (each PA keeps its own maximum), so
cell 0 sees less interference. The main campaign was repeated with the neighbours at the same number of chains as
cell 0 (60 runs, `studies.allsites`); 64 chains are the same runs in both cases.

| Level | Chains | Neighbours | Saving, symbol shutdown | Burst users over 20 ms | Late video segments | SINR at peak | First-transmission errors |
|---|---|---|---|---|---|---|---|
| Night | 16 | 64 / same | 32.1% / 32.1% | 0 / 0 of 20 | - | - | - |
| Day | 16 | 64 / same | 31.6% / 31.7% | 4 / 3 of 100 | - | - | - |
| Peak | 64 | 64 | 7.1% | 8 of 70 | 2 | 35.8 dB | 15.9% |
| Peak | 32 | 64 / same | 23.1% / 23.8% | 24 / 12 of 70 | 6 / 3 | 30.0 / 31.1 dB | 20.2% / 17.7% |
| Peak | 16 | 64 / same | 31.9% / 32.6% | 33 / 13 of 70 | 13 / 8 | 25.3 / 27.3 dB | 22.5% / 19.1% |

At night and by day nothing changes: the neighbours are almost silent. At peak, neighbours with fewer chains
raise the SINR in cell 0 by 1-2 dB, cut the errors by 2.5-3.4 points and halve the users over 20 ms, but 32
and 16 chains still fail the QoS criterion (+5.7 and +7.1 points of users over 20 ms, and extra late segments).
So the best setting per level does not change, and the results of the earlier steps, with neighbours at 64,
are slightly pessimistic for the QoS at peak. The SINR and errors with neighbours at 64 come from the mix
campaign of step 9, whose OFDMA runs are identical to the main ones.
