"""A policy that decides by itself: every decision interval it looks at the load just measured and picks the active
chains for the next one. Compared with always on and with the oracle that knows the load in advance (as in daily.py).

Ingredients (all with symbol shutdown):
- power and QoS against load and chains (64, 48, 32, 24, 16), from NS-3: night (1 Mbit/s, 2 users), day profile at
  5-100 Mbit/s every 10 (10 burst users, bs-results-grid, the main campaign at 40 for 64/32/16 chains);
  at 100 Mbit/s either the day profile (default) or, with --peak, the peak profile (53 Mbit/s of video + bursts);
- a QoS-acceptable load per number of chains: the highest grid load whose QoS passes the criterion of campaign.py
  (relative to 64 chains), and every lower grid load passes too;
- a day of 5-minute loads: our 8/12/4 h levels with one-hour ramps, times random fluctuations (ASSUMPTIONS below).
Each 5-minute step is evaluated with the 10 s runs of its load (quasi-static assumption). A step is a QoS violation
when its load is above the acceptable load of the chains in use. Switching chains is taken as instantaneous."""
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save
from studies.daily import half_ci

GRID = paths.RAW / "bs-results-grid"
# ASSUMPTIONS ---------------------------------------------------------------------------
STEP_MIN = 5
LEVELS = [(0, 7, 1), (7, 17, 40), (17, 21, 100), (21, 23, 40), (23, 24, 1)]   # hour from, hour to, Mbit/s: 8/12/4 h
RAMP_H = 1                     # each change of level takes one hour (centred on the boundary)
NOISE_SIGMA, NOISE_RHO = 0.25, 0.8   # log-normal fluctuation per 5-minute step, AR(1) correlation between steps
MAX_MBPS = 100                 # loads are clipped to the highest simulated level
DAYS = 300                     # simulated days
INTERVALS_MIN = (5, 15, 60)    # decision intervals
MARGINS = (0, 0.25, 0.5, 1.0)  # safety margin on the measured load
# ---------------------------------------------------------------------------------------
LOADS = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
CHAINS = (64, 48, 32, 24, 16)
PEAK = "--peak" in sys.argv    # 100 Mbit/s from the peak profile (with video) instead of day100
# --final: the final campaign (bs-results-indep/x1): every neighbour picks its chains for its own load, same load as
# cell 0, loads up to 150 Mbit/s; QoS from studies.final (paired with 64 chains seed by seed, 20 seeds at 80-150)
FINAL = "--final" in sys.argv
SFX = "_final" if FINAL else "_peak" if PEAK else ""
if FINAL:
    LOADS, MAX_MBPS = [1, 5] + list(range(10, 151, 10)), 150
IND = paths.RAW / "bs-results-indep" / "x1"
STEPS = 24 * 60 // STEP_MIN


def run_name(load, a, r):
    """The grid run if it exists (48 and 24 chains, other loads), else the main campaign (64/32/16 at 1, 40 and peak)."""
    if FINAL:
        return IND / (f"night_a{a}_r{r}" if load == 1 else f"day{load}_a{a}_r{r}")
    if load == 100 and PEAK:
        grid, main = GRID / f"peak100_a{a}_r{r}", c.RAW / f"peak100_a{a}_r{r}"
    else:
        grid = GRID / (f"night_a{a}_r{r}" if load == 1 else f"day{load}_a{a}_r{r}")
        main = c.RAW / f"{'night' if load == 1 else 'day'}_a{a}_r{r}"
    return grid if grid.with_name(grid.name + "_flows.csv").exists() else main


def curves():
    """Mean power (Piovesan W and 3GPP Category 1, relative) and QoS per load and chains."""
    from studies.threegpp import slot_power
    rows, users = [], []
    for load in LOADS:
        for a in CHAINS:
            for r in range(1, (20 if FINAL else c.SEEDS) + 1):
                o = run_name(load, a, r)
                if not o.with_name(o.name + "_flows.csv").exists():
                    continue
                m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
                late = 0
                if o.with_name(o.name + "_segments.csv").exists():
                    s = pd.read_csv(f"{o}_segments.csv")
                    s = s[s.sent == s.pkts]
                    late = int(((s.rx < c.MIN_RX * s.pkts) | (s.last_rx_s - s.start_s > c.SEGMENT_S)).sum())
                rows.append(dict(load=load, chains=a, seed=r, loss=100 * m["loss"], late=late,
                                 piovesan=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W,
                                 piovesan_on=float(pw.piovesan(m["prb_load"], a)) * c.W,
                                 tgpp=slot_power(o, a, True, 1)[0].mean(), tgpp_on=slot_power(o, a, False, 1)[0].mean()))
                f = pd.read_csv(f"{o}_flows.csv")
                users.append(f[f.kind == "burst"].assign(load=load, chains=a, seed=r))
    d, u = pd.DataFrame(rows), pd.concat(users)
    u["over"] = u.delay_p95_s * 1e3 > c.LIMIT_MS
    q = d.groupby(["load", "chains"]).agg(piovesan=("piovesan", "mean"), tgpp=("tgpp", "mean"),
                                          piovesan_on=("piovesan_on", "mean"), tgpp_on=("tgpp_on", "mean"), loss=("loss", "mean"),
                                          late=("late", "sum"), seeds=("seed", "size"))
    q["over_pct"] = 100 * u.groupby(["load", "chains"]).over.mean()
    ref = q.xs(64, level="chains")
    q["extra_pct"] = q.over_pct - ref.over_pct.reindex(q.index, level="load").to_numpy()
    q["extra_late"] = q.late - ref.late.reindex(q.index, level="load").to_numpy()
    q["ok"] = (q.extra_pct <= 100 * c.MAX_EXTRA_USERS) & (q.extra_late <= 0) & (q.loss < 100 * c.MAX_LOSS)
    if FINAL:   # paired criterion of studies.final (24 and 16 chains have 10 seeds, 64 has 20 at 80-150)
        f = pd.read_csv(paths.RESULTS / "final.csv").query("factor == 'x1'").set_index(["load", "chains"])
        q["ok"], q["extra_pct"] = f.ok.reindex(q.index), f.extra_pct.reindex(q.index)
    return q


