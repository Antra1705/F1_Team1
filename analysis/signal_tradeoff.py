"""Phase 11 (optional, ~40 min): can Predictive TCP be fair on fast links without losing its gains?

Phase 10 found that on fast or long links the flows share unfairly (Jain 0.45 at 50 Mbps / 20 ms),
because delayed ACKs inflate the smoothed RTT of small windows. This experiment retrains the
model on a cleaner RTT signal (the lowest raw RTT sample of each 100 ms interval,
TcpPredictive::MinRttSignal) and tunes every candidate, on the TRAINING seeds 1-3 only.

Candidates: the deployed model (smoothed RTT, delay-only, 0.5 s) and the 5 model-selection
candidates of select_model.py retrained on the new signal. Each gets the full Phase 7 grid
(Beta x MinWindow, detector off).

Rule written before running:
  1. the Phase 7 limits (goodput >= 97% of Reno at medium, high and single flow; Jain >= 0.9 at
     medium and high);
  2. plus Jain >= 0.9 at 50 Mbps / 20 ms, high load (queue 247 = 1.3x BDP); checked for the
     eligible settings in order of score until one passes (plus any within 2 points of it);
  3. the largest drop + RTT reduction; within 2 points, the highest Jain at high load.

Outcome (see README finding 21): only full-feature-set models with a hard cut pass the 50 Mbps
limit, and the best of them (score -69) keeps about half of the deployed model's gain (-122).
The deployed model was therefore kept; the 50 Mbps limit was not adopted after its price was
seen, and this is stated openly.

Needs ./run_all.sh to have run (results/raw/ with the rtt_min_int_ms columns). Writes runs to
results/signal_tradeoff/ and the table to results/model/signal_tradeoff.csv, then restores and
rebuilds the deployed tree.

Usage: .venv/bin/python analysis/signal_tradeoff.py
"""

import os
import subprocess
from pathlib import Path

import pandas as pd
from sklearn.tree import DecisionTreeClassifier

import build_dataset as bd
from compare_variants import run_metrics
from export_tree import HEADER, write_header
from ml_experiments import FEATURE_SETS
from train_model import choose_depth

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
RENO_SINGLE = ROOT / "results" / "tuning" / "reno_single"
WORK = ROOT / "results" / "signal_tradeoff"
TABLE = ROOT / "results" / "model" / "signal_tradeoff.csv"
NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3"))

BETAS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9]
MIN_WINDOWS = [2, 4, 6]
SEEDS = [1, 2, 3]
CANDIDATES = [("smoothed", "Delay only", 0.5)] + [
    ("min", f, h) for f, h in [("Phase 2 set", 0.5), ("Full set", 0.5), ("Full set", 0.2), ("Full set", 1.0),
                               ("Delay only", 0.5)]]
FAST_LINK = "--rate=50Mbps --delay=20ms --queue=247 --simTime=60"


def ns3_run(args):
    subprocess.run(["./ns3", "run", "--no-build", "tcp-predictor " + args], cwd=NS3_DIR, check=True,
                   capture_output=True)


def compile_candidate(signal, features_name, horizon):
    bd.RTT_SIGNAL = signal
    data = bd.build(horizon)
    train = data[data.seed.isin(SEEDS)]
    features = FEATURE_SETS[features_name]
    depth, _ = choose_depth(train[features], train.label, train.seed)
    tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50, class_weight="balanced",
                                  random_state=0).fit(train[features], train.label)
    write_header(tree, note=f"{horizon} s")
    subprocess.run([str(ROOT / "build.sh")], check=True, capture_output=True)
    return depth, int(tree.get_n_leaves())


def vs_reno(out, level, seed):
    m, r = run_metrics(out, "predictive", level, seed), run_metrics(RAW, "reno", level, seed)
    return [100 * (m["drops"] - r["drops"]) / r["drops"],
            100 * (m["mean_rtt_ms"] - r["mean_rtt_ms"]) / r["mean_rtt_ms"],
            100 * m["goodput_mbps"] / r["goodput_mbps"], m["jain_fairness"]]


