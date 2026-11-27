"""Sleep with a wake-up time, simulated in NS-3 (step 6 of docs/STEPS.md; campaign bs-results-wake).

Same chains and seeds as the main campaign, with the sleep controller of bs-energy.cc on: the AAU sleeps between
bursts and needs Tw to go down and Tw to come back. Three settings: (Tw, SSB period) = (0.5 ms, 20 ms), (5, 20), (5, 160).

Power of a run: Piovesan with symbol shutdown, as in lib.campaign, minus the time asleep at the "RF off" power
instead of the idle awake power (studies.wakeup.idle_watt). Each run is paired with the same seed without sleep.

Run from analysis/:  ../.venv/bin/python -m studies.wakeup_ns3
"""
import matplotlib.pyplot as plt
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import AQUA, BLUE, INK, ORANGE, PROFILES, save
from studies.daily import HOURS, energy, half_ci
from studies.wakeup import CASES, idle_watt

RAW = paths.RAW / "bs-results-wake"
SETTINGS = [("0.5", 20), ("5", 20), ("5", 160)]  # Tw [ms] (as in the file names), SSB period [ms]
SEEDS = range(1, campaign.SEEDS + 1)


def share_asleep(sleep_file):
    """The sleep controller writes the slots spent in each state; returns (share of time asleep, its row)."""
    states = pd.read_csv(sleep_file).iloc[0]
    return states["sleep"] / states[["awake", "down", "sleep", "up"]].sum(), states


def load(main):
    """All runs of the campaign: one row per run, the burst users, the video segments."""
    rows, users, segments = [], [], []
    for profile, chains in CASES.items():
        for tw, ssb in SETTINGS:
            for seed in SEEDS:
                prefix = RAW / f"{profile}_a{chains}_t{tw}_s{ssb}_r{seed}"
                if not prefix.with_name(prefix.name + "_flows.csv").exists():
                    continue                                    # 5 ms not simulated at peak
                metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
                asleep, states = share_asleep(f"{prefix}_sleep.csv")
                watt = (float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W
                        - asleep * (idle_watt(chains) - power.CARRIER_OFF * campaign.W))
                key = dict(profile=profile, tw=tw, ssb=ssb, seed=seed)
                rows.append(dict(**key, asleep=100 * asleep, watt=watt,
                                 ref=main.loc[(profile, chains, seed), "watt_sym"],     # same seed, no sleep
                                 on=main.loc[(profile, 64, seed), "watt"],             # same seed, always on
                                 loss=100 * metrics["loss"], ref_loss=100 * main.loc[(profile, chains, seed), "loss"],
                                 violations=states.violations))
                users.append(pd.read_csv(f"{prefix}_flows.csv").assign(**key))
                if profile.startswith("peak"):
                    segments.append(pd.read_csv(f"{prefix}_segments.csv").assign(**key))
    runs = pd.DataFrame(rows)
    users = pd.concat(users)
    burst = users[users.kind == "burst"].assign(p95_ms=lambda x: 1e3 * x.delay_p95_s)
    return runs, burst, pd.concat(segments)


def table(runs, burst):
    """One row per level and setting: time asleep, extra saving, delays and losses against no sleep."""
    out = []
    for (profile, tw, ssb), group in runs.groupby(["profile", "tw", "ssb"], sort=False):
        users = burst[(burst.profile == profile) & (burst.tw == tw) & (burst.ssb == ssb)]
        users_no_sleep = campaign.burst[(campaign.burst.profile == profile) & (campaign.burst.chains == CASES[profile])]
        extra = 100 * (1 - group.watt / group.ref)
        out.append(dict(profile=profile, tw=tw, ssb=ssb, runs=len(group),
                        asleep=group.asleep.mean(), asleep_ci=half_ci(group.asleep),
                        ref_W=group.ref.mean(), watt=group.watt.mean(), extra_pct=extra.mean(), extra_ci=half_ci(extra),
                        save_vs_on=(100 * (1 - group.watt / group.on)).mean(),
                        median_p95=users.p95_ms.median(), ref_median=users_no_sleep.p95_ms.median(),
                        over=int((users.p95_ms > campaign.LIMIT_MS).sum()),
                        ref_over=int((users_no_sleep.p95_ms > campaign.LIMIT_MS).sum()), users=len(users),
                        loss=group.loss.mean(), ref_loss=group.ref_loss.mean(), violations=int(group.violations.sum())))
    out = pd.DataFrame(out)
    out["extra_users_pct"] = 100 * (out.over - out.ref_over) / out.users
    return out


