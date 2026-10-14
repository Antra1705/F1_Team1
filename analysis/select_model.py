"""Phase 6: choose which model to deploy by testing candidates inside NS-3.

Offline scores do not tell the whole story: once the tree controls the sending
rate, it changes the traffic it is predicting (Phase 3 found a feedback loop).
So every candidate tree is exported to C++, compiled into Predictive TCP and
run at medium and high congestion on the TRAINING seeds 1-3 only. Seeds 4-5
stay untouched for the final results. The controller settings are the ones
used when the model was chosen (Phase 6: Beta 0.85, MinWindow 4, no competition
detector); they were tuned afterwards (tune_controller.py, tune_competition.py).

Selection rule (fixed before looking at test seeds):
  1. keep candidates with goodput >= 95% of Reno and Jain fairness >= 0.9 at both levels;
  2. of those, pick the largest average reduction in drops plus RTT vs Reno.

Writes results/model/selection.csv. The chosen candidate is set as the
default in build_dataset.py (HORIZON) and train_model.py (MODEL_FEATURES).

Usage: .venv/bin/python analysis/select_model.py
"""

import json
import os
import subprocess
from pathlib import Path

import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from build_dataset import build
from compare_variants import run_metrics
from export_tree import write_header
from ml_experiments import FEATURE_SETS
from train_model import TRAIN_SEEDS, choose_depth

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
WORK = ROOT / "results" / "model_selection"
NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3"))
# Reference mode (./run_all.sh --reference): the simulation outputs come from the
# macOS reference data in reference/, so no NS-3 run is started here.
REFERENCE = os.environ.get("PTCP_REFERENCE") == "1"


PHASE6_CONTROLLER = ("--ns3::TcpPredictive::Beta=0.85 --ns3::TcpPredictive::MinWindow=4 "
                     "--ns3::TcpPredictive::CompetitionWindow=0s")  # detector added in Phase 8b
CANDIDATES = [  # (feature set, horizon in s)
    ("Phase 2 set", 0.5),
    ("Full set", 0.5),
    ("Full set", 0.2),
    ("Full set", 1.0),
    ("Delay only", 0.5),
]


def main():
    rows = []
    for features_name, horizon in CANDIDATES:
        features = FEATURE_SETS[features_name]
        name = f"{features_name.lower().replace(' ', '_')}_{horizon}s"
        data = build(horizon)
        train = data[data.seed.isin(TRAIN_SEEDS)]
        depth, _ = choose_depth(train[features], train.label, train.seed)
        tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50, class_weight="balanced",
                                      random_state=0).fit(train[features], train.label)
        if not REFERENCE:
            write_header(tree, note=f"{horizon} s")
            subprocess.run([str(ROOT / "build.sh")], check=True, capture_output=True)
        out = WORK / name
        out.mkdir(parents=True, exist_ok=True)
        for level in ["medium", "high"]:
            for seed in TRAIN_SEEDS:
                if not REFERENCE:
                    subprocess.run(["./ns3", "run", "--no-build",
                                    f"tcp-predictor --variant=predictive --level={level} --seed={seed} --outDir={out} "
                                    f"{PHASE6_CONTROLLER}"],
                                   cwd=NS3_DIR, check=True, capture_output=True)
                m = run_metrics(out, "predictive", level, seed)
                r = run_metrics(RAW, "reno", level, seed)
                rows.append({"candidate": name, "features": features_name, "horizon_s": horizon, "depth": depth,
                             "leaves": int(tree.get_n_leaves()), "level": level, "seed": seed,
                             "drops_vs_reno_%": 100 * (m["drops"] - r["drops"]) / r["drops"],
                             "rtt_vs_reno_%": 100 * (m["mean_rtt_ms"] - r["mean_rtt_ms"]) / r["mean_rtt_ms"],
                             "goodput_vs_reno_%": 100 * m["goodput_mbps"] / r["goodput_mbps"],
                             "jain": m["jain_fairness"]})
        print(f"{name}: depth {depth}, {tree.get_n_leaves()} leaves -- done")
    runs = pd.DataFrame(rows)
    summary = runs.groupby(["candidate", "level"], sort=False)[
        ["depth", "leaves", "drops_vs_reno_%", "rtt_vs_reno_%", "goodput_vs_reno_%", "jain"]].mean()
    summary.round(2).to_csv(ROOT / "results" / "model" / "selection.csv")
    print("\nPredictive TCP with each candidate model (mean of training seeds 1-3, change vs Reno):")
    print(summary.round(2).to_string())

    per = summary.groupby(level="candidate", sort=False)
    eligible = per.apply(lambda s: (s["goodput_vs_reno_%"] >= 95).all() and (s.jain >= 0.9).all())
    score = per["drops_vs_reno_%"].mean() + per["rtt_vs_reno_%"].mean()
    chosen = score[eligible].idxmin()
    print(f"\nEligible: {list(eligible[eligible].index)}")
    print(f"Chosen: {chosen} (drops + RTT change {score[chosen]:.1f}%)")
    (ROOT / "results" / "model" / "selection_choice.json").write_text(json.dumps(
        {"chosen": chosen, "eligible": list(eligible[eligible].index),
         "score": {k: round(v, 2) for k, v in score.items()}}, indent=2))


if __name__ == "__main__":
    main()
