"""Energy efficiency of the AAU in bit per joule (step 4 of docs/STEPS.md).

Efficiency = traffic delivered by cell 0 (IP level, headers included) / AAU power, seed by seed, for every level,
number of chains and with or without symbol shutdown; then for a whole day per policy (studies.daily).
The formula-only night states are left out: in those the 4G layer carries the traffic, not the AAU.

Needs results/campaign.csv (run lib.campaign first). Run from analysis/:  ../.venv/bin/python -m studies.efficiency
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, paths
from lib.style import BLUE, CHAINS, INK, MUTED, ORANGE, PROFILES, save
from studies.daily import HOURS, POLICIES, energy, half_ci

SEEDS = range(1, campaign.SEEDS + 1)


def runs_by_key():
    return campaign.runs.set_index(["profile", "chains", "seed"]).sort_index()


def kbit_per_joule(runs, profile, chains, symbol):
    """Efficiency of one level and chain count, one value per seed. Mbit/s / W = Mbit/J, hence x 1000 for kbit/J."""
    level = runs.loc[(profile, chains)]
    return (1e3 * level.thr / level["watt_sym" if symbol else "watt"]).to_numpy()


def daily_kbit_per_joule(runs, policy):
    """Bits delivered over the day / energy of the day, one value per seed [kbit/J]."""
    bits = sum(h * 3600 * 1e6 * np.array([runs.loc[(level, POLICIES[policy][level][0], s), "thr"] for s in SEEDS])
               for level, h in HOURS.items())
    return bits / (energy(policy, HOURS) * 3.6e6) / 1e3     # kWh -> J is x 3.6e6


def plot(table):
    """One panel per level (very different scales), bars with and without symbol shutdown; hatched: QoS fails."""
    fig, axes = plt.subplots(1, 3, figsize=(10, 4.2))
    for ax, (profile, title) in zip(axes, PROFILES.items()):
        level = table[table.profile == profile]
        top = (level.kbit_J + level.kbit_J_ci).max()
        for k, color in ((0, BLUE), (1, ORANGE)):
            bars_data = level[level.symbol == bool(k)]
            x = np.arange(3) + (k - .5) * .4
            bars = ax.bar(x, bars_data.kbit_J, .36, color=color, yerr=bars_data.kbit_J_ci,
                          error_kw=dict(ecolor=INK, lw=1, capsize=2))
            for bar, xi, value, ci, good in zip(bars, x, bars_data.kbit_J, bars_data.kbit_J_ci, bars_data.qos_ok):
                if not good:
                    bar.set_hatch("///")
                    bar.set_edgecolor("white")
                ax.text(xi, value + ci + .015 * top, f"{value:.1f}" if value < 10 else f"{value:.0f}",
                        ha="center", fontsize=8, color=INK)
        ax.set(title=title, xticks=range(3), xticklabels=CHAINS, xlabel="active chains", ylim=(0, 1.15 * top))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("energy efficiency [kbit/J]")
    box = plt.Rectangle
    fig.legend([box((0, 0), 1, 1, color=BLUE), box((0, 0), 1, 1, color=ORANGE),
                box((0, 0), 1, 1, facecolor=MUTED, hatch="///", edgecolor="white")],
               ["without symbol", "with symbol", "QoS not acceptable"], loc="lower right", ncol=3, frameon=False, fontsize=9)
    save(fig, "efficiency.png", "10 seeds, 10 s; y scales differ; bars: 95% CI")


if __name__ == "__main__":
    runs = runs_by_key()
    qos = pd.read_csv(paths.RESULTS / "campaign.csv", index_col=["profile", "chains"])
    qos_ok = qos.qos_ok   # relative QoS criterion of lib.campaign (users over the limit, late segments, losses)

    rows = []
    for profile in PROFILES:
        reference = kbit_per_joule(runs, profile, 64, 0)
        for chains in CHAINS:
            for symbol in (0, 1):
                v = kbit_per_joule(runs, profile, chains, symbol)
                gain = 100 * (v / reference - 1)    # paired by seed
                rows.append(dict(profile=profile, chains=chains, symbol=bool(symbol), kbit_J=v.mean(), kbit_J_ci=half_ci(v),
                                 gain_pct=gain.mean(), gain_ci=half_ci(gain), qos_ok=bool(qos_ok[(profile, chains)])))
    table = pd.DataFrame(rows)
    table.to_csv(paths.RESULTS / "efficiency.csv", index=False)
    pd.set_option("display.width", 200)
    print(table.round(2).to_string(index=False))

    reference = daily_kbit_per_joule(runs, "always on")
    for policy in POLICIES:
        v = daily_kbit_per_joule(runs, policy)
        gain = 100 * (v / reference - 1)
        print(f"day total, {policy}: {v.mean():.1f} +/- {half_ci(v):.1f} kbit/J, "
              f"gain {gain.mean():.1f} +/- {half_ci(gain):.1f} %")

    plot(table)
