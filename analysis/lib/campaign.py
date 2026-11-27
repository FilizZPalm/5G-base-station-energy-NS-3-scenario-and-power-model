"""The main campaign (bs-results-main): night, day and peak, each with 64, 32 and 16 chains, 10 seeds = 90 runs.

This module has two jobs:
  1. it holds the QoS criterion and the constants every study shares (limits, seeds, peak power);
  2. it loads the 90 runs into tables, the first time a study asks for them:
       runs   one row per run: power with and without symbol shutdown, saving, PRB load, losses ...
       users  one row per user and run (from the flows files)
       burst  the burst users only, with their 95th-percentile delay in ms (p95_ms)
       segs   one row per video segment and run (peak only)
       whole  the complete video segments, with late = arrived incomplete or after the deadline

The same seed gives the same user positions and traffic for every number of chains, so savings and QoS differences
between chain counts are paired seed by seed.

Run it directly to print the table per level and chains and write results/campaign.csv:
    ../.venv/bin/python -m lib.campaign
"""
import numpy as np
import pandas as pd

from lib import ns3data, paths, power

RAW = paths.RAW / "bs-results-main"
PROFILES = ("night", "day", "peak100")
CHAINS = (64, 32, 16)
DURATION = 10            # s, measured window of every run
SEEDS = 10
W = power.P_PEAK_W       # Piovesan power is in units of the peak power: multiply by W for watt

# ASSUMPTIONS: the QoS criterion -----------------------------------------------------------------------------------
LIMIT_MS = 20            # a burst user is "over the limit" if its 95th-percentile packet delay is above this
SEGMENT_S = 2.0          # a video segment must arrive within this time ...
MIN_RX = 0.99            # ... with at least 99% of its packets (no retransmission over UDP)
MAX_EXTRA_USERS = 0.05   # acceptable: at most 5 more burst users in 100 over the limit than with 64 chains ...
MAX_LOSS = 0.01          # ... no extra late video segment, and losses under 1%
# ------------------------------------------------------------------------------------------------------------------

T975 = 2.262             # Student t quantile for a 95% interval with 10 seeds (9 degrees of freedom)
# The same quantile for every sample size the studies use: 10 seeds, 20 seeds (final study), 300 days (policy).
T975_BY_DF = {9: 2.262, 19: 2.093, 299: 1.968}   # degrees of freedom (n - 1) -> 97.5% quantile


def t975(n):
    """97.5% Student t quantile for a sample of n values (n - 1 degrees of freedom)."""
    if n - 1 not in T975_BY_DF:
        raise ValueError(f"no Student t quantile for {n} values: add n - 1 = {n - 1} to T975_BY_DF")
    return T975_BY_DF[n - 1]


def load_run(profile, chains, seed):
    """One run of the main campaign -> (row of results, users table, segments table or None)."""
    prefix = RAW / f"{profile}_a{chains}_r{seed}"
    key = dict(profile=profile, chains=chains, seed=seed)
    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", DURATION)
    row = dict(**key,
               watt=float(power.piovesan(metrics["prb_load"], chains)) * W,                         # no shutdown
               watt_sym=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * W,  # symbol shutdown
               **metrics)
    users = pd.read_csv(f"{prefix}_flows.csv").assign(**key)
    segments_file = prefix.with_name(prefix.name + "_segments.csv")
    segments = pd.read_csv(segments_file).assign(**key) if segments_file.exists() else None
    return row, users, segments


