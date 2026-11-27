"""Energy of one day, per sleep policy (step 3 of docs/STEPS.md).

A day is made of the three simulated levels: every hour is night, day or peak (8/12/4 h, an assumption). The energy
of the day is the sum of hours x power of the level, seed by seed; the saving is against 64 chains always on.

Policies (chains and symbol shutdown per level):
  always on          64 chains, no shutdown
  symbol             64 chains, power amplifiers off in empty symbols
  symbol + channel   16 chains at night and by day, 64 at peak, with symbol shutdown
and two that replace the night with a state from the power formula only (no wake-up time, no 4G QoS simulated):
  + night carriers off*   all carriers off at night, the 4G anchor carries the traffic
  + night dormancy*       deep dormancy at night

Run from analysis/:  ../.venv/bin/python -m studies.daily
Also imported by other studies for HOURS, POLICIES, energy() and half_ci().
"""
from functools import cache

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, paths, power
from lib.style import BLUE, INK, ORANGE, save

# ASSUMPTIONS ------------------------------------------------------------------------------------------------------
HOURS = {"night": 8, "day": 12, "peak100": 4}
# other splits of the day, night/day/peak hours, to see how much the result depends on them
SENSITIVITY = {"6/14/4": (6, 14, 4), "8/12/4 (base)": (8, 12, 4), "10/10/4": (10, 10, 4),
               "8/14/2": (8, 14, 2), "8/10/6": (8, 10, 6)}
# policy -> per level: (active chains, symbol shutdown 0/1)
POLICIES = {
    "always on": {"night": (64, 0), "day": (64, 0), "peak100": (64, 0)},
    "symbol": {"night": (64, 1), "day": (64, 1), "peak100": (64, 1)},
    "symbol + channel": {"night": (16, 1), "day": (16, 1), "peak100": (64, 1)},
}
# night states from the power formula only, in units of the peak power (the rest of the day as symbol + channel)
NIGHT_STATES = {"+ night carriers off*": power.CARRIER_OFF, "+ night dormancy*": power.DORMANT}
# ------------------------------------------------------------------------------------------------------------------

SEEDS = range(1, campaign.SEEDS + 1)


def half_ci(values):
    """Half width of the 95% confidence interval of the mean (Student t for the number of values)."""
    return np.std(values, ddof=1) * campaign.t975(len(values)) / np.sqrt(len(values))


@cache
def runs_by_key():
    """The main campaign runs, looked up by (level, chains, seed). Also used by studies.efficiency and
    studies.models."""
    return campaign.runs.set_index(["profile", "chains", "seed"]).sort_index()


def level_power(policy, level):
    """AAU power of one level under one policy, one value per seed [W]."""
    runs = runs_by_key()
    if level == "night" and policy in NIGHT_STATES:
        # the AAU is in the formula-only state; the 4G anchor carries the night traffic at ANCHOR_W_PER_MBPS
        sent = np.array([runs.loc[("night", 64, s), "sent"] for s in SEEDS])
        return NIGHT_STATES[policy] * campaign.W + power.ANCHOR_W_PER_MBPS * sent
    chains, symbol = POLICIES.get(policy, POLICIES["symbol + channel"])[level]
    column = "watt_sym" if symbol else "watt"
    return np.array([runs.loc[(level, chains, s), column] for s in SEEDS])


def energy(policy, hours):
    """Energy of one day, one value per seed [kWh]. hours: level -> hours per day."""
    return sum(h * level_power(policy, level) for level, h in hours.items()) / 1000


NAMES = list(POLICIES) + list(NIGHT_STATES)


DAILY_NOTE = "* night from the power formula only (no wake-up, no 4G QoS). 10 seeds; bars: 95% CI"


def plot(table, names=None, formula_only=NIGHT_STATES, filename="daily_power.png", note=DAILY_NOTE):
    """Horizontal bars: energy of the day per policy, with the saving. table: indexed by policy, with kWh_day, kWh_ci
    and saving_pct. Policies in formula_only are drawn in orange. Also used by studies.final."""
    names = NAMES if names is None else names
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = [ORANGE if n in formula_only else BLUE for n in names]
    ax.barh(names[::-1], table.kWh_day[names][::-1], .6, color=colors[::-1], xerr=table.kWh_ci[names][::-1],
            error_kw=dict(ecolor=INK, lw=1, capsize=2))
    for n in names:
        label = f"{table.kWh_day[n]:.1f} kWh" + (f"  (−{table.saving_pct[n]:.0f}%)" if n != "always on" else "")
        ax.text(table.kWh_day[n] + table.kWh_ci[n] + .2, n, label, va="center", fontsize=9, color=INK)
    ax.set(xlabel="AAU energy per day [kWh]", xlim=(0, 22),
           title=f"Energy of one day ({'/'.join(map(str, HOURS.values()))} h night/day/peak, assumed)")
    ax.grid(axis="y", visible=False)
    save(fig, filename, note)


if __name__ == "__main__":
    reference = energy("always on", HOURS)
    rows = []
    for n in NAMES:
        e = energy(n, HOURS)
        saving = 100 * (1 - e / reference)   # paired by seed
        rows.append(dict(policy=n, kWh_day=e.mean(), kWh_ci=half_ci(e), saving_pct=saving.mean(),
                         saving_ci=half_ci(saving), **{f"W_{level}": level_power(n, level).mean() for level in HOURS}))
    table = pd.DataFrame(rows).set_index("policy")
    table.to_csv(paths.RESULTS / "daily.csv")
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(table.round(2).to_string())

    # saving with other splits of the day
    sensitivity = {}
    for split, hours in SENSITIVITY.items():
        h = dict(zip(HOURS, hours))
        sensitivity[split] = {n: 100 * (1 - energy(n, h).mean() / energy("always on", h).mean()) for n in NAMES[1:]}
    print("\nsaving % by hours night/day/peak\n", pd.DataFrame(sensitivity).T.round(1).to_string(), sep="")

    plot(table)