def main():
    deployed = HEADER.read_text()
    rows = []
    try:
        for signal, features_name, horizon in CANDIDATES:
            name = f"{signal}:{features_name.lower().replace(' ', '_')}_{horizon}s"
            depth, leaves = compile_candidate(signal, features_name, horizon)
            flag = (f"--ns3::TcpPredictive::MinRttSignal={'true' if signal == 'min' else 'false'} "
                    f"--ns3::TcpPredictive::CompetitionWindow=0s")
            grid = []
            for beta in BETAS:
                for min_window in MIN_WINDOWS:
                    out = WORK / name.replace(":", "_") / f"b{beta}_mw{min_window}"
                    out.mkdir(parents=True, exist_ok=True)
                    arg = f"--ns3::TcpPredictive::Beta={beta} --ns3::TcpPredictive::MinWindow={min_window} {flag}"
                    row = {"candidate": name, "depth": depth, "leaves": leaves, "beta": beta, "min_window": min_window}
                    for level in ["medium", "high"]:
                        values = []
                        for seed in SEEDS:
                            ns3_run(f"--variant=predictive --level={level} --seed={seed} --outDir={out} {arg}")
                            values.append(vs_reno(out, level, seed))
                        mean = pd.DataFrame(values).mean()
                        row.update({f"drops_{level}": mean[0], f"rtt_{level}": mean[1], f"good_{level}": mean[2],
                                    f"jain_{level}": mean[3]})
                    single = []
                    for seed in SEEDS:
                        ns3_run(f"--variant=predictive --level=single --seed={seed} --outDir={out} {arg}")
                        single.append(100 * run_metrics(out, "predictive", "single", seed)["goodput_mbps"]
                                      / run_metrics(RENO_SINGLE, "reno", "single", seed)["goodput_mbps"])
                    row["good_single"] = sum(single) / len(single)
                    grid.append(row)
            grid = pd.DataFrame(grid)
            grid["eligible_phase7"] = ((grid[["good_medium", "good_high", "good_single"]] >= 97).all(axis=1)
                                       & (grid[["jain_medium", "jain_high"]] >= 0.9).all(axis=1))
            grid["score"] = (grid.drops_medium + grid.drops_high) / 2 + (grid.rtt_medium + grid.rtt_high) / 2
            grid["jain_50mbps"] = float("nan")
            best_pass = None
            for i, r in grid[grid.eligible_phase7].sort_values("score").iterrows():
                if best_pass is not None and r.score > best_pass + 2:
                    break
                out = WORK / name.replace(":", "_") / f"b{r.beta}_mw{int(r.min_window)}" / "net50"
                out.mkdir(parents=True, exist_ok=True)
                arg = f"--ns3::TcpPredictive::Beta={r.beta} --ns3::TcpPredictive::MinWindow={int(r.min_window)} {flag}"
                jain = []
                for seed in SEEDS:
                    ns3_run(f"--variant=predictive --level=high --seed={seed} {FAST_LINK} --outDir={out} {arg}")
                    jain.append(run_metrics(out, "predictive", "high", seed)["jain_fairness"])
                grid.loc[i, "jain_50mbps"] = sum(jain) / len(jain)
                if grid.loc[i, "jain_50mbps"] >= 0.9 and best_pass is None:
                    best_pass = r.score
            rows.append(grid)
            print(f"{name}: done", flush=True)
    finally:
        HEADER.write_text(deployed)  # restore the deployed tree
        subprocess.run([str(ROOT / "build.sh")], check=True, capture_output=True)

    table = pd.concat(rows, ignore_index=True)
    table.round(3).to_csv(TABLE, index=False)
    passing = table[table.eligible_phase7 & (table.jain_50mbps >= 0.9)]
    near = passing[passing.score <= passing.score.min() + 2]
    pick = near.loc[near.jain_high.idxmax()]
    print(f"Best setting that is also fair at 50 Mbps: {pick.candidate}, beta {pick.beta}, "
          f"MinWindow {int(pick.min_window)}, score {pick.score:.1f} (Jain at 50 Mbps {pick.jain_50mbps:.2f})")


if __name__ == "__main__":
    main()
