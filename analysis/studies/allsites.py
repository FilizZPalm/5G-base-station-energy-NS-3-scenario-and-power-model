"""All sites with fewer chains (step 12 of docs/STEPS.md; campaign bs-results-allsites).

Until step 11 only cell 0 switched chains off and the neighbours kept 64. Here the neighbours use the same number of
chains as cell 0 (32 or 16). Same seeds, so same users and traffic: the only change is the neighbours' array and
transmit power, hence the interference seen by cell 0. With 64 chains the two campaigns are the same runs.

At peak, the SINR and the errors at first transmission per block come from the rx traces (<prefix>_rx.csv). For
neighbours at 64 they come from the OFDMA/OFDMA runs of the mix campaign (step 9), which repeat the main peak runs
with the traces on.

Run from analysis/:  ../.venv/bin/python -m studies.allsites
"""
import pandas as pd

from lib import campaign, ns3data, paths, power
from studies.daily import half_ci

ALLSITES = paths.RAW / "bs-results-allsites"
MIX = paths.RAW / "bs-results-mix" / "ofdma-ofdma"
PROFILES = ("night", "day", "peak100")
CHAINS = (32, 16)


def run(raw, profile, chains, seed):
    """Power with symbol shutdown, QoS and (if traced) SINR and errors of one run."""
    prefix = raw / f"{profile}_a{chains}_r{seed}"
    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
    flows = pd.read_csv(f"{prefix}_flows.csv")
    burst = flows[flows.kind == "burst"]
    late = 0
    if profile == "peak100":
        late = int(campaign.whole_segments(pd.read_csv(f"{prefix}_segments.csv")).late.sum())
    out = dict(watt_sym=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W,
               prb=100 * metrics["prb_load"], over=int((burst.delay_p95_s * 1e3 > campaign.LIMIT_MS).sum()),
               users=len(burst), late=late, loss=100 * metrics["loss"])
    rx_file = prefix.with_name(prefix.name + "_rx.csv")
    if rx_file.exists():
        rx = pd.read_csv(rx_file)
        out |= dict(sinr=rx.sinr_db_w.sum() / rx.res.sum(),           # SINR weighted by resources [dB]
                    bler=100 * rx.corrupt.sum() / rx.tbs.sum())        # blocks in error [%]
    return out


def sinr_and_errors(profile, chains, seed):
    """SINR and errors for neighbours at 64, from the mix campaign (main runs with traces)."""
    return {k: v for k, v in run(MIX, profile, chains, seed).items() if k in ("sinr", "bler")}


def load():
    rows = []
    for profile in PROFILES:
        for seed in range(1, campaign.SEEDS + 1):
            always_on_prefix = campaign.RAW / f"{profile}_a64_r{seed}"
            always_on = float(power.piovesan(ns3data.summary(f"{always_on_prefix}_slots.csv", f"{always_on_prefix}_flows.csv",
                                                             campaign.DURATION)["prb_load"], 64)) * campaign.W
            for chains in CHAINS:
                for neighbours, raw in (("64", campaign.RAW), ("same", ALLSITES)):
                    result = run(raw, profile, chains, seed)
                    if profile == "peak100" and neighbours == "64":
                        result |= sinr_and_errors(profile, chains, seed)
                    rows.append(dict(profile=profile, chains=chains, neighbours=neighbours, seed=seed,
                                     saving=100 * (1 - result["watt_sym"] / always_on), **result))
            result = run(campaign.RAW, profile, 64, seed)               # 64 chains: the reference, same in both
            if profile == "peak100":
                result |= sinr_and_errors(profile, 64, seed)
            rows.append(dict(profile=profile, chains=64, neighbours="64 (ref)", seed=seed,
                             saving=100 * (1 - result["watt_sym"] / always_on), **result))
    return pd.DataFrame(rows)


def table(runs):
    """Means per level, chains and neighbours, and the QoS criterion relative to 64 chains."""
    grouped = runs.groupby(["profile", "chains", "neighbours"], sort=False)
    out = grouped.agg(watt=("watt_sym", "mean"), saving=("saving", "mean"), prb=("prb", "mean"), over=("over", "sum"),
                      users=("users", "sum"), late=("late", "sum"), loss=("loss", "mean"), sinr=("sinr", "mean"),
                      bler=("bler", "mean"))
    out["saving_ci"] = grouped.saving.apply(half_ci)
    reference = out.xs("64 (ref)", level="neighbours").droplevel("chains")
    out["extra_pct"] = 100 * (out.over / out.users) - 100 * (reference.over / reference.users).reindex(out.index, level="profile").to_numpy()
    out["extra_late"] = out.late - reference.late.reindex(out.index, level="profile").to_numpy()
    out["qos_ok"] = ((out.extra_pct <= 100 * campaign.MAX_EXTRA_USERS) & (out.extra_late <= 0)
                     & (out.loss < 100 * campaign.MAX_LOSS))
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    runs = load()
    runs.to_csv(paths.RESULTS / "allsites_runs.csv", index=False)
    result = table(runs)
    result.to_csv(paths.RESULTS / "allsites.csv")
    print(result.round(2).to_string())

    # paired differences, neighbours "same" minus neighbours at 64
    paired = runs[runs.neighbours != "64 (ref)"].pivot_table(index=["profile", "chains", "seed"], columns="neighbours",
                                                             values=["watt_sym", "prb", "over", "sinr", "bler"])
    for metric in ("watt_sym", "prb", "sinr", "bler"):
        if (metric, "same") in paired:
            diff = (paired[(metric, "same")] - paired[(metric, "64")]).groupby(level=["profile", "chains"])
            print(metric, "same - 64:", {k: f"{x.mean():+.2f} ± {half_ci(x):.2f}" for k, x in diff if x.notna().all()})
