"""Peak load search: how much traffic can a cell with all 64 chains carry?

Step 1 of docs/STEPS.md. Before choosing the peak level, the peak profile (3 video users + 7 burst users) was
simulated at 80, 100 and 120 Mbit/s with 64 chains, 10 seeds each (campaign bs-results-load). For every run this
script checks three things:

  - losses: under 1% of the packets lost;
  - video:  every complete video segment arrives in time (99% of its packets within 2 s);
  - bursts: no burst user has a 95th-percentile delay above 20 ms.

A load is a good peak level if most seeds pass all three. Run from analysis/:  ../.venv/bin/python -m studies.load_search
"""
import pandas as pd

from lib import ns3data, paths, power

RAW_FOLDER = paths.RAW / "bs-results-load"
LOADS_MBPS = (80, 100, 120)
SEEDS = range(1, 11)
SIMULATED_SECONDS = 10
CHAINS = 64

# ASSUMPTIONS: the QoS limits (the same as in lib/campaign.py)
DELAY_LIMIT_MS = 20      # a burst user is "over the limit" if its p95 delay is above this
SEGMENT_DEADLINE_S = 2.0  # a video segment must be received within this time ...
SEGMENT_MIN_SHARE = 0.99  # ... with at least this share of its packets
MAX_LOSS = 0.01           # at most 1% of the packets lost


def late_segments(segments):
    """Video segments that arrived incomplete or too late. Segments cut by the start or the end of the run
    (not all packets sent) are ignored."""
    complete = segments[segments.sent == segments.pkts]
    incomplete = complete.rx < SEGMENT_MIN_SHARE * complete.pkts
    too_slow = complete.last_rx_s - complete.start_s > SEGMENT_DEADLINE_S
    return complete[incomplete | too_slow], len(complete)


def prb_load_per_carrier(slots_file):
    """Share of the resource blocks used on each of the two carriers, over the measured window."""
    slots = pd.read_csv(slots_file)
    end_slot = round((ns3data.WARMUP + SIMULATED_SECONDS) / ns3data.SLOT)
    slots = slots[slots.slot < end_slot]                       # drop the drain at the end of the run
    slots = slots.assign(available=slots.avail_rb * slots.avail_sym)
    per_carrier = slots.groupby("carrier")[["used_reg", "available"]].sum()
    return per_carrier.used_reg / per_carrier.available


def analyse_run(load, seed):
    """One NS-3 run -> one row of results, and the table of its users."""
    prefix = RAW_FOLDER / f"peak{load}_a{CHAINS}_r{seed}"
    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", SIMULATED_SECONDS)

    users = pd.read_csv(f"{prefix}_flows.csv")
    users["p95_ms"] = users.delay_p95_s * 1000
    users["loss"] = 1 - users.rx_pkts / users.tx_pkts
    burst_users = users[users.kind == "burst"]

    late, n_segments = late_segments(pd.read_csv(f"{prefix}_segments.csv"))
    prb = prb_load_per_carrier(f"{prefix}_slots.csv")

    # Piovesan model, in watt: without and with symbol shutdown (PAs off in empty symbols)
    watt = float(power.piovesan(metrics["prb_load"], CHAINS)) * power.P_PEAK_W
    watt_symbol = float(power.piovesan(metrics["prb_load"], CHAINS, metrics["pa_off"])) * power.P_PEAK_W

    row = dict(
        load=load,
        seed=seed,
        sent=metrics["sent"],                 # offered traffic [Mbit/s]
        thr=metrics["thr"],                   # received traffic [Mbit/s]
        loss=metrics["loss"],
        pa_off=metrics["pa_off"],             # share of time the PAs can sleep
        prb0=prb[0],
        prb1=prb[1],
        burst_over=int((burst_users.p95_ms > DELAY_LIMIT_MS).sum()),
        burst_max=burst_users.p95_ms.max(),
        video_bad=len(late),
        segments=n_segments,
        video_bad_ues=str(sorted(late.ue.unique().tolist())),
        watt=watt,
        watt_sym=watt_symbol,
    )
    return row, users.assign(load=load, seed=seed)


def run_all():
    rows, users = [], []
    for load in LOADS_MBPS:
        for seed in SEEDS:
            row, run_users = analyse_run(load, seed)
            rows.append(row)
            users.append(run_users)
    runs = pd.DataFrame(rows)
    runs["ok_loss"] = runs.loss < MAX_LOSS
    runs["ok_video"] = runs.video_bad == 0
    runs["ok_burst"] = runs.burst_over == 0
    runs["ok"] = runs.ok_loss & runs.ok_video & runs.ok_burst
    return runs, pd.concat(users)


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    runs, users = run_all()

    print(runs.round(3).to_string(index=False))

    print(runs.groupby("load")[["ok_loss", "ok_video", "ok_burst", "ok"]].sum())   # seeds that pass, per load

    means = ["sent", "thr", "loss", "pa_off", "watt", "watt_sym", "burst_over", "video_bad", "segments"]
    print(runs.groupby("load")[means].agg("mean").round(3))

    burst_users = users[users.kind == "burst"]
    over = burst_users[burst_users.p95_ms > DELAY_LIMIT_MS]
    print("burst users over limit", over.groupby("load").size().to_dict(), "of",
          burst_users.groupby("load").size().to_dict())

    lossy = users[users.loss > MAX_LOSS]
    print(lossy[["load", "seed", "ue", "kind", "loss", "p95_ms"]].round(3).to_string(index=False))
