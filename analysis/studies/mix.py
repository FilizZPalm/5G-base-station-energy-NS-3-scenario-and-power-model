"""Why TDMA serves the peak better: cell 0 and neighbour sites with OFDMA or TDMA, independently (2 x 2, paired by seed).

Every transport block received in cell 0 is traced (_tb.csv). Effects are averaged over the other factor:
cell-0 effect = mean over neighbour schedulers of (TDMA - OFDMA in cell 0), and the same for the neighbours."""
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import BLUE, CHAINS, INK, ORANGE, save
from studies.daily import half_ci
import matplotlib.pyplot as plt

RAW = paths.RAW / "bs-results-mix"
SCH = ("ofdma", "tdma")
rows = []
for c0 in SCH:
    for nb in SCH:
        for a in (64, 32, 16):
            for r in range(1, c.SEEDS + 1):
                o = RAW / f"{c0}-{nb}" / f"peak100_a{a}_r{r}"
                m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
                f = pd.read_csv(f"{o}_flows.csv")
                b = 1e3 * f[f.kind == "burst"].delay_p95_s
                s = pd.read_csv(f"{o}_segments.csv")
                s = s[s.sent == s.pkts]
                late = ((s.rx < c.MIN_RX * s.pkts) | (s.last_rx_s - s.start_s > c.SEGMENT_S)).sum()
                t = pd.read_csv(f"{o}_tb.csv")
                first = t[t.rv == 0]
                rows.append(dict(cell0=c0, neigh=nb, chains=a, seed=r,
                                 watt_sym=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W, pa_off=m["pa_off"],
                                 prb=m["prb_load"], delay_ms=1e3 * m["delay"], over=int((b > c.LIMIT_MS).sum()),
                                 late=int(late), loss=100 * m["loss"],
                                 retx=100 * (t.rv > 0).mean(),                   # blocks that are retransmissions
                                 bler=100 * first.corrupt.mean(),                # errors on first transmissions
                                 spread=(first.sinr_db - first.sinr_min_db).mean(),  # SINR in-block: mean - worst RB
                                 rbs=first.rbs.mean(), syms=first.syms.mean()))
d = pd.DataFrame(rows)
COLS = ["watt_sym", "pa_off", "prb", "delay_ms", "over", "late", "loss", "retx", "bler", "spread", "rbs", "syms"]

if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    g = d.groupby(["chains", "cell0", "neigh"], sort=False)
    out = g[COLS].mean()
    for k in ("over", "late"):
        out[k] = g[k].sum()  # users of 70, segments of 147
    out.to_csv(paths.RESULTS / "mix.csv")
    print(out.round(3).to_string())

    print("\nEffects, paired by seed (mean +- 95 % CI):")
    w = d.set_index(["chains", "seed", "cell0", "neigh"]).sort_index()
    eff = []
    for a in (64, 32, 16):
        x = w.loc[a]
        v = lambda c0, nb, k: x.xs((c0, nb), level=("cell0", "neigh"))[k].to_numpy()
        for k in ("watt_sym", "bler", "spread", "delay_ms", "loss", "over"):
            e = {"cell 0": (v("tdma", "ofdma", k) - v("ofdma", "ofdma", k) + v("tdma", "tdma", k) - v("ofdma", "tdma", k)) / 2,
                 "neighbours": (v("ofdma", "tdma", k) - v("ofdma", "ofdma", k) + v("tdma", "tdma", k) - v("tdma", "ofdma", k)) / 2,
                 "interaction": v("tdma", "tdma", k) - v("tdma", "ofdma", k) - v("ofdma", "tdma", k) + v("ofdma", "ofdma", k)}
            eff.append(dict(chains=a, metric=k, **{n: f"{e[n].mean():+.2f} +- {half_ci(e[n]):.2f}" for n in e}))
    print(pd.DataFrame(eff).to_string(index=False))

    # Figure: first-transmission errors and in-block SINR spread; colour = cell 0, hatching = neighbours with TDMA
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    combos = [(c0, nb) for c0 in SCH for nb in SCH]
    for ax, (k, lab, top) in zip(axes, (("bler", "blocks in error at first transmission [%]", 30),
                                        ("spread", "SINR in the block: mean - worst RB [dB]", 13))):
        for j, (c0, nb) in enumerate(combos):
            x = [i + (j - 1.5) * .2 for i in range(3)]
            y = [out.loc[(a, c0, nb), k] for a in CHAINS]
            ax.bar(x, y, .18, color=BLUE if c0 == "ofdma" else ORANGE, hatch="///" if nb == "tdma" else None,
                   edgecolor="white", lw=0, label=f"cell 0 {c0.upper()}, neighbours {nb.upper()}")
            for xi, yi in zip(x, y):
                ax.text(xi, yi + top / 80, f"{yi:.0f}" if k == "bler" else f"{yi:.1f}", ha="center", fontsize=7,
                        color=INK)
        ax.set(xticks=range(3), xticklabels=CHAINS, xlabel="active chains in cell 0", ylabel=lab, ylim=(0, top))
        ax.grid(axis="x", visible=False)
    axes[0].set_title("Peak: errors")
    axes[1].set_title("Peak: interference uneven in frequency")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=2, frameon=False, fontsize=8)
    save(fig, "mix.png", "10 seeds, paired. Hatched: neighbour sites with TDMA")