def load():
    """Load the 90 runs. Returns the tables described at the top of this file, as a dict."""
    rows, users, segments = [], [], []
    for profile in PROFILES:
        for chains in CHAINS:
            for seed in range(1, SEEDS + 1):
                row, run_users, run_segments = load_run(profile, chains, seed)
                rows.append(row)
                users.append(run_users)
                if run_segments is not None:
                    segments.append(run_segments)
    runs, users, segments = pd.DataFrame(rows), pd.concat(users), pd.concat(segments)

    # Saving against 64 chains always on (no symbol shutdown), same level and seed
    always_on = runs[runs.chains == 64].set_index(["profile", "seed"]).watt
    reference = [always_on[(p, s)] for p, s in zip(runs.profile, runs.seed)]
    runs["save"] = 100 * (1 - runs.watt / reference)
    runs["save_sym"] = 100 * (1 - runs.watt_sym / reference)
    runs["loss_pct"] = 100 * runs.loss

    users["p95_ms"] = users.delay_p95_s * 1e3
    burst = users[users.kind == "burst"]

    whole = segments[segments.sent == segments.pkts]   # segments cut by the start or the end of the run are dropped
    whole = whole.assign(complete=whole.rx >= MIN_RX * whole.pkts, time_s=whole.last_rx_s - whole.start_s)
    whole["late"] = ~whole.complete | (whole.time_s > SEGMENT_S)
    return dict(runs=runs, users=users, segs=segments, burst=burst, whole=whole)


_tables = None


def __getattr__(name):
    """campaign.runs, campaign.burst, ... load the 90 runs on first use (once), not when the module is imported."""
    global _tables
    if name in ("runs", "users", "segs", "burst", "whole"):
        if _tables is None:
            _tables = load()
        return _tables[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def table(runs, burst, whole):
    """Mean and 95% CI per level and chains, delays, late segments and whether the QoS is acceptable."""
    key = ["profile", "chains"]
    by_level = runs.groupby(key)
    cols = ["watt", "watt_sym", "save", "save_sym", "prb_load", "pa_off", "sent", "thr", "loss_pct"]
    mean, ci = by_level[cols].mean(), by_level[cols].std() * T975 / np.sqrt(SEEDS)
    out = mean.join(ci.add_suffix("_ci"))

    p95 = burst.groupby(key).p95_ms
    out["burst_median_ms"], out["burst_p95user_ms"], out["burst_max_ms"] = p95.median(), p95.quantile(.95), p95.max()
    over = burst[burst.p95_ms > LIMIT_MS]
    out["users"], out["users_over"] = p95.size(), over.groupby(key).size()
    out["users_over"] = out.users_over.fillna(0).astype(int)
    out["seeds_over"] = over.groupby(key).seed.nunique()
    out["seeds_over"] = out.seeds_over.fillna(0).astype(int)

    seg = whole.groupby(key)
    out["segments"], out["segments_late"], out["segment_max_s"] = seg.size(), seg.late.sum(), seg.time_s.max()
    out["video_seeds_late"] = whole[whole.late].groupby(key).seed.nunique()

    # QoS relative to 64 chains: same users, so a user with a poor radio link counts the same in both
    share_over = out.users_over / out.users
    out["extra_users_pct"] = 100 * (share_over - share_over.xs(64, level="chains").reindex(share_over.index, level="profile"))
    late = out.segments_late.fillna(0)
    out["extra_late"] = late - late.xs(64, level="chains").reindex(late.index, level="profile")
    out["qos_ok"] = ((out.extra_users_pct <= 100 * MAX_EXTRA_USERS) & (late == 0)
                     & (out.loss_pct < 100 * MAX_LOSS))
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    t = load()
    out = table(t["runs"], t["burst"], t["whole"])
    out.to_csv(paths.RESULTS / "campaign.csv")
    print(out.round(3).T.to_string())

    peak_burst = t["burst"][t["burst"].profile == "peak100"]
    print(peak_burst.groupby(["chains", "seed"]).p95_ms.max().unstack())           # worst user per seed at peak
    peak_runs = t["runs"][t["runs"].profile == "peak100"]
    print(peak_runs.pivot(index="chains", columns="seed", values="loss_pct").round(2))   # losses per seed at peak
    whole = t["whole"]
    print(whole[whole.late].groupby(["chains", "seed", "ue"]).size())             # late segments per user
