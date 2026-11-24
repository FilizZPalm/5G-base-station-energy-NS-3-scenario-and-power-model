"""Traffic profile x sleep mode (SU-MIMO scenario) -> AAU power and delay, from the single-seed test runs.

Cell 0 uses 64, 32 or 16 chains, the other sites always 64. Carrier shutdown and deep dormancy
come from the power formula only: no NS-3 run, wake-up time or 4G QoS is considered."""
from pathlib import Path
import pandas as pd
import ns3data
import power as pw

RAW = ns3data.RAW.parent / "bs-results-test" / "sumimo"
W = pw.P_PEAK_W
ANCHOR_W_PER_MBPS = 1.0  # ASSUMPTION: extra 4G power (Uitto: 160 W idle -> 170 W at 10 Mbit/s)

rows = []
for prof in ("night", "day", "peak", "peak150"):
    for a in (64, 32, 16):
        tag = f"{prof}_a{a}"
        m = ns3data.summary(RAW / f"{tag}_slots.csv", RAW / f"{tag}_flows.csv")
        on = float(pw.piovesan(m["prb_load"], a)) * W
        sym = float(pw.piovesan(m["prb_load"], a, m["pa_off"])) * W
        rows += [dict(profile=prof, state=f"{a} chains", watt=on, **m),
                 dict(profile=prof, state=f"{a} chains + symbol", watt=sym, **m)]
    if prof == "night":
        mbps = rows[-6]["sent"]
        for n, p in (("all carriers off", pw.CARRIER_OFF), ("deep dormancy", pw.DORMANT)):
            rows.append(dict(profile=prof, state=n, watt=p * W + ANCHOR_W_PER_MBPS * mbps, sent=mbps))

d = pd.DataFrame(rows)
d["saving_%"] = 100 * (1 - d.watt / d.groupby("profile").watt.transform("first"))
d["delay_ms"], d["p95_ms"] = d.delay * 1e3, d.p95 * 1e3
d = d[["profile", "state", "watt", "saving_%", "prb_load", "pa_off", "sent", "delay_ms", "p95_ms", "loss"]]
d.to_csv(Path(__file__).parent / "profiles.csv", index=False)
print(d.round(4).to_string(index=False))
