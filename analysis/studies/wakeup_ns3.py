"""Wake-up campaign (bs-results-wake): sleep simulated in NS-3, paired by seed with the main campaign.

Power: symbol shutdown as in campaign.py, minus the sleep time in the 'RF off' state (wakeup.py)."""
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from studies.daily import HOURS, energy, half_ci
from studies.wakeup import CASES, idle_watt

RAW = paths.RAW / "bs-results-wake"
SETTINGS = [("0.5", 20), ("5", 20), ("5", 160)]  # Tw [ms], SSB period [ms]
seeds = range(1, c.SEEDS + 1)
main = c.runs.set_index(["profile", "chains", "seed"])

rows, users, segs = [], [], []
for p, a in CASES.items():
    for tw, ssb in SETTINGS:
        for r in seeds:
            o = RAW / f"{p}_a{a}_t{tw}_s{ssb}_r{r}"
            if not o.with_name(o.name + "_flows.csv").exists():
                continue
            m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
            z = pd.read_csv(f"{o}_sleep.csv").iloc[0]
            f = z["sleep"] / z[["awake", "down", "sleep", "up"]].sum()
            watt = float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W - f * (idle_watt(a) - pw.CARRIER_OFF * c.W)
            key = dict(profile=p, tw=tw, ssb=ssb, seed=r)
            rows.append(dict(**key, asleep=100 * f, watt=watt, ref=main.loc[(p, a, r), "watt_sym"],
                             on=main.loc[(p, 64, r), "watt"], loss=100 * m["loss"],
                             ref_loss=100 * main.loc[(p, a, r), "loss"], violations=z.violations))
            users.append(pd.read_csv(f"{o}_flows.csv").assign(**key))
            if p.startswith("peak"):
                segs.append(pd.read_csv(f"{o}_segments.csv").assign(**key))
d = pd.DataFrame(rows)
u = pd.concat(users)
u = u[u.kind == "burst"].assign(p95_ms=lambda x: 1e3 * x.delay_p95_s)

if __name__ == "__main__":
    out = []
    for (p, tw, ssb), g in d.groupby(["profile", "tw", "ssb"], sort=False):
        x = u[(u.profile == p) & (u.tw == tw) & (u.ssb == ssb)]
        b = c.burst[(c.burst.profile == p) & (c.burst.chains == CASES[p])]
        extra = 100 * (1 - g.watt / g.ref)
        out.append(dict(profile=p, tw=tw, ssb=ssb, runs=len(g), asleep=g.asleep.mean(), asleep_ci=half_ci(g.asleep),
                        ref_W=g.ref.mean(), watt=g.watt.mean(), extra_pct=extra.mean(), extra_ci=half_ci(extra),
                        save_vs_on=(100 * (1 - g.watt / g.on)).mean(),
                        median_p95=x.p95_ms.median(), ref_median=b.p95_ms.median(),
                        over=int((x.p95_ms > c.LIMIT_MS).sum()), ref_over=int((b.p95_ms > c.LIMIT_MS).sum()), users=len(x),
                        loss=g.loss.mean(), ref_loss=g.ref_loss.mean(), violations=int(g.violations.sum())))
    r = pd.DataFrame(out)
    r["extra_users_pct"] = 100 * (r.over - r.ref_over) / r.users
    r.to_csv(paths.RESULTS / "wakeup_ns3.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(r.round(2).to_string(index=False))
    s = pd.concat(segs)
    s = s[s.sent == s.pkts]
    print("peak segments late:", int(((s.rx < c.MIN_RX * s.pkts) | (s.last_rx_s - s.start_s > c.SEGMENT_S)).sum()),
          "of", len(s), "| without sleep:",
          int(c.whole[(c.whole.profile == "peak100") & (c.whole.chains == 64)].late.sum()))

    # One day (kWh), 0.5 ms everywhere, or 5 ms / SSB 160 ms at night only
    def w(p, tw, ssb):
        return d[(d.profile == p) & (d.tw == tw) & (d.ssb == ssb)].sort_values("seed").watt.to_numpy()
    ref, best = energy("always on", HOURS), energy("symbol + channel", HOURS)
    plain = {p: main.xs((p, CASES[p]), level=("profile", "chains")).sort_index().watt_sym.to_numpy() for p in HOURS}
    for name, lv in (("0.5 ms everywhere", {p: w(p, "0.5", 20) for p in HOURS}),
                     ("0.5 ms at night only", {**plain, "night": w("night", "0.5", 20)}),
                     ("5 ms, SSB 160, night only", {**plain, "night": w("night", "5", 160)}),
                     ("5 ms, SSB 20, night only", {**plain, "night": w("night", "5", 20)})):
        e = sum(h * lv[p] for p, h in HOURS.items()) / 1000
        print(f"{name}: {e.mean():.2f} kWh, vs always on {(100 * (1 - e / ref)).mean():.1f} +/- "
              f"{half_ci(100 * (1 - e / ref)):.1f} %, vs symbol + channel {(100 * (1 - e / best)).mean():.1f} %")
