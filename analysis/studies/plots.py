"""Figures of the main campaign (step 2 of docs/STEPS.md):

  power_by_profile.png    AAU power per level and chains, with and without symbol shutdown
  peak_p95_per_user.png   at peak, the 95th-percentile delay of every burst user, per number of chains
  night_sleep_modes.png   night power with every sleep option, from symbol shutdown to deep dormancy
  power_vs_qos.png        day and peak: power against the share of burst users over the delay limit

Run from analysis/:  ../.venv/bin/python -m studies.plots
"""
import matplotlib.pyplot as plt
import numpy as np

from lib import campaign, power
from lib.style import AQUA, BLUE, CHAINS, INK, MUTED, NOTE, ORANGE, PROFILES, save


def summary_tables():
    """Mean and 95% CI of the power per level and chains, and the share of burst users over the limit [%]."""
    by_level = campaign.runs.groupby(["profile", "chains"])
    mean = by_level[["watt", "watt_sym", "sent"]].mean()
    ci = by_level[["watt", "watt_sym"]].std() * campaign.t975(campaign.SEEDS) / np.sqrt(campaign.SEEDS)
    burst = campaign.burst
    over_pct = 100 * burst.assign(o=burst.p95_ms > campaign.LIMIT_MS).groupby(["profile", "chains"]).o.mean()
    return mean, ci, over_pct


def plot_power_by_profile(mean, ci):
    fig, axes = plt.subplots(1, 3, figsize=(10, 4.2), sharey=True)
    for ax, (profile, title) in zip(axes, PROFILES.items()):
        for k, (column, color, label) in enumerate((("watt", BLUE, "without symbol shutdown"),
                                                    ("watt_sym", ORANGE, "with symbol shutdown"))):
            y = [mean.loc[(profile, a), column] for a in CHAINS]
            err = [ci.loc[(profile, a), column] for a in CHAINS]
            x = [i + (k - .5) * .4 for i in range(3)]
            ax.bar(x, y, .36, color=color, label=label, yerr=err, error_kw=dict(ecolor=INK, lw=1, capsize=2))
            for xi, yi, ei in zip(x, y, err):
                ax.text(xi, yi + ei + 10, f"{yi:.0f}", ha="center", fontsize=8, color=INK)
        ax.set(title=title, xticks=range(3), xticklabels=CHAINS, xlabel="active chains", ylim=(0, 900))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("AAU power [W]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=2, frameon=False)
    save(fig, "power_by_profile.png", NOTE + "; bars: 95% CI")


def plot_peak_delays():
    """Cumulative distribution of the users' p95 delay at peak, one line per number of chains."""
    burst = campaign.burst
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for chains, color, style in zip(CHAINS, (BLUE, ORANGE, AQUA), ("-", "--", "-.")):
        delays = np.sort(burst[(burst.profile == "peak100") & (burst.chains == chains)].p95_ms)
        share_below = 100 * np.arange(1, len(delays) + 1) / len(delays)
        n_over = (delays > campaign.LIMIT_MS).sum()
        ax.step(delays, share_below, where="post", color=color, ls=style, lw=2,
                label=f"{chains} chains ({n_over} of {len(delays)} users over {campaign.LIMIT_MS} ms)")
    ax.axvline(campaign.LIMIT_MS, color=MUTED, ls=":", lw=1.5)
    ax.set(xscale="log", xlabel="p95 delay of a burst user [ms]", ylabel="users below this delay [%]",
           ylim=(0, 101), title="Peak (100 Mbit/s): burst users, all seeds")
    ax.legend(frameon=False, loc="lower right")
    save(fig, "peak_p95_per_user.png", "Dotted line: assumed limit. " + NOTE)


def plot_night_sleep_modes(mean):
    """Night power for every option: simulated ones (blue) and formula-only states (orange)."""
    options = [(f"{a} chains" + suffix, mean.loc[("night", a), column], BLUE) for a in CHAINS
               for suffix, column in (("", "watt"), (" + symbol", "watt_sym"))]
    anchor = power.ANCHOR_W_PER_MBPS * mean.loc[("night", 64), "sent"]   # the 4G anchor carries the night traffic
    options += [("all carriers off", power.CARRIER_OFF * campaign.W + anchor, ORANGE),
                ("deep dormancy", power.DORMANT * campaign.W + anchor, ORANGE)]
    options.sort(key=lambda option: option[1])
    always_on = mean.loc[("night", 64), "watt"]

    fig, ax = plt.subplots(figsize=(8, 4.3))
    ax.barh([o[0] for o in options], [o[1] for o in options], .6, color=[o[2] for o in options])
    for label, w, _ in options:
        ax.text(w + 8, label, f"{w:.0f} W" + (f"  (−{100 * (1 - w / always_on):.0f}%)" if w < always_on else ""),
                va="center", fontsize=9, color=INK)
    ax.set(xlabel="AAU power [W]", xlim=(0, 800), title="Night: power by sleep mode")
    ax.grid(axis="y", visible=False)
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=k) for k in (BLUE, ORANGE)],
              ["NS-3 + power model", "power model only (no wake-up, no 4G QoS)"], frameon=False,
              fontsize=8, loc="upper center", bbox_to_anchor=(.5, -.14), ncol=2)
    save(fig, "night_sleep_modes.png")


def plot_power_vs_qos(mean, over_pct):
    """With symbol shutdown: each point is a number of chains; lower left is better."""
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    for profile, color, marker, dy in (("day", ORANGE, "s", 10), ("peak100", BLUE, "o", 8)):
        xs = [mean.loc[(profile, a), "watt_sym"] for a in CHAINS]
        ys = [over_pct[(profile, a)] for a in CHAINS]
        ax.plot(xs, ys, color=color, lw=2, marker=marker, ms=8, label=PROFILES[profile])
        for a, x, y in zip(CHAINS, xs, ys):
            ax.annotate(f"{a} chains", (x, y), xytext=(6, dy), textcoords="offset points", fontsize=9, color=INK)
    ax.set(xlabel="AAU power with symbol shutdown [W]", ylabel=f"burst users with p95 over {campaign.LIMIT_MS} ms [%]",
           xlim=(460, 780), ylim=(-2, 56), title="Power against QoS")
    ax.legend(frameon=False)
    save(fig, "power_vs_qos.png")


if __name__ == "__main__":
    mean, ci, over_pct = summary_tables()
    plot_power_by_profile(mean, ci)
    plot_peak_delays()
    plot_night_sleep_modes(mean)
    plot_power_vs_qos(mean, over_pct)
