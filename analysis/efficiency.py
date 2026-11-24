"""Energy efficiency (bit/Joule) of the AAU from the multi-seed campaign.

Delivered DL traffic of cell 0 (IP level, headers included) divided by AAU power, seed by seed.
Formula-only night states are left out: their traffic is carried by the 4G layer, not by the AAU."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import campaign as c
from daily import HOURS, POLICIES, energy, half_ci
from plots import BLUE, CHAINS, INK, MUTED, ORANGE, PROFILES, save

HERE = c.Path(__file__).parent
w = c.runs.set_index(["profile", "chains", "seed"]).sort_index()
seeds = range(1, c.SEEDS + 1)


def kbit_per_joule(profile, chains, sym):
    """One value per seed. Mbit/s / W = Mbit/J, hence the factor 1000."""
    r = w.loc[(profile, chains)]
    return (1e3 * r.thr / r["watt_sym" if sym else "watt"]).to_numpy()


def daily_kbit_per_joule(policy):
    """Delivered bits over the day / energy of the day, one value per seed."""
    bits = sum(h * 3600 * 1e6 * np.array([w.loc[(l, POLICIES[policy][l][0], s), "thr"] for s in seeds])
               for l, h in HOURS.items())
    return bits / (energy(policy, HOURS) * 3.6e6) / 1e3


if __name__ == "__main__":
    qos = pd.read_csv(HERE / "campaign.csv", index_col=["profile", "chains"])
    # Relative QoS criterion (users over the limit, loss); written by campaign.py
    ok = (qos.extra_users_pct <= 100 * c.MAX_EXTRA_USERS) & (qos.loss_pct < 100 * c.MAX_LOSS)
    rows = []
    for p in PROFILES:
        ref = kbit_per_joule(p, 64, 0)
        for a in CHAINS:
            for sym in (0, 1):
                v = kbit_per_joule(p, a, sym)
                gain = 100 * (v / ref - 1)  # paired by seed
                rows.append(dict(profile=p, chains=a, symbol=bool(sym), kbit_J=v.mean(), kbit_J_ci=half_ci(v),
                                 gain_pct=gain.mean(), gain_ci=half_ci(gain), qos_ok=bool(ok[(p, a)])))
    r = pd.DataFrame(rows)
    r.to_csv(HERE / "efficiency.csv", index=False)
    pd.set_option("display.width", 200)
    print(r.round(2).to_string(index=False))
    ref = daily_kbit_per_joule("always on")
    for n in POLICIES:
        v = daily_kbit_per_joule(n)
        g = 100 * (v / ref - 1)
        print(f"day total, {n}: {v.mean():.1f} +/- {half_ci(v):.1f} kbit/J, gain {g.mean():.1f} +/- {half_ci(g):.1f} %")

    # Different orders of magnitude: one y scale per profile
    fig, axes = plt.subplots(1, 3, figsize=(10, 4.2))
    for ax, (p, title) in zip(axes, PROFILES.items()):
        q = r[r.profile == p]
        top = (q.kbit_J + q.kbit_J_ci).max()
        for k, color in ((0, BLUE), (1, ORANGE)):
            s = q[q.symbol == bool(k)]
            x = np.arange(3) + (k - .5) * .4
            bars = ax.bar(x, s.kbit_J, .36, color=color, yerr=s.kbit_J_ci, error_kw=dict(ecolor=INK, lw=1, capsize=2))
            for b, xi, v, e, good in zip(bars, x, s.kbit_J, s.kbit_J_ci, s.qos_ok):
                if not good:
                    b.set_hatch("///")
                    b.set_edgecolor("white")
                ax.text(xi, v + e + .015 * top, f"{v:.1f}" if v < 10 else f"{v:.0f}", ha="center", fontsize=8, color=INK)
        ax.set(title=title, xticks=range(3), xticklabels=CHAINS, xlabel="active chains", ylim=(0, 1.15 * top))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("energy efficiency [kbit/J]")
    P = plt.Rectangle
    fig.legend([P((0, 0), 1, 1, color=BLUE), P((0, 0), 1, 1, color=ORANGE),
                P((0, 0), 1, 1, facecolor=MUTED, hatch="///", edgecolor="white")],
               ["without symbol", "with symbol", "QoS not acceptable"], loc="lower right", ncol=3, frameon=False, fontsize=9)
    save(fig, "efficiency.png", "10 seeds, 10 s; y scales differ; bars: 95% CI")
