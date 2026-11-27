"""A small sketch of how OFDMA and TDMA fill one downlink slot (14 symbols x the resource blocks of a carrier), for the
README and step 8. Illustrative: three users with the same data; it shows the idea, not a simulated slot.

Run from analysis/:  ../.venv/bin/python -m studies.schedulers
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from lib.style import AQUA, BLUE, GRID, INK, MUTED, ORANGE, save

SYMBOLS, RBS = 14, 12    # a slot has 14 symbols; 12 resource blocks drawn (a real carrier has 80)
USERS = {"user A": BLUE, "user B": ORANGE, "user C": AQUA}


def slot(ax, title, cell):
    """Draw one slot. cell(symbol, rb) -> colour of that cell, or None if it is empty. Symbol 0 is the control
    symbol."""
    for symbol in range(SYMBOLS):
        for rb in range(RBS):
            color = MUTED if symbol == 0 else cell(symbol, rb)
            ax.add_patch(Rectangle((symbol + .06, rb + .06), .88, .88, facecolor=color or "white",
                                   edgecolor=GRID if color is None else "none", lw=.6))
    ax.set(xlim=(0, SYMBOLS), ylim=(0, RBS), xticks=[.5, 13.5], xticklabels=["1", "14"], yticks=[])
    ax.set_xlabel("symbols of one 0.5 ms slot (time)", fontsize=8)
    ax.set_ylabel("frequency (resource blocks)", fontsize=8)
    ax.tick_params(labelsize=8, length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(title, fontsize=10, color=INK, loc="left")


def ofdma(symbol, rb):
    """Each user gets 3 resource blocks for the whole slot (39 cells); the top of the band stays free."""
    return None if rb >= 9 else list(USERS.values())[rb // 3]


def tdma(symbol, rb):
    """Each user gets the whole band for 3 symbols (36 cells); the end of the slot stays empty."""
    return BLUE if symbol <= 3 else ORANGE if symbol <= 6 else AQUA if symbol <= 9 else None


if __name__ == "__main__":
    fig, (ax_ofdma, ax_tdma) = plt.subplots(1, 2, figsize=(9, 3.3))
    slot(ax_ofdma, "OFDMA: users share the band, every symbol is busy", ofdma)
    slot(ax_tdma, "TDMA: users take turns, the slot ends early", tdma)
    ax_ofdma.text(7.5, 10.5, "free resource blocks, but every symbol\ncarries data: amplifiers stay on", ha="center",
            va="center", fontsize=8, color=INK)
    ax_tdma.text(12, 6, "empty\nsymbols:\namplifiers\noff", ha="center", va="center", fontsize=8, color=INK)
    handles = [Rectangle((0, 0), 1, 1, color=color) for color in (*USERS.values(), MUTED)]
    fig.legend(handles, [*USERS, "control (always on)"], loc="upper center", ncol=4, frameon=False, fontsize=8,
               bbox_to_anchor=(.5, .93))
    fig.suptitle("Same data for three users, two ways to fill a downlink slot", fontsize=11, color=INK, y=.99)
    fig.subplots_adjust(top=.72)
    save(fig, "schedulers.png", "Sketch, not a simulated slot: a 30 MHz carrier has 80 resource blocks. Symbol 1 "
                                "carries the control channel with either scheduler.")
