"""Read the raw output of one NS-3 run and turn it into a few numbers: how busy the radio was, how long the power
amplifiers could sleep, and the quality of service.

Each run of bs-energy.cc writes (among others) two files for cell 0:
  <prefix>_slots.csv   one row per downlink slot and carrier: symbols and resource blocks available and used
  <prefix>_flows.csv   one row per user: packets and bytes sent and received, delay sum and 95th percentile

Timeline of a run: WARMUP seconds that are not measured, then the measured window, then a drain (0.5 s in the
campaigns) where no new traffic starts and queued data is still delivered. Slot numbers count from the start of the
simulation; the slot trace begins after the warm-up (slot 600) and the drain is cut off here.
"""
import numpy as np
import pandas as pd

WARMUP = 0.3      # s, not measured
SLOT = 0.5e-3     # s, one slot at 30 kHz subcarrier spacing (numerology 1)

# A power amplifier needs time to switch off and on again: 71 us in total (sleep mode 1), i.e. two symbols at
# 30 kHz. So an empty stretch of symbols saves two symbols less than its length.
TRANSITION_SYM = 2


def summary(slots_file, flows_file, duration):
    """All the metrics of one run, as a dict. duration: the measured window of the run [s] (10 in the campaigns).

    prb_load       share of the downlink resources (resource blocks x symbols) that carried data, both carriers
    pa_off         share of the downlink symbols in which the power amplifiers can sleep (symbol shutdown)
    empty_slots    share of slots with no data on either carrier
    idle_mean_ms   mean length of a stretch of empty slots [ms]
    idle_max_ms    longest stretch of empty slots [ms]
    ues_per_active_slot  users served in a slot that carries data, on average
    thr, sent      received and offered traffic [Mbit/s]
    delay, p95     mean packet delay and packet-weighted mean of the users' 95th-percentile delay [s]
    loss           share of packets lost
    """
    slots = pd.read_csv(slots_file)
    last_slot = round((WARMUP + duration) / SLOT)
    slots = slots[slots.slot < last_slot]                       # drop the drain
    flows = pd.read_csv(flows_file)

    # The two carriers share one multi-carrier power amplifier: it can sleep only in symbols where neither carrier
    # transmits. Data always starts right after the control symbol on both carriers, so the symbols in use on the
    # two carriers together are simply those of the busier one.
    per_slot = slots.groupby("slot").agg(used=("used_sym", "max"), avail=("avail_sym", "max"))
    sleeping_symbols = (per_slot.avail - per_slot.used - TRANSITION_SYM).clip(lower=0)

    # Stretches of consecutive empty slots (no data on either carrier). Uplink slots are not in the trace, but the
    # time they take is counted because the stretch is measured from its first to its last slot number.
    empty = per_slot.used == 0
    stretches = pd.DataFrame({"slot": per_slot.index, "empty": empty.values})
    stretches["id"] = (stretches["empty"] != stretches["empty"].shift()).cumsum()
    empty_stretches = stretches[stretches["empty"]].groupby("id").slot
    stretch_seconds = (empty_stretches.max() - empty_stretches.min() + 1) * SLOT

    users_in_active_slots = slots[slots.ues > 0].groupby("slot").ues.sum()
    received_packets = flows.rx_pkts.sum()

    return dict(
        prb_load=slots.used_reg.sum() / (slots.avail_rb * slots.avail_sym).sum(),
        pa_off=sleeping_symbols.sum() / (per_slot.avail + 1).sum(),  # +1: the control symbol, always transmitted
        empty_slots=empty.mean(),
        idle_mean_ms=stretch_seconds.mean() * 1e3 if len(stretch_seconds) else 0.0,
        idle_max_ms=stretch_seconds.max() * 1e3 if len(stretch_seconds) else 0.0,
        ues_per_active_slot=users_in_active_slots.mean() if len(users_in_active_slots) else 0.0,
        thr=flows.rx_bytes.sum() * 8e-6 / duration,
        delay=flows.delay_sum_s.sum() / received_packets if received_packets else np.nan,
        p95=np.average(flows.delay_p95_s, weights=flows.rx_pkts) if received_packets else np.nan,
        loss=1 - received_packets / flows.tx_pkts.sum() if len(flows) else 0.0,
        sent=flows.tx_bytes.sum() * 8e-6 / duration,
    )
