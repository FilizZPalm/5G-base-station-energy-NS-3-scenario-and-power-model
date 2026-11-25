"""Where raw data, generated results and figures live. Every script takes its paths from here."""
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parent.parent
RAW = ANALYSIS.parent / "ns-3.46.1"          # NS-3 outputs: RAW / "bs-results-..."
RESULTS = ANALYSIS / "results"               # generated CSV files
FIGURES = ANALYSIS / "figures"               # generated PNG files

for _d in (RESULTS, FIGURES):
    _d.mkdir(parents=True, exist_ok=True)
