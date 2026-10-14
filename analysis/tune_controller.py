"""Phase 7: tune how Predictive TCP reacts to a High prediction.

Grid over
  - Beta:      window multiplier on High (0.5 = halve, 0.9 = cut 10%)
  - MinWindow: window (segments) below which the predictor never acts
run at medium and high congestion, and with a single flow alone on the link,
on the TRAINING seeds 1-3 only. Seeds 4-5 stay untouched for the final results.
The competition detector (added later, Phase 8b) is switched off here, as it was
when these values were chosen. Medium growth is not tuned: the Phase 6
ablation showed it barely matters, because the delay tree rarely predicts Medium.

Selection rule:
  1. keep settings with goodput >= 97% of Reno and Jain fairness >= 0.9 at medium
     and high load, and goodput >= 97% of Reno with a single flow;
  2. score = average drops change + average RTT change vs Reno at medium and high
     load (lower is better);
  3. among settings within 2 points of the best score, pick the fairest at high load.
The single-flow check was added after the first version of the rule chose
Beta 0.5: halving on every High prediction left a lone flow at 87% of Reno's
goodput, because the window then falls below the bandwidth-delay product.

Writes results/model/tuning.csv, results/model/tuning_choice.json and
results/graphs/tuning_grid.png. The chosen values become the attribute
defaults in ns3/tcp-variants.cc.

Usage: .venv/bin/python analysis/tune_controller.py
"""

import json
import os
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from compare_variants import run_metrics

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
WORK = ROOT / "results" / "tuning"
GRAPHS = ROOT / "results" / "graphs"
NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3"))
# Reference mode (./run_all.sh --reference): the simulation outputs come from the
# macOS reference data in reference/, so no NS-3 run is started here.
REFERENCE = os.environ.get("PTCP_REFERENCE") == "1"


BETAS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9]
MIN_WINDOWS = [2, 4, 6]
SEEDS = [1, 2, 3]
LEVELS = ["medium", "high"]
GOODPUT_LIMIT = 97.0  # % of Reno


def ns3_run(args):
    if REFERENCE:
        return
    subprocess.run(["./ns3", "run", "--no-build", "tcp-predictor " + args], cwd=NS3_DIR, check=True,
                   capture_output=True)


