"""Compare this machine's results with the macOS reference results.

The reference (reference/) was produced on macOS (Apple Silicon, clang 17,
NS-3.48). This script checks every result table, the generated C++ header,
the dataset and the graphs against it:

  - IDENTICAL: byte-for-byte the same as on macOS
  - DIFFERENT: for tables, it also reports the largest numeric difference, so a
    re-simulation on another system can be judged ("same to 3 significant figures")

Usage: .venv/bin/python analysis/verify_reference.py [--strict]
  --strict  exit with an error if any data file (not graph) differs
"""

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric_difference(produced, expected):
    """Largest absolute and relative difference between two CSV tables (numeric columns)."""
    try:
        a, b = pd.read_csv(produced), pd.read_csv(expected)
    except Exception:
        return None
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        return "different shape or columns"
    num = a.select_dtypes("number").columns.intersection(b.select_dtypes("number").columns)
    if len(num) == 0:
        return "text differs"
    x, y = a[num].to_numpy(float), b[num].to_numpy(float)
    absdiff = np.nanmax(np.abs(x - y))
    rel = np.nanmax(np.abs(x - y) / np.maximum(np.abs(y), 1e-12))
    return f"max abs diff {absdiff:.4g}, max rel diff {100 * rel:.3g}%"


def main():
    strict = "--strict" in sys.argv
    lines = [l for l in (REF / "SHA256SUMS").read_text().splitlines() if l and not l.startswith("#")]
    data_ok = data_total = graphs_ok = graphs_total = 0
    problems = []
    for line in lines:
        parts = line.split()
        digest, rel, kind = parts[0], parts[1], (parts[2] if len(parts) > 2 else "data")
        if kind == "archive":
            continue
        path = ROOT / rel
        if kind == "graph":
            graphs_total += 1
            graphs_ok += path.exists() and sha256(path) == digest
            continue
        data_total += 1
        if not path.exists():
            problems.append(f"MISSING    {rel}")
        elif sha256(path) == digest:
            data_ok += 1
        else:
            detail = ""
            expected = REF / "expected" / rel
            if path.suffix == ".csv" and expected.exists():
                detail = numeric_difference(path, expected) or ""
            problems.append(f"DIFFERENT  {rel}" + (f"  ({detail})" if detail else ""))

    print(f"Data files identical to the macOS reference: {data_ok}/{data_total}")
    print(f"Graphs identical (informational; font rendering can differ by system): {graphs_ok}/{graphs_total}")
    for p in problems:
        print("  " + p)
    if not problems:
        print("RESULT: every result is IDENTICAL to the macOS reference.")
    else:
        print("RESULT: some results differ from the macOS reference (see above).")
    if strict and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
