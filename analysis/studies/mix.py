"""Why TDMA serves the peak better: cell 0 and neighbour sites with OFDMA or TDMA, independently (2 x 2, paired by seed).

Every transport block received in cell 0 is traced (_tb.csv). Effects are averaged over the other factor:
cell-0 effect = mean over neighbour schedulers of (TDMA - OFDMA in cell 0), and the same for the neighbours."""
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from studies.daily import half_ci

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
