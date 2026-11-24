"""Figures from the single-seed test runs (run profiles.py first): PNG files in figures/."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import ns3data

HERE = Path(__file__).parent
RAW = ns3data.RAW.parent / "bs-results-test" / "sumimo"
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)
LIMIT_MS = 20  # ASSUMPTION: QoS limit on the p95 delay of every single user
PROFILES = {"night": "Night (0.8 Mbit/s)", "day": "Day (38 Mbit/s)", "peak150": "Peak (152 Mbit/s)"}
CHAINS = (64, 32, 16)
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e1e0d9"
NOTE = "One seed, 1.5 s per run; SU-MIMO; neighbour cells at 64 chains"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True})

d = pd.read_csv(HERE / "profiles.csv")
flows = pd.concat([pd.read_csv(RAW / f"{p}_a{a}_flows.csv").assign(profile=p, chains=a)
                   for p in PROFILES for a in CHAINS])
flows["p95_ms"] = flows.delay_p95_s * 1e3
worst = flows.groupby(["profile", "chains"]).p95_ms.agg(worst_ms="max", users="size",
                                                        over=lambda x: (x > LIMIT_MS).sum())


def watt(p, state):
    return d[(d.profile == p) & (d.state == state)].watt.iloc[0]


def save(fig, name, note=NOTE):
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.text(0.01, 0.01, note, fontsize=8, color=MUTED)
    fig.savefig(OUT / name, dpi=200, facecolor="white")
    plt.close(fig)


# 1. Power with and without symbol shutdown
fig, axes = plt.subplots(1, 3, figsize=(10, 4), sharey=True)
for ax, (p, title) in zip(axes, PROFILES.items()):
    for k, (suffix, color, lab) in enumerate((("", BLUE, "without symbol shutdown"),
                                              (" + symbol", ORANGE, "with symbol shutdown"))):
        y = [watt(p, f"{a} chains{suffix}") for a in CHAINS]
        x = [i + (k - .5) * .4 for i in range(3)]
        ax.bar(x, y, .36, color=color, label=lab)
        for xi, yi in zip(x, y):
            ax.text(xi, yi + 8, f"{yi:.0f}", ha="center", fontsize=8, color=INK)
    ax.set(title=title, xticks=range(3), xticklabels=CHAINS, xlabel="active chains", ylim=(0, 900))
    ax.grid(axis="x", visible=False)
axes[0].set_ylabel("AAU power [W]")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower right", ncol=2, frameon=False)
save(fig, "power_by_profile.png")

# 2. p95 delay of each user at peak
fig, axes = plt.subplots(1, 3, figsize=(10, 4.2), sharex=True, sharey=True)
for ax, a in zip(axes, CHAINS):
    f = flows[(flows.profile == "peak150") & (flows.chains == a)]
    for kind, color, m in (("video", BLUE, "s"), ("burst", ORANGE, "o")):
        g = f[f.kind == kind]
        ax.hlines(g.ue, 0, g.p95_ms, color=GRID, lw=2)
        ax.scatter(g.p95_ms, g.ue, s=55, color=color, marker=m, label=kind, zorder=3)
    for r in f[f.p95_ms > LIMIT_MS].itertuples():
        ax.text(r.p95_ms + 2, r.ue, f"{r.p95_ms:.1f}", va="center", fontsize=8, color=INK)
    ax.axvline(LIMIT_MS, color=MUTED, ls="--", lw=1)
    n = int((f.p95_ms > LIMIT_MS).sum())
    ax.set(title=f"{a} chains: {n} of {len(f)} users over {LIMIT_MS} ms", xlabel="p95 delay [ms]",
           xlim=(0, 82), yticks=range(10))
    ax.title.set_fontsize(10)
axes[0].set_ylabel("user (UE)")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower right", ncol=2, frameon=False)
save(fig, "peak_p95_per_user.png", "Peak, 152 Mbit/s. Dashed line: assumed limit. " + NOTE)

# 3. Night power by sleep mode
n = d[d.profile == "night"].sort_values("watt")
formula = n.state.isin(["all carriers off", "deep dormancy"])
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(n.state, n.watt, .6, color=[ORANGE if f else BLUE for f in formula])
for s, w, sv in zip(n.state, n.watt, n["saving_%"]):
    ax.text(w + 8, s, f"{w:.0f} W" + (f"  (−{sv:.0f}%)" if sv > 0 else ""), va="center", fontsize=9, color=INK)
ax.set(xlabel="AAU power [W]", xlim=(0, 800), title="Night: power by sleep mode")
ax.grid(axis="y", visible=False)
hs = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (BLUE, ORANGE)]
ax.legend(hs, ["NS-3 + power model", "power model only (no wake-up, no 4G QoS)"], frameon=False,
          fontsize=8, loc="upper center", bbox_to_anchor=(.5, -.14), ncol=2)
save(fig, "night_sleep_modes.png")

# 4. Energy / QoS trade-off at peak
fig, ax = plt.subplots(figsize=(7, 4.2))
xs = [watt("peak150", f"{a} chains") for a in CHAINS]
ys = [worst.loc[("peak150", a), "worst_ms"] for a in CHAINS]
ax.plot(xs, ys, color=BLUE, lw=2, marker="o", ms=9)
for a, x, y in zip(CHAINS, xs, ys):
    ax.annotate(f"{a} chains\n{x:.0f} W, {y:.1f} ms", (x, y), xytext=(8, 8), textcoords="offset points",
                fontsize=9, color=INK)
ax.axhline(LIMIT_MS, color=MUTED, ls="--", lw=1)
ax.text(540, LIMIT_MS + 1, "assumed limit", fontsize=8, color=MUTED)
ax.set(xlabel="AAU power [W]", ylabel="p95 delay of the worst user [ms]", xlim=(530, 880), ylim=(0, 85),
       title="Peak (152 Mbit/s): power against worst-user delay")
save(fig, "peak_tradeoff.png")
print(worst)