def capacity(q):
    """Highest load each number of chains sustains with acceptable QoS (all lower grid loads acceptable too)."""
    cap = {}
    for a in CHAINS:
        ok = q.xs(a, level="chains").ok.reindex(LOADS, fill_value=False)   # a load never simulated is not acceptable
        good = [l for l in LOADS if ok.loc[:l].all()]
        cap[a] = max(good) if good else 0
    return cap


def base_profile():
    """Mean load of each 5-minute step [Mbit/s]: the levels, with linear one-hour ramps between them."""
    t = (np.arange(STEPS) + .5) * STEP_MIN / 60
    flat = np.select([(t >= h0) & (t < h1) for h0, h1, _ in LEVELS], [m for _, _, m in LEVELS])
    w = round(RAMP_H * 60 / STEP_MIN)
    padded = np.concatenate([flat[-w:], flat, flat[:w]])            # the day wraps around midnight
    return np.convolve(padded, np.ones(w) / w, mode="same")[w:-w]


def days(rng, n):
    """n days of 5-minute loads: base profile times an AR(1) log-normal fluctuation."""
    base = base_profile()
    e = rng.normal(0, NOISE_SIGMA, (n, STEPS))
    x = np.zeros((n, STEPS))
    x[:, 0] = e[:, 0]
    for k in range(1, STEPS):
        x[:, k] = NOISE_RHO * x[:, k - 1] + np.sqrt(1 - NOISE_RHO**2) * e[:, k]
    return np.clip(base * np.exp(x - NOISE_SIGMA**2 / 2), 0, MAX_MBPS)


def interp(q, col, load, chains):
    """Power at any load, linear between grid loads."""
    y = q.xs(chains, level="chains")[col].reindex(LOADS).to_numpy()
    return np.interp(load, LOADS, y)


def choose(load, cap, margin=0.0):
    """Fewest chains whose acceptable load covers load * (1 + margin)."""
    need = load * (1 + margin)
    out = np.full(load.shape, 64)
    for a in sorted(CHAINS, reverse=True):          # 64, 48, 32, 24, 16: keep the smallest that fits
        out = np.where(need <= cap[a], a, out)
    return out


def evaluate(load, chains, q, cap, symbol=True):
    """Energy per day (Piovesan kWh, 3GPP relative units x h), QoS violations (% of time) and switches per day."""
    h = STEP_MIN / 60
    sfx = "" if symbol else "_on"
    piov = sum(np.where(chains == a, interp(q, "piovesan" + sfx, load, a), 0) for a in CHAINS)
    tg = sum(np.where(chains == a, interp(q, "tgpp" + sfx, load, a), 0) for a in CHAINS)
    bad = np.zeros(load.shape, bool)
    for a in CHAINS:
        bad |= (chains == a) & (load > cap[a])
    full = load > cap[64]          # not even 64 chains give acceptable QoS: the cell is saturated, not the policy's fault
    return dict(kwh=(piov * h).sum(1) / 1e3, tgpp=(tg * h).sum(1), viol=100 * (bad & ~full).mean(1),
                saturated=100 * full.mean(1), switches=(np.diff(chains, axis=1) != 0).sum(1))


