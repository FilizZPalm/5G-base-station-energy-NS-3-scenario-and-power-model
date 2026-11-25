"""Figures from the multi-seed campaign (bs-results-main): PNG files in figures/."""
import matplotlib.pyplot as plt
import numpy as np
from lib import campaign as c, power as pw
from lib.style import AQUA, BLUE, CHAINS, INK, MUTED, NOTE, ORANGE, PROFILES, save

g = c.runs.groupby(["profile", "chains"])
mean = g[["watt", "watt_sym", "sent"]].mean()
ci = g[["watt", "watt_sym"]].std() * c.T975 / np.sqrt(c.SEEDS)
over = 100 * c.burst.assign(o=c.burst.p95_ms > c.LIMIT_MS).groupby(["profile", "chains"]).o.mean()


if __name__ == "__main__":
    # 1. Power with and without symbol shutdown
    fig, axes = plt.subplots(1, 3, figsize=(10, 4.2), sharey=True)
    for ax, (p, title) in zip(axes, PROFILES.items()):
        for k, (col, color, lab) in enumerate((("watt", BLUE, "without symbol shutdown"),
                                               ("watt_sym", ORANGE, "with symbol shutdown"))):
            y = [mean.loc[(p, a), col] for a in CHAINS]
            e = [ci.loc[(p, a), col] for a in CHAINS]
            x = [i + (k - .5) * .4 for i in range(3)]
            ax.bar(x, y, .36, color=color, label=lab, yerr=e, error_kw=dict(ecolor=INK, lw=1, capsize=2))
            for xi, yi, ei in zip(x, y, e):
                ax.text(xi, yi + ei + 10, f"{yi:.0f}", ha="center", fontsize=8, color=INK)
        ax.set(title=title, xticks=range(3), xticklabels=CHAINS, xlabel="active chains", ylim=(0, 900))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("AAU power [W]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=2, frameon=False)
    save(fig, "power_by_profile.png", NOTE + "; bars: 95% CI")

    # 2. Distribution of the p95 delay of the burst users at peak
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for a, color, ls in zip(CHAINS, (BLUE, ORANGE, AQUA), ("-", "--", "-.")):
        v = np.sort(c.burst[(c.burst.profile == "peak100") & (c.burst.chains == a)].p95_ms)
        ax.step(v, 100 * np.arange(1, len(v) + 1) / len(v), where="post", color=color, ls=ls, lw=2,
                label=f"{a} chains ({(v > c.LIMIT_MS).sum()} of {len(v)} users over {c.LIMIT_MS} ms)")
    ax.axvline(c.LIMIT_MS, color=MUTED, ls=":", lw=1.5)
    ax.set(xscale="log", xlabel="p95 delay of a burst user [ms]", ylabel="users below this delay [%]",
           ylim=(0, 101), title="Peak (100 Mbit/s): burst users, all seeds")
    ax.legend(frameon=False, loc="lower right")
    save(fig, "peak_p95_per_user.png", "Dotted line: assumed limit. " + NOTE)

    # 3. Night power by sleep mode
    n = [(f"{a} chains" + s, mean.loc[("night", a), col], BLUE) for a in CHAINS
         for s, col in (("", "watt"), (" + symbol", "watt_sym"))]
    extra = pw.ANCHOR_W_PER_MBPS * mean.loc[("night", 64), "sent"]
    n += [("all carriers off", pw.CARRIER_OFF * c.W + extra, ORANGE),
          ("deep dormancy", pw.DORMANT * c.W + extra, ORANGE)]
    n.sort(key=lambda t: t[1])
    ref = mean.loc[("night", 64), "watt"]
    fig, ax = plt.subplots(figsize=(8, 4.3))
    ax.barh([t[0] for t in n], [t[1] for t in n], .6, color=[t[2] for t in n])
    for lab, w, _ in n:
        ax.text(w + 8, lab, f"{w:.0f} W" + (f"  (−{100 * (1 - w / ref):.0f}%)" if w < ref else ""),
                va="center", fontsize=9, color=INK)
    ax.set(xlabel="AAU power [W]", xlim=(0, 800), title="Night: power by sleep mode")
    ax.grid(axis="y", visible=False)
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=k) for k in (BLUE, ORANGE)],
              ["NS-3 + power model", "power model only (no wake-up, no 4G QoS)"], frameon=False,
              fontsize=8, loc="upper center", bbox_to_anchor=(.5, -.14), ncol=2)
    save(fig, "night_sleep_modes.png")

    # 4. Energy / QoS trade-off (with symbol shutdown)
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    for p, color, m, dy in (("day", ORANGE, "s", 10), ("peak100", BLUE, "o", 8)):
        xs, ys = [mean.loc[(p, a), "watt_sym"] for a in CHAINS], [over[(p, a)] for a in CHAINS]
        ax.plot(xs, ys, color=color, lw=2, marker=m, ms=8, label=PROFILES[p])
        for a, x, y in zip(CHAINS, xs, ys):
            ax.annotate(f"{a} chains", (x, y), xytext=(6, dy), textcoords="offset points", fontsize=9, color=INK)
    ax.set(xlabel="AAU power with symbol shutdown [W]", ylabel=f"burst users with p95 over {c.LIMIT_MS} ms [%]",
           xlim=(460, 780), ylim=(-2, 56), title="Power against QoS")
    ax.legend(frameon=False)
    save(fig, "power_vs_qos.png")
