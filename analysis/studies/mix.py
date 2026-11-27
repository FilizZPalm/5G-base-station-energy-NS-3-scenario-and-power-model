"""Why TDMA serves the peak better (step 9 of docs/STEPS.md; campaign bs-results-mix).

At peak, cell 0 and the neighbour sites each use OFDMA or TDMA, independently: four combinations, same seeds, so
every difference is paired. Every transport block (TB) received in cell 0 is traced (<prefix>_tb.csv), which gives
the errors at first transmission and how uneven the interference is across the resource blocks of a block.

Effects are averaged over the other factor (a 2 x 2 design):
  cell 0 effect      mean over the neighbours' scheduler of (cell 0 TDMA - cell 0 OFDMA)
  neighbours effect  mean over cell 0's scheduler of (neighbours TDMA - neighbours OFDMA)
  interaction        how much one effect depends on the other

Run from analysis/:  ../.venv/bin/python -m studies.mix
"""
import matplotlib.pyplot as plt
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import BLUE, CHAINS, INK, ORANGE, save
from studies.daily import half_ci

RAW = paths.RAW / "bs-results-mix"
SCHEDULERS = ("ofdma", "tdma")
COLS = ["watt_sym", "pa_off", "prb", "delay_ms", "over", "late", "loss", "retx", "bler", "spread", "rbs", "syms"]


def late_segments(prefix):
    """Late video segments of a run."""
    return campaign.whole_segments(pd.read_csv(f"{prefix}_segments.csv")).late.sum()


def load():
    rows = []
    for cell0 in SCHEDULERS:
        for neighbours in SCHEDULERS:
            for chains in (64, 32, 16):
                for seed in range(1, campaign.SEEDS + 1):
                    prefix = RAW / f"{cell0}-{neighbours}" / f"peak100_a{chains}_r{seed}"
                    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
                    flows = pd.read_csv(f"{prefix}_flows.csv")
                    p95_ms = 1e3 * flows[flows.kind == "burst"].delay_p95_s
                    blocks = pd.read_csv(f"{prefix}_tb.csv")
                    first = blocks[blocks.rv == 0]              # first transmissions (redundancy version 0)
                    rows.append(dict(cell0=cell0, neigh=neighbours, chains=chains, seed=seed,
                                     watt_sym=float(power.piovesan(metrics["prb_load"], chains, metrics["pa_off"])) * campaign.W,
                                     pa_off=metrics["pa_off"], prb=metrics["prb_load"], delay_ms=1e3 * metrics["delay"],
                                     over=int((p95_ms > campaign.LIMIT_MS).sum()), late=int(late_segments(prefix)),
                                     loss=100 * metrics["loss"],
                                     retx=100 * (blocks.rv > 0).mean(),                     # blocks that are retransmissions
                                     bler=100 * first.corrupt.mean(),                       # errors at first transmission
                                     spread=(first.sinr_db - first.sinr_min_db).mean(),     # SINR in a block: mean - worst RB
                                     rbs=first.rbs.mean(), syms=first.syms.mean()))
    return pd.DataFrame(rows)


def effects(runs):
    """Cell 0, neighbours and interaction effects per chains and metric, paired by seed (mean +- 95% CI)."""
    by_key = runs.set_index(["chains", "seed", "cell0", "neigh"]).sort_index()
    out = []
    for chains in (64, 32, 16):
        these = by_key.loc[chains]

        def value(cell0, neighbours, metric):
            return these.xs((cell0, neighbours), level=("cell0", "neigh"))[metric].to_numpy()

        for metric in ("watt_sym", "bler", "spread", "delay_ms", "loss", "over"):
            oo, ot = value("ofdma", "ofdma", metric), value("ofdma", "tdma", metric)   # cell 0 first, neighbours second
            to, tt = value("tdma", "ofdma", metric), value("tdma", "tdma", metric)
            effect = {"cell 0": (to - oo + tt - ot) / 2,
                      "neighbours": (ot - oo + tt - to) / 2,
                      "interaction": tt - to - ot + oo}
            out.append(dict(chains=chains, metric=metric,
                            **{name: f"{e.mean():+.2f} +- {half_ci(e):.2f}" for name, e in effect.items()}))
    return pd.DataFrame(out)


def plot(means):
    """Errors at first transmission and SINR spread in a block; colour = cell 0, hatching = neighbours with TDMA."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    combinations = [(cell0, neighbours) for cell0 in SCHEDULERS for neighbours in SCHEDULERS]
    for ax, (metric, label, top) in zip(axes, (("bler", "blocks in error at first transmission [%]", 30),
                                               ("spread", "SINR in the block: mean - worst RB [dB]", 13))):
        for j, (cell0, neighbours) in enumerate(combinations):
            x = [i + (j - 1.5) * .2 for i in range(3)]
            y = [means.loc[(a, cell0, neighbours), metric] for a in CHAINS]
            ax.bar(x, y, .18, color=BLUE if cell0 == "ofdma" else ORANGE, hatch="///" if neighbours == "tdma" else None,
                   edgecolor="white", lw=0, label=f"cell 0 {cell0.upper()}, neighbours {neighbours.upper()}")
            for xi, yi in zip(x, y):
                ax.text(xi, yi + top / 80, f"{yi:.0f}" if metric == "bler" else f"{yi:.1f}", ha="center", fontsize=7,
                        color=INK)
        ax.set(xticks=range(3), xticklabels=CHAINS, xlabel="active chains in cell 0", ylabel=label, ylim=(0, top))
        ax.grid(axis="x", visible=False)
    axes[0].set_title("Peak: errors")
    axes[1].set_title("Peak: interference uneven in frequency")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower right", ncol=2, frameon=False, fontsize=8)
    save(fig, "mix.png", "10 seeds, paired. Hatched: neighbour sites with TDMA")


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30)
    runs = load()
    grouped = runs.groupby(["chains", "cell0", "neigh"], sort=False)
    means = grouped[COLS].mean()
    for metric in ("over", "late"):
        means[metric] = grouped[metric].sum()     # totals: users of 70, segments of 147
    means.to_csv(paths.RESULTS / "mix.csv")
    print(means.round(3).to_string())

    print("\nEffects, paired by seed (mean +- 95 % CI):")
    print(effects(runs).to_string(index=False))
    plot(means)
