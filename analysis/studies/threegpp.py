"""The 3GPP power model (TR 38.864, clause 5.1) on the NS-3 traces (step 10 of docs/STEPS.md).

Same traffic as with Piovesan, a different power model: symbol and channel shutdown, then light and deep sleep with
the transition times and energies given by the same report. Powers are relative (deep sleep = 1).

The power of a slot is built symbol by symbol from the slot trace of cell 0 (pattern DDDSU, 14 symbols per slot):
  - control symbol: always transmitted, over the whole carrier (ASSUMPTION);
  - downlink data symbol: resource blocks in use = used_reg / used_sym (the same in every used symbol of the slot);
  - empty downlink symbol: micro sleep with symbol shutdown (immediate, as in the report), else radio units on
    without output;
  - uplink symbols (the U slot and the last symbol of the S slot): active uplink (ASSUMPTION: no uplink data is
    simulated);
  - the second carrier costs 0.7 of the first (contiguous carriers); sleep states and transition energies are
    multiplied by 1.7 too (ASSUMPTION).
Light and deep sleep: the trace estimate of studies.wakeup with total transition time T = 2 Tw, and for Category 1
also simulated in NS-3 (campaign bs-results-wake3gpp).

Run from analysis/:  ../.venv/bin/python -m studies.threegpp
Also imported by studies.policy and studies.final (slot_power, symbol_table, ns3_sleeps).
"""
from functools import cache

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib import campaign, paths, power
from lib.style import AQUA, BLUE, CHAINS, INK, ORANGE, save
from studies.daily import HOURS, POLICIES, energy, half_ci
from studies.wakeup import CASES, FIRST, N, SLOT_MS, run, trace

SYM = 14                                # symbols per slot
CC = 1 + power.TGPP_EXTRA_CC            # two contiguous carriers = 1.7 x one carrier
SSB = {"SSB 20 ms": 20, "SSB 160 ms": 160, "no SSB": 0}
SEEDS = range(1, campaign.SEEDS + 1)
WAKE = paths.RAW / "bs-results-wake3gpp"
# sleeps simulated in NS-3, Category 1 only (Category 2 needs 640 ms or 10 s): (level, state, SSB period [ms])
NS3 = [("night", "light", 20), ("night", "light", 160), ("night", "deep", 160), ("day", "light", 20),
       ("peak100", "light", 20)]


def slot_power(prefix, chains, symbol, cat):
    """3GPP power of one run. Returns (mean power of each measured slot, power of an empty awake slot), both in relative
    units per symbol. chains: active chains; symbol: symbol shutdown on; cat: Category 1 or 2."""
    slots = pd.read_csv(f"{prefix}_slots.csv")
    slots = slots[(slots.slot >= FIRST) & (slots.slot < FIRST + N)]
    active_ru, p = chains / 64, power.TGPP[cat]
    control = power.tgpp_dl_symbol(80, active_ru, cat)                     # control symbol over the whole carrier
    uplink = power.tgpp_ul_symbol(active_ru, cat)
    empty = p["micro"] if symbol else power.tgpp_dl_symbol(0, active_ru, cat)
    rbs = np.where(slots.used_sym > 0, slots.used_reg / slots.used_sym.clip(lower=1), 0)
    energy_per_row = (control + slots.used_sym * power.tgpp_dl_symbol(rbs, active_ru, cat)
                      + (slots.avail_sym - slots.used_sym) * empty
                      + (SYM - 1 - slots.avail_sym) * uplink) * np.where(slots.carrier == 0, 1, power.TGPP_EXTRA_CC)
    per_slot = np.full(N, SYM * uplink * CC)                               # uplink slots are not in the trace
    downlink = energy_per_row.groupby(slots.slot).sum()                    # both carriers of a slot together
    per_slot[downlink.index.to_numpy() - FIRST] = downlink.to_numpy()
    # an empty awake frame (3 D + 1 S + 1 U slots), averaged per slot
    d_slot = control + 13 * empty
    s_slot = control + 12 * empty + uplink
    idle = (3 * d_slot + s_slot + SYM * uplink) / 5 * CC
    return per_slot / SYM, idle / SYM


def sleep_power(base, idle, off, sleeps, state, cat):
    """Mean power with sleeps: the share of time not awake (off) costs the sleep state instead of the idle awake
    power, and each of the sleeps adds the transition energy of the state."""
    p = power.TGPP[cat]
    return base - off * (idle - p[state] * CC) + sleeps * p[f"e_{state}"] * CC / (N * SLOT_MS)


@cache
def symbol_table():
    """One row per category, level, chains, seed and symbol shutdown: mean relative power (rel), empty-slot power
    (idle) and saving against 64 chains always on (save)."""
    rows = []
    for cat in (1, 2):
        for profile in HOURS:
            for chains in CHAINS:
                for seed in SEEDS:
                    for symbol in (False, True):
                        per_slot, idle = slot_power(campaign.RAW / f"{profile}_a{chains}_r{seed}", chains, symbol, cat)
                        rows.append(dict(cat=cat, profile=profile, chains=chains, seed=seed, symbol=symbol,
                                         rel=per_slot.mean(), idle=idle))
    table = pd.DataFrame(rows)
    always_on = always_on_power(table)
    table["save"] = 100 * (1 - table.rel / [always_on[k] for k in zip(table.cat, table.profile, table.seed)])
    return table


