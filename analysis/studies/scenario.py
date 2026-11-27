"""A map of the simulated scenario (geometry and radio settings of ns-3.46.1/scratch/bs-energy.cc), for the README.
The sites, distances and radio settings are those of the program. The user positions are only an example: NS-3 draws
them per seed and keeps a user only if its own site is the strongest, shadowing included, which is not reproduced here.

Panels: the map of the three sites (left), the active chains of the array, the two carriers and the TDD frame (right).
Run from analysis/:  ../.venv/bin/python -m studies.scenario
"""
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Polygon, Rectangle

from lib.style import BLUE, GRID, INK, MUTED, ORANGE, save

RADIUS, MIN_R, UES = 250, 35, 10                      # cell radius [m], minimum user distance [m], users per site
ISD = 2 * RADIUS                                      # inter-site distance [m]
SITES = np.array([[0, 0]] + [[ISD * np.cos(2 * np.pi * g / 6), ISD * np.sin(2 * np.pi * g / 6)] for g in (1, 2)])
SHAPES = {64: (8, 8), 48: (6, 8), 32: (4, 8), 24: (4, 6), 16: (4, 4)}   # rows x columns of elements


def example_users(rng):
    """10 users per site, uniform in the 35-250 m ring, kept only if their own site is the nearest."""
    out = []
    for s in SITES:
        pts = []
        while len(pts) < UES:
            r, t = np.sqrt(rng.uniform(MIN_R**2, RADIUS**2)), rng.uniform(0, 2 * np.pi)
            p = s + r * np.array([np.cos(t), np.sin(t)])
            if np.argmin(np.linalg.norm(SITES - p, axis=1)) == len(out):
                pts.append(p)
        out.append(np.array(pts))
    return out


def clean(ax):
    """No grid and no frame."""
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)


def antenna(ax, x, y, color, k=1.0):
    """A small mast with an antenna panel and radio waves; (x, y) is the foot of the mast, k the scale (1 = 100 m)."""
    legs = [(x - 16 * k, y), (x - 4 * k, y + 62 * k), (x + 4 * k, y + 62 * k), (x + 16 * k, y)]
    ax.add_patch(Polygon(legs, closed=True, fill=False, edgecolor=color, lw=1.4, joinstyle="round", zorder=6))
    for f in (.25, .5, .75):                                            # lattice: cross bars and diagonals
        w = 16 - 12 * f
        ax.plot([x - w * k, x + w * k], [y + 62 * f * k] * 2, color=color, lw=.8, zorder=6)
    ax.plot([x - 16 * k, x + 10 * k, x - 7 * k, x + 4 * k], [y, y + 31 * k, y + 46 * k, y + 62 * k],
            color=color, lw=.6, zorder=6)
    ax.add_patch(FancyBboxPatch((x - 7 * k, y + 60 * k), 14 * k, 30 * k, boxstyle=f"round,pad=0,rounding_size={3 * k}",
                                facecolor=color, edgecolor="white", lw=.8, zorder=7))
    for r in (22, 36):                                                  # radio waves on both sides of the panel
        for t1, t2 in ((-45, 45), (135, 225)):
            ax.add_patch(Arc((x, y + 75 * k), 2 * r * k, 2 * r * k, theta1=t1, theta2=t2, color=color, lw=1.2,
                             zorder=6))


def phone(ax, x, y, color, k=1.0):
    """A small smartphone centred at (x, y)."""
    ax.add_patch(FancyBboxPatch((x - 7 * k, y - 12 * k), 14 * k, 24 * k, boxstyle=f"round,pad=0,rounding_size={3 * k}",
                                facecolor=color, edgecolor="white", lw=.6, zorder=4))
    ax.add_patch(Rectangle((x - 5 * k, y - 7 * k), 10 * k, 16 * k, facecolor="white", alpha=.55, lw=0, zorder=4))


