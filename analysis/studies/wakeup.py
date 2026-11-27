"""Sleep with a wake-up time, estimated on the traces of the main campaign (step 6 of docs/STEPS.md; no new NS-3 runs).

Question: if the whole AAU sleeps between bursts, how much energy does it save and how much delay does it add?

Model, slot by slot, of cell 0:
  - every downlink slot that carried data in the trace is one unit of work, arriving in that slot;
  - when the AAU has been idle for a while (the idle timer), it goes to sleep; going down and coming back up take
    Tw each, during which nothing is served;
  - work that arrives while the AAU is not awake waits; once awake, one unit is served per downlink slot;
  - the AAU must be awake for every SSB (the synchronisation signal), so it wakes up in time for it.
The delay is a lower bound: only the queue of the cell is modelled, the scheduling does not change.

Run from analysis/:  ../.venv/bin/python -m studies.wakeup
Also imported by studies.night, studies.wakeup_ns3 and studies.threegpp (trace, run, idle_watt, CASES ...).
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save

SLOT_MS = ns3data.SLOT * 1e3                                 # 0.5 ms
FIRST = round(ns3data.WARMUP / ns3data.SLOT)                # first measured slot (600)
N = round(campaign.DURATION / ns3data.SLOT)                 # measured slots per run (20000)

# ASSUMPTIONS ------------------------------------------------------------------------------------------------------
CASES = {"night": 16, "day": 16, "peak100": 64}              # chains of the best setting per level, symbol shutdown on
TW_MS = (0.5, 5, 50, 500)                                    # Tw: half of the minimum duration of SM2, SM3, (50), SM4
SSB_MS = (20, 160, None)                                     # SSB period; None: no SSB (the 4G anchor keeps the users)
TIMERS = {"immediate": 0, "2 Tw": 2}                         # idle time before sleeping, in units of Tw
DEPTH = {"RF off": power.CARRIER_OFF, "dormancy": power.DORMANT}   # Piovesan power while asleep
# ------------------------------------------------------------------------------------------------------------------

AWAKE, GOING_DOWN, ASLEEP, WAKING_UP = range(4)


def trace(profile, chains, seed):
    """Two arrays over the measured slots: is it a downlink slot, and does it carry data."""
    slots = pd.read_csv(campaign.RAW / f"{profile}_a{chains}_r{seed}_slots.csv")
    used_symbols = slots.groupby("slot").used_sym.max()       # busier of the two carriers
    is_downlink, has_work = np.zeros(N, bool), np.zeros(N, bool)
    index = used_symbols.index.to_numpy() - FIRST
    inside = (index >= 0) & (index < N)
    is_downlink[index[inside]] = True                          # uplink slots are not in the trace
    has_work[index[inside]] = used_symbols.to_numpy()[inside] > 0
    return is_downlink, has_work


def run(is_downlink, has_work, tw, ssb, timer):
    """Simulate the sleep controller over one trace. tw, ssb (period, 0 = none) and timer are in slots.

    Returns: share of time asleep, delay of each unit of work [ms], units left unserved at the end,
    share of time not awake (asleep or in a transition), number of times the AAU went to sleep.
    """
    state, transition_left, idle_slots = AWAKE, 0, 0
    queue, next_unit, delays = [], 0, []          # arrival slot of each unit; index of the next one to serve
    slots_asleep, slots_not_awake, sleeps = 0, 0, 0
    for t in range(N):
        if has_work[t]:
            queue.append(t)
        waiting = next_unit < len(queue)
        to_ssb = (-t) % ssb if ssb else N          # slots until the next SSB (0: an SSB is sent now)

        if state == ASLEEP and (waiting or to_ssb <= tw):
            # wake up: unplanned because of traffic, or planned to be awake for the SSB
            state, transition_left = WAKING_UP, tw

        if state == AWAKE:
            if waiting and is_downlink[t]:          # serve one unit
                delays.append(t - queue[next_unit])
                next_unit += 1
                idle_slots = 0
            elif waiting:                           # work waiting in an uplink slot: not idle
                idle_slots = 0
            elif ssb and to_ssb == 0:               # sending the SSB: not idle, but the idle count goes on
                pass
            else:
                idle_slots += 1
                # go to sleep after the idle timer, if there is time to come back before the next SSB
                if idle_slots > timer and to_ssb > 2 * tw + 1:
                    state, transition_left = GOING_DOWN, tw
                    sleeps += 1
        elif state == ASLEEP:
            slots_asleep += 1

        slots_not_awake += state != AWAKE
        if state in (GOING_DOWN, WAKING_UP):
            transition_left -= 1
            if transition_left <= 0:
                state = ASLEEP if state == GOING_DOWN else AWAKE
                idle_slots = 0
    return slots_asleep / N, np.array(delays) * SLOT_MS, len(queue) - next_unit, slots_not_awake / N, sleeps


def idle_watt(chains):
    """Power of an awake AAU without data, symbol shutdown on: of the 14 symbols of a slot only the control symbol and
    the two transition symbols keep the PAs on, so they are off in 13 - 2 of 14."""
    return float(power.piovesan(0, chains, (13 - ns3data.TRANSITION_SYM) / 14)) * campaign.W


def plot(table):
    """Extra saving over symbol shutdown, RF off state, timer 2 Tw; label = added p95 delay."""
    titles = {"night": "Night, 16 chains", "day": "Day, 16 chains", "peak100": "Peak, 64 chains"}
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.2), sharey=True)
    shown = table[(table.depth == "RF off") & (table.timer == "2 Tw") & (table.tw_ms <= 50)]
    tws = sorted(shown.tw_ms.unique())
    for ax, (profile, title) in zip(axes, titles.items()):
        for k, (ssb, color, label) in enumerate(((20, BLUE, "SSB every 20 ms"), (160, ORANGE, "SSB every 160 ms"),
                                                 (0, AQUA, "no SSB"))):
            bars = shown[(shown.profile == profile) & (shown.ssb_ms == ssb)].set_index("tw_ms").loc[tws]
            x = np.arange(len(tws)) + (k - 1) * .28
            ax.bar(x, bars.extra_saving_pct, .25, color=color, label=label)
            for xi, saving, delay in zip(x, bars.extra_saving_pct, bars.delay_p95):
                if saving > .5:
                    ax.text(xi, saving + .4, f"+{delay:.0f} ms", ha="center", fontsize=7, rotation=90, color=INK)
        ax.set(title=title, xticks=range(len(tws)), xticklabels=[f"{t:g}" for t in tws], xlabel="wake-up time Tw [ms]",
               ylim=(0, 27))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("extra saving over symbol shutdown [%]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=3, frameon=False, fontsize=9)
    save(fig, "wakeup.png", "RF off, idle timer 2 Tw. Labels: added p95 delay")


if __name__ == "__main__":
    rows = []
    main = campaign.runs.set_index(["profile", "chains", "seed"])
    seeds = range(1, campaign.SEEDS + 1)
    for profile, chains in CASES.items():
        traces = [trace(profile, chains, seed) for seed in seeds]
        without_sleep = np.array([main.loc[(profile, chains, seed), "watt_sym"] for seed in seeds])
        for tw_ms in TW_MS:
            for ssb_ms in SSB_MS:
                for timer_name, timer_in_tw in TIMERS.items():
                    tw = round(tw_ms / SLOT_MS)
                    ssb = round(ssb_ms / SLOT_MS) if ssb_ms else 0
                    results = [run(is_dl, work, tw, ssb, timer_in_tw * tw) for is_dl, work in traces]
                    asleep = np.array([r[0] for r in results])            # per seed
                    delays = np.concatenate([r[1] for r in results])
                    unserved = sum(r[2] for r in results)
                    for depth, sleep_power in DEPTH.items():
                        # while asleep the AAU draws the sleep power instead of the idle awake power
                        watt = without_sleep - asleep * (idle_watt(chains) - sleep_power * campaign.W)
                        rows.append(dict(profile=profile, chains=chains, tw_ms=tw_ms, ssb_ms=ssb_ms or 0, timer=timer_name,
                                         depth=depth, asleep_pct=100 * asleep.mean(), watt=watt.mean(),
                                         extra_saving_pct=100 * (1 - watt.mean() / without_sleep.mean()),
                                         delay_mean=delays.mean(), delay_p95=np.percentile(delays, 95),
                                         delay_max=delays.max(), unserved=unserved))
    table = pd.DataFrame(rows)
    table.to_csv(paths.RESULTS / "wakeup.csv", index=False)
    pd.set_option("display.width", 220, "display.max_rows", 200)
    print({k: round(idle_watt(a), 1) for k, a in CASES.items()}, {k: round(v * campaign.W, 1) for k, v in DEPTH.items()})
    print(table[(table.depth == "RF off")].round(2).drop(columns="depth").to_string(index=False))
    plot(table)
