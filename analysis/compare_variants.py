"""Phases 3 and 5: compare Predictive TCP with Tahoe, Reno, CUBIC, Vegas and BBR.

Reads every run in results/raw (and results/ablation), computes per-run
metrics, averages them over the 10 seeds, checks the PRD success criteria
(section 10.3) and writes CSV tables to results/.

Usage: .venv/bin/python analysis/compare_variants.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
ABLATION = ROOT / "results" / "ablation"
OUT = ROOT / "results"

VARIANTS = ["tahoe", "reno", "cubic", "vegas", "bbr", "predictive"]
BASELINES = ["tahoe", "reno", "cubic", "vegas", "bbr"]
LEVELS = ["low", "medium", "high"]
SEEDS = list(range(1, 11))  # 1-3 train/tune, 4-10 evaluation only (6-10 since Phase 13)
SIM_TIME = 60.0
METRICS = ["goodput_mbps", "mean_rtt_ms", "drops", "retransmissions", "mean_queue_pkts", "jain_fairness"]


def run_metrics(directory, variant, level, seed):
    tag = f"{variant}_{level}_s{seed}"
    samples = pd.read_csv(directory / f"samples_{tag}.csv")
    flows = pd.read_csv(directory / f"flowmon_{tag}.csv")
    tcp = flows[flows.protocol == "tcp"]
    queue = samples.drop_duplicates("time")
    thr = tcp.throughput_mbps.to_numpy()
    jain = thr.sum() ** 2 / (len(thr) * (thr ** 2).sum()) if len(thr) and (thr ** 2).sum() > 0 else np.nan
    row = {
        "variant": variant, "level": level, "seed": seed,
        "goodput_mbps": samples.thr_mbps.sum() * 0.1 / SIM_TIME,
        "mean_rtt_ms": samples.srtt_ms.mean(),
        "drops": queue.drops.sum(),
        "retransmissions": tcp.retransmissions.sum(),
        "mean_queue_pkts": queue.queue_pkts.mean(),
        "jain_fairness": jain,
    }
    info = directory / f"runinfo_{tag}.csv"
    row["proactive_reductions"] = pd.read_csv(info).proactive_reductions.iloc[0] if info.exists() else 0
    return row


def pct(new, old):
    return 100.0 * (new - old) / old if old else np.nan


def main():
    runs = pd.DataFrame([run_metrics(RAW, v, l, s) for l in LEVELS for v in VARIANTS for s in SEEDS])
    runs.to_csv(OUT / "comparison_runs.csv", index=False)

    mean = runs.groupby(["level", "variant"], sort=False)[METRICS + ["proactive_reductions"]].mean()
    std = runs.groupby(["level", "variant"], sort=False)[METRICS].std()
    summary = mean.join(std, rsuffix="_std")
    summary.round(3).to_csv(OUT / "comparison_summary.csv")

    print(f"Mean over {len(SEEDS)} seeds:")
    print(mean.round(2).to_string())

    # ---- PRD section 10.3 success criteria (Medium and High levels) --------
    checks = []
    for level in ["medium", "high"]:
        p, r, c = (mean.loc[(level, v)] for v in ["predictive", "reno", "cubic"])
        checks += [
            {"level": level, "criterion": "Drops at least 30% lower than Reno",
             "value": f"{pct(p.drops, r.drops):+.1f}%", "met": pct(p.drops, r.drops) <= -30},
            {"level": level, "criterion": "Average RTT lower than Reno",
             "value": f"{pct(p.mean_rtt_ms, r.mean_rtt_ms):+.1f}%", "met": p.mean_rtt_ms < r.mean_rtt_ms},
            {"level": level, "criterion": "Average RTT lower than CUBIC",
             "value": f"{pct(p.mean_rtt_ms, c.mean_rtt_ms):+.1f}%", "met": p.mean_rtt_ms < c.mean_rtt_ms},
            {"level": level, "criterion": "Goodput at least 90% of Reno",
             "value": f"{100 * p.goodput_mbps / r.goodput_mbps:.1f}%",
             "met": p.goodput_mbps >= 0.9 * r.goodput_mbps},
        ]
    p = mean.loc[("high", "predictive")]
    checks.append({"level": "high", "criterion": "Jain fairness index at least 0.9 (bulk flows)",
                   "value": f"{p.jain_fairness:.3f}", "met": p.jain_fairness >= 0.9})
    checks = pd.DataFrame(checks)
    checks.to_csv(OUT / "prd_criteria_check.csv", index=False)
    print("\nPRD 10.3 success criteria:")
    print(checks.to_string(index=False))

    # ---- Change vs each baseline ------------------------------------------
    rel = []
    for level in LEVELS:
        p = mean.loc[(level, "predictive")]
        for base in BASELINES:
            b = mean.loc[(level, base)]
            rel.append({"level": level, "vs": base,
                        "goodput_%": pct(p.goodput_mbps, b.goodput_mbps),
                        "rtt_%": pct(p.mean_rtt_ms, b.mean_rtt_ms),
                        "drops_%": pct(p.drops, b.drops),
                        "retransmissions_%": pct(p.retransmissions, b.retransmissions),
                        "queue_%": pct(p.mean_queue_pkts, b.mean_queue_pkts)})
    rel = pd.DataFrame(rel)
    rel.round(1).to_csv(OUT / "predictive_vs_baselines.csv", index=False)
    print("\nPredictive TCP change vs each baseline (%):")
    print(rel.round(1).to_string(index=False))

    # ---- Paired comparison: in how many seeds is Predictive better? -------
    # Every variant sees the same traffic for a given seed, so seeds can be paired.
    wins = []
    for level in ["medium", "high"]:
        part = runs[runs.level == level].pivot(index="seed", columns="variant")
        for base in BASELINES:
            wins.append({
                "level": level, "vs": base,
                "fewer_drops": int((part.drops.predictive < part.drops[base]).sum()),
                "lower_rtt": int((part.mean_rtt_ms.predictive < part.mean_rtt_ms[base]).sum()),
                "goodput_within_5pct": int((part.goodput_mbps.predictive >= 0.95 * part.goodput_mbps[base]).sum()),
                "seeds": len(part),
            })
    wins = pd.DataFrame(wins)
    wins.to_csv(OUT / "seed_wins.csv", index=False)
    print(f"\nSeeds (out of {len(SEEDS)}) where Predictive TCP is better:")
    print(wins.to_string(index=False))

    # ---- Ablation ---------------------------------------------------------
    if ABLATION.exists():
        abl = []
        settings = {"proposed (beta 0.8, MinWindow 4)": RAW,
                    "no proactive cut (beta 1.0)": ABLATION / "beta1",
                    "before tuning (beta 0.85)": ABLATION / "phase6",
                    "halve on High (beta 0.5, MinWindow 6)": ABLATION / "halving",
                    "no reaction to Medium": ABLATION / "nohold"}
        for name, directory in settings.items():
            for level in ["medium", "high"]:
                for seed in SEEDS:
                    m = run_metrics(directory, "predictive", level, seed)
                    m["setting"] = name
                    abl.append(m)
        abl = pd.DataFrame(abl).groupby(["level", "setting"], sort=False)[
            ["goodput_mbps", "mean_rtt_ms", "drops", "jain_fairness", "proactive_reductions"]].mean()
        abl.round(2).to_csv(OUT / "ablation_summary.csv")
        print(f"\nAblation (mean over {len(SEEDS)} seeds):")
        print(abl.round(2).to_string())

    (OUT / "comparison_overview.json").write_text(json.dumps({
        "criteria_met": int(checks.met.sum()), "criteria_total": int(len(checks))}, indent=2))


if __name__ == "__main__":
    main()
