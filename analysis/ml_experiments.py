"""Phase 6: which features and which prediction horizon work best?

Trains a Decision Tree (same procedure as train_model.py: depth chosen by
cross-validation on seeds 1-3, tested on seeds 4-5) for every combination of

  - feature set: loss only, delay only, the Phase 2 set, and the full set
  - horizon:     labels 0.2 s, 0.5 s and 1.0 s ahead

and writes results/model/experiments.csv and two graphs. This answers
"does the tree learn more than a loss count?" and "how far ahead can it see?".

Usage: .venv/bin/python analysis/ml_experiments.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from build_dataset import build
from train_model import TEST_SEEDS, TRAIN_SEEDS, choose_depth, early_warning, evaluate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "model" / "experiments.csv"
GRAPHS = ROOT / "results" / "graphs"

FEATURE_SETS = {
    "Loss only": ["loss_recent", "loss_2s", "since_loss"],
    "Delay only": ["rtt_ratio", "rtt_grad", "est_queue_pkts", "rtt_trend_05", "rtt_trend_1", "rtt_vs_avg"],
    "Phase 2 set": ["rtt_ratio", "rtt_grad", "est_queue_pkts", "cwnd_rel", "loss_recent", "loss_2s"],
    "Full set": ["rtt_ratio", "rtt_grad", "est_queue_pkts", "cwnd_rel", "loss_recent", "loss_2s",
                 "rtt_trend_05", "rtt_trend_1", "rtt_vs_avg", "since_loss"],
}
HORIZONS = [0.2, 0.5, 1.0]
COLORS = {"Loss only": "#c0392b", "Delay only": "#8e44ad", "Phase 2 set": "#2e86c1", "Full set": "#1e8449"}


def main():
    rows = []
    for horizon in HORIZONS:
        data = build(horizon)
        train = data[data.seed.isin(TRAIN_SEEDS)]
        test = data[data.seed.isin(TEST_SEEDS)].copy()
        for name, features in FEATURE_SETS.items():
            depth, _ = choose_depth(train[features], train.label, train.seed)
            tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50, class_weight="balanced",
                                          random_state=0).fit(train[features], train.label)
            test["pred"] = tree.predict(test[features])
            leads, false_alarms = early_warning(test, "pred")
            used = [f for f, imp in zip(features, tree.feature_importances_) if imp > 0]
            rows.append({"horizon_s": horizon, "features": name, "depth": depth,
                         "leaves": int(tree.get_n_leaves()),
                         **{k: v for k, v in evaluate(name, test.label, test.pred).items() if k != "model"},
                         "warned_200ms_pct": (leads >= 0.2).mean() * 100,
                         "false_alarm_pct": false_alarms,
                         "features_used": " ".join(used)})
            print(f"horizon {horizon} s, {name:12s}: depth {depth}, macro-F1 {rows[-1]['macro_f1']:.3f}, "
                  f"High recall {rows[-1]['high_recall']:.3f}, uses {used}")
    results = pd.DataFrame(rows)
    results.round(4).to_csv(OUT, index=False)

    # ---- Graph 1: macro-F1 and High recall for every feature set and horizon
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=150, sharey=True)
    x = np.arange(len(HORIZONS))
    for ax, (col, label) in zip(axes, [("macro_f1", "Macro-F1"), ("high_recall", "Recall (High)")]):
        for k, name in enumerate(FEATURE_SETS):
            part = results[results.features == name].set_index("horizon_s")
            bars = ax.bar(x + (k - 1.5) * 0.2, part.loc[HORIZONS, col], 0.2, color=COLORS[name], label=name)
            ax.bar_label(bars, fmt="%.2f", fontsize=6.5, padding=1)
        ax.set_xticks(x, [f"{h} s ahead" for h in HORIZONS])
        ax.set_title(label, fontsize=10, weight="bold")
        ax.set_ylim(0, 1.05)
        ax.grid(alpha=0.3, axis="y")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=len(FEATURE_SETS), fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 0.93))
    fig.suptitle("Decision Tree quality by feature set and prediction horizon (test seeds 4-5)", weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(GRAPHS / "ml_feature_sets.png")
    plt.close(fig)

    # ---- Graph 2: early warning vs false alarms at the deployed horizon (0.5 s)
    part = results[results.horizon_s == 0.5].set_index("features")
    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
    # Feature sets that land on the same point share one label
    points = {}
    for name in FEATURE_SETS:
        xy = (round(part.loc[name, "false_alarm_pct"], 2), round(part.loc[name, "warned_200ms_pct"], 2))
        points.setdefault(xy, []).append(name)
    for (fx, wy), names in points.items():
        ax.scatter(fx, wy, s=90, color=COLORS[names[-1]], edgecolor="black" if "Full set" in names else "none",
                   label=" = ".join(names))
        ax.annotate(" = ".join(names), (fx, wy), textcoords="offset points", xytext=(0, 9), ha="center",
                    fontsize=8)
    ax.margins(x=0.15, y=0.12)
    ax.set_xlabel("False alarms (% of High predictions with no drop in the next 1 s)")
    ax.set_ylabel("Drop bursts warned ≥ 200 ms ahead (%)")
    ax.set_title("Early warning vs false alarms (0.5 s horizon; upper-left is better)", fontsize=10, weight="bold")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_warning_tradeoff.png")
    plt.close(fig)

    print("\n" + results.drop(columns="features_used").round(3).to_string(index=False))


if __name__ == "__main__":
    main()