def always_on_power(table):
    """64 chains, no symbol shutdown, by (category, level, seed)."""
    return table[(table.chains == 64) & ~table.symbol].set_index(["cat", "profile", "seed"]).rel


@cache
def trace_sleeps():
    """Light and deep sleep on top of symbol + channel shutdown (chains of studies.wakeup), estimated on the traces."""
    table = symbol_table()
    with_symbol = table[table.symbol].set_index(["cat", "profile", "chains", "seed"])
    always_on = always_on_power(table)
    rows = []
    for profile, chains in CASES.items():
        traces = {seed: trace(profile, chains, seed) for seed in SEEDS}
        for cat in (1, 2):
            p = power.TGPP[cat]
            for state in ("light", "deep"):
                tw = round(p[f"t_{state}"] / 2 / SLOT_MS)          # slots to go down (and to come up)
                for name, ssb in SSB.items():
                    if ssb and 2 * tw >= ssb / SLOT_MS:
                        continue                                    # no room between two SSBs
                    if 2 * tw >= N:
                        continue                                    # longer than the simulated window
                    for seed in SEEDS:
                        asleep, delays, _, off, n_sleeps = run(*traces[seed], tw, round(ssb / SLOT_MS), 2 * tw)
                        base, idle = with_symbol.loc[(cat, profile, chains, seed), ["rel", "idle"]]
                        rows.append(dict(cat=cat, profile=profile, chains=chains, state=state, ssb=name, seed=seed,
                                         off=100 * off, rel=sleep_power(base, idle, off, n_sleeps, state, cat), base=base,
                                         on=always_on[(cat, profile, seed)],
                                         p95=np.percentile(delays, 95) if len(delays) else 0))
    table = pd.DataFrame(rows)
    table["extra"] = 100 * (1 - table.rel / table.base)
    return table


@cache
def ns3_sleeps():
    """The same sleeps simulated in NS-3 (Category 1), with Tw = T / 2."""
    with_symbol = symbol_table()[symbol_table().symbol].set_index(["cat", "profile", "chains", "seed"])
    rows = []
    for profile, state, ssb in NS3:
        chains, p = CASES[profile], power.TGPP[1]
        tw = p[f"t_{state}"] / 2                                  # ms
        for seed in SEEDS:
            prefix = WAKE / f"{profile}_a{chains}_t{tw:g}_s{ssb}_r{seed}"
            if not prefix.with_name(prefix.name + "_sleep.csv").exists():
                continue
            per_slot, idle = slot_power(prefix, chains, True, 1)
            states = pd.read_csv(f"{prefix}_sleep.csv").iloc[0]
            total = states[["awake", "down", "sleep", "up"]].sum()
            off = (total - states.awake) / total                      # share of time not awake
            n_sleeps = states.down / (tw / SLOT_MS)                   # slots going down / slots per transition
            flows = pd.read_csv(f"{prefix}_flows.csv")
            p95_ms = 1e3 * flows[flows.kind == "burst"].delay_p95_s
            rows.append(dict(cat=1, profile=profile, state=state, ssb=f"SSB {ssb} ms", seed=seed, off=100 * off,
                             rel=sleep_power(per_slot.mean(), idle, off, n_sleeps, state, 1),
                             base=with_symbol.loc[(1, profile, chains, seed), "rel"], violations=states.violations,
                             over=int((p95_ms > campaign.LIMIT_MS).sum()), users=len(p95_ms), max_p95=p95_ms.max(),
                             loss=100 * (1 - flows.rx_pkts.sum() / flows.tx_pkts.sum())))
    table = pd.DataFrame(rows)
    if len(table):
        table["extra"] = 100 * (1 - table.rel / table.base)
    return table


def sleep_level(cat, profile, state, ssb, traced, simulated):
    """Power of a level with light or deep sleep, one value per seed: NS-3 when all seeds were simulated, else the
    trace estimate; empty if neither (the sleep does not fit between two SSBs). Also used by studies.final."""
    for source in (simulated, traced):
        if len(source):
            rows = source[(source.cat == cat) & (source.profile == profile) & (source.state == state) & (source.ssb == ssb)]
            if len(rows) == campaign.SEEDS:
                return rows.sort_values("seed").rel.to_numpy()
    return np.array([])


