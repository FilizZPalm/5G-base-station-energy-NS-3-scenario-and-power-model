"""Common look of the figures: colours, labels and how a figure is saved (with a note at the bottom)."""
import matplotlib
matplotlib.use("Agg")   # draw to files only, no window
import matplotlib.pyplot as plt

from lib import paths

OUT = paths.FIGURES
PROFILES = {"night": "Night (1 Mbit/s)", "day": "Day (40 Mbit/s)", "peak100": "Peak (100 Mbit/s)"}
CHAINS = (64, 32, 16)   # chain counts of the main campaign

# Colours: three series colours, then text and grid greys
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e1e0d9"

NOTE = "10 seeds, 10 s per run; SU-MIMO; neighbour cells at 64 chains"   # default note under a figure

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True})


def save(fig, name, note=NOTE, tight=True):
    """Save fig as figures/<name> with a small note at the bottom left, and close it. tight=False: the figure sets its
    own margins (tight_layout cannot place axes with a fixed aspect), keeping the bottom 6% free for the note."""
    if tight:
        fig.tight_layout(rect=(0, 0.06, 1, 1))   # leave the bottom 6% for the note
    fig.text(0.01, 0.01, note, fontsize=8, color=MUTED)
    fig.savefig(OUT / name, dpi=200, facecolor="white")
    plt.close(fig)
