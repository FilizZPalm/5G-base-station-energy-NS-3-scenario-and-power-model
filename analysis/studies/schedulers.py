"""A small sketch of how OFDMA and TDMA fill one downlink slot (14 symbols x the resource blocks of a carrier), for the
README. Illustrative: three users with the same data; it shows the idea, not a simulated slot."""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from lib.style import AQUA, BLUE, GRID, INK, MUTED, ORANGE, save

SYMBOLS, RBS = 14, 12
USERS = {"user A": BLUE, "user B": ORANGE, "user C": AQUA}


def slot(ax, title, cell):
    """cell(symbol, rb) -> color, or None for an empty symbol."""
    for t in range(SYMBOLS):
        for f in range(RBS):
            c = MUTED if t == 0 else cell(t, f)
            ax.add_patch(Rectangle((t + .06, f + .06), .88, .88, facecolor=c or "white", edgecolor=GRID if c is None else "none",
                                   lw=.6))
    ax.set(xlim=(0, SYMBOLS), ylim=(0, RBS), xticks=[.5, 13.5], xticklabels=["1", "14"], yticks=[])
    ax.set_xlabel("symbols of one 0.5 ms slot (time)", fontsize=8)
    ax.set_ylabel("frequency (resource blocks)", fontsize=8)
    ax.tick_params(labelsize=8, length=0)
    ax.grid(False)
    for k in ax.spines.values():
        k.set_visible(False)
    ax.set_title(title, fontsize=10, color=INK, loc="left")


def ofdma(t, f):          # each user gets 3 resource blocks for the whole slot (39 cells); the top of the band stays free
    return None if f >= 9 else list(USERS.values())[f // 3]


def tdma(t, f):           # each user gets the whole band for 3 symbols (36 cells); the end of the slot stays empty
    return BLUE if t <= 3 else ORANGE if t <= 6 else AQUA if t <= 9 else None


if __name__ == "__main__":
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.3))
    slot(a1, "OFDMA: users share the band, every symbol is busy", ofdma)
    slot(a2, "TDMA: users take turns, the slot ends early", tdma)
    a1.text(7.5, 10.5, "free resource blocks, but every symbol\ncarries data: amplifiers stay on", ha="center",
            va="center", fontsize=8, color=INK)
    a2.text(12, 6, "empty\nsymbols:\namplifiers\noff", ha="center", va="center", fontsize=8, color=INK)
    handles = [Rectangle((0, 0), 1, 1, color=c) for c in (*USERS.values(), MUTED)]
    fig.legend(handles, [*USERS, "control (always on)"], loc="upper center", ncol=4, frameon=False, fontsize=8,
               bbox_to_anchor=(.5, .93))
    fig.suptitle("Same data for three users, two ways to fill a downlink slot", fontsize=11, color=INK, y=.99)
    fig.subplots_adjust(top=.72)
    save(fig, "schedulers.png", "Sketch, not a simulated slot: a 30 MHz carrier has 80 resource blocks. Symbol 1 carries the "
                                "control channel with either scheduler.")
