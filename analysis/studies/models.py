"""Same campaign runs, three power models: Piovesan (5G AAU), EARTH (LTE) and Bjornson (massive MIMO).

EARTH is one sector of the three-sector LTE site (2 of 6 TRX) and has no number of chains: it can express
symbol-like sleep only. Bjornson has the number of antennas but no sleep. Circuit parameters are those of
each paper. Radiated power: EARTH its own; Bjornson either our AAU (104.9 W at 64 chains, same as Piovesan)
or the paper's EE-optimal level (about 0.1 W per antenna, a result of its optimization, not a hardware limit).
Shapes and relative savings are compared, not only watts."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, paths, power as pw
from studies.daily import HOURS, half_ci
from lib.style import AQUA, BLUE, CHAINS, INK, MUTED, ORANGE, PROFILES, save

K_USERS = 1  # ASSUMPTION: SU-MIMO, one UE per resource (sensitivity with 10 below)
PTX_PER_ANTENNA_W = 0.1  # Bjornson Sec. VII: "around 100 mW/antenna" with ZF at the EE optimum
B_HZ = 60e6  # two 30 MHz carriers
w = c.runs.set_index(["profile", "chains", "seed"]).sort_index()


def bjornson(load, rate, m, k=K_USERS, ptx_per_antenna=pw.PTX_MAX * pw.P_PEAK_W / 64):
    return pw.bjornson(load, rate, m=m, k=k, b=B_HZ, ptx_w=ptx_per_antenna * m)


MODELS = {  # name -> f(run, chains, sleep) [W], one run per seed
    "Piovesan": lambda r, a, s: pw.piovesan(r.prb_load, a, r.pa_off if s else 0) * c.W,
    "EARTH macro": lambda r, a, s: pw.earth(r.prb_load, "Macro", r.pa_off if s else 0) / 3,
    "EARTH RRH": lambda r, a, s: pw.earth(r.prb_load, "RRH", r.pa_off if s else 0) / 3,
    "Bjornson": lambda r, a, s: bjornson(r.prb_load, r.thr / 1e3, a),
    "Bjornson, 0.1 W/ant.": lambda r, a, s: bjornson(r.prb_load, r.thr / 1e3, a, ptx_per_antenna=PTX_PER_ANTENNA_W),
}
FULL = {"Piovesan": c.W, "EARTH macro": float(pw.earth(1, "Macro")) / 3, "EARTH RRH": float(pw.earth(1, "RRH")) / 3,
        "Bjornson": float(bjornson(1, 0.2, 64)),
        "Bjornson, 0.1 W/ant.": float(bjornson(1, 0.2, 64, ptx_per_antenna=PTX_PER_ANTENNA_W))}
CAN_SLEEP = {"Piovesan", "EARTH macro", "EARTH RRH"}
CAN_CHANNEL = {"Piovesan", "Bjornson", "Bjornson, 0.1 W/ant."}
BEST = {"night": 16, "day": 16, "peak100": 64}


def watt(name, profile, chains=64, sleep=False):
    return np.asarray(MODELS[name](w.loc[(profile, chains)], chains, sleep), float)


def policy_watt(name, profile, policy):
    """symbol + channel as far as the model can express them."""
    sleep = "symbol" in policy and name in CAN_SLEEP
    a = BEST[profile] if "channel" in policy and name in CAN_CHANNEL else 64
    return watt(name, profile, a, sleep)


POLICIES = ("always on", "symbol", "channel", "symbol + channel")


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_columns", 30)
    rows = []
    for n in MODELS:
        e0 = sum(h * policy_watt(n, p, "always on") for p, h in HOURS.items()) / 1000
        for pol in POLICIES:
            ok = (("symbol" not in pol) or n in CAN_SLEEP) and (("channel" not in pol) or n in CAN_CHANNEL)
            e = sum(h * policy_watt(n, p, pol) for p, h in HOURS.items()) / 1000
            rows.append(dict(model=n, policy=pol, expressible=ok, kWh_day=e.mean(),
                             saving_pct=(100 * (1 - e / e0)).mean(), saving_ci=half_ci(100 * (1 - e / e0)),
                             **{p: policy_watt(n, p, pol).mean() for p in HOURS}))
    r = pd.DataFrame(rows)
    r.to_csv(paths.RESULTS / "models.csv", index=False)
    print(r.round(2).to_string(index=False))
    print("\nzero load / full load:")
    for n in MODELS:
        z = {"Piovesan": float(pw.piovesan(0)) * c.W, "EARTH macro": float(pw.earth(0, "Macro")) / 3,
             "EARTH RRH": float(pw.earth(0, "RRH")) / 3, "Bjornson": float(bjornson(0, 0, 64)), "Bjornson, 0.1 W/ant.": float(bjornson(0, 0, 64))}[n]
        print(f"  {n}: {z:.0f} / {FULL[n]:.0f} W = {100 * z / FULL[n]:.0f} %")
    print("Bjornson K=10:", {p: round(float(np.mean(bjornson(w.loc[(p, 64)].prb_load, w.loc[(p, 64)].thr / 1e3, 64, 10))), 1) for p in HOURS})
    z = float(pw.piovesan(0)) * c.W
    print(f"P_BS per antenna for Bjornson to match Piovesan at zero load: {(z - float(bjornson(0, 0, 64)) + 64) / 64:.1f} W (paper: 1)")

    colors = {"Piovesan": BLUE, "EARTH macro": ORANGE, "EARTH RRH": AQUA, "Bjornson": MUTED, "Bjornson, 0.1 W/ant.": "#a3a29c"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for k, n in enumerate(MODELS):
        y = np.array([watt(n, p).mean() for p in PROFILES])
        axes[0].bar(np.arange(3) + (k - 2) * .17, y, .15, color=colors[n], label=n)
        for xi, v in zip(np.arange(3) + (k - 2) * .17, y):
            axes[0].text(xi, v + 8, f"{v:.0f}", ha="center", fontsize=6.5, color=INK)
        axes[1].bar(np.arange(3) + (k - 2) * .17, 100 * y / FULL[n], .15, color=colors[n])
        for xi, v in zip(np.arange(3) + (k - 2) * .17, 100 * y / FULL[n]):
            axes[1].text(xi, v + 1, f"{v:.0f}", ha="center", fontsize=6.5, color=INK)
    axes[0].set(title="Always on, 64 chains: watts", ylabel="power [W]", ylim=(0, 880))
    axes[1].set(title="Same, as a share of each model's full load", ylabel="% of full-load power", ylim=(0, 105))
    for ax in axes:
        ax.set(xticks=range(3), xticklabels=PROFILES.values())
        ax.grid(axis="x", visible=False)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=5, frameon=False, fontsize=9)
    save(fig, "models.png", "EARTH: one LTE sector, 2 TRX. 10 seeds")
