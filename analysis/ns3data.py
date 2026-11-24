"""Turns raw NS-3 outputs into one table: (antennas, offered load) -> PRB load, idle PA time, QoS."""
import re
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "ns-3.46.1" / "bs-results"
WARMUP, DURATION, DRAIN, SLOT = 0.3, 1.5, 0.05, 0.5e-3
TRANSITION_SYM = 2  # 71 us (SM1, off + on) at 30 kHz SCS


def summary(slots_file, flows_file, duration=DURATION):
    s = pd.read_csv(slots_file)
    s = s[s.slot < round((WARMUP + duration) / SLOT)]           # drop the drain
    f = pd.read_csv(flows_file)
    # Both carriers share the MCPA: it can sleep only where neither transmits. Data starts
    # right after the control symbol on both, so the union of two blocks is the longer one.
    j = s.groupby("slot").agg(used=("used_sym", "max"), avail=("avail_sym", "max"))
    idle = (j.avail - j.used - TRANSITION_SYM).clip(lower=0)
    rx = f.rx_pkts.sum()
    # Idle periods: from first to last slot of each empty stretch on both carriers. UL slots
    # are not in the trace but the elapsed time across them is counted.
    empty = (j.used == 0)
    sl = pd.DataFrame({"slot": j.index, "empty": empty.values})
    sl["id"] = (sl["empty"] != sl["empty"].shift()).cumsum()
    e = sl[sl["empty"]].groupby("id").slot
    runs = (e.max() - e.min() + 1) * SLOT
    act = s[s.ues > 0].groupby("slot").ues.sum()
    return dict(prb_load=s.used_reg.sum() / (s.avail_rb * s.avail_sym).sum(),
                pa_off=idle.sum() / (j.avail + 1).sum(),        # +1: DL control, always on
                empty_slots=empty.mean(),
                idle_mean_ms=runs.mean() * 1e3 if len(runs) else 0.0,
                idle_max_ms=runs.max() * 1e3 if len(runs) else 0.0,
                ues_per_active_slot=act.mean() if len(act) else 0.0,
                thr=f.rx_bytes.sum() * 8e-6 / duration,
                delay=f.delay_sum_s.sum() / rx if rx else np.nan,
                p95=np.average(f.delay_p95_s, weights=f.rx_pkts) if rx else np.nan,
                loss=1 - rx / f.tx_pkts.sum() if len(f) else 0.0,
                sent=f.tx_bytes.sum() * 8e-6 / duration)


def one_run(slots_file):
    ant, off, run = map(float, re.match(r"a(\d+)_l([\d.]+)_r(\d+)_", slots_file.name).groups())
    flows_file = str(slots_file).replace("_slots", "_flows")
    return dict(ant=int(ant), offered=off, run=int(run), **summary(slots_file, flows_file))


def table():
    rows = [one_run(p) for p in sorted(RAW.glob("a*_r*_slots.csv")) if "part" not in p.name]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    t = table()
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(t.groupby(["ant", "offered"]).mean().round(4).drop(columns="run"))
    t.to_csv(Path(__file__).parent / "metrics.csv", index=False)
    print(t.groupby(["ant", "offered"]).size().to_string())
