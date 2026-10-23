"""Phase 8b: tune the competition detector of Predictive TCP.

Without it, Predictive TCP gets only ~23% of the bandwidth when it shares the
link with CUBIC (Phase 8).

Phase 10: the detector now measures the base RTT from raw RTT samples
(TcpPredictive::DetectorRawBase, default on). With the lowest smoothed RTT used in
Phase 8b, flows that start behind CUBIC's standing queue learned a base RTT of
60-85 ms instead of 44 ms and never detected the competitor. The grid and the
selection rule below are unchanged; only the base RTT differs. The detector watches the lowest RTT over a window:
if the queue never drains, a loss-based sender is assumed and Predictive TCP
behaves like plain Reno until the queue drains again.

Grid over the window length, the threshold and a hold time (how long to stay
in competitive mode after the queue was last seen not draining), plus the
detector switched off, on the TRAINING seeds 1-3 only:
  - medium and high load with only Predictive flows (must keep the gains)
  - a single flow (must keep filling the link)
  - high load, 4 Predictive flows vs 4 CUBIC flows (the share should approach 50%)

Selection rule (fixed before running):
  1. the Phase 7 limits: goodput >= 97% of Reno at medium, high and single-flow,
     Jain fairness >= 0.9 at medium and high;
  2. keep the main result: drops at least 50% and RTT at least 10% below Reno at
     medium and high load;
  3. pick the setting whose share against CUBIC is closest to 50%;
  4. within 2 points of that share, prefer the larger drop + RTT reduction.

Writes results/model/competition_tuning.csv, results/model/competition_choice.json
and results/graphs/competition_tuning.png. The chosen values become the
attribute defaults in ns3/tcp-variants.cc.

Usage: .venv/bin/python analysis/tune_competition.py
"""

import json
import os
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from compare_variants import run_metrics

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
WORK = ROOT / "results" / "competition_tuning"
GRAPHS = ROOT / "results" / "graphs"
NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3"))
# Reference mode (./run_all.sh --reference): the simulation outputs come from the
# macOS reference data in reference/, so no NS-3 run is started here.
REFERENCE = os.environ.get("PTCP_REFERENCE") == "1"


WINDOWS = [1, 2, 4]              # seconds
THRESHOLDS = [1.15, 1.25, 1.4]   # lowest RTT / base RTT
HOLDS = [0, 5, 10]               # seconds
SEEDS = [1, 2, 3]
LEVELS = ["medium", "high"]
GOODPUT_LIMIT = 97.0


def ns3_run(args):
    if REFERENCE:
        return
    subprocess.run(["./ns3", "run", "--no-build", "tcp-predictor " + args], cwd=NS3_DIR, check=True,
                   capture_output=True)


def share(directory, seed):
    """Share (%) of TCP goodput taken by the even-numbered (Predictive) flows."""
    samples = pd.read_csv(directory / f"samples_predictive-vs-cubic_high_s{seed}.csv")
    mbit = samples.groupby("flow").thr_mbps.sum()
    return 100 * mbit[mbit.index % 2 == 0].sum() / mbit.sum()


def evaluate(name, extra):
    out = WORK / name
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in SEEDS:
        for level in LEVELS:
            ns3_run(f"--variant=predictive --level={level} --seed={seed} --outDir={out} {extra}")
            m = run_metrics(out, "predictive", level, seed)
            r = run_metrics(RAW, "reno", level, seed)
            info = pd.read_csv(out / f"runinfo_predictive_{level}_s{seed}.csv").iloc[0]
            rows.append({"level": level, "seed": seed,
                         "drops_vs_reno_%": 100 * (m["drops"] - r["drops"]) / r["drops"],
                         "rtt_vs_reno_%": 100 * (m["mean_rtt_ms"] - r["mean_rtt_ms"]) / r["mean_rtt_ms"],
                         "goodput_vs_reno_%": 100 * m["goodput_mbps"] / r["goodput_mbps"],
                         "jain": m["jain_fairness"], "competitive_%": info.competitive_mode_pct})
        ns3_run(f"--variant=predictive --level=single --seed={seed} --outDir={out} {extra}")
        m = run_metrics(out, "predictive", "single", seed)
        r = run_metrics(WORK / "reno_single", "reno", "single", seed)
        rows.append({"level": "single", "seed": seed, "goodput_vs_reno_%": 100 * m["goodput_mbps"] / r["goodput_mbps"]})
        ns3_run(f"--variant=predictive --mix=cubic --level=high --seed={seed} --outDir={out} {extra}")
        info = pd.read_csv(out / f"runinfo_predictive-vs-cubic_high_s{seed}.csv").iloc[0]
        rows.append({"level": "vs_cubic", "seed": seed, "share_%": share(out, seed),
                     "competitive_%": info.competitive_mode_pct})
    runs = pd.DataFrame(rows)
    mean = runs.groupby("level").mean(numeric_only=True)
    result = {"setting": name}
    for level in LEVELS:
        for col in ["drops_vs_reno_%", "rtt_vs_reno_%", "goodput_vs_reno_%", "jain", "competitive_%"]:
            result[f"{col}_{level}"] = mean.loc[level, col]
    result["goodput_vs_reno_%_single"] = mean.loc["single", "goodput_vs_reno_%"]
    result["share_vs_cubic_%"] = mean.loc["vs_cubic", "share_%"]
    result["competitive_%_vs_cubic"] = mean.loc["vs_cubic", "competitive_%"]
    return result


