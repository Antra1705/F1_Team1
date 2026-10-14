"""Phase 2, step 2: train and evaluate the congestion predictors.

- Decision Tree (depth chosen by cross-validation, max depth 5) and
  Logistic Regression, both with balanced class weights.
- Train on seeds 1-3, test on seeds 4-5 (test runs are never seen in training).
- Compared with a reactive, loss-based detector (what classic TCP knows).
- Early warning: how long before each burst of bottleneck drops the model
  first predicts High.

Usage: .venv/bin/python analysis/train_model.py
"""

import json
import os
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix, f1_score,
                             precision_recall_fscore_support)
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, plot_tree

from build_dataset import FEATURES, HORIZON, LABEL_NAMES

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "results" / "dataset.csv"
MODEL_DIR = ROOT / "results" / "model"
GRAPHS = ROOT / "results" / "graphs"

# Features the deployed model may use. Throughput and absolute cwnd are left out:
# they describe the sender's own rate, so once the model controls that rate it
# would read its own slowdown as congestion and keep slowing down (feedback loop).
# Phase 6 chose the delay features by testing candidates inside NS-3
# (analysis/select_model.py); Phase 2 used
# rtt_ratio,rtt_grad,est_queue_pkts,cwnd_rel,loss_recent,loss_2s.
MODEL_FEATURES = os.environ.get(
    "MODEL_FEATURES",
    "rtt_ratio,rtt_grad,est_queue_pkts,rtt_trend_05,rtt_trend_1,rtt_vs_avg").split(",")

TRAIN_SEEDS = [1, 2, 3]
TEST_SEEDS = [4, 5]
DEPTHS = [2, 3, 4, 5]
HIGH = 2


def choose_depth(X, y, groups):
    scores = {}
    for depth in DEPTHS:
        tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50,
                                      class_weight="balanced", random_state=0)
        scores[depth] = cross_val_score(tree, X, y, groups=groups, cv=GroupKFold(n_splits=3),
                                        scoring="f1_macro").mean()
    best = max(scores.values())
    # Smallest depth within 0.005 of the best: lighter model, same quality
    depth = min(d for d, s in scores.items() if s >= best - 0.005)
    return depth, scores


def evaluate(name, y_true, y_pred):
    p, r, f, _ = precision_recall_fscore_support(y_true == HIGH, y_pred == HIGH, average="binary",
                                                 zero_division=0)
    return {
        "model": name,
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
        "high_precision": p,
        "high_recall": r,
        "high_f1": f,
    }


