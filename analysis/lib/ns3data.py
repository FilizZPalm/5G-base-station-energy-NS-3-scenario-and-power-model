"""Turns the raw NS-3 outputs of one run into metrics: PRB load, idle PA time, QoS."""
import numpy as np
import pandas as pd

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
