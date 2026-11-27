"""Busier nights (step 7 of docs/STEPS.md): what if the night carries 5, 10 or 15 Mbit/s instead of 1?

For each night (2 users) and chain count: power, QoS and the saving of symbol shutdown; then the extra saving of
sleep with a wake-up time (simulated in NS-3, 16 chains), and the energy of a day with each night.

EARTH (Auer et al. 2011, Fig. 4) puts the daily minimum of active users at 14% of the maximum, while our night is at
1% of the peak traffic. The two quantities differ, so these nights are a sensitivity check, not a calibration.

Campaigns: bs-results-night (busier nights), bs-results-night-wake (their sleep runs); the 1 Mbit/s night comes from
the main and wake-up campaigns. Run from analysis/:  ../.venv/bin/python -m studies.night
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, ns3data, paths, power
from lib.style import BLUE, INK, ORANGE, save
from studies.daily import HOURS, half_ci
from studies.wakeup import idle_watt

RAW = paths.RAW / "bs-results-night"
WAKE = paths.RAW / "bs-results-night-wake"
WAKE_MAIN = paths.RAW / "bs-results-wake"
NIGHTS = {"night": 1, "night5": 5, "night10": 10, "night15": 15}   # name -> Mbit/s
SETTINGS = [("0.5", 20), ("5", 160)]                                 # sleep: Tw [ms], SSB period [ms]
SEEDS = range(1, campaign.SEEDS + 1)


def read_run(prefix):
    """Metrics of a run and the p95 delay of each burst user [ms]."""
    metrics = ns3data.summary(f"{prefix}_slots.csv", f"{prefix}_flows.csv", campaign.DURATION)
    flows = pd.read_csv(f"{prefix}_flows.csv")
    return metrics, 1e3 * flows[flows.kind == "burst"].delay_p95_s.to_numpy()


def load():
    """runs: one row per night, chains and seed. sleeps: one row per night, sleep setting and seed (16 chains)."""
    runs, sleeps = [], []
    for night in NIGHTS:
        for chains in (64, 32, 16):
            for seed in SEEDS:
                folder = campaign.RAW if night == "night" else RAW
                metrics, p95 = read_run(folder / f"{night}_a{chains}_r{seed}")
                runs.append(dict(night=night, chains=chains, seed=seed, p95=p95, thr=metrics["thr"],
                                 loss=100 * metrics["loss"], prb=metrics["prb_load"],
                                 watt=campaign.watt(metrics, chains, symbol=False),
                                 watt_sym=campaign.watt(metrics, chains)))
        for tw, ssb in SETTINGS:
            for seed in SEEDS:
                folder = WAKE_MAIN if night == "night" else WAKE
                prefix = folder / f"{night}_a16_t{tw}_s{ssb}_r{seed}"
                metrics, p95 = read_run(prefix)
                states = pd.read_csv(f"{prefix}_sleep.csv").iloc[0]
                asleep = states["sleep"] / states[["awake", "down", "sleep", "up"]].sum()
                watt = campaign.watt(metrics, 16) - asleep * (idle_watt(16) - power.CARRIER_OFF * campaign.W)
                sleeps.append(dict(night=night, tw=tw, ssb=ssb, seed=seed, asleep=100 * asleep, p95=p95,
                                   violations=states.violations, watt=watt))
    return pd.DataFrame(runs), pd.DataFrame(sleeps)


def users_over(group):
    """'over/total' burst users above the delay limit, and the worst p95 delay, over all runs of a group."""
    p95 = np.concatenate(list(group.p95))
    return f"{int((p95 > campaign.LIMIT_MS).sum())}/{len(p95)}", float(np.max(p95))


def chains_table(runs):
    out = []
    for (night, chains), group in runs.groupby(["night", "chains"], sort=False):
        always_on = runs[(runs.night == night) & (runs.chains == 64)].watt.to_numpy()
        over, worst = users_over(group)
        saving = 100 * (1 - group.watt_sym.to_numpy() / always_on)
        out.append(dict(night=night, chains=chains, thr=group.thr.mean(), prb=group.prb.mean(), watt=group.watt.mean(),
                        watt_sym=group.watt_sym.mean(), saving_sym=saving.mean(), saving_ci=half_ci(saving),
                        over20=over, max_p95=worst, loss=group.loss.mean()))
    return pd.DataFrame(out)


def sleep_table(runs, sleeps):
    out = []
    no_sleep = runs[runs.chains == 16].set_index(["night", "seed"]).watt_sym
    for (night, tw, ssb), group in sleeps.groupby(["night", "tw", "ssb"], sort=False):
        reference = no_sleep[night].loc[group.seed].to_numpy()
        extra = 100 * (1 - group.watt.to_numpy() / reference)
        over, worst = users_over(group)
        out.append(dict(night=night, tw=tw, ssb=ssb, asleep=group.asleep.mean(), watt=group.watt.mean(),
                        extra=extra.mean(), extra_ci=half_ci(extra), over20=over, max_p95=worst,
                        violations=int(group.violations.sum())))
    return pd.DataFrame(out)


def print_days(runs, sleeps):
    """Energy of a day (8/12/4 h) with each night; day and peak from the main campaign."""
    print("\nDay energy with each night (hours 8/12/4):")
    main = campaign.runs.set_index(["profile", "chains", "seed"])

    def day_and_peak(chains_day, chains_peak, column):
        """Energy of the 12 h of day and 4 h of peak [Wh], one value per seed."""
        return sum(HOURS[p] * main.xs((p, a), level=("profile", "chains")).sort_index()[column].to_numpy()
                   for p, a in (("day", chains_day), ("peak100", chains_peak)))

    for night in NIGHTS:
        this_night = runs[runs.night == night]

        def night_watt(chains, column):
            return this_night[this_night.chains == chains].sort_values("seed")[column].to_numpy()

        always_on = (8 * night_watt(64, "watt") + day_and_peak(64, 64, "watt")) / 1e3
        best = (8 * night_watt(16, "watt_sym") + day_and_peak(16, 64, "watt_sym")) / 1e3
        sleep_watt = sleeps[(sleeps.night == night) & (sleeps.tw == "0.5")].sort_values("seed").watt.to_numpy()
        with_sleep = (8 * sleep_watt + day_and_peak(16, 64, "watt_sym")) / 1e3
        sleep_saving = 100 * (1 - with_sleep / always_on)
        print(f"  {night}: always on {always_on.mean():.2f}, symbol + channel {best.mean():.2f} "
              f"(-{(100 * (1 - best / always_on)).mean():.1f} %), + 0.5 ms sleep at night {with_sleep.mean():.2f} "
              f"(-{sleep_saving.mean():.1f} +/- {half_ci(sleep_saving):.1f} %)")


def plot(sleep_result):
    """Extra saving of sleep as the night gets busier, labelled with the time asleep."""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    mbps = list(NIGHTS.values())
    for (tw, ssb), color, marker, dy in zip(SETTINGS, (BLUE, ORANGE), ("o", "s"), (9, -16)):
        setting = sleep_result[(sleep_result.tw == tw) & (sleep_result.ssb == ssb)].set_index("night").loc[list(NIGHTS)]
        ax.errorbar(mbps, setting.extra, setting.extra_ci, color=color, marker=marker, ms=8, lw=2, capsize=2,
                    label=f"Tw {tw} ms, SSB every {ssb} ms")
        for x, y, asleep in zip(mbps, setting.extra, setting.asleep):
            ax.annotate(f"asleep {asleep:.0f}%", (x, y), xytext=(0, dy), textcoords="offset points", ha="center",
                        fontsize=8, color=INK)
    ax.set(xticks=mbps, xlabel="night traffic [Mbit/s], 2 users", ylabel="extra saving over symbol + channel [%]",
           ylim=(0, 22), title="Busier nights: what sleep still saves (16 chains)")
    ax.legend(frameon=False, loc="lower left")
    save(fig, "night_load.png", "RF off state, simulated in NS-3. 10 seeds; bars: 95% CI")


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_columns", 30)
    runs, sleeps = load()
    print(chains_table(runs).round(2).to_string(index=False))
    sleep_result = sleep_table(runs, sleeps)
    sleep_result.to_csv(paths.RESULTS / "night.csv", index=False)
    print(sleep_result.round(2).to_string(index=False))
    print_days(runs, sleeps)
    plot(sleep_result)