def daily_savings(table, traced, simulated):
    """Saving of one day (8/12/4 h) per category and policy, against 64 chains always on, mean and 95% CI."""
    def level(cat, profile, chains, symbol):
        rows = table[(table.cat == cat) & (table.profile == profile) & (table.chains == chains) & (table.symbol == symbol)]
        return rows.sort_values("seed").rel.to_numpy()

    out = []
    for cat in (1, 2):
        reference = sum(h * level(cat, p, 64, False) for p, h in HOURS.items())
        policies = {name: {p: level(cat, p, *setting) for p, setting in POLICIES[name].items()} for name in POLICIES}
        best = policies["symbol + channel"]
        for name, ssb in (("+ light sleep everywhere", "SSB 20 ms"), ("+ light sleep at night", "SSB 160 ms"),
                          ("+ light sleep at night", "no SSB"), ("+ deep sleep at night", "SSB 160 ms"),
                          ("+ deep sleep at night", "no SSB")):
            state = name.split()[1]                             # "light" or "deep"
            night = sleep_level(cat, "night", state, ssb, traced, simulated)
            if not len(night):
                continue
            levels = dict(best, night=night)
            if "everywhere" in name:
                levels = {p: sleep_level(cat, p, state, ssb, traced, simulated) for p in HOURS}
                if any(not len(v) for v in levels.values()):
                    continue
            policies[f"{name} ({ssb})"] = levels
        for name, levels in policies.items():
            e = sum(h * levels[p] for p, h in HOURS.items())
            saving = 100 * (1 - e / reference)
            out.append(dict(cat=cat, policy=name, saving=saving.mean(), ci=half_ci(saving)))
    return pd.DataFrame(out)


NOTE = ("Hours 8/12/4. Sleep: NS-3 where simulated, else trace estimate; no bar: not possible.\n"
        "Deep sleep at night puts every night burst user over 20 ms. 10 seeds")


def plot(days, piovesan=None, filename="threegpp.png", note=NOTE):
    """Saving of one day: Piovesan against 3GPP Category 1 and 2. days: one row per category and policy with the
    saving; piovesan: policy -> Piovesan saving (default: the main campaign). Also used by studies.final."""
    if piovesan is None:
        piovesan = {n: 100 * (1 - energy(n, HOURS) / energy("always on", HOURS)).mean() for n in POLICIES}
    names = [n for n in days[days.cat == 1].policy if n != "always on"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(names))
    for k, (label, color, values) in enumerate((
            ("Piovesan", BLUE, [piovesan.get(n, np.nan) for n in names]),
            ("3GPP Category 1", ORANGE, [days[(days.cat == 1) & (days.policy == n)].saving.mean() for n in names]),
            ("3GPP Category 2", AQUA, [days[(days.cat == 2) & (days.policy == n)].saving.mean() for n in names]))):
        ax.barh(y + (k - 1) * .27, values, .25, color=color, label=label)
        for yi, v in zip(y + (k - 1) * .27, values):
            if np.isfinite(v):
                ax.text(v + .5, yi, f"{v:.0f}%", va="center", fontsize=8, color=INK)
    ax.set(yticks=y, yticklabels=names, xlabel="saving over one day against 64 chains always on [%]", xlim=(0, 100),
           title="Same NS-3 traffic, three power models")
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right")
    save(fig, filename, note)


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_rows", 200)
    table, traced, simulated = symbol_table(), trace_sleeps(), ns3_sleeps()

    grouped = table.groupby(["cat", "profile", "chains", "symbol"], sort=False)
    out = grouped[["rel", "save"]].mean().join(grouped.save.agg(half_ci).rename("save_ci"))
    out.to_csv(paths.RESULTS / "threegpp.csv")
    print(out.round(2).to_string())
    print("\nPiovesan, same policies (saving % against 64 chains always on):")
    print(campaign.runs.groupby(["profile", "chains"])[["save", "save_sym"]].mean().round(1).to_string())

    grouped = traced.groupby(["cat", "profile", "state", "ssb"], sort=False)
    out = grouped[["off", "extra", "p95"]].mean().join(grouped.extra.agg(half_ci).rename("extra_ci"))
    out.to_csv(paths.RESULTS / "threegpp_sleep.csv")
    print("\nSleep on top of symbol + channel (estimate on the traces; off = time not awake %):")
    print(out.round(2).to_string())

    if len(simulated):
        grouped = simulated.groupby(["profile", "state", "ssb"], sort=False)
        out = grouped[["off", "extra", "max_p95", "loss"]].mean().join(grouped.extra.agg(half_ci).rename("extra_ci")) \
            .join(grouped.over.sum()).join(grouped.users.sum()).join(grouped.violations.sum()) \
            .join(grouped.seed.size().rename("runs"))
        out.to_csv(paths.RESULTS / "threegpp_ns3.csv")
        print("\nSame sleeps simulated in NS-3, Category 1 (over: burst users with p95 over the limit):")
        print(out.round(2).to_string())
        burst = campaign.burst
        print("without sleep, burst users over the limit:",
              {p: int((burst[(burst.profile == p) & (burst.chains == a)].p95_ms > campaign.LIMIT_MS).sum())
               for p, a in CASES.items()})

    print("\nOne day, hours 8/12/4, saving % against 64 chains always on (mean +- 95 % CI over seeds):")
    days = daily_savings(table, traced, simulated)
    days.to_csv(paths.RESULTS / "threegpp_daily.csv", index=False)
    print(days.round(2).to_string(index=False))
    plot(days)
