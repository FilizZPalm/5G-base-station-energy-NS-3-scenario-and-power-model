"""TDMA against OFDMA scheduling in all sites: power, idle PA time and QoS, paired by seed (same users and traffic)."""
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from studies.daily import HOURS, half_ci

RAW = {"ofdma": c.RAW, "tdma": paths.RAW / "bs-results-tdma"}
runs, users, segs = [], [], []
for sch, raw in RAW.items():
    for p in HOURS:
        for a in (64, 32, 16):
            for r in range(1, c.SEEDS + 1):
                o, key = f"{p}_a{a}_r{r}", dict(sch=sch, profile=p, chains=a, seed=r)
                m = ns3data.summary(raw / f"{o}_slots.csv", raw / f"{o}_flows.csv", c.DURATION)
                s = pd.read_csv(raw / f"{o}_slots.csv")
                busy = s[s.slot < round((ns3data.WARMUP + c.DURATION) / ns3data.SLOT)].groupby("slot").used_sym.max()
                runs.append(dict(**key, watt=float(pw.piovesan(m["prb_load"], a)) * c.W, used_sym=busy[busy > 0].mean(),
                                 watt_sym=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W, **m))
                users.append(pd.read_csv(raw / f"{o}_flows.csv").assign(**key))
                f = raw / f"{o}_segments.csv"
                if f.exists():
                    segs.append(pd.read_csv(f).assign(**key))
runs, users, segs = pd.DataFrame(runs), pd.concat(users), pd.concat(segs)
burst = users[users.kind == "burst"].assign(p95_ms=lambda u: u.delay_p95_s * 1e3)
whole = segs[segs.sent == segs.pkts]
whole = whole.assign(late=(whole.rx < c.MIN_RX * whole.pkts) | (whole.last_rx_s - whole.start_s > c.SEGMENT_S))
w = runs.set_index(["sch", "profile", "chains", "seed"]).sort_index()


def v(sch, p, a, col):
    return w.loc[(sch, p, a), col].to_numpy()


def q(x):
    return f"{x.mean():.2f}+-{half_ci(x):.2f}"


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 40)
    out = []
    for p in HOURS:
        for a in (64, 32, 16):
            # The comparison is paired only if both schedulers were offered the same traffic.
            assert np.allclose(v("ofdma", p, a, "sent"), v("tdma", p, a, "sent")), (p, a)
            for sch in RAW:
                g = lambda d: d[(d.sch == sch) & (d.profile == p) & (d.chains == a)]
                b, s = g(burst).p95_ms, g(whole)
                dw = v(sch, p, a, "watt_sym") - v("ofdma", p, a, "watt_sym")
                out.append(dict(profile=p, chains=a, sch=sch, watt=v(sch, p, a, "watt").mean(),
                                watt_sym=v(sch, p, a, "watt_sym").mean(), d_watt_sym=dw.mean(), d_ci=half_ci(dw),
                                saving=q(100 * (1 - v(sch, p, a, "watt_sym") / v("ofdma", p, 64, "watt"))),
                                pa_off=v(sch, p, a, "pa_off").mean(), empty=v(sch, p, a, "empty_slots").mean(),
                                used_sym=v(sch, p, a, "used_sym").mean(), prb=v(sch, p, a, "prb_load").mean(),
                                median_p95=b.median(), max_p95=b.max(), over=int((b > c.LIMIT_MS).sum()), users=len(b),
                                late=int(s.late.sum()), segs=len(s), loss=100 * v(sch, p, a, "loss").mean()))
    r = pd.DataFrame(out)
    r.to_csv(paths.RESULTS / "tdma.csv", index=False)
    print(r.round(3).to_string(index=False))

    print("\nDay energy [kWh], saving % against OFDMA always on (hours 8/12/4):")
    e = lambda sch, conf, col: sum(h * v(sch, p, a, col) for (p, h), a in zip(HOURS.items(), conf)) / 1e3
    ref = e("ofdma", (64, 64, 64), "watt")
    for name, conf, col in (("always on", (64, 64, 64), "watt"), ("symbol", (64, 64, 64), "watt_sym"),
                            ("symbol + channel", (16, 16, 64), "watt_sym")):
        o, t = e("ofdma", conf, col), e("tdma", conf, col)
        print(f"  {name}: OFDMA {o.mean():.2f} (-{q(100 * (1 - o / ref))}), TDMA {t.mean():.2f} (-{q(100 * (1 - t / ref))}), "
              f"TDMA against OFDMA {q(100 * (t / o - 1))} %")

    print("\nPeak, paired burst users over the limit:")
    k = ["chains", "seed", "ue"]
    b = burst[burst.profile == "peak100"].set_index(["sch"] + k).p95_ms
    j = pd.concat({s: b[s] for s in RAW}, axis=1)
    assert j.notna().all().all()
    for a in (64, 32, 16):
        x = j.loc[a]
        o, t = x.ofdma > c.LIMIT_MS, x.tdma > c.LIMIT_MS
        d = o.groupby("seed").sum() - t.groupby("seed").sum()
        print(f"  {a}: both {(o & t).sum()}, only OFDMA {(o & ~t).sum()}, only TDMA {(~o & t).sum()}, of {len(x)}; users with "
              f"lower p95 under TDMA {(x.tdma < x.ofdma).sum()}, higher {(x.tdma > x.ofdma).sum()}; seeds better/worse "
              f"{(d > 0).sum()}/{(d < 0).sum()}; quantiles 50/90 OFDMA {x.ofdma.quantile([.5, .9]).round(1).tolist()} "
              f"TDMA {x.tdma.quantile([.5, .9]).round(1).tolist()}")
    print(runs[runs.profile == "peak100"].assign(l=lambda x: 100 * x.loss).pivot(
        index=["chains", "sch"], columns="seed", values="l").round(2).to_string())
