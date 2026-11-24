"""NS-3 metrics -> AAU power over an assumed 24 h profile, with cumulative sleep policies.
Seed 1 only, the one with a (nearly) complete grid. No QoS evaluation here."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import ns3data
import power as pw

HERE = Path(__file__).resolve().parent
(HERE / "figures").mkdir(exist_ok=True)
W = pw.P_PEAK_W
STEP_H = 0.25
# ASSUMPTIONS ---------------------------------------------------------------------------
PROFILE = np.array([.12, .06, .03, .015, .012, .015, .04, .12, .25, .38, .46, .52,   # 0-11 h
                    .55, .55, .52, .50, .52, .58, .68, .80, .95, 1., .75, .35])      # 12-23 h
PEAK_MBPS = 80.0
THR_32, THR_16 = 0.30, 0.15     # PRB load, measured in the previous step
THR_CARRIER = 5.0               # Mbit/s: all carriers off, traffic on the 4G layer
THR_DORMANT, DORMANT_STEPS = 2.0, 4
ANCHOR_W_PER_MBPS = 1.0         # extra 4G power (Uitto: 160 W idle -> 170 W at 10 Mbit/s)
# ---------------------------------------------------------------------------------------

t = ns3data.table()
t = t[(t.run == 1) & (t.offered <= 100)]
g = {a: d.sort_values("sent") for a, d in t.groupby("ant")}


def radio(a, col, x):
    return np.interp(x, g[a].sent, g[a][col])


h = np.arange(0, 24, STEP_H)
mbps = np.interp(h, np.arange(25), np.append(PROFILE, PROFILE[0])) * PEAK_MBPS
prev = np.roll(mbps, 1)                          # reactive: last measured step (periodic day)


def states(opts):
    s = np.full(len(h), "64", dtype=object)
    if "channel" in opts:
        l = radio(64, "prb_load", prev)
        s[l < THR_32] = "32"
        s[l < THR_16] = "16"
    if "carrier" in opts:
        s[prev < THR_CARRIER] = "off"
    if "dormancy" in opts:
        low = prev < THR_DORMANT
        for i in range(len(h)):
            if all(low[(i - k) % len(h)] for k in range(DORMANT_STEPS)):
                s[i] = "dormant"
    return s


def power(opts):
    s, p = states(opts), np.zeros(len(h))
    for i, (st, x) in enumerate(zip(s, mbps)):
        if st in ("off", "dormant"):
            p[i] = (pw.CARRIER_OFF if st == "off" else pw.DORMANT) * W + ANCHOR_W_PER_MBPS * x
        else:
            a = int(st)
            off = radio(a, "pa_off", x) if "symbol" in opts else 0
            p[i] = float(pw.piovesan(radio(a, "prb_load", x), a, off)) * W
    return s, p


POL = {"always on": (), "symbol": ("symbol",), "+ channel": ("symbol", "channel"),
       "+ carrier (all off)": ("symbol", "channel", "carrier"),
       "+ dormancy": ("symbol", "channel", "carrier", "dormancy")}
out, series = [], {}
for n, o in POL.items():
    s, p = power(o)
    series[n] = p
    out.append(dict(policy=n, mean_W=p.mean(), kWh_day=p.sum() * STEP_H / 1000,
                    **{k: (s == k).mean() * 24 for k in ("64", "32", "16", "off", "dormant")}))
r = pd.DataFrame(out).set_index("policy")
r.insert(2, "saving_%", 100 * (1 - r.kWh_day / r.kWh_day.iloc[0]))
r.to_csv(HERE / "daily.csv")
print(r.round(2).to_string())
print("columns 64..dormant: hours per day. One of two carriers off, zero load: "
      f"{float(pw.piovesan(0)) * W:.0f} W, unchanged (shared MCPA, T=1)")

C = ["#52514e", "#2a78d6", "#1baf7a", "#eda100", "#4a3aa7"]
fig, ax = plt.subplots(2, 1, figsize=(8, 6), sharex=True, height_ratios=[1, 2.2])
ax[0].plot(h, mbps, c="#52514e"); ax[0].set_ylabel("traffic [Mbit/s]")
for (n, p), c in zip(series.items(), C):
    ax[1].step(h, p, where="post", c=c, lw=1.8, label=n)
ax[1].set(ylabel="AAU power [W]\n(incl. extra 4G power)", xlabel="hour", ylim=(0, None), xticks=range(0, 25, 3))
ax[1].legend(frameon=False, ncols=2)
for a in ax:
    a.grid(alpha=.25); a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig(HERE / "figures" / "daily_power.png", dpi=150)
