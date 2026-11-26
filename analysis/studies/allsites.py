"""All sites with fewer chains: the neighbours use the same number of chains as cell 0 (bs-results-allsites, 32 and 16
chains) instead of 64 (main campaign). Same seeds, so same users and traffic: the only change is the neighbours' array
and transmit power, hence the interference in cell 0. 64 chains are the same run in both campaigns.
At peak, per-block SINR and first-transmission errors come from the rx traces; for neighbours at 64 they are taken from
the OFDMA/OFDMA runs of the mix campaign, which repeat the main peak runs with the traces on."""
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from studies.daily import half_ci

ALL = paths.RAW / "bs-results-allsites"
MIX = paths.RAW / "bs-results-mix" / "ofdma-ofdma"
PROFILES, CHAINS = ("night", "day", "peak100"), (32, 16)


def run(raw, prof, a, r):
    o = raw / f"{prof}_a{a}_r{r}"
    m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", c.DURATION)
    f = pd.read_csv(f"{o}_flows.csv")
    b = f[f.kind == "burst"]
    late = 0
    if prof == "peak100":
        s = pd.read_csv(f"{o}_segments.csv")
        s = s[s.sent == s.pkts]
        late = int(((s.rx < c.MIN_RX * s.pkts) | (s.last_rx_s - s.start_s > c.SEGMENT_S)).sum())
    out = dict(watt_sym=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * c.W, prb=100 * m["prb_load"],
               over=int((b.delay_p95_s * 1e3 > c.LIMIT_MS).sum()), users=len(b), late=late, loss=100 * m["loss"])
    rx = o.with_name(o.name + "_rx.csv")
    if rx.exists():
        x = pd.read_csv(rx)
        out |= dict(sinr=x.sinr_db_w.sum() / x.res.sum(), bler=100 * x.corrupt.sum() / x.tbs.sum())
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    rows = []
    for prof in PROFILES:
        for r in range(1, c.SEEDS + 1):
            ref = run(c.RAW, prof, 64, r)["watt_sym"]
            always_on = float(pw.piovesan(ns3data.summary(c.RAW / f"{prof}_a64_r{r}_slots.csv",
                                                          c.RAW / f"{prof}_a64_r{r}_flows.csv", c.DURATION)["prb_load"], 64)) * c.W
            for a in CHAINS:
                for nb, raw in (("64", c.RAW), ("same", ALL)):
                    d = run(raw, prof, a, r)
                    if prof == "peak100" and nb == "64":
                        d |= {k: v for k, v in run(MIX, prof, a, r).items() if k in ("sinr", "bler")}
                    rows.append(dict(profile=prof, chains=a, neighbours=nb, seed=r, saving=100 * (1 - d["watt_sym"] / always_on),
                                     **d))
            for nb in ("64",):
                d = run(c.RAW, prof, 64, r)
                if prof == "peak100":
                    d |= {k: v for k, v in run(MIX, prof, 64, r).items() if k in ("sinr", "bler")}
                rows.append(dict(profile=prof, chains=64, neighbours="64 (ref)", seed=r,
                                 saving=100 * (1 - d["watt_sym"] / always_on), **d))
    d = pd.DataFrame(rows)
    d.to_csv(paths.RESULTS / "allsites_runs.csv", index=False)
    g = d.groupby(["profile", "chains", "neighbours"], sort=False)
    t = g.agg(watt=("watt_sym", "mean"), saving=("saving", "mean"), prb=("prb", "mean"), over=("over", "sum"),
              users=("users", "sum"), late=("late", "sum"), loss=("loss", "mean"), sinr=("sinr", "mean"), bler=("bler", "mean"))
    t["saving_ci"] = g.saving.apply(half_ci)
    ref = t.xs("64 (ref)", level="neighbours").droplevel("chains")
    t["extra_pct"] = 100 * (t.over / t.users) - 100 * (ref.over / ref.users).reindex(t.index, level="profile").to_numpy()
    t["extra_late"] = t.late - ref.late.reindex(t.index, level="profile").to_numpy()
    t["qos_ok"] = (t.extra_pct <= 100 * c.MAX_EXTRA_USERS) & (t.extra_late <= 0) & (t.loss < 100 * c.MAX_LOSS)
    t.to_csv(paths.RESULTS / "allsites.csv")
    print(t.round(2).to_string())
    # paired differences, neighbours same - neighbours 64
    p = d[d.neighbours != "64 (ref)"].pivot_table(index=["profile", "chains", "seed"], columns="neighbours",
                                                  values=["watt_sym", "prb", "over", "sinr", "bler"])
    for v in ("watt_sym", "prb", "sinr", "bler"):
        if (v, "same") in p:
            diff = (p[(v, "same")] - p[(v, "64")]).groupby(level=["profile", "chains"])
            print(v, "same - 64:", {k: f"{x.mean():+.2f} ± {half_ci(x):.2f}" for k, x in diff if x.notna().all()})
