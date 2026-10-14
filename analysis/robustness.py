"""Phase 8: do the results hold beyond the one setup used so far?

1. Buffer sweep: every variant with a 20-, 50- and 100-packet bottleneck queue
   (the model was trained and the controller tuned with 50 packets only).
2. Competition with CUBIC: at high load, 4 flows of one variant share the link
   with 4 CUBIC flows. A fair variant gets about 50% of the bandwidth.

Needs run_robustness.sh to have run. Writes CSV tables to results/robustness/
and two graphs.

Usage: .venv/bin/python analysis/robustness.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from compare_variants import run_metrics
from make_graphs import COLORS, NAMES, VARIANTS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
ROBUST = ROOT / "results" / "robustness"
GRAPHS = ROOT / "results" / "graphs"

QUEUES = [20, 50, 100]
LEVELS = ["medium", "high"]
SEEDS = [1, 2, 3, 4, 5]
MIXED = ["cubic", "reno", "vegas", "bbr", "predictive_nodetector", "predictive"]
MIXED_NAMES = {**NAMES, "predictive_nodetector": "Predictive, no detector",
               "predictive": "Predictive (proposed)"}
MIXED_COLORS = {**COLORS, "predictive_nodetector": "#7dcea0"}
BDP_PACKETS = 38  # 10 Mbps x 44 ms / 1448-byte segments


def queue_dir(queue):
    return RAW if queue == 50 else ROBUST / f"queue{queue}"


def buffer_sweep():
    runs = pd.DataFrame([{**run_metrics(queue_dir(q), v, lv, s), "queue": q}
                         for q in QUEUES for lv in LEVELS for v in VARIANTS for s in SEEDS])
    mean = runs.groupby(["queue", "level", "variant"])[
        ["goodput_mbps", "mean_rtt_ms", "drops", "jain_fairness"]].mean()
    mean.round(3).to_csv(ROBUST / "buffer_sweep.csv")

    rel = []
    for q in QUEUES:
        for lv in LEVELS:
            p, r = mean.loc[(q, lv, "predictive")], mean.loc[(q, lv, "reno")]
            part = runs[(runs.queue == q) & (runs.level == lv)].pivot(index="seed", columns="variant")
            competitive = np.mean([pd.read_csv(queue_dir(q) / f"runinfo_predictive_{lv}_s{s}.csv")
                                   .competitive_mode_pct.iloc[0] for s in SEEDS])
            rel.append({"queue": q, "level": lv,
                        "drops_vs_reno_%": 100 * (p.drops - r.drops) / r.drops,
                        "rtt_vs_reno_%": 100 * (p.mean_rtt_ms - r.mean_rtt_ms) / r.mean_rtt_ms,
                        "goodput_vs_reno_%": 100 * p.goodput_mbps / r.goodput_mbps,
                        "jain": p.jain_fairness,
                        "seeds_fewer_drops": int((part.drops.predictive < part.drops.reno).sum()),
                        "seeds_lower_rtt": int((part.mean_rtt_ms.predictive < part.mean_rtt_ms.reno).sum()),
                        "reno_mode_%": competitive})
    rel = pd.DataFrame(rel)
    rel.round(2).to_csv(ROBUST / "buffer_vs_reno.csv", index=False)

    # 100-packet queue, high load, competition detector off
    off = pd.DataFrame([run_metrics(ROBUST / "queue100_nodetector", "predictive", "high", s) for s in SEEDS]).mean(
        numeric_only=True)
    r = mean.loc[(100, "high", "reno")]
    pd.DataFrame([{"drops_vs_reno_%": 100 * (off.drops - r.drops) / r.drops,
                   "rtt_vs_reno_%": 100 * (off.mean_rtt_ms - r.mean_rtt_ms) / r.mean_rtt_ms,
                   "goodput_vs_reno_%": 100 * off.goodput_mbps / r.goodput_mbps,
                   "jain": off.jain_fairness}]).round(2).to_csv(ROBUST / "buffer_100_nodetector.csv", index=False)

    fig, axes = plt.subplots(2, 4, figsize=(15, 6.5), dpi=150, sharex=True)
    metrics = [("drops", "Bottleneck drops"), ("mean_rtt_ms", "Mean RTT (ms)"),
               ("goodput_mbps", "Goodput (Mbps)"), ("jain_fairness", "Jain fairness")]
    for row, lv in enumerate(LEVELS):
        for col, (metric, label) in enumerate(metrics):
            ax = axes[row, col]
            for v in VARIANTS:
                values = [mean.loc[(q, lv, v), metric] for q in QUEUES]
                ax.plot(QUEUES, values, "o-", color=COLORS[v], lw=2.2 if v == "predictive" else 1.2,
                        ms=4, label=NAMES[v])
            if metric == "drops":
                ax.set_yscale("symlog", linthresh=10)
            if metric == "jain_fairness":
                ax.set_ylim(0.7, 1.01)  # same scale at both levels
            ax.set_title(f"{lv.capitalize()}: {label}", fontsize=9, weight="bold")
            ax.set_xticks(QUEUES, [f"{q}\n({q / BDP_PACKETS:.1f}×BDP)" for q in QUEUES])
            ax.grid(alpha=0.3)
            if row == 1:
                ax.set_xlabel("Bottleneck queue (packets)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=len(VARIANTS), fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 0.95))
    fig.suptitle("Buffer-size sweep (mean of 5 seeds; model trained and tuned with 50 packets only)",
                 weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(GRAPHS / "robustness_buffer.png")
    plt.close(fig)
    return rel


def competition():
    rows = []
    for v in MIXED:
        for s in SEEDS:
            if v == "predictive_nodetector":
                path = ROBUST / "mixed_nodetector" / f"samples_predictive-vs-cubic_high_s{s}.csv"
            else:
                path = ROBUST / "mixed" / f"samples_{v}-vs-cubic_high_s{s}.csv"
            samples = pd.read_csv(path)
            mbit = samples.groupby("flow").thr_mbps.sum() * 0.1  # megabits delivered per flow
            tested = mbit[mbit.index % 2 == 0].sum()  # even flows: the tested variant
            cubic = mbit[mbit.index % 2 == 1].sum()   # odd flows: CUBIC
            queue = samples.drop_duplicates("time")
            rows.append({"variant": v, "seed": s, "share_%": 100 * tested / (tested + cubic),
                         "tested_mbps": tested / 60, "cubic_mbps": cubic / 60,
                         "mean_rtt_ms": samples.srtt_ms.mean(), "drops": queue.drops.sum()})
    runs = pd.DataFrame(rows)
    summary = runs.groupby("variant", sort=False).agg(
        share_mean=("share_%", "mean"), share_std=("share_%", "std"), tested_mbps=("tested_mbps", "mean"),
        cubic_mbps=("cubic_mbps", "mean"), mean_rtt_ms=("mean_rtt_ms", "mean"), drops=("drops", "mean"))
    summary.round(2).to_csv(ROBUST / "mixed_competition.csv")

    fig, ax = plt.subplots(figsize=(9.5, 4.4), dpi=150)
    y = np.arange(len(MIXED))[::-1]
    ax.barh(y, summary.share_mean, xerr=summary.share_std, capsize=3,
            color=[MIXED_COLORS[v] for v in MIXED], alpha=0.85)
    for yi, v in zip(y, MIXED):
        pts = runs[runs.variant == v]["share_%"]
        ax.scatter(pts, [yi] * len(pts), color="black", s=10, zorder=3)
        ax.text(101, yi, f"{summary.loc[v, 'share_mean']:.1f}%", va="center", fontsize=8)
    ax.axvline(50, color="black", ls="--", lw=1, label="fair share (50%)")
    ax.set_yticks(y, [f"{MIXED_NAMES[v].replace(' (proposed)', '')} vs CUBIC" for v in MIXED])
    ax.set_xlim(0, 110)
    ax.set_xlabel("Share of TCP goodput taken by the first variant (%); dots = seeds")
    ax.set_title("4 flows of each variant sharing the link with 4 CUBIC flows (high load)",
                 fontsize=10, weight="bold")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(GRAPHS / "mixed_competition.png")
    plt.close(fig)
    return summary


def main():
    rel = buffer_sweep()
    print("Predictive TCP vs Reno at each buffer size (mean of 5 seeds):")
    print(rel.round(1).to_string(index=False))
    summary = competition()
    print("\nSharing the link with 4 CUBIC flows (high load, mean of 5 seeds):")
    print(summary.round(2).to_string())


if __name__ == "__main__":
    main()
