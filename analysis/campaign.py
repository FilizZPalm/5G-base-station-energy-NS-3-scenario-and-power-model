"""Multi-seed campaign (bs-results-seg): AAU power and QoS per profile and chains, mean and 95% CI over seeds.

The same seed gives the same UE drop and traffic for every number of chains, so savings are paired."""
from pathlib import Path
import numpy as np
import pandas as pd
import ns3data
import power as pw

RAW = ns3data.RAW.parent / "bs-results-seg"
DURATION, SEEDS, W = 10, 10, pw.P_PEAK_W
LIMIT_MS, SEGMENT_S = 20, 2.0  # ASSUMPTIONS: burst p95 limit, segment deadline
MIN_RX = 0.99  # ASSUMPTION: a segment is usable with 99% of its packets (no retransmission over UDP)
T975 = 2.262  # Student t, 9 degrees of freedom

runs, users, segs = [], [], []
for prof in ("night", "day", "peak150"):
    for a in (64, 32, 16):
        for r in range(1, SEEDS + 1):
            o = f"{prof}_a{a}_r{r}"
            key = dict(profile=prof, chains=a, seed=r)
            m = ns3data.summary(RAW / f"{o}_slots.csv", RAW / f"{o}_flows.csv", DURATION)
            runs.append(dict(**key, watt=float(pw.piovesan(m["prb_load"], a)) * W,
                             watt_sym=float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * W, **m))
            users.append(pd.read_csv(RAW / f"{o}_flows.csv").assign(**key))
            p = RAW / f"{o}_segments.csv"
            if p.exists():
                segs.append(pd.read_csv(p).assign(**key))
runs, users, segs = pd.DataFrame(runs), pd.concat(users), pd.concat(segs)
base = runs[runs.chains == 64].set_index(["profile", "seed"]).watt
b = [base[(p, s)] for p, s in zip(runs.profile, runs.seed)]
runs["save"], runs["save_sym"] = 100 * (1 - runs.watt / b), 100 * (1 - runs.watt_sym / b)
runs["loss_pct"] = 100 * runs.loss
users["p95_ms"] = users.delay_p95_s * 1e3
burst = users[users.kind == "burst"]
whole = segs[segs.sent == segs.pkts]  # segments cut by the start or the end are dropped
whole = whole.assign(complete=whole.rx >= MIN_RX * whole.pkts, time_s=whole.last_rx_s - whole.start_s)
whole["late"] = ~whole.complete | (whole.time_s > SEGMENT_S)

if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    k = ["profile", "chains"]
    g = runs.groupby(k)
    cols = ["watt", "watt_sym", "save", "save_sym", "prb_load", "pa_off", "sent", "thr", "loss_pct"]
    mean, ci = g[cols].mean(), g[cols].std() * T975 / np.sqrt(SEEDS)
    out = mean.join(ci.add_suffix("_ci"))
    q = burst.groupby(k).p95_ms
    out["burst_median_ms"], out["burst_p95user_ms"], out["burst_max_ms"] = q.median(), q.quantile(.95), q.max()
    out["users"], out["users_over"] = q.size(), burst[burst.p95_ms > LIMIT_MS].groupby(k).size()
    out["users_over"] = out.users_over.fillna(0).astype(int)
    out["seeds_over"] = burst[burst.p95_ms > LIMIT_MS].groupby(k).seed.nunique()
    out["seeds_over"] = out.seeds_over.fillna(0).astype(int)
    s = whole.groupby(k)
    out["segments"], out["segments_late"], out["segment_max_s"] = s.size(), s.late.sum(), s.time_s.max()
    out["video_seeds_late"] = whole[whole.late].groupby(k).seed.nunique()
    out.to_csv(Path(__file__).parent / "campaign.csv")
    print(out.round(3).T.to_string())
    print(burst[burst.profile == "peak150"].groupby(["chains", "seed"]).p95_ms.max().unstack())
    print(runs[runs.profile == "peak150"].pivot(index="chains", columns="seed", values="loss_pct").round(2))
    print(whole[whole.late].groupby(["chains", "seed", "ue"]).size())
