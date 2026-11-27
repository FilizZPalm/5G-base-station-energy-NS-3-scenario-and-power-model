"""The same simulated traffic through three power models (step 5 of docs/STEPS.md).

  Piovesan   our 5G AAU model (lib.power)
  EARTH      an older LTE model; here one sector of a three-sector site (2 of 6 transceivers), so its watts / 3.
             It has no number of chains: it can only express a symbol-like sleep.
  Bjornson   a massive-MIMO model: it has the number of antennas but no sleep.

Each model keeps the circuit parameters of its own paper. Radiated power: EARTH its own; Bjornson either our AAU
(104.9 W at 64 chains, as in Piovesan) or the paper's energy-efficient level (about 0.1 W per antenna, a result of its
optimisation, not a hardware limit). The point is to compare shapes and relative savings, not only watts.

Run from analysis/:  ../.venv/bin/python -m studies.models
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, paths, power
from lib.style import AQUA, BLUE, INK, MUTED, ORANGE, PROFILES, save
from studies.daily import HOURS, half_ci

# ASSUMPTIONS ------------------------------------------------------------------------------------------------------
K_USERS = 1               # SU-MIMO: one user per resource (a sensitivity with 10 is printed)
PTX_PER_ANTENNA_W = 0.1   # Bjornson Sec. VII: "around 100 mW/antenna" with zero forcing at the efficiency optimum
B_HZ = 60e6               # two 30 MHz carriers
# ------------------------------------------------------------------------------------------------------------------
OUR_PTX_PER_ANTENNA_W = power.PTX_MAX * power.P_PEAK_W / 64
BEST_CHAINS = {"night": 16, "day": 16, "peak100": 64}   # the best setting per level (step 2)
POLICIES = ("always on", "symbol", "channel", "symbol + channel")


def bjornson(load, rate_gbps, chains, k=K_USERS, ptx_per_antenna=OUR_PTX_PER_ANTENNA_W):
    return power.bjornson(load, rate_gbps, m=chains, k=k, b=B_HZ, ptx_w=ptx_per_antenna * chains)


# Each model: power [W] of the runs of one level (one row per seed), given the chains and whether it sleeps
def piovesan_w(runs, chains, sleep):
    return power.piovesan(runs.prb_load, chains, runs.pa_off if sleep else 0) * campaign.W


def earth_macro_w(runs, chains, sleep):
    return power.earth(runs.prb_load, "Macro", runs.pa_off if sleep else 0) / 3


def earth_rrh_w(runs, chains, sleep):
    return power.earth(runs.prb_load, "RRH", runs.pa_off if sleep else 0) / 3


def bjornson_w(runs, chains, sleep):
    return bjornson(runs.prb_load, runs.thr / 1e3, chains)


def bjornson_low_w(runs, chains, sleep):
    return bjornson(runs.prb_load, runs.thr / 1e3, chains, ptx_per_antenna=PTX_PER_ANTENNA_W)


MODELS = {"Piovesan": piovesan_w, "EARTH macro": earth_macro_w, "EARTH RRH": earth_rrh_w,
          "Bjornson": bjornson_w, "Bjornson, 0.1 W/ant.": bjornson_low_w}
FULL_LOAD_W = {"Piovesan": campaign.W, "EARTH macro": float(power.earth(1, "Macro")) / 3,
               "EARTH RRH": float(power.earth(1, "RRH")) / 3, "Bjornson": float(bjornson(1, 0.2, 64)),
               "Bjornson, 0.1 W/ant.": float(bjornson(1, 0.2, 64, ptx_per_antenna=PTX_PER_ANTENNA_W))}
ZERO_LOAD_W = {"Piovesan": float(power.piovesan(0)) * campaign.W, "EARTH macro": float(power.earth(0, "Macro")) / 3,
               "EARTH RRH": float(power.earth(0, "RRH")) / 3, "Bjornson": float(bjornson(0, 0, 64)),
               "Bjornson, 0.1 W/ant.": float(bjornson(0, 0, 64))}
CAN_SLEEP = {"Piovesan", "EARTH macro", "EARTH RRH"}
CAN_SWITCH_CHAINS = {"Piovesan", "Bjornson", "Bjornson, 0.1 W/ant."}


def runs_by_key():
    return campaign.runs.set_index(["profile", "chains", "seed"]).sort_index()


def watt(runs, model, profile, chains=64, sleep=False):
    """Power of one level, one value per seed [W]."""
    return np.asarray(MODELS[model](runs.loc[(profile, chains)], chains, sleep), float)


def policy_watt(runs, model, profile, policy):
    """Power of one level under a policy, applying only what the model can express."""
    sleep = "symbol" in policy and model in CAN_SLEEP
    chains = BEST_CHAINS[profile] if "channel" in policy and model in CAN_SWITCH_CHAINS else 64
    return watt(runs, model, profile, chains, sleep)


def plot(runs):
    """Always on: watts per level, and the same as a share of each model's full-load power."""
    colors = {"Piovesan": BLUE, "EARTH macro": ORANGE, "EARTH RRH": AQUA, "Bjornson": MUTED, "Bjornson, 0.1 W/ant.": "#a3a29c"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for k, model in enumerate(MODELS):
        x = np.arange(3) + (k - 2) * .17
        watts = np.array([watt(runs, model, p).mean() for p in PROFILES])
        share = 100 * watts / FULL_LOAD_W[model]
        axes[0].bar(x, watts, .15, color=colors[model], label=model)
        for xi, v in zip(x, watts):
            axes[0].text(xi, v + 8, f"{v:.0f}", ha="center", fontsize=6.5, color=INK)
        axes[1].bar(x, share, .15, color=colors[model])
        for xi, v in zip(x, share):
            axes[1].text(xi, v + 1, f"{v:.0f}", ha="center", fontsize=6.5, color=INK)
    axes[0].set(title="Always on, 64 chains: watts", ylabel="power [W]", ylim=(0, 880))
    axes[1].set(title="Same, as a share of each model's full load", ylabel="% of full-load power", ylim=(0, 105))
    for ax in axes:
        ax.set(xticks=range(3), xticklabels=PROFILES.values())
        ax.grid(axis="x", visible=False)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=5, frameon=False, fontsize=9)
    save(fig, "models.png", "EARTH: one LTE sector, 2 TRX. 10 seeds")


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_columns", 30)
    runs = runs_by_key()
    rows = []
    for model in MODELS:
        e_always_on = sum(h * policy_watt(runs, model, p, "always on") for p, h in HOURS.items()) / 1000
        for policy in POLICIES:
            expressible = (("symbol" not in policy) or model in CAN_SLEEP) and (("channel" not in policy) or model in CAN_SWITCH_CHAINS)
            e = sum(h * policy_watt(runs, model, p, policy) for p, h in HOURS.items()) / 1000    # kWh per seed
            saving = 100 * (1 - e / e_always_on)
            rows.append(dict(model=model, policy=policy, expressible=expressible, kWh_day=e.mean(),
                             saving_pct=saving.mean(), saving_ci=half_ci(saving),
                             **{p: policy_watt(runs, model, p, policy).mean() for p in HOURS}))
    table = pd.DataFrame(rows)
    table.to_csv(paths.RESULTS / "models.csv", index=False)
    print(table.round(2).to_string(index=False))

    print("\nzero load / full load:")
    for model in MODELS:
        z, full = ZERO_LOAD_W[model], FULL_LOAD_W[model]
        print(f"  {model}: {z:.0f} / {full:.0f} W = {100 * z / full:.0f} %")
    print("Bjornson K=10:", {p: round(float(np.mean(bjornson(runs.loc[(p, 64)].prb_load, runs.loc[(p, 64)].thr / 1e3, 64, 10))), 1)
                             for p in HOURS})
    z = float(power.piovesan(0)) * campaign.W
    print(f"P_BS per antenna for Bjornson to match Piovesan at zero load: {(z - float(bjornson(0, 0, 64)) + 64) / 64:.1f} W (paper: 1)")

    plot(runs)
