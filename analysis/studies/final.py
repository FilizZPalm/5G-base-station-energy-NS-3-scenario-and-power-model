"""Final study: every cell picks its own chains (step 13 of docs/STEPS.md; campaign bs-results-indep).

Cell 0 runs every chain count at every load. Each neighbour carries 0.5, 1 or 2 times the burst load of cell 0 (at
most 150 Mbit/s) and picks its chains with the rule of run_campaign.sh (RULE) for its own load. Day profile (10 burst
users per site) from 5 to 150 Mbit/s, night at 1 Mbit/s. At 1x and 80-150 Mbit/s, 64/48/32 chains have 20 seeds,
the others 10. Folders: bs-results-indep/x0.5, x1, x2.

Outputs:
  - per neighbour load, load and chains: power, saving, SINR, errors and QoS relative to 64 chains on the same seeds
    (results/final.csv, final_runs.csv);
  - the highest load each number of chains carries with acceptable QoS, with every lower load acceptable too
    (final_capacity.csv), compared with the rule the neighbours used (which should describe the cell applying it);
  - one day (8/12/4 h) on this configuration, Piovesan and 3GPP (final_daily.csv, final_threegpp.csv), and with three
    power models: Piovesan and 3GPP Category 1 and 2 (final_models.csv);
  - figures final_curves.png, final_capacity.png, final_daily.png and final_models.png.

Run from analysis/:  ../.venv/bin/python -m studies.final
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, save
from studies.daily import half_ci
from studies.threegpp import night_sleep_qos_ok, ns3_sleeps, sleep_level, slot_power, symbol_table, trace_sleeps

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
FINAL_POLICY = "symbol + channel, final (48 at peak)"
NIGHT_SLEEP = "+ sleep at night, Tw 0.5 ms"


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
                                     piovesan=campaign.watt(metrics, chains),
                                     piovesan_on=campaign.watt(metrics, chains, symbol=False),
                                     tgpp=slot_power(prefix, chains, True, 1)[0].mean(),
                                     tgpp_on=slot_power(prefix, chains, False, 1)[0].mean(),
                                     prb=100 * metrics["prb_load"], loss=100 * metrics["loss"], thr=metrics["thr"],
                                     sinr=rx.sinr_db_w.sum() / rx.res.sum(),               # weighted by resources [dB]
                                     bler=100 * rx.corrupt.sum() / rx.tbs.sum()))          # blocks in error [%]
                    flows = pd.read_csv(f"{prefix}_flows.csv")
                    burst = flows[flows.kind == "burst"]
                    users.append(burst.assign(factor=folder, load=load, chains=chains, seed=seed))
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
                      over=("over", "sum"), users=("users", "sum"), ref_over=("ref_over", "sum"),
                      ref_users=("ref_users", "sum"))
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
        main = campaign.RAW / f"peak100_a{chains}_r{seed}"
        return grid if grid.with_name(grid.name + "_flows.csv").exists() else main
    return RAW / "x1" / name(1 if level == "night" else 40, chains, seed)


def piovesan_level(level, chains, symbol):
    """Piovesan power of a level of the day, one value per seed [W]."""
    out = []
    for seed in range(1, campaign.SEEDS + 1):
        prefix = level_run(level, chains, seed)
        metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
        out.append(campaign.watt(metrics, chains, symbol))
    return np.array(out)


def tgpp_level(level, chains, symbol, cat=1):
    """3GPP power of a level of the day, one value per seed [relative units]."""
    return np.array([slot_power(level_run(level, chains, seed), chains, bool(symbol), cat)[0].mean()
                     for seed in range(1, campaign.SEEDS + 1)])


def night_variants():
    """Night power of the variants that go beyond symbol + channel shutdown, one value per seed [W]:
      sleep with a wake-up time of 0.5 ms (SSB every 20 ms), simulated in NS-3 (bs-results-wake, studies.wakeup_ns3);
      all carriers off, or deep dormancy, from the power formula only; the 4G anchor carries the night traffic.
    The sleep runs have neighbours at 64 chains; at 1 Mbit/s the neighbours make no difference (day_3gpp checks it)."""
    from studies import wakeup_ns3
    sleep_runs, _, _ = wakeup_ns3.load(campaign.runs.set_index(["profile", "chains", "seed"]))
    night_sleep = sleep_runs[(sleep_runs.profile == "night") & (sleep_runs.tw == "0.5") & (sleep_runs.ssb == 20)]
    sent = []
    for seed in range(1, campaign.SEEDS + 1):
        prefix = level_run("night", 64, seed)
        sent.append(ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)["sent"])
    anchor = power.ANCHOR_W_PER_MBPS * np.array(sent)
    return {NIGHT_SLEEP: night_sleep.sort_values("seed").watt.to_numpy(),
            "+ night carriers off*": power.CARRIER_OFF * campaign.W + anchor,
            "+ night dormancy*": power.DORMANT * campaign.W + anchor}


def day_energy():
    """Per policy: energy of one day (Piovesan kWh), saving against always on (Piovesan and, where the policy exists
    in the 3GPP model, Category 1) with 95% CI, and the mean power of each level."""
    watts = {name: {level: piovesan_level(level, *setting) for level, setting in levels.items()}
             for name, levels in DAY_POLICIES.items()}
    rels = {name: {level: tgpp_level(level, *setting) for level, setting in levels.items()}
            for name, levels in DAY_POLICIES.items()}
    for name, night in night_variants().items():       # the rest of the day as the final symbol + channel
        watts[name] = dict(watts[FINAL_POLICY], night=night)

    def day_total(levels, scale):
        total = 0
        for level in HOURS:
            total = total + HOURS[level] * levels[level] * scale
        return total

    always_on_kwh = day_total(watts["always on"], 1e-3)
    always_on_rel = day_total(rels["always on"], 1)
    rows = []
    for name, levels in watts.items():
        kwh = day_total(levels, 1e-3)
        saving = 100 * (1 - kwh / always_on_kwh)
        row = dict(policy=name, kwh=kwh.mean(), saving=saving.mean(), saving_3gpp=np.nan, kwh_ci=half_ci(kwh),
                   saving_ci=half_ci(saving), saving_3gpp_ci=np.nan)
        if name in rels:
            saving_3gpp = 100 * (1 - day_total(rels[name], 1) / always_on_rel)
            row |= dict(saving_3gpp=saving_3gpp.mean(), saving_3gpp_ci=half_ci(saving_3gpp))
        rows.append(row | {f"W_{level}": levels[level].mean() for level in HOURS})
    return pd.DataFrame(rows).set_index("policy")


def day_3gpp():
    """3GPP Category 1 and 2, one day on the final configuration: symbol, symbol + channel (48 chains at peak) and
    light or deep sleep at night on top (NS-3 where simulated, else the trace estimate, from studies.threegpp: their
    nights have neighbours at 64 chains, which at 1 Mbit/s makes no difference; the returned check is the largest
    difference between the earlier and the final night with 16 chains). qos_ok: the settings without sleep are those
    with acceptable QoS at every level; a sleep is judged on the night by studies.threegpp.night_sleep_qos_ok."""
    traced, simulated, earlier = trace_sleeps(), ns3_sleeps(), symbol_table()
    rows = []
    for cat in (1, 2):
        always_on = sum(h * tgpp_level(level, 64, False, cat) for level, h in HOURS.items())
        best = {"night": tgpp_level("night", 16, True, cat), "day": tgpp_level("day", 16, True, cat),
                "peak": tgpp_level("peak", 48, True, cat)}
        policies = {"always on": {level: tgpp_level(level, 64, False, cat) for level in HOURS},
                    "symbol": {level: tgpp_level(level, 64, True, cat) for level in HOURS},
                    "channel": {"night": tgpp_level("night", 16, False, cat), "day": tgpp_level("day", 16, False, cat),
                                "peak": tgpp_level("peak", 48, False, cat)},
                    "symbol + channel": best}
        qos_ok = dict.fromkeys(policies, True)
        for name, ssb in (("+ light sleep at night", "SSB 160 ms"), ("+ light sleep at night", "no SSB"),
                          ("+ deep sleep at night", "SSB 160 ms"), ("+ deep sleep at night", "no SSB")):
            state = name.split()[1]                             # "light" or "deep"
            night = sleep_level(cat, "night", state, ssb, traced, simulated)
            if len(night):
                policies[f"{name} ({ssb})"] = dict(best, night=night)
                qos_ok[f"{name} ({ssb})"] = night_sleep_qos_ok(cat, state, ssb, traced, simulated)
        for name, levels in policies.items():
            saving = 100 * (1 - sum(h * levels[level] for level, h in HOURS.items()) / always_on)
            rows.append(dict(cat=cat, policy=name, saving=saving.mean(), ci=half_ci(saving), qos_ok=qos_ok[name]))
    night_earlier = earlier[(earlier.cat == 1) & (earlier.profile == "night") & (earlier.chains == 16)
                            & earlier.symbol].sort_values("seed").rel.to_numpy()
    check = np.abs(night_earlier - tgpp_level("night", 16, True, 1)).max()
    return pd.DataFrame(rows), check


# --- Figures ------------------------------------------------------------------------------------------------------
def plot_curves(result):
    """Neighbours at 1x: saving against load per chains (hollow = QoS not acceptable), and the QoS cost with its CI."""
    same_load = result.xs("x1", level="factor")
    fig, (ax_saving, ax_qos) = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {64: INK, 48: AQUA, 32: BLUE, 24: MUTED, 16: ORANGE}
    for chains in CHAINS:
        line = same_load.xs(chains, level="chains")
        ax_saving.plot(line.index, line.saving, color=colors[chains], lw=1.6, label=f"{chains} chains")
        ax_saving.scatter(line.index[~line.ok], line.saving[~line.ok], s=40, facecolor="white",
                          edgecolor=colors[chains], lw=1.4, zorder=3)
        ax_saving.scatter(line.index[line.ok], line.saving[line.ok], s=16, color=colors[chains], zorder=3)
        if chains != 64:
            ax_qos.errorbar(line.index, line.extra_pct, yerr=line.extra_ci, color=colors[chains], lw=1.4, capsize=2,
                            label=f"{chains} chains")
    ax_saving.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="saving against 64 chains always on [%]",
                  title="Power: symbol shutdown + fewer chains")
    ax_saving.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0.12, 0.08))
    ax_saving.text(.02, .03, "hollow: QoS not acceptable", transform=ax_saving.transAxes, fontsize=8, color=INK)
    ax_qos.axhline(100 * campaign.MAX_EXTRA_USERS, color=INK, lw=1, ls="--", label="limit: +5 users in 100")
    ax_qos.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="extra burst users over 20 ms vs 64 chains [points]",
               title="QoS cost (95% CI over seeds)")
    ax_qos.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_curves.png", "Every cell picks its chains for its own load; neighbours at the same load as "
                                  "cell 0. 10 seeds, 20 for 64/48/32 chains at 80-150 Mbit/s")


def plot_capacity(limits):
    """Acceptable load per chains, one bar per neighbour load."""
    fig, ax = plt.subplots(figsize=(9, 3.8))
    width, shown = .26, (16, 24, 32, 48, 64)
    for k, (folder, color) in enumerate(zip(FACTORS, (AQUA, BLUE, ORANGE))):
        values = limits[folder].reindex(shown)
        ax.bar(np.arange(len(shown)) + (k - 1) * width, values, width * .92, color=color,
               label=f"neighbours at {FACTORS[folder]:g}x the load")
        for i, y in enumerate(values):   # 150 is the highest simulated load: the real limit may be higher
            label = f"{y:g}+" if y == max(LOADS) else f"{y:g}"
            ax.text(i + (k - 1) * width, y + 2, label, ha="center", fontsize=7.5, color=INK)
    ax.set(xticks=range(len(shown)), xticklabels=[f"{a} chains" + (" + symbol" if a == 64 else "") for a in shown],
           ylim=(0, 170), ylabel="highest load with acceptable QoS [Mbit/s]",
           title="How much load fewer chains can carry")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_capacity.png", "64 chains: losses under 1% (it is the QoS reference). 150+: highest load "
                                    "simulated. 0.5x and 2x at 10-20-40-60-80-100-120-150 Mbit/s, 1x every 10")


CHAINS_BY_LEVEL = {"night": 16, "day": 16, "peak": 48}     # the final best setting


def day_models(days_3gpp):
    """Saving of one day per power model and policy, final configuration: Piovesan from the same runs as the day,
    3GPP Category 1 and 2 from day_3gpp. Only 3GPP has light and deep sleep."""
    rows = []
    always_on = sum(h * piovesan_level(level, 64, False) for level, h in HOURS.items())
    for policy in ("symbol", "channel", "symbol + channel"):
        chains = CHAINS_BY_LEVEL if "channel" in policy else dict.fromkeys(HOURS, 64)
        energy = sum(h * piovesan_level(level, chains[level], "symbol" in policy) for level, h in HOURS.items())
        saving = 100 * (1 - energy / always_on)
        rows.append(dict(model="Piovesan", policy=policy, saving=saving.mean(), ci=half_ci(saving), qos_ok=True))
    names = {1: "3GPP Category 1", 2: "3GPP Category 2"}
    for _, row in days_3gpp[days_3gpp.policy != "always on"].iterrows():
        rows.append(dict(model=names[row["cat"]], policy=row["policy"], saving=row["saving"], ci=row["ci"],
                         qos_ok=row["qos_ok"]))
    return pd.DataFrame(rows)


MODEL_STYLE = {"Piovesan": BLUE, "3GPP Category 1": ORANGE, "3GPP Category 2": AQUA}


def plot_models(models):
    """Saving of one day, Piovesan and 3GPP, one group of bars per policy; no bar: the model cannot express it;
    hatched: the night QoS is not acceptable."""
    policies = list(dict.fromkeys(models.policy))
    order = ["symbol", "channel", "symbol + channel"] + [p for p in policies if p.startswith("+")]
    fig, ax = plt.subplots(figsize=(9, 5.4))
    y = np.arange(len(order))
    width = .27
    for k, (model, color) in enumerate(MODEL_STYLE.items()):
        rows = [models[(models.model == model) & (models.policy == p)] for p in order]
        values = [row.saving.mean() for row in rows]
        offset = y + (k - 1) * width
        bars = ax.barh(offset, values, width * .92, color=color, label=model)
        for bar, row in zip(bars, rows):
            if len(row) and not row.qos_ok.all():
                bar.set_hatch("///")
                bar.set_edgecolor("white")
        for yi, v in zip(offset, values):
            if np.isfinite(v):
                ax.text(v + .5, yi, f"{v:.0f}%", va="center", fontsize=8, color=INK)
    ax.set(yticks=y, yticklabels=order, xlabel="saving over one day against 64 chains always on [%]", xlim=(0, 100),
           title="Same NS-3 traffic, three power models")
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=MUTED, hatch="///", edgecolor="white"))
    labels.append("QoS not acceptable at night")
    ax.legend(handles, labels, frameon=False, loc="upper right")
    save(fig, "final_models.png", "Hours 8/12/4, final configuration (16 chains at night and by day, 48 at peak). "
                                  "Sleep at night: NS-3 where simulated, else trace estimate\n"
                                  "(QoS: p95 delay within 20 ms). No bar: not possible (see the README). 10 seeds")


def plot_day(day):
    """The day figure of the README, on the final configuration (same drawing as step 3)."""
    from studies import daily
    shown = {"always on": "always on", "symbol": "symbol", FINAL_POLICY: "symbol + channel", NIGHT_SLEEP: NIGHT_SLEEP,
             "+ night carriers off*": "+ night carriers off*", "+ night dormancy*": "+ night dormancy*"}
    columns = dict(kwh="kWh_day", kwh_ci="kWh_ci", saving="saving_pct")
    table = day.loc[list(shown)].rename(index=shown).rename(columns=columns)
    daily.plot(table, list(shown.values()), formula_only=("+ night carriers off*", "+ night dormancy*"),
               filename="final_daily.png",
               note="Night, day: final campaign; peak: 48 chains, video profile. * formula only (no wake-up, no 4G "
                    "QoS). 10 seeds; 95% CI")


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
    days_3gpp, check = day_3gpp()
    days_3gpp.to_csv(paths.RESULTS / "final_threegpp.csv", index=False)
    print("\none day, 3GPP:\n", days_3gpp.round(2).to_string(index=False))
    print(f"night with 16 chains, earlier against final configuration, largest difference: {check:.4f}")

    plot_curves(result)
    plot_capacity(limits)
    plot_day(day)
    models = day_models(days_3gpp)
    models.to_csv(paths.RESULTS / "final_models.csv", index=False)
    print("\none day per power model:\n", models.round(2).to_string(index=False))
    plot_models(models)
