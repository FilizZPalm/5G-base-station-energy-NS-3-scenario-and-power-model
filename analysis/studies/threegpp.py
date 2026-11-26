"""The 3GPP power model (TR 38.864, clause 5.1) on the NS-3 traces: symbol and channel shutdown, then light and
deep sleep with the transition times and energies of the same report. Compared with Piovesan.

Power is built symbol by symbol from the slot traces of cell 0 (pattern DDDSU, 14 symbols per slot):
- control symbol: always transmitted, ASSUMPTION over the whole carrier;
- DL data symbol in use: RBs in use = used_reg / used_sym (the same in every used symbol of the slot);
- empty DL symbol: micro sleep (immediate, as in the TR) with symbol shutdown, else RUs on without output;
- UL symbols (U slot, and the last symbol of the S slot): active UL, ASSUMPTION (no UL data is simulated);
- second carrier x 0.7 (contiguous carriers); sleep states and transition energies also x 1.7 (ASSUMPTION).
Light and deep sleep: the trace estimate of studies.wakeup, total transition time T = 2 Tw."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lib import campaign as c, ns3data, paths, power as pw
from lib.style import AQUA, BLUE, CHAINS, INK, ORANGE, PROFILES, save
from studies.daily import HOURS, POLICIES, half_ci
from studies.wakeup import CASES, FIRST, N, SLOT_MS, run

SYM, CC = 14, 1 + pw.TGPP_EXTRA_CC
SSB = {"SSB 20 ms": 20, "SSB 160 ms": 160, "no SSB": 0}
seeds = range(1, c.SEEDS + 1)


def slot_power(prefix, chains, symbol, cat):
    """Mean power of each slot of the measured window [relative units]; and of an empty awake slot."""
    s = pd.read_csv(f"{prefix}_slots.csv")
    s = s[(s.slot >= FIRST) & (s.slot < FIRST + N)]
    sa, p = chains / 64, pw.TGPP[cat]
    ctrl, ul = pw.tgpp_dl_symbol(80, sa, cat), pw.tgpp_ul_symbol(sa, cat)
    empty = p["micro"] if symbol else pw.tgpp_dl_symbol(0, sa, cat)
    rb = np.where(s.used_sym > 0, s.used_reg / s.used_sym.clip(lower=1), 0)
    e = (ctrl + s.used_sym * pw.tgpp_dl_symbol(rb, sa, cat) + (s.avail_sym - s.used_sym) * empty
         + (SYM - 1 - s.avail_sym) * ul) * np.where(s.carrier == 0, 1, pw.TGPP_EXTRA_CC)
    out = np.full(N, SYM * ul * CC)                       # UL slots are not in the trace
    dl = e.groupby(s.slot).sum()
    out[dl.index.to_numpy() - FIRST] = dl.to_numpy()
    # An empty awake frame (3 D + 1 S + 1 U slots), averaged per slot
    d = ctrl + 13 * empty
    sp = ctrl + 12 * empty + ul
    idle = (3 * d + sp + SYM * ul) / 5 * CC
    return out / SYM, idle / SYM


def sleep_power(base, idle, off, sleeps, state, cat):
    """Mean power with sleeps: the time not awake costs the sleep state, plus the energy of each transition."""
    p = pw.TGPP[cat]
    return base - off * (idle - p[state] * CC) + sleeps * p[f"e_{state}"] * CC / (N * SLOT_MS)


rows, sleeps = [], []
for cat in (1, 2):
    for prof in HOURS:
        for a in CHAINS:
            for r in seeds:
                for symbol in (False, True):
                    x, idle = slot_power(c.RAW / f"{prof}_a{a}_r{r}", a, symbol, cat)
                    rows.append(dict(cat=cat, profile=prof, chains=a, seed=r, symbol=symbol, rel=x.mean(), idle=idle))
d = pd.DataFrame(rows)
on = d[(d.chains == 64) & ~d.symbol].set_index(["cat", "profile", "seed"]).rel
d["save"] = 100 * (1 - d.rel / [on[k] for k in zip(d.cat, d.profile, d.seed)])

# Light and deep sleep on top of symbol + channel shutdown (chains of studies.wakeup), estimate on the traces
w = d[d.symbol].set_index(["cat", "profile", "chains", "seed"])
from studies.wakeup import trace  # noqa: E402
for prof, a in CASES.items():
    tr = {r: trace(prof, a, r) for r in seeds}
    for cat in (1, 2):
        p = pw.TGPP[cat]
        for state in ("light", "deep"):
            tw = round(p[f"t_{state}"] / 2 / SLOT_MS)
            for name, ssb in SSB.items():
                if ssb and 2 * tw >= ssb / SLOT_MS:
                    continue                                    # no room between two SSBs
                if 2 * tw >= N:
                    continue                                    # longer than the simulated window
                for r in seeds:
                    asleep, dly, _, off, n = run(*tr[r], tw, round(ssb / SLOT_MS), 2 * tw)
                    base, idle = w.loc[(cat, prof, a, r), ["rel", "idle"]]
                    sleeps.append(dict(cat=cat, profile=prof, chains=a, state=state, ssb=name, seed=r, off=100 * off,
                                       rel=sleep_power(base, idle, off, n, state, cat), base=base,
                                       on=on[(cat, prof, r)], p95=np.percentile(dly, 95) if len(dly) else 0))
z = pd.DataFrame(sleeps)
z["extra"] = 100 * (1 - z.rel / z.base)

# The same sleeps simulated in NS-3 (Category 1 only: Category 2 needs 640 ms or 10 s), Tw = T / 2
WAKE = paths.RAW / "bs-results-wake3gpp"
NS3 = [("night", "light", 20), ("night", "light", 160), ("night", "deep", 160), ("day", "light", 20),
       ("peak100", "light", 20)]
ns3 = []
for prof, state, ssb in NS3:
    a, p = CASES[prof], pw.TGPP[1]
    tw = p[f"t_{state}"] / 2
    for r in seeds:
        o = WAKE / f"{prof}_a{a}_t{tw:g}_s{ssb}_r{r}"
        if not o.with_name(o.name + "_sleep.csv").exists():
            continue
        x, idle = slot_power(o, a, True, 1)
        k = pd.read_csv(f"{o}_sleep.csv").iloc[0]
        tot = k[["awake", "down", "sleep", "up"]].sum()
        off, n = (tot - k.awake) / tot, k.down / (tw / SLOT_MS)
        f = pd.read_csv(f"{o}_flows.csv")
        b = 1e3 * f[f.kind == "burst"].delay_p95_s
        base = w.loc[(1, prof, a, r), "rel"]
        ns3.append(dict(cat=1, profile=prof, state=state, ssb=f"SSB {ssb} ms", seed=r, off=100 * off,
                        rel=sleep_power(x.mean(), idle, off, n, state, 1), base=base, violations=k.violations,
                        over=int((b > c.LIMIT_MS).sum()), users=len(b), max_p95=b.max(), loss=100 * (1 - f.rx_pkts.sum() / f.tx_pkts.sum())))
sim = pd.DataFrame(ns3)
if len(sim):
    sim["extra"] = 100 * (1 - sim.rel / sim.base)

if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_rows", 200)
    g = d.groupby(["cat", "profile", "chains", "symbol"], sort=False)
    t = g[["rel", "save"]].mean().join(g.save.agg(half_ci).rename("save_ci"))
    t.to_csv(paths.RESULTS / "threegpp.csv")
    print(t.round(2).to_string())
    print("\nPiovesan, same policies (saving % against 64 chains always on):")
    print(c.runs.groupby(["profile", "chains"])[["save", "save_sym"]].mean().round(1).to_string())

    q = z.groupby(["cat", "profile", "state", "ssb"], sort=False)
    s = q[["off", "extra", "p95"]].mean().join(q.extra.agg(half_ci).rename("extra_ci"))
    s.to_csv(paths.RESULTS / "threegpp_sleep.csv")
    print("\nSleep on top of symbol + channel (estimate on the traces; off = time not awake %):")
    print(s.round(2).to_string())
    if len(sim):
        q = sim.groupby(["profile", "state", "ssb"], sort=False)
        n3 = q[["off", "extra", "max_p95", "loss"]].mean().join(q.extra.agg(half_ci).rename("extra_ci")) \
            .join(q.over.sum()).join(q.users.sum()).join(q.violations.sum()).join(q.seed.size().rename("runs"))
        n3.to_csv(paths.RESULTS / "threegpp_ns3.csv")
        print("\nSame sleeps simulated in NS-3, Category 1 (over: burst users with p95 over the limit):")
        print(n3.round(2).to_string())
        print("without sleep, burst users over the limit:", {p: int((c.burst[(c.burst.profile == p) & (c.burst.chains == a)]
                                                                      .p95_ms > c.LIMIT_MS).sum()) for p, a in CASES.items()})

    print("\nOne day, hours 8/12/4, saving % against 64 chains always on (mean +- 95 % CI over seeds):")
    lv = lambda cat, prof, a, sym: d[(d.cat == cat) & (d.profile == prof) & (d.chains == a) & (d.symbol == sym)] \
        .sort_values("seed").rel.to_numpy()
    def sl(cat, prof, state, ssb):
        # NS-3 when all seeds are there, else the trace estimate
        for src in (sim, z):
            if len(src):
                x = src[(src.cat == cat) & (src.profile == prof) & (src.state == state) & (src.ssb == ssb)]
                if len(x) == c.SEEDS:
                    return x.sort_values("seed").rel.to_numpy()
        return np.array([])
    days = []
    for cat in (1, 2):
        ref = sum(h * lv(cat, p, 64, False) for p, h in HOURS.items())
        pol = {n: {p: lv(cat, p, *v) for p, v in POLICIES[n].items()} for n in POLICIES}
        best = pol["symbol + channel"]
        for name, ssb in (("+ light sleep everywhere", "SSB 20 ms"), ("+ light sleep at night", "SSB 160 ms"),
                          ("+ light sleep at night", "no SSB"), ("+ deep sleep at night", "SSB 160 ms"),
                          ("+ deep sleep at night", "no SSB")):
            state = name.split()[1]
            night = sl(cat, "night", state, ssb)
            if not len(night):
                continue
            lv_ = dict(best, night=night)
            if "everywhere" in name:
                lv_ = {p: sl(cat, p, state, ssb) for p in HOURS}
                if any(not len(v) for v in lv_.values()):
                    continue
            pol[f"{name} ({ssb})"] = lv_
        for n, levels in pol.items():
            e = sum(h * levels[p] for p, h in HOURS.items())
            v = 100 * (1 - e / ref)
            days.append(dict(cat=cat, policy=n, saving=v.mean(), ci=half_ci(v)))
    days = pd.DataFrame(days)
    days.to_csv(paths.RESULTS / "threegpp_daily.csv", index=False)
    print(days.round(2).to_string(index=False))

    # Figure: saving of one day, Piovesan against 3GPP Category 1 and 2
    from studies.daily import energy
    piov = {n: 100 * (1 - energy(n, HOURS) / energy("always on", HOURS)).mean() for n in POLICIES}
    names = [n for n in days[days.cat == 1].policy if n != "always on"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(names))
    for k, (lab, color, vals) in enumerate((
            ("Piovesan", BLUE, [piov.get(n, np.nan) for n in names]),
            ("3GPP Category 1", ORANGE, [days[(days.cat == 1) & (days.policy == n)].saving.mean() for n in names]),
            ("3GPP Category 2", AQUA, [days[(days.cat == 2) & (days.policy == n)].saving.mean() for n in names]))):
        ax.barh(y + (k - 1) * .27, vals, .25, color=color, label=lab)
        for yi, v in zip(y + (k - 1) * .27, vals):
            if np.isfinite(v):
                ax.text(v + .5, yi, f"{v:.0f}%", va="center", fontsize=8, color=INK)
    ax.set(yticks=y, yticklabels=names, xlabel="saving over one day against 64 chains always on [%]", xlim=(0, 100),
           title="Same NS-3 traffic, three power models")
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right")
    save(fig, "threegpp.png", "Hours 8/12/4. Sleep: NS-3 where simulated, else trace estimate; no bar: not possible.\n"
                              "Deep sleep at night puts every night burst user over 20 ms. 10 seeds")