def main():
    # Reno alone on the link (single-flow reference; not part of the baseline runs)
    reno_single = WORK / "reno_single"
    reno_single.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        ns3_run(f"--variant=reno --level=single --seed={seed} --outDir={reno_single}")
    rows = []
    for beta in BETAS:
        for min_window in MIN_WINDOWS:
            out = WORK / f"beta{beta}_minw{min_window}"
            out.mkdir(parents=True, exist_ok=True)
            for level in LEVELS:
                for seed in SEEDS:
                    ns3_run(f"--variant=predictive --level={level} --seed={seed} --outDir={out} "
                            f"--ns3::TcpPredictive::Beta={beta} --ns3::TcpPredictive::MinWindow={min_window} "
                            f"--ns3::TcpPredictive::CompetitionWindow=0s")
                    m = run_metrics(out, "predictive", level, seed)
                    r = run_metrics(RAW, "reno", level, seed)
                    rows.append({"beta": beta, "min_window": min_window, "level": level, "seed": seed,
                                 "drops_vs_reno_%": 100 * (m["drops"] - r["drops"]) / r["drops"],
                                 "rtt_vs_reno_%": 100 * (m["mean_rtt_ms"] - r["mean_rtt_ms"]) / r["mean_rtt_ms"],
                                 "goodput_vs_reno_%": 100 * m["goodput_mbps"] / r["goodput_mbps"],
                                 "jain": m["jain_fairness"]})
            for seed in SEEDS:
                ns3_run(f"--variant=predictive --level=single --seed={seed} --outDir={out} "
                        f"--ns3::TcpPredictive::Beta={beta} --ns3::TcpPredictive::MinWindow={min_window} "
                        f"--ns3::TcpPredictive::CompetitionWindow=0s")
                m = run_metrics(out, "predictive", "single", seed)
                r = run_metrics(reno_single, "reno", "single", seed)
                rows.append({"beta": beta, "min_window": min_window, "level": "single", "seed": seed,
                             "goodput_vs_reno_%": 100 * m["goodput_mbps"] / r["goodput_mbps"]})
            print(f"beta {beta}, MinWindow {min_window}: done")
    runs = pd.DataFrame(rows)
    grid = runs.groupby(["beta", "min_window", "level"])[
        ["drops_vs_reno_%", "rtt_vs_reno_%", "goodput_vs_reno_%", "jain"]].mean().unstack("level")
    grid.columns = [f"{metric}_{level}" for metric, level in grid.columns]
    grid = grid.dropna(axis=1, how="all")  # single-flow runs only report goodput

    # ---- Selection rule ---------------------------------------------------
    grid["eligible"] = ((grid[[f"goodput_vs_reno_%_{lv}" for lv in LEVELS + ["single"]]] >= GOODPUT_LIMIT)
                        .all(axis=1) & (grid[[f"jain_{lv}" for lv in LEVELS]] >= 0.9).all(axis=1))
    grid["score"] = (grid[[f"drops_vs_reno_%_{lv}" for lv in LEVELS]].mean(axis=1)
                     + grid[[f"rtt_vs_reno_%_{lv}" for lv in LEVELS]].mean(axis=1))
    eligible = grid[grid.eligible]
    near_best = eligible[eligible.score <= eligible.score.min() + 2]
    beta, min_window = near_best.jain_high.idxmax()
    grid.round(3).to_csv(ROOT / "results" / "model" / "tuning.csv")
    (ROOT / "results" / "model" / "tuning_choice.json").write_text(json.dumps(
        {"beta": beta, "min_window": int(min_window), "score": round(grid.loc[(beta, min_window), "score"], 2),
         "eligible": int(grid.eligible.sum()), "settings": len(grid)}, indent=2))

    # ---- Graph: each metric vs beta, one line per MinWindow ----------------
    fig, axes = plt.subplots(2, 5, figsize=(18, 6.5), dpi=150, sharex=True)
    metrics = [("drops_vs_reno_%", "Drops vs Reno (%)"), ("rtt_vs_reno_%", "RTT vs Reno (%)"),
               ("goodput_vs_reno_%", "Goodput (% of Reno)"), ("jain", "Jain fairness")]
    colors = {2: "#c0392b", 4: "#1e8449", 6: "#2e86c1"}
    for row, level in enumerate(LEVELS):
        for col, (metric, label) in enumerate(metrics):
            ax = axes[row, col]
            for mw in MIN_WINDOWS:
                part = grid.xs(mw, level="min_window")
                ax.plot(part.index, part[f"{metric}_{level}"], "o-", color=colors[mw], ms=4,
                        label=f"MinWindow {mw}")
            ax.plot(beta, grid.loc[(beta, min_window), f"{metric}_{level}"], "*", ms=16, color="gold",
                    mec="black", label="chosen")
            if metric == "goodput_vs_reno_%":
                ax.axhline(GOODPUT_LIMIT, color="red", ls="--", lw=0.8)
            if metric == "jain":
                ax.axhline(0.9, color="red", ls="--", lw=0.8)
            ax.set_title(f"{level.capitalize()}: {label}", fontsize=9, weight="bold")
            ax.grid(alpha=0.3)
            if row == 1:
                ax.set_xlabel("β (window multiplier on High)")
    ax = axes[0, 4]
    for mw in MIN_WINDOWS:
        part = grid.xs(mw, level="min_window")
        ax.plot(part.index, part["goodput_vs_reno_%_single"], "o-", color=colors[mw], ms=4)
    ax.plot(beta, grid.loc[(beta, min_window), "goodput_vs_reno_%_single"], "*", ms=16, color="gold", mec="black")
    ax.axhline(GOODPUT_LIMIT, color="red", ls="--", lw=0.8)
    ax.set_ylim(60, 115)  # MinWindow 2 with beta 0.5 collapses to ~8%; off the scale
    ax.set_title("Single flow: Goodput (% of Reno)", fontsize=9, weight="bold")
    ax.grid(alpha=0.3)
    axes[1, 4].axis("off")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle(f"Controller tuning on training seeds 1-3 (red dashes = selection limits; "
                 f"chosen β = {beta}, MinWindow = {min_window})", weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "tuning_grid.png")
    plt.close(fig)

    show = grid.drop(columns="eligible").round(2)
    print("\nMean of training seeds 1-3 (change vs Reno):")
    print(show.to_string())
    print(f"\nEligible: {int(grid.eligible.sum())} of {len(grid)} settings")
    print(f"Chosen: Beta = {beta}, MinWindow = {min_window}")

    # The chosen values must be the defaults compiled into TcpPredictive
    source = (ROOT / "ns3" / "tcp-variants.cc").read_text()
    if f"DoubleValue({beta})" not in source or f"UintegerValue({min_window})" not in source:
        print("WARNING: update the Beta / MinWindow defaults in ns3/tcp-variants.cc to the chosen values")


if __name__ == "__main__":
    main()