def main():
    reno_single = WORK / "reno_single"
    reno_single.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        ns3_run(f"--variant=reno --level=single --seed={seed} --outDir={reno_single}")

    results = [dict(evaluate("off", "--ns3::TcpPredictive::CompetitionWindow=0s"), window_s=0, threshold=np.nan,
                    hold_s=np.nan)]
    print(f"off: share vs CUBIC {results[-1]['share_vs_cubic_%']:.1f}%")
    for window in WINDOWS:
        for threshold in THRESHOLDS:
            for hold in HOLDS:
                name = f"w{window}s_t{threshold}_h{hold}s"
                extra = (f"--ns3::TcpPredictive::CompetitionWindow={window}s "
                         f"--ns3::TcpPredictive::CompetitionThreshold={threshold} "
                         f"--ns3::TcpPredictive::CompetitionHold={hold}s")
                results.append(dict(evaluate(name, extra), window_s=window, threshold=threshold, hold_s=hold))
                r = results[-1]
                print(f"{name}: share vs CUBIC {r['share_vs_cubic_%']:.1f}%, competitive mode alone "
                      f"{r['competitive_%_medium']:.1f}% / {r['competitive_%_high']:.1f}%, "
                      f"drops {r['drops_vs_reno_%_medium']:+.0f}% / {r['drops_vs_reno_%_high']:+.0f}%")
    grid = pd.DataFrame(results).set_index("setting")

    # ---- Selection rule ---------------------------------------------------
    limits = ((grid[[f"goodput_vs_reno_%_{lv}" for lv in LEVELS + ["single"]]] >= GOODPUT_LIMIT).all(axis=1)
              & (grid[[f"jain_{lv}" for lv in LEVELS]] >= 0.9).all(axis=1))
    keeps_gain = ((grid[[f"drops_vs_reno_%_{lv}" for lv in LEVELS]] <= -50).all(axis=1)
                  & (grid[[f"rtt_vs_reno_%_{lv}" for lv in LEVELS]] <= -10).all(axis=1))
    grid["eligible"] = limits & keeps_gain
    grid["share_gap"] = (grid["share_vs_cubic_%"] - 50).abs()
    grid["score"] = (grid[[f"drops_vs_reno_%_{lv}" for lv in LEVELS]].mean(axis=1)
                     + grid[[f"rtt_vs_reno_%_{lv}" for lv in LEVELS]].mean(axis=1))
    eligible = grid[grid.eligible]
    near = eligible[eligible.share_gap <= eligible.share_gap.min() + 2]
    chosen = near.score.idxmin()
    grid.round(3).to_csv(ROOT / "results" / "model" / "competition_tuning.csv")
    c = grid.loc[chosen]
    (ROOT / "results" / "model" / "competition_choice.json").write_text(json.dumps(
        {"chosen": chosen, "window_s": float(c.window_s),
         "threshold": None if np.isnan(c.threshold) else float(c.threshold),
         "hold_s": None if np.isnan(c.hold_s) else float(c.hold_s),
         "share_vs_cubic_%": round(float(c["share_vs_cubic_%"]), 2),
         "eligible": int(grid.eligible.sum()), "settings": len(grid)}, indent=2))

    # ---- Graph: share vs CUBIC against the cost at high load (medium load is
    # unaffected: every setting gives about -91% drops / -26% RTT there) ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), dpi=150)
    for ax, (metric, label) in zip(axes, [("drops_vs_reno_%_high", "Drops vs Reno at high load, Predictive only (%)"),
                                          ("rtt_vs_reno_%_high", "RTT vs Reno at high load, Predictive only (%)")]):
        ok = grid[grid.eligible]
        bad = grid[~grid.eligible]
        ax.scatter(ok["share_vs_cubic_%"], ok[metric], s=40, color="#1e8449", label="passes the rule")
        ax.scatter(bad["share_vs_cubic_%"], bad[metric], s=40, color="#bbbbbb", label="fails a limit")
        for name, text in [("off", "detector off"), (chosen, f"chosen ({chosen})")]:
            ax.scatter(grid.loc[name, "share_vs_cubic_%"], grid.loc[name, metric], s=110, facecolor="none",
                       edgecolor="black", lw=1.5)
            ax.annotate(text, (grid.loc[name, "share_vs_cubic_%"], grid.loc[name, metric]),
                        textcoords="offset points", xytext=(8, 8), fontsize=8)
        ax.axvline(50, color="black", ls="--", lw=1)
        ax.set_xlabel("Share of bandwidth when sharing with CUBIC (%); fair = 50%")
        ax.set_ylabel(label)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, loc="center left")
    fig.suptitle("Competition detector tuning on seeds 1-3: fairer to CUBIC costs gains at high load",
                 weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "competition_tuning.png")
    plt.close(fig)

    show = grid.drop(columns=["eligible"]).round(2)
    print("\n" + show.to_string())
    print(f"\nEligible: {int(grid.eligible.sum())} of {len(grid)}")
    print(f"Chosen: {chosen}")
    source = (ROOT / "ns3" / "tcp-variants.cc").read_text()
    expected = "TimeValue(Seconds(0))" if c.window_s == 0 else f"TimeValue(Seconds({c.window_s:g}))"
    if expected not in source:
        print("WARNING: update the CompetitionWindow / CompetitionThreshold defaults in ns3/tcp-variants.cc")


if __name__ == "__main__":
    main()
