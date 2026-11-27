"""A policy that picks the chains by itself (step 11 of docs/STEPS.md; step 13 with --final).

Every decision interval the policy looks at the load just measured, adds a safety margin and keeps the fewest chains
that carry that load with acceptable QoS for the next interval. It is compared with 64 chains always on and with an
oracle that knows the load of every step in advance (as in studies.daily).

Ingredients, all with symbol shutdown:
  1. power and QoS against load and chains (64, 48, 32, 24, 16), from NS-3 (curves):
       default   night (1 Mbit/s, 2 users) and the day profile at 5-100 Mbit/s (bs-results-grid; the main campaign at
                 40 Mbit/s for 64/32/16 chains), neighbours at 64 chains;
       --peak    the same, but 100 Mbit/s from the peak profile with video (53 Mbit/s of video + bursts);
       --final   the final campaign (bs-results-indep/x1): every neighbour picks its chains for its own load, same load
                 as cell 0, up to 150 Mbit/s; QoS from studies.final (paired seed by seed, 20 seeds at 80-150);
  2. the acceptable load of each number of chains (capacity): the highest simulated load whose QoS passes the
     criterion of lib.campaign, with every lower load passing too;
  3. many days of 5-minute loads: our 8/12/4 h levels with one-hour ramps, times a random fluctuation (ASSUMPTIONS).
Each 5-minute step uses the 10 s runs of its load (the load is taken as constant within a step). A step is a QoS
violation when its load is above the acceptable load of the chains in use. Switching chains is instantaneous and free.

Run from analysis/:  ../.venv/bin/python -m studies.policy [--peak | --final]   (--final needs studies.final first)
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save
from studies.daily import half_ci

GRID = paths.RAW / "bs-results-grid"
FINAL_RAW = paths.RAW / "bs-results-indep" / "x1"

# ASSUMPTIONS ------------------------------------------------------------------------------------------------------
STEP_MIN = 5                                   # length of a step of the simulated days [min]
LEVELS = [(0, 7, 1), (7, 17, 40), (17, 21, 100), (21, 23, 40), (23, 24, 1)]   # hour from, hour to, Mbit/s: 8/12/4 h
RAMP_H = 1                                     # each change of level takes one hour (centred on the boundary)
NOISE_SIGMA, NOISE_RHO = 0.25, 0.8             # log-normal fluctuation per step, AR(1) correlation between steps
MAX_MBPS = 100                                 # loads are clipped to the highest simulated level
DAYS = 300                                     # simulated days
INTERVALS_MIN = (5, 15, 60)                    # decision intervals
MARGINS = (0, 0.25, 0.5, 1.0)                  # safety margin on the measured load
# ------------------------------------------------------------------------------------------------------------------

LOADS = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]     # simulated loads [Mbit/s]
CHAINS = (64, 48, 32, 24, 16)
PEAK = "--peak" in sys.argv
FINAL = "--final" in sys.argv
SUFFIX = "_final" if FINAL else "_peak" if PEAK else ""    # added to the names of the output files
if FINAL:
    LOADS, MAX_MBPS = [1, 5] + list(range(10, 151, 10)), 150
STEPS = 24 * 60 // STEP_MIN                    # steps per day


# --- 1. Power and QoS against load (from NS-3) --------------------------------------------------------------------
def run_prefix(load, chains, seed):
    """Where the run of this load, chains and seed is: the final campaign with --final; otherwise the grid run if it
    exists (48 and 24 chains, other loads), else the main campaign (64/32/16 chains at 1, 40 and peak)."""
    if FINAL:
        return FINAL_RAW / (f"night_a{chains}_r{seed}" if load == 1 else f"day{load}_a{chains}_r{seed}")
    if load == 100 and PEAK:
        grid, main = GRID / f"peak100_a{chains}_r{seed}", campaign.RAW / f"peak100_a{chains}_r{seed}"
    else:
        grid = GRID / (f"night_a{chains}_r{seed}" if load == 1 else f"day{load}_a{chains}_r{seed}")
        main = campaign.RAW / f"{'night' if load == 1 else 'day'}_a{chains}_r{seed}"
    return grid if grid.with_name(grid.name + "_flows.csv").exists() else main


def late_segments(prefix):
    """Late video segments of a run (0 if it has no video)."""
    if not prefix.with_name(prefix.name + "_segments.csv").exists():
        return 0
    segments = pd.read_csv(f"{prefix}_segments.csv")
    whole = segments[segments.sent == segments.pkts]
    return int(((whole.rx < campaign.MIN_RX * whole.pkts) | (whole.last_rx_s - whole.start_s > campaign.SEGMENT_S)).sum())


def curves():
    """Per load and chains: mean power (Piovesan W and 3GPP Category 1 relative, with and without symbol shutdown),
    QoS and whether it is acceptable (ok)."""
    from studies.threegpp import slot_power
    rows, users = [], []
    for load in LOADS:
        for chains in CHAINS:
            for seed in range(1, (20 if FINAL else campaign.SEEDS) + 1):
                prefix = run_prefix(load, chains, seed)
                if not prefix.with_name(prefix.name + "_flows.csv").exists():
                    continue
                metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
                rows.append(dict(load=load, chains=chains, seed=seed, loss=100 * metrics["loss"], late=late_segments(prefix),
                                 piovesan=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W,
                                 piovesan_on=float(power.piovesan(metrics["prb_load"], chains)) * campaign.W,
                                 tgpp=slot_power(prefix, chains, True, 1)[0].mean(),
                                 tgpp_on=slot_power(prefix, chains, False, 1)[0].mean()))
                flows = pd.read_csv(f"{prefix}_flows.csv")
                users.append(flows[flows.kind == "burst"].assign(load=load, chains=chains, seed=seed))
    runs, users = pd.DataFrame(rows), pd.concat(users)
    users["over"] = users.delay_p95_s * 1e3 > campaign.LIMIT_MS
    table = runs.groupby(["load", "chains"]).agg(piovesan=("piovesan", "mean"), tgpp=("tgpp", "mean"),
                                                 piovesan_on=("piovesan_on", "mean"), tgpp_on=("tgpp_on", "mean"),
                                                 loss=("loss", "mean"), late=("late", "sum"), seeds=("seed", "size"))
    table["over_pct"] = 100 * users.groupby(["load", "chains"]).over.mean()
    with_64 = table.xs(64, level="chains")
    table["extra_pct"] = table.over_pct - with_64.over_pct.reindex(table.index, level="load").to_numpy()
    table["extra_late"] = table.late - with_64.late.reindex(table.index, level="load").to_numpy()
    table["ok"] = ((table.extra_pct <= 100 * campaign.MAX_EXTRA_USERS) & (table.extra_late <= 0)
                   & (table.loss < 100 * campaign.MAX_LOSS))
    if FINAL:   # the paired criterion of studies.final (24 and 16 chains have 10 seeds, 64 has 20 at 80-150)
        final = pd.read_csv(paths.RESULTS / "final.csv").query("factor == 'x1'").set_index(["load", "chains"])
        table["ok"], table["extra_pct"] = final.ok.reindex(table.index), final.extra_pct.reindex(table.index)
    return table


def capacity(table):
    """Highest load each number of chains carries with acceptable QoS (all lower simulated loads acceptable too)."""
    limits = {}
    for chains in CHAINS:
        ok = table.xs(chains, level="chains").ok.reindex(LOADS, fill_value=False)   # a load never simulated is not ok
        good = [load for load in LOADS if ok.loc[:load].all()]
        limits[chains] = max(good) if good else 0
    return limits


def interp(table, column, load, chains):
    """Power at any load, linear between the simulated loads."""
    y = table.xs(chains, level="chains")[column].reindex(LOADS).to_numpy()
    return np.interp(load, LOADS, y)


# --- 2. Simulated days --------------------------------------------------------------------------------------------
def base_profile():
    """Mean load of each step of the day [Mbit/s]: the levels, with linear one-hour ramps between them."""
    hour = (np.arange(STEPS) + .5) * STEP_MIN / 60
    flat = np.select([(hour >= h0) & (hour < h1) for h0, h1, _ in LEVELS], [mbps for _, _, mbps in LEVELS])
    ramp = round(RAMP_H * 60 / STEP_MIN)
    padded = np.concatenate([flat[-ramp:], flat, flat[:ramp]])      # the day wraps around midnight
    return np.convolve(padded, np.ones(ramp) / ramp, mode="same")[ramp:-ramp]


def days(rng, n):
    """n days of step loads: base profile times a log-normal fluctuation correlated between steps (AR(1))."""
    base = base_profile()
    noise = rng.normal(0, NOISE_SIGMA, (n, STEPS))
    x = np.zeros((n, STEPS))
    x[:, 0] = noise[:, 0]
    for k in range(1, STEPS):
        x[:, k] = NOISE_RHO * x[:, k - 1] + np.sqrt(1 - NOISE_RHO**2) * noise[:, k]
    return np.clip(base * np.exp(x - NOISE_SIGMA**2 / 2), 0, MAX_MBPS)   # - sigma^2/2: keeps the mean equal to base


# --- 3. Policies --------------------------------------------------------------------------------------------------
def choose(load, limits, margin=0.0):
    """Fewest chains whose acceptable load covers load * (1 + margin); 64 if none does."""
    need = load * (1 + margin)
    out = np.full(load.shape, 64)
    for chains in sorted(CHAINS, reverse=True):          # 64, 48, 32, 24, 16: keep the smallest that fits
        out = np.where(need <= limits[chains], chains, out)
    return out


def policies(load, limits):
    """Chains per step for every policy: name -> (decision interval, margin, chains)."""
    out = {"64 chains + symbol": (None, None, np.full(load.shape, 64)), "oracle": (STEP_MIN, 0, choose(load, limits))}
    for interval in INTERVALS_MIN:
        steps_per_interval = interval // STEP_MIN
        n = load.shape[1] // steps_per_interval
        measured = load[:, :n * steps_per_interval].reshape(load.shape[0], n, steps_per_interval).mean(2)
        # each interval uses the load measured in the previous one; the first interval of the day uses the last one
        # of the same day (the day wraps around midnight)
        previous = np.roll(measured, 1, axis=1)
        for margin in MARGINS:
            chains = np.repeat(choose(previous, limits, margin), steps_per_interval, axis=1)
            out[f"reactive {interval} min, margin {margin:.0%}"] = (interval, margin, chains)
    return out


def evaluate(load, chains, table, limits, symbol=True):
    """Per day: energy (Piovesan kWh, 3GPP relative units x h), time with QoS not acceptable because of the policy [%],
    time with the cell saturated [%] and chain switches."""
    hours_per_step = STEP_MIN / 60
    suffix = "" if symbol else "_on"
    piovesan = sum(np.where(chains == a, interp(table, "piovesan" + suffix, load, a), 0) for a in CHAINS)
    tgpp = sum(np.where(chains == a, interp(table, "tgpp" + suffix, load, a), 0) for a in CHAINS)
    too_few = np.zeros(load.shape, bool)
    for a in CHAINS:
        too_few |= (chains == a) & (load > limits[a])
    saturated = load > limits[64]      # not even 64 chains give acceptable QoS: not the policy's fault
    return dict(kwh=(piovesan * hours_per_step).sum(1) / 1e3, tgpp=(tgpp * hours_per_step).sum(1),
                viol=100 * (too_few & ~saturated).mean(1), saturated=100 * saturated.mean(1),
                switches=(np.diff(chains, axis=1) != 0).sum(1))


def results_table(load, chosen, table, limits):
    """One row per policy: saving against always on (Piovesan and 3GPP), violations, saturation and switches."""
    results = {"always on": (None, None, evaluate(load, np.full(load.shape, 64), table, limits, symbol=False))}
    results |= {name: (interval, margin, evaluate(load, chains, table, limits))
                for name, (interval, margin, chains) in chosen.items()}
    always_on = results["always on"][2]
    rows = []
    for name, (interval, margin, e) in results.items():
        saving, saving_3gpp = 100 * (1 - e["kwh"] / always_on["kwh"]), 100 * (1 - e["tgpp"] / always_on["tgpp"])
        rows.append(dict(policy=name, interval_min=interval, margin=margin, kwh=e["kwh"].mean(), saving=saving.mean(),
                         saving_ci=half_ci(saving), saving_3gpp=saving_3gpp.mean(), violation_pct=e["viol"].mean(),
                         violation_ci=half_ci(e["viol"]), days_with_violation=100 * (e["viol"] > 0).mean(),
                         saturated_pct=e["saturated"].mean(), switches=e["switches"].mean()))
    return pd.DataFrame(rows)


# --- Figures ------------------------------------------------------------------------------------------------------
def plot_day(load, chosen, limits):
    """One simulated day: the load with the acceptable load of each number of chains, and the chains picked."""
    fig, (ax_load, ax_chains) = plt.subplots(2, 1, figsize=(9, 5.4), sharex=True, gridspec_kw=dict(height_ratios=(2, 1)))
    hour = np.arange(STEPS) * STEP_MIN / 60
    ax_load.plot(hour, base_profile(), color=MUTED, lw=1.5, ls="--", label="mean profile (8/12/4 h)")
    ax_load.plot(hour, load[0], color=BLUE, lw=1.5, label="one simulated day")
    shown = [a for a in CHAINS if a != 64 or FINAL]     # final: 64 chains saturate above their limit, so show it
    for limit in sorted({limits[a] for a in shown}):
        names = ", ".join(str(a) for a in CHAINS[::-1] if a in shown and limits[a] == limit)
        ax_load.axhline(limit, color=ORANGE, lw=1, ls=":")
        ax_load.text(0.2, limit + 1.5, f"{names} chains: QoS acceptable up to {limit} Mbit/s", fontsize=8, color=INK)
    ax_load.set(ylabel="offered load [Mbit/s]", ylim=(0, MAX_MBPS + 5), title="A day and the chains a reactive policy picks")
    ax_load.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 0.05), fontsize=8)
    name = "reactive 5 min, margin 50%"    # the rule chosen in the README
    ax_chains.step(hour, chosen[name][2][0], where="post", color=ORANGE, lw=1.5, label=name)
    ax_chains.step(hour, choose(load[0], limits), where="post", color=MUTED, lw=1, ls="--", label="oracle")
    ax_chains.set(xlabel="hour of the day", ylabel="active chains", yticks=CHAINS, xlim=(0, 24), xticks=range(0, 25, 3))
    ax_chains.legend(frameon=False, loc="upper left", fontsize=8)
    save(fig, f"policy_day{SUFFIX}.png", "Load: our 8/12/4 h levels, one-hour ramps, log-normal fluctuation every 5 min (assumed)")


def plot_tradeoff(result, limits):
    """Saving against time with QoS not acceptable, one line per decision interval, one point per margin."""
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for interval, color, marker in zip(INTERVALS_MIN, (BLUE, ORANGE, AQUA), ("o", "s", "^")):
        line = result[result.interval_min == interval].sort_values("margin")
        line = line[line.policy.str.startswith("reactive")]
        ax.plot(line.violation_pct, line.saving, color=color, marker=marker, ms=7, lw=2, label=f"reactive, every {interval} min")
        for _, point in line.iterrows() if interval == 15 else ():
            ax.annotate(f"margin +{point.margin:.0%}", (point.violation_pct, point.saving), xytext=(8, -11),
                        textcoords="offset points", fontsize=7, color=INK)
    no_decision = result[result.policy == "64 chains + symbol"].saving.iloc[0]
    ax.axhline(no_decision, color=MUTED, lw=1, ls="--")
    ax.text(2, no_decision + .1, "64 chains + symbol, no decision", fontsize=8, color=INK)
    oracle = result[result.policy == "oracle"].iloc[0]
    ax.plot(oracle.violation_pct, oracle.saving, marker="*", ms=14, color=INK, ls="none", label="oracle (knows the load)")
    ax.set(xlabel="time with QoS not acceptable [%]", ylabel="saving against always on [%] (Piovesan)",
           title="What a policy that decides by itself keeps")
    ax.legend(frameon=False, loc="center right", fontsize=8)
    saturation = (f"\nNot counted: {result.saturated_pct.iloc[0]:.1f}% of the time the load is above what even 64 chains "
                  f"carry ({limits[64]} Mbit/s)") if FINAL else ""
    save(fig, f"policy_tradeoff{SUFFIX}.png", f"{DAYS} simulated days. Margin on the measured load: 0, 25, 50, 100% from "
                                              "right to left on every line (labelled on the 15 min one)" + saturation)


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_rows", 100)
    table = curves()
    limits = capacity(table)
    table.to_csv(paths.RESULTS / f"policy_curves{SUFFIX}.csv")
    print(table.round(2).to_string())
    print("acceptable load per chains [Mbit/s]:", limits)

    load = days(np.random.default_rng(1), DAYS)
    chosen = policies(load, limits)
    result = results_table(load, chosen, table, limits)
    result.to_csv(paths.RESULTS / f"policy{SUFFIX}.csv", index=False)
    print(result.round(2).to_string(index=False))
    print(f"mean load {load.mean():.1f} Mbit/s; hours above 80 Mbit/s per day {(load > 80).sum(1).mean() * STEP_MIN / 60:.2f}")

    plot_day(load, chosen, limits)
    plot_tradeoff(result, limits)
