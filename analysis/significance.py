"""Are the headline differences statistically significant? (Phase 12)

Each seed gives every variant the same traffic, so the runs are paired by seed.
For Predictive TCP against each baseline, at medium and high load, this script
tests drops, mean RTT and goodput with:

  - a paired t-test (two-sided) and the 95% confidence interval of the mean
    per-seed difference (Predictive minus baseline, in the metric's own unit);
  - an exact sign test (one-sided, in the direction of the observed difference).

A Wilcoxon signed-rank test is reported as well (two-sided, exact); with 10 seeds its
smallest possible p-value is 0.002 (with 5 seeds it was 0.0625, which is why Phase 12
relied on the t-test and the sign test).

Needs compare_variants.py to have run (results/comparison_runs.csv).
Writes results/significance.csv.

Usage: .venv/bin/python analysis/significance.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
BASELINES = ["reno", "cubic", "tahoe", "vegas", "bbr"]
LEVELS = ["medium", "high"]
METRICS = {"drops": "drops", "mean_rtt_ms": "RTT (ms)", "goodput_mbps": "goodput (Mbps)"}


def main():
    runs = pd.read_csv(RESULTS / "comparison_runs.csv")
    rows = []
    for level in LEVELS:
        part = runs[runs.level == level]
        pred = part[part.variant == "predictive"].set_index("seed")
        for base in BASELINES:
            other = part[part.variant == base].set_index("seed")
            for metric, label in METRICS.items():
                diff = (pred[metric] - other[metric]).dropna()
                n = len(diff)
                mean, sd = diff.mean(), diff.std(ddof=1)
                half = stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n) if n > 1 else np.nan
                t_p = stats.ttest_rel(pred.loc[diff.index, metric], other.loc[diff.index, metric]).pvalue
                below = int((diff < 0).sum())
                above = int((diff > 0).sum())
                # One-sided exact sign test in the direction of the mean difference (ties dropped)
                wins = below if mean < 0 else above
                sign_p = stats.binomtest(wins, below + above, 0.5, alternative="greater").pvalue \
                    if below + above else 1.0
                wilcoxon_p = stats.wilcoxon(diff).pvalue if (diff != 0).any() else 1.0
                rows.append({"level": level, "vs": base, "metric": label, "seeds": n,
                             "mean_diff": mean, "ci95_low": mean - half, "ci95_high": mean + half,
                             "baseline_mean": other.loc[diff.index, metric].mean(),
                             "seeds_lower": below, "seeds_higher": above,
                             "t_test_p": t_p, "wilcoxon_p": wilcoxon_p, "sign_test_p": sign_p})
    table = pd.DataFrame(rows)
    table.to_csv(RESULTS / "significance.csv", index=False, float_format="%.6g")
    show = table[table.vs.isin(["reno", "cubic"])]
    print(show.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
