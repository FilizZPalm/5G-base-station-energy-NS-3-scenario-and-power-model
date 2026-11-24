"""Campaign results (night, day, peak levels) -> energy of one day, per sleep policy.

Each hour of the day is one of the three simulated levels; hours per level are an assumption.
Sleep modes with a formula only (all carriers off, deep dormancy) are marked: no wake-up, no 4G QoS."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import campaign as c
import power as pw
from plots import ANCHOR_W_PER_MBPS, BLUE, GRID, INK, MUTED, ORANGE, OUT

HERE = c.Path(__file__).parent
# ASSUMPTIONS ---------------------------------------------------------------------------
HOURS = {"night": 8, "day": 12, "peak100": 4}
SENSITIVITY = {"6/14/4": (6, 14, 4), "8/12/4 (base)": (8, 12, 4), "10/10/4": (10, 10, 4),
               "8/14/2": (8, 14, 2), "8/10/6": (8, 10, 6)}
# policy -> (chains, symbol shutdown) per level; the last two replace the night with a formula-only state
POLICIES = {
    "always on": {"night": (64, 0), "day": (64, 0), "peak100": (64, 0)},
    "symbol": {"night": (64, 1), "day": (64, 1), "peak100": (64, 1)},
    "symbol + channel": {"night": (16, 1), "day": (16, 1), "peak100": (64, 1)},
}
NIGHT_STATES = {"+ night carriers off*": pw.CARRIER_OFF, "+ night dormancy*": pw.DORMANT}
# ---------------------------------------------------------------------------------------

w = c.runs.set_index(["profile", "chains", "seed"])
seeds = range(1, c.SEEDS + 1)


def level_power(policy, level):
    """AAU power of a level, one value per seed [W]."""
    if level == "night" and policy in NIGHT_STATES:
        sent = np.array([w.loc[("night", 64, s), "sent"] for s in seeds])
        return NIGHT_STATES[policy] * c.W + ANCHOR_W_PER_MBPS * sent
    a, sym = POLICIES.get(policy, POLICIES["symbol + channel"])[level]
    return np.array([w.loc[(level, a, s), "watt_sym" if sym else "watt"] for s in seeds])


def energy(policy, hours):
    """Energy of the day, one value per seed [kWh]."""
    return sum(h * level_power(policy, l) for l, h in hours.items()) / 1000


def half_ci(v):
    return np.std(v, ddof=1) * c.T975 / np.sqrt(len(v))


names = list(POLICIES) + list(NIGHT_STATES)
if __name__ == "__main__":
    ref = energy("always on", HOURS)
    rows = []
    for n in names:
        e = energy(n, HOURS)
        s = 100 * (1 - e / ref)  # paired by seed
        rows.append(dict(policy=n, kWh_day=e.mean(), kWh_ci=half_ci(e), saving_pct=s.mean(), saving_ci=half_ci(s),
                         **{f"W_{l}": level_power(n, l).mean() for l in HOURS}))
    r = pd.DataFrame(rows).set_index("policy")
    r.to_csv(HERE / "daily.csv")
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(r.round(2).to_string())
    t = {k: {n: 100 * (1 - energy(n, dict(zip(HOURS, v))).mean() / energy("always on", dict(zip(HOURS, v))).mean())
             for n in names[1:]} for k, v in SENSITIVITY.items()}
    print("\nsaving % by hours night/day/peak\n", pd.DataFrame(t).T.round(1).to_string(), sep="")

    fig, ax = plt.subplots(figsize=(8, 4))
    cols = [ORANGE if n in NIGHT_STATES else BLUE for n in names]
    ax.barh(names[::-1], r.kWh_day[::-1], .6, color=cols[::-1], xerr=r.kWh_ci[::-1],
            error_kw=dict(ecolor=INK, lw=1, capsize=2))
    for n in names:
        ax.text(r.kWh_day[n] + r.kWh_ci[n] + .2, n, f"{r.kWh_day[n]:.1f} kWh"
                + (f"  (−{r.saving_pct[n]:.0f}%)" if n != "always on" else ""), va="center", fontsize=9, color=INK)
    ax.set(xlabel="AAU energy per day [kWh]", xlim=(0, 22),
           title=f"Energy of one day ({'/'.join(map(str, HOURS.values()))} h night/day/peak, assumed)")
    ax.grid(axis="y", visible=False)
    fig.tight_layout(rect=(0, .06, 1, 1))
    fig.text(.01, .01, "* night from the power formula only (no wake-up, no 4G QoS). 10 seeds; bars: 95% CI",
             fontsize=8, color=MUTED)
    fig.savefig(OUT / "daily_power.png", dpi=200, facecolor="white")