def policies(load, cap):
    """Chains per 5-minute step for every policy: dict name -> (interval, margin, chains)."""
    out = {"64 chains + symbol": (None, None, np.full(load.shape, 64)), "oracle": (STEP_MIN, 0, choose(load, cap))}
    for iv in INTERVALS_MIN:
        k = iv // STEP_MIN
        n = load.shape[1] // k
        measured = load[:, :n * k].reshape(load.shape[0], n, k).mean(2)
        # the first interval of the day uses the last one of the same day (the day wraps around midnight)
        prev = np.roll(measured, 1, axis=1)
        for m in MARGINS:
            out[f"reactive {iv} min, margin {m:.0%}"] = (iv, m, np.repeat(choose(prev, cap, m), k, axis=1))
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_rows", 100)
    q = curves()
    cap = capacity(q)
    q.to_csv(paths.RESULTS / f"policy_curves{SFX}.csv")
    print(q.round(2).to_string())
    print("acceptable load per chains [Mbit/s]:", cap)

    load = days(np.random.default_rng(1), DAYS)
    pol = policies(load, cap)
    res = {"always on": (None, None, evaluate(load, np.full(load.shape, 64), q, cap, symbol=False))}
    res |= {n: (iv, m, evaluate(load, ch, q, cap)) for n, (iv, m, ch) in pol.items()}
    ref, ref3 = res["always on"][2]["kwh"], res["always on"][2]["tgpp"]
    rows = []
    for n, (iv, m, e) in res.items():
        s, s3 = 100 * (1 - e["kwh"] / ref), 100 * (1 - e["tgpp"] / ref3)
        rows.append(dict(policy=n, interval_min=iv, margin=m, kwh=e["kwh"].mean(), saving=s.mean(), saving_ci=half_ci(s),
                         saving_3gpp=s3.mean(), violation_pct=e["viol"].mean(), violation_ci=half_ci(e["viol"]),
                         days_with_violation=100 * (e["viol"] > 0).mean(), saturated_pct=e["saturated"].mean(),
                         switches=e["switches"].mean()))
    r = pd.DataFrame(rows)
    r.to_csv(paths.RESULTS / f"policy{SFX}.csv", index=False)
    print(r.round(2).to_string(index=False))
    print(f"mean load {load.mean():.1f} Mbit/s; hours above 80 Mbit/s per day {(load > 80).sum(1).mean() * STEP_MIN / 60:.2f}")

    # Figure 1: one example day
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.4), sharex=True, gridspec_kw=dict(height_ratios=(2, 1)))
    t = np.arange(STEPS) * STEP_MIN / 60
    a1.plot(t, base_profile(), color=MUTED, lw=1.5, ls="--", label="mean profile (8/12/4 h)")
    a1.plot(t, load[0], color=BLUE, lw=1.5, label="one simulated day")
    for v in sorted({cap[a] for a in CHAINS if a != 64 or FINAL}):   # final: 64 chains saturate above their limit
        names = ", ".join(str(a) for a in CHAINS[::-1] if (a != 64 or FINAL) and cap[a] == v)
        a1.axhline(v, color=ORANGE, lw=1, ls=":")
        a1.text(0.2, v + 1.5, f"{names} chains: QoS acceptable up to {v} Mbit/s", fontsize=8, color=INK)
    a1.set(ylabel="offered load [Mbit/s]", ylim=(0, MAX_MBPS + 5), title="A day and the chains a reactive policy picks")
    a1.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 0.05), fontsize=8)
    name = "reactive 15 min, margin 25%"
    a2.step(t, pol[name][2][0], where="post", color=ORANGE, lw=1.5, label=name)
    a2.step(t, choose(load[0], cap), where="post", color=MUTED, lw=1, ls="--", label="oracle")
    a2.set(xlabel="hour of the day", ylabel="active chains", yticks=CHAINS, xlim=(0, 24), xticks=range(0, 25, 3))
    a2.legend(frameon=False, loc="upper left", fontsize=8)
    save(fig, f"policy_day{SFX}.png", "Load: our 8/12/4 h levels, one-hour ramps, log-normal fluctuation every 5 min (assumed)")

    # Figure 2: saving against QoS violations, per decision interval and margin
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for iv, color, mk in zip(INTERVALS_MIN, (BLUE, ORANGE, AQUA), ("o", "s", "^")):
        x = r[r.interval_min == iv].sort_values("margin")
        x = x[x.policy.str.startswith("reactive")]
        ax.plot(x.violation_pct, x.saving, color=color, marker=mk, ms=7, lw=2, label=f"reactive, every {iv} min")
        for _, z in x.iterrows() if iv == 15 else ():
            ax.annotate(f"margin +{z.margin:.0%}", (z.violation_pct, z.saving), xytext=(8, -11), textcoords="offset points",
                        fontsize=7, color=INK)
    s64 = r[r.policy == "64 chains + symbol"].saving.iloc[0]
    ax.axhline(s64, color=MUTED, lw=1, ls="--")
    ax.text(2, s64 + .1, "64 chains + symbol, no decision", fontsize=8, color=INK)
    o = r[r.policy == "oracle"].iloc[0]
    ax.plot(o.violation_pct, o.saving, marker="*", ms=14, color=INK, ls="none", label="oracle (knows the load)")
    ax.set(xlabel="time with QoS not acceptable [%]", ylabel="saving against always on [%] (Piovesan)",
           title="What a policy that decides by itself keeps")
    ax.legend(frameon=False, loc="center right", fontsize=8)
    sat = f"\nNot counted: {r.saturated_pct.iloc[0]:.1f}% of the time the load is above what even 64 chains carry " \
          f"({cap[64]} Mbit/s)" if FINAL else ""
    save(fig, f"policy_tradeoff{SFX}.png", f"{DAYS} simulated days. Margin on the measured load: 0, 25, 50, 100% from right to "
                                     "left on every line (labelled on the 15 min one)" + sat)