def print_days(runs, main):
    """Energy of one day with sleep everywhere, or at night only (rest of the day as symbol + channel)."""
    def watt(profile, tw, ssb):
        return runs[(runs.profile == profile) & (runs.tw == tw) & (runs.ssb == ssb)].sort_values("seed").watt.to_numpy()

    always_on, best = energy("always on", HOURS), energy("symbol + channel", HOURS)
    no_sleep = {p: main.xs((p, CASES[p]), level=("profile", "chains")).sort_index().watt_sym.to_numpy() for p in HOURS}
    variants = (("0.5 ms everywhere", {p: watt(p, "0.5", 20) for p in HOURS}),
                ("0.5 ms at night only", {**no_sleep, "night": watt("night", "0.5", 20)}),
                ("5 ms, SSB 160, night only", {**no_sleep, "night": watt("night", "5", 160)}),
                ("5 ms, SSB 20, night only", {**no_sleep, "night": watt("night", "5", 20)}))
    for name, level_watt in variants:
        e = sum(h * level_watt[p] for p, h in HOURS.items()) / 1000
        print(f"{name}: {e.mean():.2f} kWh, vs always on {(100 * (1 - e / always_on)).mean():.1f} +/- "
              f"{half_ci(100 * (1 - e / always_on)):.1f} %, vs symbol + channel {(100 * (1 - e / best)).mean():.1f} %")


def plot(table):
    """Extra saving over symbol + channel per level and setting."""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    styles = {("0.5", 20): (BLUE, "Tw 0.5 ms, SSB every 20 ms"), ("5", 20): (ORANGE, "Tw 5 ms, SSB every 20 ms"),
              ("5", 160): (AQUA, "Tw 5 ms, SSB every 160 ms")}
    for k, ((tw, ssb), (color, label)) in enumerate(styles.items()):
        setting = table[(table.tw == tw) & (table.ssb == ssb)].set_index("profile")
        xs = [i + (k - 1) * .27 for i, p in enumerate(PROFILES) if p in setting.index]
        profiles = [p for p in PROFILES if p in setting.index]
        ax.bar(xs, setting.extra_pct[profiles], .25, color=color, label=label, yerr=setting.extra_ci[profiles],
               error_kw=dict(ecolor=INK, lw=1, capsize=2))
        for x, p in zip(xs, profiles):
            ax.text(x, setting.extra_pct[p] + setting.extra_ci[p] + .4, f"{setting.extra_pct[p]:.1f}%",
                    ha="center", fontsize=8, color=INK)
    ax.set(xticks=range(3), xticklabels=[f"{PROFILES[p]}, {CASES[p]} chains" for p in PROFILES], ylim=(0, 21),
           ylabel="extra saving over symbol + channel [%]", title="Sleep with a wake-up time, simulated in NS-3")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False)
    save(fig, "wakeup_ns3.png", "RF off state, idle timer 2 Tw; 5 ms not simulated at peak. 10 seeds; bars: 95% CI")


if __name__ == "__main__":
    main = campaign.runs.set_index(["profile", "chains", "seed"])
    runs, burst, segments = load(main)
    result = table(runs, burst)
    result.to_csv(paths.RESULTS / "wakeup_ns3.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(result.round(2).to_string(index=False))

    whole = campaign.whole_segments(segments)
    late_no_sleep = campaign.whole[(campaign.whole.profile == "peak100") & (campaign.whole.chains == 64)].late.sum()
    print("peak segments late:", int(whole.late.sum()), "of", len(whole), "| without sleep:", int(late_no_sleep))

    print_days(runs, main)
    plot(result)