def draw_map(ax):
    users = example_users(np.random.default_rng(4))
    for g, (s, u) in enumerate(zip(SITES, users)):
        color = BLUE if g == 0 else MUTED
        ax.add_patch(Circle(s, RADIUS, facecolor=color, alpha=.12 if g == 0 else .07, edgecolor=color, lw=1.2,
                            ls="-" if g == 0 else "--"))
        for p in u:
            phone(ax, *p, color, 1.4)
        antenna(ax, s[0], s[1] - 45, ORANGE if g == 0 else MUTED, 1.5)
        name = "Cell 0: measured, saves energy" if g == 0 else f"Neighbour {g}: interference"
        y_name = s[1] - RADIUS - 8 if g == 0 else s[1] + RADIUS + 18      # cell 0: below its circle; others: above
        ax.text(s[0], y_name, name, ha="center", va="top" if g == 0 else "bottom",
                fontsize=9, color=INK, weight="bold" if g == 0 else "normal", zorder=8,
                bbox=dict(fc="white", ec="none", alpha=.8, pad=1))
    ax.annotate("", SITES[1], SITES[0], arrowprops=dict(arrowstyle="<->", color=INK, lw=1, shrinkA=4, shrinkB=22))
    mid = SITES[1] / 2
    ax.text(mid[0] + 22, mid[1] - 14, "500 m", fontsize=9, color=INK, rotation=60, ha="center", va="center")
    ax.plot([0, RADIUS], [0, 0], color=INK, lw=1)
    ax.text(RADIUS * .62, 10, "250 m", fontsize=9, color=INK, ha="center")
    ax.set(xlim=(-520, 520), ylim=(-520, 800), aspect="equal", xticks=[], yticks=[])   # top: room for the names
    clean(ax)
    ax.set_title("3 sites, 10 users each (urban macro, 3GPP UMa)", fontsize=11, color=INK)
    antenna(ax, -500, -352, INK, .45)
    ax.text(-470, -330, "site: one AAU on a 25 m mast", fontsize=8.5, color=INK, va="center")
    phone(ax, -500, -375, INK, 1.4)
    ax.text(-470, -375, "user: 1.5 m high, attached to the strongest site", fontsize=8.5, color=INK, va="center")
    ax.text(-515, -410, "Traffic per cell (10 s per level, 10 seeds):\n"
            "  night  1 Mbit/s, 2 active users\n  day  40 Mbit/s, 10 burst users\n"
            "  peak  100 Mbit/s, 3 video + 7 burst users", fontsize=8.5, color=INK, va="top")


def draw_array(ax):
    x = 0
    for a, (r, c) in SHAPES.items():
        for i in range(8):
            for j in range(8):
                on = i < r and j < c
                ax.add_patch(Rectangle((x + j + .1, i + .1), .8, .8, facecolor=BLUE if on else GRID, edgecolor="none"))
        ax.text(x + 4, -1, f"{a} chains\n{r}×{c}", ha="center", va="top", fontsize=8, color=INK)
        x += 9.5
    ax.set(xlim=(-.3, x - 1.2), ylim=(-3.6, 8.2), aspect="equal", xticks=[], yticks=[])
    clean(ax)
    ax.set_title("Antenna array: active chains (channel shutdown)", fontsize=10, color=INK, loc="left")


def draw_carriers(ax):
    for k, (f0, name) in enumerate(((3470, "carrier 1"), (3500, "carrier 2"))):
        ax.add_patch(Rectangle((f0, 0), 30, 1, facecolor=BLUE if k == 0 else "#6fa3e3", edgecolor="white", lw=2))
        ax.text(f0 + 15, .5, f"{name}: 30 MHz\n80 resource blocks", ha="center", va="center", fontsize=8, color="white")
    ax.set(xlim=(3460, 3540), ylim=(0, 1), yticks=[], xticks=[3470, 3500, 3530])
    ax.set_xlabel("frequency [MHz], band n78. 1 resource block = 12 subcarriers × 30 kHz", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(False)
    for k in ("left", "top", "right"):
        ax.spines[k].set_visible(False)
    ax.set_title("Two contiguous 30 MHz carriers", fontsize=10, color=INK, loc="left")


def draw_frame(ax):
    kinds = [("downlink", BLUE), ("downlink", BLUE), ("downlink", BLUE), ("special", "#6fa3e3"), ("uplink", ORANGE)]
    for i, (k, color) in enumerate(kinds):
        ax.add_patch(Rectangle((i, 0), 1, 1, facecolor=color, edgecolor="white", lw=2))
        ax.text(i + .5, .5, k, ha="center", va="center", fontsize=8.5, color="white", weight="bold")
    ax.set(xlim=(0, 5), ylim=(0, 1), yticks=[], xticks=np.arange(6), xticklabels=[f"{.5 * i:g}" for i in range(6)])
    ax.set_xlabel("time [ms], 14 symbols per slot; then repeats", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(False)
    for k in ("left", "top", "right"):
        ax.spines[k].set_visible(False)
    ax.set_title("TDD pattern DDDSU, 0.5 ms slots", fontsize=10, color=INK, loc="left")


if __name__ == "__main__":
    fig = plt.figure(figsize=(11, 5.6))
    gs = fig.add_gridspec(3, 2, width_ratios=(.8, 1), height_ratios=(1.5, .8, .8), wspace=.08, hspace=1.0,
                          left=.01, right=.99, top=.94, bottom=.13)    # bottom: x labels and the note
    draw_map(fig.add_subplot(gs[:, 0]))
    draw_array(fig.add_subplot(gs[0, 1]))
    draw_carriers(fig.add_subplot(gs[1, 1]))
    draw_frame(fig.add_subplot(gs[2, 1]))
    save(fig, "scenario.png", "Geometry and radio settings from bs-energy.cc; user positions are an example (NS-3 "
                              "draws them per seed, shadowing included). 104.9 W radiated at 64 chains, SU-MIMO with "
                              "2 layers.", tight=False)
