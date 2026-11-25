"""Wake-up estimate on the campaign traces (no new NS-3 runs): energy saved against delay added.

Slot-by-slot model of cell 0. Every DL slot with data is one unit of work. After an idle timer the
AAU goes to sleep; down and up transitions take Tw each. Work that arrives meanwhile waits, then
is served one unit per DL slot. The AAU must be awake for every SSB (planned wake-up).
Lower bound on the delay: only the cell queue is modelled, with no change in scheduling."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save

SLOT_MS = ns3data.SLOT * 1e3
FIRST, N = round(ns3data.WARMUP / ns3data.SLOT), round(c.DURATION / ns3data.SLOT)
# ASSUMPTIONS ---------------------------------------------------------------------------
CASES = {"night": 16, "day": 16, "peak100": 64}         # chains chosen by the campaign, all with symbol shutdown
TW_MS = (0.5, 5, 50, 500)                                # half of the minimum durations of SM2, SM3, (50), SM4
SSB_MS = (20, 160, None)                                 # SSB period; None: no SSB (traffic anchor on 4G)
TIMERS = {"immediate": 0, "2 Tw": 2}                     # idle time before sleeping, in units of Tw
DEPTH = {"RF off": pw.CARRIER_OFF, "dormancy": pw.DORMANT}  # power states of Piovesan
# ---------------------------------------------------------------------------------------


def trace(profile, chains, seed):
    s = pd.read_csv(c.RAW / f"{profile}_a{chains}_r{seed}_slots.csv")
    u = s.groupby("slot").used_sym.max()
    dl, work = np.zeros(N, bool), np.zeros(N, bool)
    idx = u.index.to_numpy() - FIRST
    keep = (idx >= 0) & (idx < N)
    dl[idx[keep]] = True
    work[idx[keep]] = u.to_numpy()[keep] > 0
    return dl, work


def run(dl, work, tw, ssb, timer):
    """tw, ssb and timer in slots. Returns the fraction of time asleep and the delay of each unit [ms]."""
    AWAKE, DOWN, SLEEP, UP = range(4)
    state, left, idle, asleep, queue, delays = AWAKE, 0, 0, 0, [], []
    head = 0
    for t in range(N):
        if work[t]:
            queue.append(t)
        waiting = head < len(queue)
        to_ssb = (-t) % ssb if ssb else N  # slots to the next SSB (0: SSB now)
        if state == SLEEP:
            # planned wake-up for the SSB, or unplanned because of traffic
            if waiting or to_ssb <= tw:
                state, left = UP, tw
        if state == AWAKE:
            if waiting and dl[t]:
                delays.append(t - queue[head])
                head += 1
                idle = 0
            elif waiting or (ssb and to_ssb == 0):
                idle = 0 if waiting else idle
            else:
                idle += 1
                if idle > timer and to_ssb > 2 * tw + 1:
                    state, left = DOWN, tw
        elif state == SLEEP:
            asleep += 1
        if state in (DOWN, UP):
            left -= 1
            if left <= 0:
                state = SLEEP if state == DOWN else AWAKE
                idle = 0
    return asleep / N, np.array(delays) * SLOT_MS, len(queue) - head


def idle_watt(chains):
    """Awake AAU without data, symbol shutdown on: only the control symbol and transitions keep the PAs on."""
    return float(pw.piovesan(0, chains, (13 - ns3data.TRANSITION_SYM) / 14)) * c.W


if __name__ == "__main__":
    rows = []
    base = c.runs.set_index(["profile", "chains", "seed"])
    for p, a in CASES.items():
        traces = [trace(p, a, r) for r in range(1, c.SEEDS + 1)]
        ref = np.array([base.loc[(p, a, r), "watt_sym"] for r in range(1, c.SEEDS + 1)])
        for tw_ms in TW_MS:
            for ssb_ms in SSB_MS:
                for tname, mult in TIMERS.items():
                    tw = round(tw_ms / SLOT_MS)
                    out = [run(d, w, tw, round(ssb_ms / SLOT_MS) if ssb_ms else 0, mult * tw) for d, w in traces]
                    f = np.array([o[0] for o in out])
                    dly = np.concatenate([o[1] for o in out])
                    left = sum(o[2] for o in out)
                    for depth, pw_sleep in DEPTH.items():
                        watt = ref - f * (idle_watt(a) - pw_sleep * c.W)
                        rows.append(dict(profile=p, chains=a, tw_ms=tw_ms, ssb_ms=ssb_ms or 0, timer=tname, depth=depth,
                                         asleep_pct=100 * f.mean(), watt=watt.mean(),
                                         extra_saving_pct=100 * (1 - watt.mean() / ref.mean()),
                                         delay_mean=dly.mean(), delay_p95=np.percentile(dly, 95),
                                         delay_max=dly.max(), unserved=left))
    r = pd.DataFrame(rows)
    r.to_csv(paths.RESULTS / "wakeup.csv", index=False)
    pd.set_option("display.width", 220, "display.max_rows", 200)
    print({k: round(idle_watt(a), 1) for k, a in CASES.items()}, {k: round(v * c.W, 1) for k, v in DEPTH.items()})
    print(r[(r.depth == "RF off")].round(2).drop(columns="depth").to_string(index=False))

    # Figure: extra saving over symbol shutdown, RF off, timer 2 Tw; label = added p95 delay
    titles = {"night": "Night, 16 chains", "day": "Day, 16 chains", "peak100": "Peak, 64 chains"}
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.2), sharey=True)
    q = r[(r.depth == "RF off") & (r.timer == "2 Tw") & (r.tw_ms <= 50)]
    tws = sorted(q.tw_ms.unique())
    for ax, (p, title) in zip(axes, titles.items()):
        for k, (ssb, color, lab) in enumerate(((20, BLUE, "SSB every 20 ms"), (160, ORANGE, "SSB every 160 ms"),
                                               (0, AQUA, "no SSB"))):
            s = q[(q.profile == p) & (q.ssb_ms == ssb)].set_index("tw_ms").loc[tws]
            x = np.arange(len(tws)) + (k - 1) * .28
            ax.bar(x, s.extra_saving_pct, .25, color=color, label=lab)
            for xi, v, dl in zip(x, s.extra_saving_pct, s.delay_p95):
                if v > .5:
                    ax.text(xi, v + .4, f"+{dl:.0f} ms", ha="center", fontsize=7, rotation=90, color=INK)
        ax.set(title=title, xticks=range(len(tws)), xticklabels=[f"{t:g}" for t in tws], xlabel="wake-up time Tw [ms]", ylim=(0, 27))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("extra saving over symbol shutdown [%]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=3, frameon=False, fontsize=9)
    save(fig, "wakeup.png", "RF off, idle timer 2 Tw. Labels: added p95 delay")
