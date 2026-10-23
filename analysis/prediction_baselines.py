"""Phase 10: how good is the congestion predictor compared with a trivial guess?

Most test samples are labelled High (almost every sample at high load), so a
model that always answers "High" already scores well on accuracy and on the
High-class F1. This script puts the deployed tree next to that trivial guess,
for all test samples and for each load level separately, using metrics that a
constant guess cannot game: balanced accuracy and the Matthews correlation
coefficient (MCC, 0 = no better than chance, 1 = perfect).

Needs train_model.py to have run (results/model/test_predictions.csv).
Writes results/model/prediction_baselines.csv.

Usage: .venv/bin/python analysis/prediction_baselines.py
"""

from pathlib import Path

import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, matthews_corrcoef, precision_score, recall_score

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "results" / "model"
HIGH = 2


def scores(label, pred):
    """Binary task: will the bottleneck be congested (High) 0.5 s from now?"""
    y, p = label == HIGH, pred == HIGH
    return {"high_share_%": 100 * y.mean(),
            "macro_f1_3class": f1_score(label, pred, average="macro"),
            "high_precision": precision_score(y, p, zero_division=0),
            "high_recall": recall_score(y, p),
            "high_f1": f1_score(y, p),
            "balanced_accuracy": balanced_accuracy_score(y, p),
            "mcc": matthews_corrcoef(y, p)}


def main():
    test = pd.read_csv(MODEL / "test_predictions.csv")
    rows = []
    for scope, part in [("all", test), ("medium", test[test.level == "medium"]),
                        ("high", test[test.level == "high"])]:
        always_high = pd.Series(HIGH, index=part.index)
        rows.append({"scope": scope, "model": "Decision Tree", **scores(part.label, part.pred_tree)})
        rows.append({"scope": scope, "model": "Always High", **scores(part.label, always_high)})
    table = pd.DataFrame(rows)
    table.round(3).to_csv(MODEL / "prediction_baselines.csv", index=False)
    print(table.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
