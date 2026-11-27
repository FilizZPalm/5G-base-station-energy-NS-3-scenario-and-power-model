"""Final study: every cell picks its own chains (step 13 of docs/STEPS.md; campaign bs-results-indep).

Cell 0 runs every chain count at every load. Each neighbour carries 0.5, 1 or 2 times the burst load of cell 0 (at
most 150 Mbit/s) and picks its chains with the rule of run_campaign.sh (RULE) for its own load. Day profile (10 burst
users per site) from 5 to 150 Mbit/s, night at 1 Mbit/s. At 1x and 80-150 Mbit/s, 64/48/32 chains have 20 seeds,
the others 10. Folders: bs-results-indep/x0.5, x1, x2.

Outputs:
  - per neighbour load, load and chains: power, saving, SINR, errors and QoS relative to 64 chains on the same seeds
    (results/final.csv, final_runs.csv);
  - the highest load each number of chains carries with acceptable QoS, with every lower load acceptable too
    (final_capacity.csv), compared with the rule the neighbours used (the rule should describe the cell that applies it);
  - one day (8/12/4 h) on this configuration, Piovesan and 3GPP Category 1 (final_daily.csv);
  - figures final_curves.png and final_capacity.png.

Run from analysis/:  ../.venv/bin/python -m studies.final
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save
from studies.daily import half_ci
from studies.threegpp import ns3_sleeps, slot_power, symbol_table

RAW = paths.RAW / "bs-results-indep"
FACTORS = {"x0.5": 0.5, "x1": 1, "x2": 2}          # folder -> neighbour load / load of cell 0
LOADS = [1, 5] + list(range(10, 151, 10))           # Mbit/s (1 = night)
CHAINS = (64, 48, 32, 24, 16)
MAX_SEEDS = 20
RULE = {40: 16, 50: 24, 100: 48, 1000: 64}          # run_campaign.sh: up to this load [Mbit/s] -> chains

# One day on the final configuration (step 3 again). Night and day from this campaign (neighbours at 1x, chains by the
# rule); peak from the peak profile with video (bs-results-main and -grid, neighbours at 64 chains): the final campaign
# has no video. With neighbours picking their own chains the peak interference can only be lower: conservative.
HOURS = {"night": 8, "day": 12, "peak": 4}
DAY_POLICIES = {"always on": {"night": (64, 0), "day": (64, 0), "peak": (64, 0)},     # level -> (chains, symbol 0/1)
                "symbol": {"night": (64, 1), "day": (64, 1), "peak": (64, 1)},
                "symbol + channel, earlier (64 at peak)": {"night": (16, 1), "day": (16, 1), "peak": (64, 1)},
                "symbol + channel, final (48 at peak)": {"night": (16, 1), "day": (16, 1), "peak": (48, 1)}}


def rule(load):
    """Chains a neighbour picks for its own load."""
    return next(chains for top, chains in sorted(RULE.items()) if load <= top)


def name(load, chains, seed):
    return f"night_a{chains}_r{seed}" if load == 1 else f"day{load}_a{chains}_r{seed}"


# --- Loads and chains ---------------------------------------------------------------------------------------------
def runs():
    """One row per neighbour load, load, chains and seed: power (Piovesan W, 3GPP relative), QoS, SINR, errors, and
    the same seed with 64 chains (ref_*) for the paired comparison."""
    rows, users = [], []
    for folder, factor in FACTORS.items():
        for load in LOADS:
            for chains in CHAINS:
                for seed in range(1, MAX_SEEDS + 1):
                    prefix = RAW / folder / name(load, chains, seed)
                    if not prefix.with_name(prefix.name + "_flows.csv").exists():
                        continue
                    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
                    rx = pd.read_csv(f"{prefix}_rx.csv")
                    neighbour_load = min(150, load * factor)
                    rows.append(dict(factor=folder, load=load, chains=chains, seed=seed, nb_load=neighbour_load,
                                     nb_chains=rule(neighbour_load),
                                     piovesan=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W,
                                     piovesan_on=float(power.piovesan(metrics["prb_load"], chains)) * campaign.W,
                                     tgpp=slot_power(prefix, chains, True, 1)[0].mean(),
                                     tgpp_on=slot_power(prefix, chains, False, 1)[0].mean(),
                                     prb=100 * metrics["prb_load"], loss=100 * metrics["loss"], thr=metrics["thr"],
                                     sinr=rx.sinr_db_w.sum() / rx.res.sum(),               # weighted by resources [dB]
                                     bler=100 * rx.corrupt.sum() / rx.tbs.sum()))          # blocks in error [%]
                    flows = pd.read_csv(f"{prefix}_flows.csv")
                    users.append(flows[flows.kind == "burst"].assign(factor=folder, load=load, chains=chains, seed=seed))
    table, users = pd.DataFrame(rows), pd.concat(users)
    users["over"] = users.delay_p95_s * 1e3 > campaign.LIMIT_MS
    per_run = users.groupby(["factor", "load", "chains", "seed"]).agg(over=("over", "sum"), users=("over", "size"))
    table = table.merge(per_run.reset_index())
    with_64 = table[table.chains == 64].set_index(["factor", "load", "seed"])
    key = list(zip(table.factor, table.load, table.seed))
    table["saving"] = 100 * (1 - table.piovesan / with_64.piovesan_on.reindex(key).to_numpy())
    table["saving_3gpp"] = 100 * (1 - table.tgpp / with_64.tgpp_on.reindex(key).to_numpy())
    table["ref_over"], table["ref_users"] = with_64.over.reindex(key).to_numpy(), with_64.users.reindex(key).to_numpy()
    return table


def table(runs):
    """Per neighbour load, load and chains: means, and the QoS relative to 64 chains on the same seeds (ok)."""
    grouped = runs.groupby(["factor", "load", "chains"])
    out = grouped.agg(seeds=("seed", "size"), nb_load=("nb_load", "first"), nb_chains=("nb_chains", "first"),
                      piovesan=("piovesan", "mean"), saving=("saving", "mean"), saving_3gpp=("saving_3gpp", "mean"),
                      prb=("prb", "mean"), loss=("loss", "mean"), sinr=("sinr", "mean"), bler=("bler", "mean"),
                      over=("over", "sum"), users=("users", "sum"), ref_over=("ref_over", "sum"), ref_users=("ref_users", "sum"))
    out["saving_ci"] = grouped.saving.apply(half_ci)
    out["over_pct"] = 100 * out.over / out.users
    out["extra_pct"] = out.over_pct - 100 * out.ref_over / out.ref_users
    # paired per seed: confidence interval of the extra share of users over the limit
    extra_per_seed = runs.assign(x=100 * (runs.over / runs.users - runs.ref_over / runs.ref_users))
    out["extra_ci"] = extra_per_seed.groupby(["factor", "load", "chains"]).x.apply(half_ci)
    out["ok"] = (out.extra_pct <= 100 * campaign.MAX_EXTRA_USERS) & (out.loss < 100 * campaign.MAX_LOSS)
    return out


def capacity(result):
    """Highest load each number of chains carries with acceptable QoS, every lower simulated load acceptable too.
    Rows: chains; columns: neighbour load."""
    out = {}
    for folder in FACTORS:
        this = result.xs(folder, level="factor")
        loads = sorted(this.index.get_level_values("load").unique())
        for chains in CHAINS:
            ok = this.xs(chains, level="chains").ok.reindex(loads, fill_value=False)
            good = [load for load in loads if ok.loc[:load].all()]
            out[(folder, chains)] = max(good) if good else 0
    return pd.Series(out).unstack(0)[list(FACTORS)]


# --- One day ------------------------------------------------------------------------------------------------------
def level_run(level, chains, seed):
    """Run used for a level of the day: peak from the grid or main campaign (with video), night and day from x1."""
    if level == "peak":
        grid = paths.RAW / "bs-results-grid" / f"peak100_a{chains}_r{seed}"
        return grid if grid.with_name(grid.name + "_flows.csv").exists() else campaign.RAW / f"peak100_a{chains}_r{seed}"
    return RAW / "x1" / name(1 if level == "night" else 40, chains, seed)


def day_energy():
    """Per policy: energy of one day (Piovesan kWh), saving against always on (Piovesan and 3GPP Category 1) with 95%
    CI, and the mean power of each level."""
    level_power, rows = {}, []        # (level, chains, symbol, seed) -> (Piovesan W, 3GPP relative), computed once
    for policy, levels in DAY_POLICIES.items():
        for seed in range(1, campaign.SEEDS + 1):
            kwh = tgpp = 0
            for level, (chains, symbol) in levels.items():
                if (level, chains, symbol, seed) not in level_power:
                    prefix = level_run(level, chains, seed)
                    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
                    level_power[(level, chains, symbol, seed)] = (
                        float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"] if symbol else 0)) * campaign.W,
                        slot_power(prefix, chains, bool(symbol), 1)[0].mean())
                watt, rel = level_power[(level, chains, symbol, seed)]
                kwh, tgpp = kwh + HOURS[level] * watt / 1e3, tgpp + HOURS[level] * rel
                rows.append(dict(policy=policy, seed=seed, level=level, chains=chains, symbol=symbol, watt=watt, tgpp=rel))
            rows.append(dict(policy=policy, seed=seed, level="day total", kwh=kwh, tgpp=tgpp))
    rows = pd.DataFrame(rows)
    totals = rows[rows.level == "day total"].set_index(["policy", "seed"])
    always_on = totals.xs("always on", level="policy")
    totals["saving"] = 100 * (1 - totals.kwh / always_on.kwh.reindex(totals.index, level="seed").to_numpy())
    totals["saving_3gpp"] = 100 * (1 - totals.tgpp / always_on.tgpp.reindex(totals.index, level="seed").to_numpy())
    grouped = totals.groupby("policy", sort=False)
    out = grouped[["kwh", "saving", "saving_3gpp"]].mean().join(grouped.kwh.apply(half_ci).rename("kwh_ci")) \
        .join(grouped.saving.apply(half_ci).rename("saving_ci")) \
        .join(grouped.saving_3gpp.apply(half_ci).rename("saving_3gpp_ci"))
    watts = rows[rows.level != "day total"].groupby(["policy", "level"], sort=False).watt.mean().unstack()
    return out.join(watts.add_prefix("W_"))


def day_light_sleep():
    """3GPP Category 1: final policy with light sleep at night (SSB every 160 ms), simulated in NS-3 (studies.threegpp).
    Those night runs have neighbours at 64 chains; at 1 Mbit/s the neighbours make no difference, which the last value
    checks (largest difference between the earlier and the final night with 16 chains)."""
    simulated, earlier = ns3_sleeps(), symbol_table()
    night_sleep = simulated[(simulated.profile == "night") & (simulated.state == "light")
                            & (simulated.ssb == "SSB 160 ms")].sort_values("seed").rel.to_numpy()
    night_earlier = earlier[(earlier.cat == 1) & (earlier.profile == "night") & (earlier.chains == 16)
                            & earlier.symbol].sort_values("seed").rel.to_numpy()

    def level(level_name, chains, symbol):
        return np.array([slot_power(level_run(level_name, chains, seed), chains, symbol, 1)[0].mean()
                         for seed in range(1, campaign.SEEDS + 1)])

    night_final = level("night", 16, True)
    always_on = sum(h * level(level_name, 64, False) for level_name, h in HOURS.items())
    e = HOURS["night"] * night_sleep + HOURS["day"] * level("day", 16, True) + HOURS["peak"] * level("peak", 48, True)
    saving = 100 * (1 - e / always_on)
    return dict(saving_3gpp=saving.mean(), ci=half_ci(saving), night_16_old_vs_final=np.abs(night_earlier - night_final).max())


# --- Figures ------------------------------------------------------------------------------------------------------
def plot_curves(result):
    """Neighbours at 1x: saving against load per chains (hollow = QoS not acceptable), and the QoS cost with its CI."""
    same_load = result.xs("x1", level="factor")
    fig, (ax_saving, ax_qos) = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {64: INK, 48: AQUA, 32: BLUE, 24: MUTED, 16: ORANGE}
    for chains in CHAINS:
        line = same_load.xs(chains, level="chains")
        ax_saving.plot(line.index, line.saving, color=colors[chains], lw=1.6, label=f"{chains} chains")
        ax_saving.scatter(line.index[~line.ok], line.saving[~line.ok], s=40, facecolor="white", edgecolor=colors[chains],
                          lw=1.4, zorder=3)
        ax_saving.scatter(line.index[line.ok], line.saving[line.ok], s=16, color=colors[chains], zorder=3)
        if chains != 64:
            ax_qos.errorbar(line.index, line.extra_pct, yerr=line.extra_ci, color=colors[chains], lw=1.4, capsize=2,
                            label=f"{chains} chains")
    ax_saving.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="saving against 64 chains always on [%]",
                  title="Power: symbol shutdown + fewer chains")
    ax_saving.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0.12, 0.08))
    ax_saving.text(.02, .03, "hollow: QoS not acceptable", transform=ax_saving.transAxes, fontsize=8, color=INK)
    ax_qos.axhline(100 * campaign.MAX_EXTRA_USERS, color=ORANGE, lw=1, ls="--")
    ax_qos.text(2, 100 * campaign.MAX_EXTRA_USERS + .8, "limit: +5 users in 100", fontsize=8, color=INK)
    ax_qos.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="extra burst users over 20 ms vs 64 chains [points]",
               title="QoS cost (95% CI over seeds)")
    ax_qos.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_curves.png", "Every cell picks its chains for its own load; neighbours at the same load as cell 0. "
                                  "10 seeds, 20 for 64/48/32 chains at 80-150 Mbit/s")


def plot_capacity(limits):
    """Acceptable load per chains, one bar per neighbour load."""
    fig, ax = plt.subplots(figsize=(9, 3.8))
    width, shown = .26, (16, 24, 32, 48, 64)
    for k, (folder, color) in enumerate(zip(FACTORS, (AQUA, BLUE, ORANGE))):
        values = limits[folder].reindex(shown)
        ax.bar(np.arange(len(shown)) + (k - 1) * width, values, width * .92, color=color,
               label=f"neighbours at {FACTORS[folder]:g}x the load")
        for i, y in enumerate(values):   # 150 is the highest simulated load: the real limit may be higher
            ax.text(i + (k - 1) * width, y + 2, f"{y:g}+" if y == max(LOADS) else f"{y:g}", ha="center", fontsize=7.5, color=INK)
    ax.set(xticks=range(len(shown)), xticklabels=[f"{a} chains" + (" + symbol" if a == 64 else "") for a in shown],
           ylim=(0, 170), ylabel="highest load with acceptable QoS [Mbit/s]", title="How much load fewer chains can carry")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_capacity.png", "64 chains: losses under 1% (it is the QoS reference). 150+: highest load simulated. "
                                    "0.5x and 2x at 10-20-40-60-80-100-120-150 Mbit/s, 1x every 10")


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_rows", 300, "display.max_columns", 30)
    all_runs = runs()
    all_runs.to_csv(paths.RESULTS / "final_runs.csv", index=False)
    result = table(all_runs)
    result.to_csv(paths.RESULTS / "final.csv")
    columns = ["seeds", "nb_load", "nb_chains", "piovesan", "saving", "saving_ci", "saving_3gpp", "prb", "sinr", "bler",
               "over_pct", "extra_pct", "extra_ci", "loss", "ok"]
    print(result[columns].round(2).to_string())

    limits = capacity(result)
    limits.to_csv(paths.RESULTS / "final_capacity.csv")
    print("\nacceptable load per chains [Mbit/s] (0.5x and 2x on 10-150 only):\n", limits)
    neighbours_64 = pd.read_csv(paths.RESULTS / "policy_curves.csv")     # neighbours at 64 chains, 1-100 Mbit/s
    print("neighbours at 64 (policy study):", neighbours_64.groupby("chains").apply(
        lambda z: max([l for l in sorted(z.load) if z[z.load <= l].ok.all()] or [0]), include_groups=False).to_dict())
    print("RULE used by the neighbours:", RULE)

    day = day_energy()
    day.to_csv(paths.RESULTS / "final_daily.csv")
    print("\none day, 8/12/4 h, saving against 64 chains always on:\n", day.round(2).to_string())
    print("3GPP Cat. 1, final + light sleep at night (SSB 160 ms):", day_light_sleep())

    plot_curves(result)
    plot_capacity(limits)
