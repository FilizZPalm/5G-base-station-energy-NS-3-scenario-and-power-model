"""Busier nights (5, 10, 15 Mbit/s, 2 UEs): power, QoS and sleep against the 1 Mbit/s night of the main campaign.

EARTH (Auer et al. 2011, Fig. 4) has a daily minimum of active users at 14 % of the maximum; our night is at 1 % of the
peak traffic. The quantities differ, so these nights are a sensitivity check, not a calibration."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import BLUE, INK, ORANGE, save
from studies.daily import HOURS, energy, half_ci
from studies.wakeup import idle_watt

RAW, WAKE, WAKE_MAIN = paths.RAW / "bs-results-night", paths.RAW / "bs-results-night-wake", paths.RAW / "bs-results-wake"
NIGHTS = {"night": 1, "night5": 5, "night10": 10, "night15": 15}  # name -> Mbit/s
SETTINGS = [("0.5", 20), ("5", 160)]  # Tw [ms], SSB period [ms]
seeds = range(1, c.SEEDS + 1)


def load(prefix):
    m = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", c.DURATION)
    f = pd.read_csv(f"{prefix}_flows.csv")
    return m, 1e3 * f[f.kind == "burst"].delay_p95_s.to_numpy()


rows, waits = [], []
for n in NIGHTS:
    for a in (64, 32, 16):
        for r in seeds:
            m, p95 = load((c.RAW if n == "night" else RAW) / f"{n}_a{a}_r{r}")
            rows.append(dict(night=n, chains=a, seed=r, p95=p95, thr=m["thr"], loss=100 * m["loss"], prb=m["prb_load"],
                             watt=float(pw.piovesan(m["prb_load"], a)) * c.W,
                             watt_sym=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W))
    for tw, ssb in SETTINGS:
        for r in seeds:
            o = (WAKE_MAIN if n == "night" else WAKE) / f"{n}_a16_t{tw}_s{ssb}_r{r}"
            m, p95 = load(o)
            z = pd.read_csv(f"{o}_sleep.csv").iloc[0]
            f = z["sleep"] / z[["awake", "down", "sleep", "up"]].sum()
            waits.append(dict(night=n, tw=tw, ssb=ssb, seed=r, asleep=100 * f, p95=p95, violations=z.violations,
                              watt=float(pw.piovesan(m["prb_load"], 16, m["pa_off"])) * c.W
                              - f * (idle_watt(16) - pw.CARRIER_OFF * c.W)))
d, s = pd.DataFrame(rows), pd.DataFrame(waits)


def over(x):
    v = np.concatenate(list(x.p95))
    return f"{int((v > c.LIMIT_MS).sum())}/{len(v)}", float(np.max(v))


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_columns", 30)
    out = []
    for (n, a), g in d.groupby(["night", "chains"], sort=False):
        ref = d[(d.night == n) & (d.chains == 64)].watt.to_numpy()
        o, mx = over(g)
        sv = 100 * (1 - g.watt_sym.to_numpy() / ref)
        out.append(dict(night=n, chains=a, thr=g.thr.mean(), prb=g.prb.mean(), watt=g.watt.mean(), watt_sym=g.watt_sym.mean(),
                        saving_sym=sv.mean(), saving_ci=half_ci(sv), over20=o, max_p95=mx, loss=g.loss.mean()))
    print(pd.DataFrame(out).round(2).to_string(index=False))
    out = []
    base = d[d.chains == 16].set_index(["night", "seed"]).watt_sym
    for (n, tw, ssb), g in s.groupby(["night", "tw", "ssb"], sort=False):
        ref = base[n].loc[g.seed].to_numpy()
        x = 100 * (1 - g.watt.to_numpy() / ref)
        o, mx = over(g)
        out.append(dict(night=n, tw=tw, ssb=ssb, asleep=g.asleep.mean(), watt=g.watt.mean(), extra=x.mean(), extra_ci=half_ci(x),
                        over20=o, max_p95=mx, violations=int(g.violations.sum())))
    w = pd.DataFrame(out)
    w.to_csv(paths.RESULTS / "night.csv", index=False)
    print(w.round(2).to_string(index=False))

    print("\nDay energy with each night (hours 8/12/4):")
    ev = {p: h for p, h in HOURS.items()}
    main = c.runs.set_index(["profile", "chains", "seed"])
    rest = lambda a_day, a_peak, col: sum(
        ev[p] * main.xs((p, a), level=("profile", "chains")).sort_index()[col].to_numpy() for p, a in (("day", a_day), ("peak100", a_peak)))
    for n in NIGHTS:
        x = d[d.night == n]
        g = lambda a, col: x[x.chains == a].sort_values("seed")[col].to_numpy()
        on = (8 * g(64, "watt") + rest(64, 64, "watt")) / 1e3
        best = (8 * g(16, "watt_sym") + rest(16, 64, "watt_sym")) / 1e3
        sl = (8 * s[(s.night == n) & (s.tw == "0.5")].sort_values("seed").watt.to_numpy() + rest(16, 64, "watt_sym")) / 1e3
        print(f"  {n}: always on {on.mean():.2f}, symbol + channel {best.mean():.2f} (-{(100 * (1 - best / on)).mean():.1f} %), "
              f"+ 0.5 ms sleep at night {sl.mean():.2f} (-{(100 * (1 - sl / on)).mean():.1f} +/- {half_ci(100 * (1 - sl / on)):.1f} %)")

    # Figure: extra saving of the sleep modes as the night gets busier
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    mbps = list(NIGHTS.values())
    for (tw, ssb), color, m, dy in zip(SETTINGS, (BLUE, ORANGE), ("o", "s"), (9, -16)):
        q = w[(w.tw == tw) & (w.ssb == ssb)].set_index("night").loc[list(NIGHTS)]
        ax.errorbar(mbps, q.extra, q.extra_ci, color=color, marker=m, ms=8, lw=2, capsize=2,
                    label=f"Tw {tw} ms, SSB every {ssb} ms")
        for x, y, a in zip(mbps, q.extra, q.asleep):
            ax.annotate(f"asleep {a:.0f}%", (x, y), xytext=(0, dy), textcoords="offset points", ha="center",
                        fontsize=8, color=INK)
    ax.set(xticks=mbps, xlabel="night traffic [Mbit/s], 2 users", ylabel="extra saving over symbol + channel [%]",
           ylim=(0, 22), title="Busier nights: what sleep still saves (16 chains)")
    ax.legend(frameon=False, loc="lower left")
    save(fig, "night_load.png", "RF off state, simulated in NS-3. 10 seeds; bars: 95% CI")
