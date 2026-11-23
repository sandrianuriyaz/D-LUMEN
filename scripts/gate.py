"""Reproducible pre-demo verification gate."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, command: list[str]):
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"GATE FAILED: {label} (exit {result.returncode})")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--quick", action="store_true")
    parser.add_argument("--workers", type=int, default=2); args = parser.parse_args()
    run("COMPILE", [sys.executable, "-m", "compileall", "-q", "parallel", "benchmark", "database", "scripts", "tests"])
    run("TEST", [sys.executable, "-m", "pytest", "-q"])
    if not args.quick:
        run("E2E", [sys.executable, "scripts/e2e_local.py", "--workers", str(args.workers)])
    print("\nGATE OK")


if __name__ == "__main__": main()
