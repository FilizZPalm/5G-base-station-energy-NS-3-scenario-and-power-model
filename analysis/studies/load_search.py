"""Peak load search (bs-results-load): which offered load do 64 chains sustain in each seed."""
import pandas as pd
from lib import ns3data, paths, power as pw

RAW = paths.RAW / "bs-results-load"
LOADS, SEEDS, DURATION, CHAINS = (80, 100, 120), 10, 10, 64
LIMIT_MS, SEGMENT_S, MIN_RX, MAX_LOSS = 20, 2.0, 0.99, 0.01  # ASSUMPTIONS

rows, users = [], []
for load in LOADS:
    for r in range(1, SEEDS + 1):
        o = RAW / f"peak{load}_a{CHAINS}_r{r}"
        m = ns3data.summary(f"{o}_slots.csv", f"{o}_flows.csv", DURATION)
        f = pd.read_csv(f"{o}_flows.csv")
        f["p95_ms"], f["loss"] = f.delay_p95_s * 1e3, 1 - f.rx_pkts / f.tx_pkts
        s = pd.read_csv(f"{o}_segments.csv")
        s = s[s.sent == s.pkts]  # whole segments only
        bad = (s.rx < MIN_RX * s.pkts) | (s.last_rx_s - s.start_s > SEGMENT_S)
        b = f[f.kind == "burst"]
        x = pd.read_csv(f"{o}_slots.csv")
        x = x[x.slot < round((ns3data.WARMUP + DURATION) / ns3data.SLOT)]
        g = x.assign(t=x.avail_rb * x.avail_sym).groupby("carrier")[["used_reg", "t"]].sum()
        rows.append(dict(load=load, seed=r, sent=m["sent"], thr=m["thr"], loss=m["loss"], pa_off=m["pa_off"],
                         prb0=g.used_reg[0] / g.t[0], prb1=g.used_reg[1] / g.t[1],
                         burst_over=int((b.p95_ms > LIMIT_MS).sum()), burst_max=b.p95_ms.max(),
                         video_bad=int(bad.sum()), segments=len(s),
                         video_bad_ues=str(sorted(s.ue[bad].unique().tolist())),
                         watt=float(pw.piovesan(m["prb_load"], CHAINS)) * pw.P_PEAK_W,
                         watt_sym=float(pw.piovesan(m["prb_load"], CHAINS, m["pa_off"])) * pw.P_PEAK_W))
        users.append(f.assign(load=load, seed=r))
d, users = pd.DataFrame(rows), pd.concat(users)
d["ok_loss"], d["ok_video"], d["ok_burst"] = d.loss < MAX_LOSS, d.video_bad == 0, d.burst_over == 0
d["ok"] = d.ok_loss & d.ok_video & d.ok_burst

if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(d.round(3).to_string(index=False))
    print(d.groupby("load")[["ok_loss", "ok_video", "ok_burst", "ok"]].sum())
    print(d.groupby("load")[["sent", "thr", "loss", "pa_off", "watt", "watt_sym", "burst_over",
                            "video_bad", "segments"]].agg("mean").round(3))
    b = users[users.kind == "burst"]
    print("burst users over limit", b[b.p95_ms > LIMIT_MS].groupby("load").size().to_dict(), "of",
          b.groupby("load").size().to_dict())
    bad = users[users.loss > MAX_LOSS]
    print(bad[["load", "seed", "ue", "kind", "loss", "p95_ms"]].round(3).to_string(index=False))
