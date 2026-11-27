"""TDMA against OFDMA scheduling, in all three sites (step 8 of docs/STEPS.md; campaign bs-results-tdma).

OFDMA gives each user some resource blocks for the whole slot, so every symbol carries data and the power amplifiers
stay on. TDMA gives each user the whole band for a few symbols, so the slot can end early and the last symbols are
empty: more time for symbol shutdown. Same users and traffic per seed, so every difference is paired.

Prints power, idle amplifier time and QoS per level, chains and scheduler, the energy of a day, and at peak which
burst users go over the delay limit with one scheduler and not the other.

Run from analysis/:  ../.venv/bin/python -m studies.tdma
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import BLUE, CHAINS, INK, ORANGE, save
from studies.daily import HOURS, half_ci

RAW = {"ofdma": campaign.RAW, "tdma": paths.RAW / "bs-results-tdma"}
CHAIN_COUNTS = (64, 32, 16)


def load():
    """runs: one row per scheduler, level, chains and seed. burst: burst users with p95_ms. whole: complete segments
    with late = arrived incomplete or after the deadline."""
    runs, users, segments = [], [], []
    last_slot = round((ns3data.WARMUP + campaign.DURATION) / ns3data.SLOT)
    for scheduler, raw in RAW.items():
        for profile in HOURS:
            for chains in CHAIN_COUNTS:
                for seed in range(1, campaign.SEEDS + 1):
                    name = f"{profile}_a{chains}_r{seed}"
                    key = dict(sch=scheduler, profile=profile, chains=chains, seed=seed)
                    metrics = ns3data.summary(raw / f"{name}_slots.csv", raw / f"{name}_flows.csv", campaign.DURATION)
                    slots = pd.read_csv(raw / f"{name}_slots.csv")
                    busy = slots[slots.slot < last_slot].groupby("slot").used_sym.max()
                    runs.append(dict(**key,
                                     watt=float(power.piovesan(metrics["prb_load"], chains)) * campaign.W,
                                     used_sym=busy[busy > 0].mean(),      # data symbols in a slot that has data
                                     watt_sym=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W,
                                     **metrics))
                    users.append(pd.read_csv(raw / f"{name}_flows.csv").assign(**key))
                    segments_file = raw / f"{name}_segments.csv"
                    if segments_file.exists():
                        segments.append(pd.read_csv(segments_file).assign(**key))
    runs, users, segments = pd.DataFrame(runs), pd.concat(users), pd.concat(segments)
    burst = users[users.kind == "burst"].assign(p95_ms=lambda u: u.delay_p95_s * 1e3)
    whole = segments[segments.sent == segments.pkts]
    whole = whole.assign(late=(whole.rx < campaign.MIN_RX * whole.pkts)
                         | (whole.last_rx_s - whole.start_s > campaign.SEGMENT_S))
    return runs, burst, whole


def mean_ci(x):
    return f"{x.mean():.2f}+-{half_ci(x):.2f}"


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 40)
    runs, burst, whole = load()
    by_key = runs.set_index(["sch", "profile", "chains", "seed"]).sort_index()

    def per_seed(scheduler, profile, chains, column):
        """One value per seed, seeds in order."""
        return by_key.loc[(scheduler, profile, chains), column].to_numpy()

    rows = []
    for profile in HOURS:
        for chains in CHAIN_COUNTS:
            # the comparison is paired only if both schedulers were offered the same traffic
            assert np.allclose(per_seed("ofdma", profile, chains, "sent"), per_seed("tdma", profile, chains, "sent")), (profile, chains)
            for scheduler in RAW:
                def this(table):
                    return table[(table.sch == scheduler) & (table.profile == profile) & (table.chains == chains)]
                p95, segs = this(burst).p95_ms, this(whole)
                watt_sym = per_seed(scheduler, profile, chains, "watt_sym")
                diff = watt_sym - per_seed("ofdma", profile, chains, "watt_sym")      # against OFDMA, same chains
                always_on = per_seed("ofdma", profile, 64, "watt")
                rows.append(dict(profile=profile, chains=chains, sch=scheduler,
                                 watt=per_seed(scheduler, profile, chains, "watt").mean(),
                                 watt_sym=watt_sym.mean(), d_watt_sym=diff.mean(), d_ci=half_ci(diff),
                                 saving=mean_ci(100 * (1 - watt_sym / always_on)),
                                 pa_off=per_seed(scheduler, profile, chains, "pa_off").mean(),
                                 empty=per_seed(scheduler, profile, chains, "empty_slots").mean(),
                                 used_sym=per_seed(scheduler, profile, chains, "used_sym").mean(),
                                 prb=per_seed(scheduler, profile, chains, "prb_load").mean(),
                                 median_p95=p95.median(), max_p95=p95.max(), over=int((p95 > campaign.LIMIT_MS).sum()),
                                 users=len(p95), late=int(segs.late.sum()), segs=len(segs),
                                 loss=100 * per_seed(scheduler, profile, chains, "loss").mean()))
    table = pd.DataFrame(rows)
    table.to_csv(paths.RESULTS / "tdma.csv", index=False)
    print(table.round(3).to_string(index=False))

    print("\nDay energy [kWh], saving % against OFDMA always on (hours 8/12/4):")

    def day_energy(scheduler, chains_per_level, column):
        return sum(h * per_seed(scheduler, p, a, column) for (p, h), a in zip(HOURS.items(), chains_per_level)) / 1e3

    reference = day_energy("ofdma", (64, 64, 64), "watt")
    for name, chains_per_level, column in (("always on", (64, 64, 64), "watt"), ("symbol", (64, 64, 64), "watt_sym"),
                                           ("symbol + channel", (16, 16, 64), "watt_sym")):
        ofdma = day_energy("ofdma", chains_per_level, column)
        tdma = day_energy("tdma", chains_per_level, column)
        print(f"  {name}: OFDMA {ofdma.mean():.2f} (-{mean_ci(100 * (1 - ofdma / reference))}), "
              f"TDMA {tdma.mean():.2f} (-{mean_ci(100 * (1 - tdma / reference))}), "
              f"TDMA against OFDMA {mean_ci(100 * (tdma / ofdma - 1))} %")

    print("\nPeak, paired burst users over the limit:")
    peak = burst[burst.profile == "peak100"].set_index(["sch", "chains", "seed", "ue"]).p95_ms
    both = pd.concat({s: peak[s] for s in RAW}, axis=1)     # one row per user, columns ofdma and tdma
    assert both.notna().all().all()
    for chains in CHAIN_COUNTS:
        users = both.loc[chains]
        over_o, over_t = users.ofdma > campaign.LIMIT_MS, users.tdma > campaign.LIMIT_MS
        better = over_o.groupby("seed").sum() - over_t.groupby("seed").sum()      # > 0: TDMA has fewer users over
        print(f"  {chains}: both {(over_o & over_t).sum()}, only OFDMA {(over_o & ~over_t).sum()}, "
              f"only TDMA {(~over_o & over_t).sum()}, of {len(users)}; users with "
              f"lower p95 under TDMA {(users.tdma < users.ofdma).sum()}, higher {(users.tdma > users.ofdma).sum()}; "
              f"seeds better/worse {(better > 0).sum()}/{(better < 0).sum()}; quantiles 50/90 OFDMA "
              f"{users.ofdma.quantile([.5, .9]).round(1).tolist()} TDMA {users.tdma.quantile([.5, .9]).round(1).tolist()}")
    print(runs[runs.profile == "peak100"].assign(l=lambda x: 100 * x.loss).pivot(
        index=["chains", "sch"], columns="seed", values="l").round(2).to_string())

    # Figure: peak, power with symbol shutdown and burst users over the limit
    fig, (ax_power, ax_qos) = plt.subplots(1, 2, figsize=(10, 4.2))
    peak_rows = table[table.profile == "peak100"]
    for k, (scheduler, color) in enumerate((("ofdma", BLUE), ("tdma", ORANGE))):
        bars = peak_rows[peak_rows.sch == scheduler].set_index("chains").loc[list(CHAINS)]
        x = [i + (k - .5) * .4 for i in range(3)]
        ax_power.bar(x, bars.watt_sym, .36, color=color, label=scheduler.upper())
        ax_qos.bar(x, bars.over, .36, color=color, label=scheduler.upper())
        for xi, watt, over in zip(x, bars.watt_sym, bars.over):
            ax_power.text(xi, watt + 10, f"{watt:.0f}", ha="center", fontsize=8, color=INK)
            ax_qos.text(xi, over + .5, f"{over}", ha="center", fontsize=8, color=INK)
    ax_power.set(ylabel="AAU power with symbol shutdown [W]", ylim=(0, 800), title="Peak: power")
    ax_qos.set(ylabel=f"burst users with p95 over {campaign.LIMIT_MS} ms (of 70)", ylim=(0, 40), title="Peak: QoS")
    for ax in (ax_power, ax_qos):
        ax.set(xticks=range(3), xticklabels=CHAINS, xlabel="active chains")
        ax.grid(axis="x", visible=False)
    ax_power.legend(frameon=False, loc="upper right")
    save(fig, "tdma.png", "Same scheduler in all three sites. 10 seeds, paired")
