"""Plot existing real benchmark CSV files; does not generate measurements."""
import argparse
import csv
import os
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="+")
    parser.add_argument("--output", default="benchmark/comparison.png")
    args = parser.parse_args()
    cache = tempfile.mkdtemp(prefix="dlumen-mpl-")
    os.environ.setdefault("MPLCONFIGDIR", cache)
    os.environ.setdefault("XDG_CACHE_HOME", cache)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("Install matplotlib dari requirements.txt") from exc
    rows = []
    for filename in args.csv:
        with open(filename, newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    if not rows: raise SystemExit("Tidak ada hasil benchmark")
    labels = [f"{r.get('scheduling',r['mode'])}\n{r.get('workers',r.get('processors','?'))} node" for r in rows]
    seconds = [float(r["execution_seconds"]) for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5)); ax.bar(labels, seconds)
    ax.set_ylabel("Execution time (seconds)"); ax.set_title("D-LUMEN Real Benchmark")
    fig.tight_layout(); Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160); print(args.output)


if __name__ == "__main__": main()
