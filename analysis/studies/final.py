"""Final study: every cell decides its own chains (bs-results-indep). Cell 0 runs every chain count at every load;
each neighbour carries 0.5, 1 or 2 times the burst load of cell 0 (at most 150 Mbit/s) and picks its chains with the
rule of run_campaign.sh (RULE) for its own load. Day profile (10 burst users per site) from 5 to 150 Mbit/s, night at
1 Mbit/s. At 1x and 80-150 Mbit/s, 64/48/32 chains have 20 seeds, the others 10.

Outputs: QoS-acceptable load per chains and neighbour load (criterion of campaign.py, relative to 64 chains on the same
seeds, every lower load acceptable too), power and saving per load, and a check that the measured thresholds at 1x
agree with RULE, which the neighbours used (the rule should describe the cell that applies it)."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import AQUA, BLUE, GRID, INK, MUTED, ORANGE, save
from studies.daily import half_ci
from studies.threegpp import slot_power

IND = paths.RAW / "bs-results-indep"
FACTORS = {"x0.5": 0.5, "x1": 1, "x2": 2}
LOADS = [1, 5] + list(range(10, 151, 10))
CHAINS = (64, 48, 32, 24, 16)
RULE = {40: 16, 50: 24, 100: 48, 1000: 64}   # run_campaign.sh: up to load -> chains (24 and 32 share 50)


def rule(load):
    return next(a for top, a in sorted(RULE.items()) if load <= top)


def name(load, a, r):
    return f"night_a{a}_r{r}" if load == 1 else f"day{load}_a{a}_r{r}"


def runs():
    rows, users = [], []
    for fx, f in FACTORS.items():
        for load in LOADS:
            for a in CHAINS:
                for r in range(1, 21):
                    o = IND / fx / name(load, a, r)
                    if not o.with_name(o.name + "_flows.csv").exists():
                        continue
                    m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
                    x = pd.read_csv(f"{o}_rx.csv")
                    nl = min(150, load * f)
                    rows.append(dict(factor=fx, load=load, chains=a, seed=r, nb_load=nl, nb_chains=rule(nl),
                                     piovesan=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W,
                                     piovesan_on=float(pw.piovesan(m["prb_load"], a)) * c.W,
                                     tgpp=slot_power(o, a, True, 1)[0].mean(), tgpp_on=slot_power(o, a, False, 1)[0].mean(),
                                     prb=100 * m["prb_load"], loss=100 * m["loss"], thr=m["thr"],
                                     sinr=x.sinr_db_w.sum() / x.res.sum(), bler=100 * x.corrupt.sum() / x.tbs.sum()))
                    fl = pd.read_csv(f"{o}_flows.csv")
                    users.append(fl[fl.kind == "burst"].assign(factor=fx, load=load, chains=a, seed=r))
    d, u = pd.DataFrame(rows), pd.concat(users)
    u["over"] = u.delay_p95_s * 1e3 > c.LIMIT_MS
    d = d.merge(u.groupby(["factor", "load", "chains", "seed"]).agg(over=("over", "sum"), users=("over", "size")).reset_index())
    ref = d[d.chains == 64].set_index(["factor", "load", "seed"])
    k = list(zip(d.factor, d.load, d.seed))
    d["saving"] = 100 * (1 - d.piovesan / ref.piovesan_on.reindex(k).to_numpy())
    d["saving_3gpp"] = 100 * (1 - d.tgpp / ref.tgpp_on.reindex(k).to_numpy())
    d["ref_over"], d["ref_users"] = ref.over.reindex(k).to_numpy(), ref.users.reindex(k).to_numpy()
    return d


def table(d):
    """Per neighbour factor, load and chains: means, QoS relative to 64 chains on the same seeds."""
    g = d.groupby(["factor", "load", "chains"])
    t = g.agg(seeds=("seed", "size"), nb_load=("nb_load", "first"), nb_chains=("nb_chains", "first"),
              piovesan=("piovesan", "mean"), saving=("saving", "mean"), saving_3gpp=("saving_3gpp", "mean"),
              prb=("prb", "mean"), loss=("loss", "mean"), sinr=("sinr", "mean"), bler=("bler", "mean"),
              over=("over", "sum"), users=("users", "sum"), ref_over=("ref_over", "sum"), ref_users=("ref_users", "sum"))
    t["saving_ci"] = g.saving.apply(half_ci)
    t["over_pct"] = 100 * t.over / t.users
    t["extra_pct"] = t.over_pct - 100 * t.ref_over / t.ref_users
    # paired per seed: CI of the extra share of users over the limit
    p = d.assign(x=100 * (d.over / d.users - d.ref_over / d.ref_users))
    t["extra_ci"] = p.groupby(["factor", "load", "chains"]).x.apply(half_ci)
    t["ok"] = (t.extra_pct <= 100 * c.MAX_EXTRA_USERS) & (t.loss < 100 * c.MAX_LOSS)
    return t


def capacity(t):
    """Highest load each chains sustain with acceptable QoS, every lower simulated load acceptable too."""
    out = {}
    for fx in FACTORS:
        x = t.xs(fx, level="factor")
        loads = sorted(x.index.get_level_values("load").unique())
        for a in CHAINS:
            ok = x.xs(a, level="chains").ok.reindex(loads, fill_value=False)
            good = [l for l in loads if ok.loc[:l].all()]
            out[(fx, a)] = max(good) if good else 0
    return pd.Series(out).unstack(0)[list(FACTORS)]


# One day (step 3 on the final configuration). Night and day from this campaign (neighbours at 1x, chains by the rule);
# peak from the peak profile with video (bs-results-main and -grid, neighbours at 64 chains): the final campaign has no
# video. With neighbours picking their own chains the peak interference can only be lower, so the peak is conservative.
HOURS = {"night": 8, "day": 12, "peak": 4}
DAY_POLICIES = {"always on": {"night": (64, 0), "day": (64, 0), "peak": (64, 0)},
                "symbol": {"night": (64, 1), "day": (64, 1), "peak": (64, 1)},
                "symbol + channel, earlier (64 at peak)": {"night": (16, 1), "day": (16, 1), "peak": (64, 1)},
                "symbol + channel, final (48 at peak)": {"night": (16, 1), "day": (16, 1), "peak": (48, 1)}}


def level_run(level, a, r):
    if level == "peak":
        grid = paths.RAW / "bs-results-grid" / f"peak100_a{a}_r{r}"
        return grid if grid.with_name(grid.name + "_flows.csv").exists() else c.RAW / f"peak100_a{a}_r{r}"
    return IND / "x1" / name(1 if level == "night" else 40, a, r)


def day_energy():
    """Per policy and seed: energy of one day, Piovesan [kWh] and 3GPP Category 1 [relative units x h]."""
    cache, rows = {}, []
    for pol, levels in DAY_POLICIES.items():
        for r in range(1, c.SEEDS + 1):
            kwh = tg = 0
            for lv, (a, sym) in levels.items():
                if (lv, a, sym, r) not in cache:
                    o = level_run(lv, a, r)
                    m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
                    cache[(lv, a, sym, r)] = (float(pw.piovesan(m["prb_load"], a, m["pa_off"] if sym else 0)) * c.W,
                                              slot_power(o, a, bool(sym), 1)[0].mean())
                w, t3 = cache[(lv, a, sym, r)]
                kwh, tg = kwh + HOURS[lv] * w / 1e3, tg + HOURS[lv] * t3
                rows.append(dict(policy=pol, seed=r, level=lv, chains=a, symbol=sym, watt=w, tgpp=t3))
            rows.append(dict(policy=pol, seed=r, level="day total", kwh=kwh, tgpp=tg))
    d = pd.DataFrame(rows)
    tot = d[d.level == "day total"].set_index(["policy", "seed"])
    ref = tot.xs("always on", level="policy")
    tot["saving"] = 100 * (1 - tot.kwh / ref.kwh.reindex(tot.index, level="seed").to_numpy())
    tot["saving_3gpp"] = 100 * (1 - tot.tgpp / ref.tgpp.reindex(tot.index, level="seed").to_numpy())
    g = tot.groupby("policy", sort=False)
    out = g[["kwh", "saving", "saving_3gpp"]].mean().join(g.kwh.apply(half_ci).rename("kwh_ci")) \
        .join(g.saving.apply(half_ci).rename("saving_ci")).join(g.saving_3gpp.apply(half_ci).rename("saving_3gpp_ci"))
    w = d[d.level != "day total"].groupby(["policy", "level"], sort=False).watt.mean().unstack()
    return out.join(w.add_prefix("W_"))


def day_light_sleep(day):
    """3GPP Category 1: final policy with light sleep at night (SSB every 160 ms), simulated in NS-3 (studies.threegpp).
    Those night runs have neighbours at 64 chains; at 1 Mbit/s the neighbours make no difference (same power here)."""
    from studies.threegpp import d as d3, sim
    night = sim[(sim.profile == "night") & (sim.state == "light") & (sim.ssb == "SSB 160 ms")].sort_values("seed").rel.to_numpy()
    old16 = d3[(d3.cat == 1) & (d3.profile == "night") & (d3.chains == 16) & d3.symbol].sort_values("seed").rel.to_numpy()
    lv = lambda l, a, sym: np.array([slot_power(level_run(l, a, r), a, sym, 1)[0].mean() for r in range(1, c.SEEDS + 1)])
    new16 = lv("night", 16, True)
    ref = sum(h * lv(l, 64, False) for l, h in HOURS.items())
    e = HOURS["night"] * night + HOURS["day"] * lv("day", 16, True) + HOURS["peak"] * lv("peak", 48, True)
    v = 100 * (1 - e / ref)
    return dict(saving_3gpp=v.mean(), ci=half_ci(v), night_16_old_vs_final=np.abs(old16 - new16).max())


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_rows", 300, "display.max_columns", 30)
    d = runs()
    d.to_csv(paths.RESULTS / "final_runs.csv", index=False)
    t = table(d)
    t.to_csv(paths.RESULTS / "final.csv")
    cols = ["seeds", "nb_load", "nb_chains", "piovesan", "saving", "saving_ci", "saving_3gpp", "prb", "sinr", "bler",
            "over_pct", "extra_pct", "extra_ci", "loss", "ok"]
    print(t[cols].round(2).to_string())
    cap = capacity(t)
    cap.to_csv(paths.RESULTS / "final_capacity.csv")
    print("\nacceptable load per chains [Mbit/s] (0.5x and 2x on 10-150 only):\n", cap)
    nb64 = pd.read_csv(paths.RESULTS / "policy_curves.csv")     # neighbours at 64 chains, 1-100 Mbit/s
    print("neighbours at 64 (policy study):", nb64.groupby("chains").apply(
        lambda z: max([l for l in sorted(z.load) if z[z.load <= l].ok.all()] or [0]), include_groups=False).to_dict())
    print("RULE used by the neighbours:", RULE)
    day = day_energy()
    day.to_csv(paths.RESULTS / "final_daily.csv")
    print("\none day, 8/12/4 h, saving against 64 chains always on:\n", day.round(2).to_string())
    print("3GPP Cat. 1, final + light sleep at night (SSB 160 ms):", day_light_sleep(day))

    # Figure 1: saving and QoS against load at 1x
    x1 = t.xs("x1", level="factor")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {64: INK, 48: AQUA, 32: BLUE, 24: MUTED, 16: ORANGE}
    for a in CHAINS:
        z = x1.xs(a, level="chains")
        a1.plot(z.index, z.saving, color=colors[a], lw=1.6, label=f"{a} chains")
        a1.scatter(z.index[~z.ok], z.saving[~z.ok], s=40, facecolor="white", edgecolor=colors[a], lw=1.4, zorder=3)
        a1.scatter(z.index[z.ok], z.saving[z.ok], s=16, color=colors[a], zorder=3)
        if a != 64:
            a2.errorbar(z.index, z.extra_pct, yerr=z.extra_ci, color=colors[a], lw=1.4, capsize=2, label=f"{a} chains")
    a1.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="saving against 64 chains always on [%]",
           title="Power: symbol shutdown + fewer chains")
    a1.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0.12, 0.08))
    a1.text(.02, .03, "hollow: QoS not acceptable", transform=a1.transAxes, fontsize=8, color=INK)
    a2.axhline(100 * c.MAX_EXTRA_USERS, color=ORANGE, lw=1, ls="--")
    a2.text(2, 100 * c.MAX_EXTRA_USERS + .8, "limit: +5 users in 100", fontsize=8, color=INK)
    a2.set(xlabel="burst load of cell 0 [Mbit/s]", ylabel="extra burst users over 20 ms vs 64 chains [points]",
           title="QoS cost (95% CI over seeds)")
    a2.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_curves.png", "Every cell picks its chains for its own load; neighbours at the same load as cell 0. "
                                  "10 seeds, 20 for 64/48/32 chains at 80-150 Mbit/s")

    # Figure 2: acceptable load per chains, per neighbour load
    fig, ax = plt.subplots(figsize=(9, 3.8))
    w, shown = .26, (16, 24, 32, 48, 64)
    for k, (fx, color) in enumerate(zip(FACTORS, (AQUA, BLUE, ORANGE))):
        v = cap[fx].reindex(shown)
        ax.bar(np.arange(len(shown)) + (k - 1) * w, v, w * .92, color=color, label=f"neighbours at {FACTORS[fx]:g}x the load")
        for i, y in enumerate(v):   # 150 is the highest simulated load: the real limit may be higher
            ax.text(i + (k - 1) * w, y + 2, f"{y:g}+" if y == max(LOADS) else f"{y:g}", ha="center", fontsize=7.5, color=INK)
    ax.set(xticks=range(len(shown)), xticklabels=[f"{a} chains" + (" + symbol" if a == 64 else "") for a in shown],
           ylim=(0, 170), ylabel="highest load with acceptable QoS [Mbit/s]", title="How much load fewer chains can carry")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "final_capacity.png", "64 chains: losses under 1% (it is the QoS reference). 150+: highest load simulated. "
                                    "0.5x and 2x at 10-20-40-60-80-100-120-150 Mbit/s, 1x every 10")