def early_warning(test, pred_col, lookback=1.0, interval=0.1):
    """Lead time (s) of a continuous High prediction before each drop burst,
    and the false-alarm rate: time steps predicted High with no drop in the next 1 s."""
    leads = []
    alarms = false_alarms = 0
    for _, run in test.groupby(["variant", "level", "seed"]):
        steps = run.groupby("time").agg(drops=("drops_now", "first"),
                                        high=(pred_col, lambda s: (s == HIGH).any()))
        steps = steps.reindex(np.round(np.arange(steps.index.min(), steps.index.max() + 1e-9,
                                                 interval), 3), fill_value=0)
        times = steps.index.values
        drops = steps.drops.values > 0
        high = steps.high.values.astype(bool)
        quiet = int(round(0.5 / interval))
        ahead = int(round(1.0 / interval))
        for i in range(len(times) - ahead):
            if high[i]:
                alarms += 1
                false_alarms += not drops[i + 1:i + 1 + ahead].any()
        for i in range(quiet, len(times)):
            if drops[i] and not drops[i - quiet:i].any():   # start of a drop burst
                lead, j = 0.0, i - 1
                while j >= 0 and high[j] and times[i] - times[j] <= lookback + 1e-9:
                    lead = times[i] - times[j]
                    j -= 1
                leads.append(round(lead, 3))
    return np.array(leads), (100.0 * false_alarms / alarms if alarms else 0.0)


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(DATASET)
    train = data[data.seed.isin(TRAIN_SEEDS)]
    test = data[data.seed.isin(TEST_SEEDS)].copy()
    X_train, y_train = train[MODEL_FEATURES], train.label
    X_test, y_test = test[MODEL_FEATURES], test.label
    print("Model features:", MODEL_FEATURES)

    depth, cv_scores = choose_depth(X_train, y_train, train.seed)
    print("Cross-validated macro-F1 by tree depth:",
          {d: round(s, 3) for d, s in cv_scores.items()}, "-> chosen depth", depth)

    tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50, class_weight="balanced",
                                  random_state=0).fit(X_train, y_train)
    logreg = make_pipeline(StandardScaler(),
                           LogisticRegression(class_weight="balanced", max_iter=2000)).fit(X_train, y_train)

    test["pred_tree"] = tree.predict(X_test)
    test["pred_logreg"] = logreg.predict(X_test)
    test["pred_reactive"] = np.where(test.loss_recent > 0, HIGH, 0)

    results = [
        evaluate("Decision Tree", y_test, test.pred_tree),
        evaluate("Logistic Regression", y_test, test.pred_logreg),
        evaluate("Reactive (loss-based)", y_test, test.pred_reactive),
    ]
    # Per-level accuracy (macro-F1 is misleading when a level has only one true class)
    by_level = {}
    for level, part in test.groupby("level"):
        by_level[level] = {name: round(accuracy_score(part.label, part[col]), 3)
                           for name, col in [("Decision Tree", "pred_tree"),
                                             ("Logistic Regression", "pred_logreg"),
                                             ("Reactive (loss-based)", "pred_reactive")]}

    warnings = {}
    for name, col in [("Decision Tree", "pred_tree"), ("Logistic Regression", "pred_logreg"),
                      ("Reactive (loss-based)", "pred_reactive")]:
        leads, false_alarm_pct = early_warning(test, col)
        warnings[name] = {
            "drop_bursts": int(len(leads)),
            "median_lead_ms": float(np.median(leads) * 1000) if len(leads) else 0.0,
            "warned_100ms_pct": float((leads >= 0.1).mean() * 100) if len(leads) else 0.0,
            "warned_200ms_pct": float((leads >= 0.2).mean() * 100) if len(leads) else 0.0,
            "false_alarm_pct": float(false_alarm_pct),
        }
        if name == "Decision Tree":
            tree_leads = leads

    # ---- Save model + metrics ---------------------------------------------
    with open(MODEL_DIR / "decision_tree.pkl", "wb") as f:
        pickle.dump(tree, f)
    with open(MODEL_DIR / "logistic_regression.pkl", "wb") as f:
        pickle.dump(logreg, f)
    test[["variant", "level", "seed", "time", "flow"] + FEATURES + ["label", "pred_tree"]].to_csv(
        MODEL_DIR / "test_predictions.csv", index=False)
    metrics = {
        "train_seeds": TRAIN_SEEDS, "test_seeds": TEST_SEEDS,
        "train_samples": int(len(train)), "test_samples": int(len(test)),
        "model_features": MODEL_FEATURES,
        "horizon_s": HORIZON,
        "tree_depth": depth, "tree_leaves": int(tree.get_n_leaves()),
        "cv_macro_f1_by_depth": {str(d): round(s, 4) for d, s in cv_scores.items()},
        "test": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in results],
        "accuracy_by_level": by_level,
        "early_warning": warnings,
        "feature_importance": dict(zip(MODEL_FEATURES, np.round(tree.feature_importances_, 4).tolist())),
    }
    (MODEL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    report = classification_report(y_test, test.pred_tree, target_names=LABEL_NAMES, digits=3)
    (MODEL_DIR / "tree_classification_report.txt").write_text(report)

    # ---- Graphs -----------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=150)
    for ax, (name, col) in zip(axes, [("Decision Tree", "pred_tree"), ("Logistic Regression", "pred_logreg")]):
        cm = confusion_matrix(y_test, test[col], normalize="true")
        ax.imshow(cm, cmap="Blues", vmin=0, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{cm[i, j]:.2f}", ha="center", va="center",
                        color="white" if cm[i, j] > 0.5 else "black", fontsize=10)
        ax.set_xticks(range(3), LABEL_NAMES)
        ax.set_yticks(range(3), LABEL_NAMES)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual (0.5 s ahead)")
        ax.set_title(f"{name}\nmacro-F1 = {f1_score(y_test, test[col], average='macro'):.3f}", fontsize=10)
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_confusion_matrices.png")

    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
    order = np.argsort(tree.feature_importances_)
    ax.barh(np.array(MODEL_FEATURES)[order], tree.feature_importances_[order], color="#2e86c1")
    ax.set_xlabel("Importance (Gini)")
    ax.set_title("Decision Tree feature importance", fontsize=10, weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_feature_importance.png")

    fig, ax = plt.subplots(figsize=(18, 8), dpi=130)
    plot_tree(tree, feature_names=MODEL_FEATURES, class_names=LABEL_NAMES, filled=True, rounded=True,
              impurity=False, proportion=True, precision=2, fontsize=7, ax=ax)
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_decision_tree.png")

    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=150)
    names = [r["model"] for r in results]
    x = np.arange(len(names))
    for k, (key, label) in enumerate([("accuracy", "Accuracy"), ("macro_f1", "Macro-F1"),
                                      ("high_recall", "Recall (High)")]):
        ax.bar(x + (k - 1) * 0.26, [r[key] for r in results], 0.26, label=label)
    ax.set_xticks(x, names)
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8)
    ax.set_title("Prediction quality on unseen runs (seeds 4-5)", fontsize=10, weight="bold")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_model_comparison.png")

    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
    ax.hist(tree_leads * 1000, bins=np.arange(0, 1101, 100), color="#1e8449", edgecolor="white")
    median_ms = np.median(tree_leads) * 1000
    median_text = "median ≥ 1000 ms (look-back limit)" if median_ms >= 1000 else f"median = {median_ms:.0f} ms"
    ax.axvline(min(median_ms, 1000), color="black", ls="--", label=median_text)
    ax.set_xticks(range(0, 1001, 200), [str(v) for v in range(0, 1000, 200)] + ["≥1000"])
    ax.set_xlabel("Warning before the drop burst (ms); last bar = warned for the full 1 s look-back")
    ax.set_ylabel("Drop bursts")
    ax.set_title("Decision Tree early warning (test runs)", fontsize=10, weight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(GRAPHS / "ml_early_warning.png")

    # ---- Console summary --------------------------------------------------
    print(f"\nTrain {len(train):,} samples (seeds {TRAIN_SEEDS}), test {len(test):,} (seeds {TEST_SEEDS})")
    print(f"Decision Tree: depth {depth}, {tree.get_n_leaves()} leaves\n")
    print(pd.DataFrame(results).round(3).to_string(index=False))
    print("\nAccuracy by congestion level:")
    print(pd.DataFrame(by_level).T.to_string())
    print("\nEarly warning before drop bursts:")
    print(pd.DataFrame(warnings).T.round(1).to_string())
    print("\nFeature importance:", metrics["feature_importance"])
    print("\nDecision Tree classification report:\n" + report)


if __name__ == "__main__":
    main()
