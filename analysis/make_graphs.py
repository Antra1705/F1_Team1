"""Phases 4-5: all comparison graphs, the final results table and a results page.

Needs compare_variants.py to have run first (reads results/comparison_runs.csv
and results/ablation_summary.csv).

Usage: .venv/bin/python analysis/make_graphs.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
RAW = RESULTS / "raw"
VALID = RESULTS / "validation"
GRAPHS = RESULTS / "graphs"

VARIANTS = ["tahoe", "reno", "cubic", "vegas", "bbr", "predictive"]
BASELINES = ["tahoe", "reno", "cubic", "vegas", "bbr"]
NAMES = {"tahoe": "Tahoe", "reno": "Reno", "cubic": "CUBIC", "vegas": "Vegas", "bbr": "BBR",
         "predictive": "Predictive (proposed)"}
COLORS = {"tahoe": "#8e8e8e", "reno": "#2e86c1", "cubic": "#e67e22", "vegas": "#8e44ad", "bbr": "#c0392b",
          "predictive": "#1e8449"}
MIXED_LABELS = {"predictive_nodetector": "Predictive, no detector",  # competition test rows
                "predictive_phase8b": "Predictive, Phase 8b detector"}
LEVELS = ["low", "medium", "high"]
EXAMPLE_SEED = 4  # a test seed (not used to train the model)
N_SEEDS = 10  # evaluation seeds per setting (seeds 1-3 train and tune; 6-10 added in Phase 13)
SEGMENT = 1448

plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3})


def time_series(level):
    fig, axes = plt.subplots(4, 1, figsize=(10, 10), dpi=150, sharex=True)
    for variant in VARIANTS:
        s = pd.read_csv(RAW / f"samples_{variant}_{level}_s{EXAMPLE_SEED}.csv")
        per_time = s.groupby("time")
        thr = per_time.thr_mbps.sum().rolling(10, min_periods=1).mean()
        rtt = s[s.thr_mbps > 0].groupby("time").srtt_ms.mean().rolling(10, min_periods=1).mean()
        queue = s.drop_duplicates("time").set_index("time").queue_pkts.rolling(10, min_periods=1).mean()
        flow0 = s[s.flow == 0].set_index("time").cwnd_bytes / SEGMENT
        style = dict(color=COLORS[variant], lw=1.6 if variant == "predictive" else 1.0, label=NAMES[variant])
        axes[0].plot(thr.index, thr, **style)
        axes[1].plot(rtt.index, rtt, **style)
        axes[2].plot(queue.index, queue, **style)
        axes[3].plot(flow0.index, flow0, **style)
    axes[0].set_ylabel("Total goodput (Mbps)")
    axes[1].set_ylabel("Mean smoothed RTT (ms)")
    axes[2].set_ylabel("Bottleneck queue (packets)")
    axes[3].set_ylabel("cwnd of flow 0 (segments)")
    axes[3].set_xlabel("time (s)")
    axes[0].legend(ncol=3, fontsize=8, loc="lower right")
    fig.suptitle(f"{level.capitalize()} congestion, seed {EXAMPLE_SEED}: throughput, RTT, queue and cwnd over time "
                 f"(1 s moving average)", weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / f"timeseries_{level}.png")
    plt.close(fig)


def bar_charts(runs):
    metrics = [("goodput_mbps", "Total goodput (Mbps)"), ("mean_rtt_ms", "Mean RTT (ms)"),
               ("drops", "Bottleneck drops"), ("retransmissions", "Retransmissions"),
               ("mean_queue_pkts", "Mean queue (packets)"), ("jain_fairness", "Jain fairness index")]
    stats = runs.groupby(["level", "variant"])
    mean, std = stats.mean(numeric_only=True), stats.std(numeric_only=True)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), dpi=150)
    x = np.arange(len(LEVELS))
    width = 0.13
    for ax, (col, label) in zip(axes.flat, metrics):
        for k, variant in enumerate(VARIANTS):
            m = [mean.loc[(lv, variant), col] for lv in LEVELS]
            e = [std.loc[(lv, variant), col] for lv in LEVELS]
            ax.bar(x + (k - 2.5) * width, m, width, yerr=e, capsize=1.5, color=COLORS[variant],
                   label=NAMES[variant])
        ax.set_xticks(x, [lv.capitalize() for lv in LEVELS])
        ax.set_title(label, fontsize=10, weight="bold")
        if col == "jain_fairness":
            ax.set_ylim(0.5, 1.02)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=len(VARIANTS), fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 0.955))
    fig.suptitle(f"Comparison of TCP variants (mean ± std over {N_SEEDS} seeds)", weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(GRAPHS / "comparison_bars.png")
    plt.close(fig)


# Label positions (points) for the crowded medium-load cluster
LABEL_OFFSETS = {("medium", "reno"): (-10, 6), ("medium", "tahoe"): (6, -20), ("medium", "cubic"): (8, 2),
                 ("medium", "predictive"): (-12, -14)}


def tradeoff_chart(runs):
    """Where each variant sits: delay vs loss (bottom-left is best), labelled with fairness."""
    stats = runs.groupby(["level", "variant"])
    mean, std = stats.mean(numeric_only=True), stats.std(numeric_only=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150)
    for ax, level in zip(axes, ["medium", "high"]):
        for variant in VARIANTS:
            m, s = mean.loc[(level, variant)], std.loc[(level, variant)]
            ax.errorbar(m.mean_rtt_ms, m.drops + 1, xerr=s.mean_rtt_ms, yerr=s.drops, fmt="o",
                        ms=11 if variant == "predictive" else 8, color=COLORS[variant], capsize=2,
                        mec="black" if variant == "predictive" else COLORS[variant], label=NAMES[variant])
            ax.annotate(f"{NAMES[variant].split(' ')[0]}\nJain {m.jain_fairness:.2f}", (m.mean_rtt_ms, m.drops + 1),
                        textcoords="offset points", xytext=LABEL_OFFSETS.get((level, variant), (8, -4)),
                        fontsize=7, ha="right" if LABEL_OFFSETS.get((level, variant), (8, 0))[0] < 0 else "left")
        ax.set_yscale("log")
        ax.set_xlabel("Mean RTT (ms)")
        ax.set_ylabel("Bottleneck drops (log scale)")
        ax.set_title(f"{level.capitalize()} congestion", fontsize=10, weight="bold")
        ax.margins(x=0.2)
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle(f"Delay vs loss for every variant (mean ± std over {N_SEEDS} seeds; lower-left is better)", weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "tradeoff_delay_loss.png")
    plt.close(fig)


def improvement_chart():
    rel = pd.read_csv(RESULTS / "predictive_vs_baselines.csv")
    rel = rel[rel.level != "low"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), dpi=150, sharey=True)
    cols = [("drops_%", "Drops"), ("retransmissions_%", "Retransmissions"), ("rtt_%", "RTT"),
            ("queue_%", "Queue"), ("goodput_%", "Goodput")]
    for ax, level in zip(axes, ["medium", "high"]):
        part = rel[rel.level == level].set_index("vs")
        x = np.arange(len(cols))
        for k, base in enumerate(BASELINES):
            values = [part.loc[base, c] for c, _ in cols]
            bars = ax.bar(x + (k - 2) * 0.16, np.clip(values, -100, 100), 0.16,
                          color=COLORS[base], label=f"vs {NAMES[base]}")
            for bar, v in zip(bars, values):
                if v > 100:  # off the scale: print the real value on top
                    ax.text(bar.get_x() + bar.get_width() / 2, 101, f"+{v:.0f}%", rotation=90,
                            ha="center", va="bottom", fontsize=6.5)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylim(-100, 160)
        ax.set_xticks(x, [name for _, name in cols])
        ax.set_title(f"{level.capitalize()} congestion", fontsize=10, weight="bold")
    axes[0].set_ylabel("Change for Predictive TCP (%)")
    axes[0].legend(fontsize=8)
    fig.suptitle("Predictive TCP relative to each baseline (negative = lower; bars cut at +100%)", weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "predictive_improvement.png")
    plt.close(fig)


def validation_chart():
    fig, axes = plt.subplots(len(VARIANTS), 1, figsize=(10, 14), dpi=150, sharex=True)
    traces = {v: pd.read_csv(VALID / f"cwnd_{v}_single_s1.csv") for v in VARIANTS}
    end = max(tr.time.max() for tr in traces.values())
    for ax, variant in zip(axes, VARIANTS):
        trace = traces[variant]
        # Only changes are logged; hold the last value to the end (Vegas stops changing early)
        trace = pd.concat([trace, trace.tail(1).assign(time=end)], ignore_index=True)
        ax.plot(trace.time, trace.cwnd_bytes / SEGMENT, lw=1.2, color=COLORS[variant], label="cwnd")
        ax.plot(trace.time, trace.ssthresh_bytes.clip(upper=4e5) / SEGMENT, lw=1, ls="--", color="black",
                label="ssthresh")
        info = pd.read_csv(VALID / f"flowmon_{variant}_single_s1.csv").iloc[0]
        ax.set_title(f"{NAMES[variant]}: {info.throughput_mbps:.2f} Mbps, "
                     f"{int(info.lost_packets)} packets lost", fontsize=10, weight="bold")
        ax.set_ylabel("segments")
        ax.set_ylim(0, 200)
        ax.legend(fontsize=8, loc="upper right")
    axes[-1].set_xlabel("time (s)")
    fig.suptitle("Congestion window of one long flow (10 Mbps bottleneck, 50-packet queue)", weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(GRAPHS / "validation_cwnd.png")
    plt.close(fig)


def ablation_chart():
    abl = pd.read_csv(RESULTS / "ablation_summary.csv")
    high = abl[abl.level == "high"].set_index("setting")
    runs = pd.read_csv(RESULTS / "comparison_runs.csv")
    base = runs[runs.level == "high"].groupby("variant")[["drops", "jain_fairness"]].mean()
    labels = [NAMES[v] for v in ["tahoe", "reno", "cubic"]] + list(high.index)
    drops = list(base.loc[["tahoe", "reno", "cubic"], "drops"]) + list(high.drops)
    fair = list(base.loc[["tahoe", "reno", "cubic"], "jain_fairness"]) + list(high.jain_fairness)
    colors = [COLORS[v] for v in ["tahoe", "reno", "cubic"]] + [
        "#145a32" if name.startswith("proposed") else "#7dcea0" for name in high.index]
    y = np.arange(len(labels))[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=150, sharey=True)
    axes[0].barh(y, drops, color=colors)
    axes[0].set_xlabel("Bottleneck drops")
    axes[1].barh(y, fair, color=colors)
    axes[1].set_xlim(0.7, 1.0)
    axes[1].axvline(0.9, color="red", ls="--", lw=1, label="PRD target 0.9")
    axes[1].set_xlabel("Jain fairness index")
    axes[1].legend(fontsize=8, loc="lower left")
    axes[0].set_yticks(y, labels)
    for ax, values, fmt in [(axes[0], drops, "{:.0f}"), (axes[1], fair, "{:.3f}")]:
        for yi, v in zip(y, values):
            ax.text(v, yi, " " + fmt.format(v), va="center", fontsize=7)
    fig.suptitle(f"Ablation at high congestion (mean of {N_SEEDS} seeds): darker green = proposed setting",
                 weight="bold")
    fig.tight_layout()
    fig.savefig(GRAPHS / "ablation_tradeoff.png")
    plt.close(fig)


def final_table(runs):
    cols = [("goodput_mbps", "Goodput (Mbps)", 2), ("mean_rtt_ms", "RTT (ms)", 1), ("drops", "Drops", 0),
            ("retransmissions", "Retransmissions", 0), ("mean_queue_pkts", "Queue (pkts)", 1),
            ("jain_fairness", "Fairness", 3)]
    stats = runs.groupby(["level", "variant"])
    mean, std = stats.mean(numeric_only=True), stats.std(numeric_only=True)
    lines = ["| Level | Variant | " + " | ".join(c[1] for c in cols) + " |",
             "|---|---|" + "---|" * len(cols)]
    rows = []
    for level in LEVELS:
        for variant in VARIANTS:
            cells = []
            for col, name, digits in cols:
                m, s = mean.loc[(level, variant), col], std.loc[(level, variant), col]
                cells.append(f"{m:.{digits}f} ± {s:.{digits}f}")
            name = f"**{NAMES[variant]}**" if variant == "predictive" else NAMES[variant]
            lines.append(f"| {level.capitalize()} | {name} | " + " | ".join(cells) + " |")
            rows.append([level, NAMES[variant]] + cells)
    pd.DataFrame(rows, columns=["Level", "Variant"] + [c[1] for c in cols]).to_csv(
        RESULTS / "final_table.csv", index=False)
    table = "\n".join(lines)
    (RESULTS / "final_table.md").write_text(table + "\n")
    return table


def results_page(table):
    metrics = json.loads((RESULTS / "model" / "metrics.json").read_text())
    tree = next(r for r in metrics["test"] if r["model"] == "Decision Tree")
    logreg = next(r for r in metrics["test"] if r["model"] == "Logistic Regression")
    reactive = next(r for r in metrics["test"] if r["model"] == "Reactive (loss-based)")
    warn = metrics["early_warning"]
    checks = pd.read_csv(RESULTS / "prd_criteria_check.csv")
    check_rows = "\n".join(f"| {r.level.capitalize()} | {r.criterion} | {r.value} | {'✅' if r.met else '❌'} |"
                           for r in checks.itertuples())
    wins = pd.read_csv(RESULTS / "seed_wins.csv")
    win_rows = "\n".join(f"| {r.level.capitalize()} | {NAMES[r.vs]} | {r.fewer_drops}/{r.seeds} | "
                         f"{r.lower_rtt}/{r.seeds} | {r.goodput_within_5pct}/{r.seeds} |" for r in wins.itertuples())
    abl = pd.read_csv(RESULTS / "ablation_summary.csv")
    abl_rows = "\n".join(f"| {r.level.capitalize()} | {r.setting} | {r.goodput_mbps:.2f} | {r.mean_rtt_ms:.1f} | "
                         f"{r.drops:.0f} | {r.jain_fairness:.3f} |" for r in abl.itertuples())
    runs = pd.read_csv(RESULTS / "comparison_runs.csv")
    avg = runs.groupby(["level", "variant"]).mean(numeric_only=True)
    rel = pd.read_csv(RESULTS / "predictive_vs_baselines.csv").set_index(["level", "vs"])

    net = pd.read_csv(RESULTS / "robustness" / "network_sweep.csv")
    net_rows = "\n".join(
        f"| {r.rate_mbps} Mbps | {r.delay_ms} ms | {r[2]:+.0f}% | {r[3]:+.0f}% | {r[4]:.1f}% | "
        f"{r.jain_predictive:.2f} | {r.jain_reno:.2f} | {r.jain_cubic:.2f} | {r[8]:.0f}% | "
        f"{r.seeds_fewer_drops}/{N_SEEDS} / {r.seeds_lower_rtt}/{N_SEEDS} |" for r in net.itertuples(index=False))
    sig = pd.read_csv(RESULTS / "significance.csv")
    def fmt_p(p):
        return "< 0.0001" if p < 1e-4 else f"{p:.4f}"
    sig_rows = "\n".join(
        f"| {r.level.capitalize()} | {NAMES[r.vs]} | {r.metric} | {r.mean_diff:+.2f} | "
        f"[{r.ci95_low:+.2f}, {r.ci95_high:+.2f}] | {r.seeds_lower}/{r.seeds} | {fmt_p(r.t_test_p)} | "
        f"{fmt_p(r.sign_test_p)} |" for r in sig[sig.vs.isin(["reno", "cubic"])].itertuples(index=False))
    sig_other = sig[~sig.vs.isin(["reno", "cubic"]) & (sig.t_test_p >= 0.05)]
    sig_other_text = "; ".join(f"{r.level} load vs {NAMES[r.vs]}, {r.metric} ({r.mean_diff:+.2f}, p = {r.t_test_p:.2f})"
                               for r in sig_other.itertuples(index=False)) or "none"
    base = pd.read_csv(RESULTS / "model" / "prediction_baselines.csv")
    base_rows = "\n".join(
        f"| {r.scope.capitalize()} | {r.model} | {r[2]:.1f}% | {r.high_precision:.3f} | {r.high_recall:.3f} | "
        f"{r.high_f1:.3f} | {r.balanced_accuracy:.3f} | {r.mcc:.3f} |" for r in base.itertuples(index=False))
    b = base.set_index(["scope", "model"])
    n = net.set_index(["rate_mbps", "delay_ms"])
    used = [f for f, imp in metrics["feature_importance"].items() if imp > 0]
    choice = json.loads((RESULTS / "model" / "selection_choice.json").read_text())
    tune = json.loads((RESULTS / "model" / "tuning_choice.json").read_text())
    buffer = pd.read_csv(RESULTS / "robustness" / "buffer_vs_reno.csv")
    buffer_rows = "\n".join(
        f"| {r.queue} | {r.level.capitalize()} | {r[2]:+.1f}% | {r[3]:+.1f}% | {r[4]:.1f}% | {r.jain:.2f} | "
        f"{r.seeds_fewer_drops}/{N_SEEDS} / {r.seeds_lower_rtt}/{N_SEEDS} | {r[8]:.0f}% |" for r in buffer.itertuples(index=False))
    big_buffer_reno_mode = buffer.set_index(["queue", "level"]).loc[(100, "high"), "reno_mode_%"]
    nodet = pd.read_csv(RESULTS / "robustness" / "buffer_100_nodetector.csv").iloc[0]
    nodet_drops, nodet_rtt = nodet["drops_vs_reno_%"], nodet["rtt_vs_reno_%"]
    mixed = pd.read_csv(RESULTS / "robustness" / "mixed_competition.csv")
    mixed_rows = "\n".join(
        f"| {MIXED_LABELS.get(r.variant, NAMES.get(r.variant))} | {r.share_mean:.1f}% ± {r.share_std:.1f} | {r.tested_mbps:.2f} | {r.cubic_mbps:.2f} | "
        f"{r.mean_rtt_ms:.1f} | {r.drops:.0f} |" for r in mixed.itertuples(index=False))
    vegas_share = f"{mixed.set_index('variant').loc['vegas', 'share_mean']:.0f}%"
    shares = mixed.set_index("variant").share_mean
    comp = json.loads((RESULTS / "model" / "competition_choice.json").read_text())
    comp_grid = pd.read_csv(RESULTS / "model" / "competition_tuning.csv")
    comp_rows = "\n".join(
        (f"| **{r.setting}** |" if r.setting == comp["chosen"] else f"| {r.setting} |")
        + f" {r.share_vs_cubic_pct:.1f}% | {r.competitive_pct_medium:.0f}% / {r.competitive_pct_high:.0f}% |"
          f" {r.drops_medium:+.0f}% / {r.drops_high:+.0f}% | {r.rtt_medium:+.0f}% / {r.rtt_high:+.0f}% |"
          f" {r.jain_high:.2f} | {'✅' if r.eligible else '❌'} |"
        for r in comp_grid.rename(columns={
            "share_vs_cubic_%": "share_vs_cubic_pct", "competitive_%_medium": "competitive_pct_medium",
            "competitive_%_high": "competitive_pct_high", "drops_vs_reno_%_medium": "drops_medium",
            "drops_vs_reno_%_high": "drops_high", "rtt_vs_reno_%_medium": "rtt_medium",
            "rtt_vs_reno_%_high": "rtt_high"}).itertuples(index=False))
    tuning = pd.read_csv(RESULTS / "model" / "tuning.csv")
    tune_rows = "\n".join(
        ("| **{}** | **{}** |" if (r.beta, r.min_window) == (tune["beta"], tune["min_window"]) else "| {} | {} |")
        .format(r.beta, r.min_window)
        + f" {r[3]:+.0f}% / {r[2]:+.0f}% | {r[5]:+.0f}% / {r[4]:+.0f}% | {r[7]:.1f}% / {r[6]:.1f}% / {r[8]:.1f}% |"
          f" {r[10]:.2f} / {r[9]:.2f} | {'✅' if r.eligible else '❌'} |"
        for r in tuning.itertuples(index=False))
    exp = pd.read_csv(RESULTS / "model" / "experiments.csv")
    exp_rows = "\n".join(
        f"| {r.horizon_s} s | {r.features} | {r.depth} | {r.leaves} | {r.macro_f1:.3f} | {r.high_recall:.3f} | "
        f"{r.warned_200ms_pct:.0f}% | {r.false_alarm_pct:.1f}% | {r.features_used} |" for r in exp.itertuples())
    sel = pd.read_csv(RESULTS / "model" / "selection.csv").rename(columns={
        "drops_vs_reno_%": "drops", "rtt_vs_reno_%": "rtt", "goodput_vs_reno_%": "goodput"})
    sel_rows = "\n".join(
        f"| {'**' + r.candidate + '**' if r.candidate == choice['chosen'] else r.candidate} | {r.level.capitalize()} | "
        f"{r.depth:.0f} | {r.leaves:.0f} | {r.drops:+.1f}% | {r.rtt:+.1f}% | {r.goodput:.1f}% | {r.jain:.3f} |"
        for r in sel.itertuples())
    runs["split"] = np.where(runs.seed <= 3, "1-3 (train)", f"4-{N_SEEDS} (unseen)")
    split = runs.groupby(["level", "split", "variant"]).mean(numeric_only=True)
    split_rows = []
    for level in ["medium", "high"]:
        for sp in ["1-3 (train)", f"4-{N_SEEDS} (unseen)"]:
            p, r = split.loc[(level, sp, "predictive")], split.loc[(level, sp, "reno")]
            split_rows.append(f"| {level.capitalize()} | {sp} | {100 * (p.drops - r.drops) / r.drops:+.1f}% | "
                              f"{100 * (p.mean_rtt_ms - r.mean_rtt_ms) / r.mean_rtt_ms:+.1f}% | "
                              f"{100 * p.goodput_mbps / r.goodput_mbps:.1f}% | {p.jain_fairness:.3f} |")
    split_rows = "\n".join(split_rows)
    delay_rows = "\n".join(
        f"| {level.capitalize()} | {NAMES[v]} | {avg.loc[(level, v), 'goodput_mbps']:.2f} | "
        f"{avg.loc[(level, v), 'mean_rtt_ms']:.1f} | {avg.loc[(level, v), 'drops']:.0f} | "
        f"{avg.loc[(level, v), 'jain_fairness']:.3f} |"
        for level in ["medium", "high"] for v in ["reno", "vegas", "bbr", "predictive"])

    def drops(v, level):
        return f"{avg.loc[(level, v), 'drops']:.0f}"

    def rtt(v, level):
        return f"{avg.loc[(level, v), 'mean_rtt_ms']:.1f}"

    def jain(v):
        return f"Jain {avg.loc[('high', v), 'jain_fairness']:.2f}"

    def single(v):
        return f"{pd.read_csv(VALID / f'flowmon_{v}_single_s1.csv').throughput_mbps.iloc[0]:.1f}"

    def fmt_rel(base):
        return "; ".join(f"{lv}: drops {rel.loc[(lv, base), 'drops_%']:+.0f}%, RTT {rel.loc[(lv, base), 'rtt_%']:+.1f}%"
                         for lv in ["medium", "high"])

    page = f"""# Results: Lightweight Predictive Congestion Estimator for TCP

Generated by `analysis/make_graphs.py`. All values are the mean over {N_SEEDS} random seeds of 60 s NS-3 simulations
(10 Mbps / 20 ms bottleneck, 50-packet FIFO queue).

## 1. TCP Variants Compared

{table}

![Comparison bars](graphs/comparison_bars.png)

![Improvement](graphs/predictive_improvement.png)

## 2. PRD Success Criteria (Section 10.3)

| Level | Criterion | Value | Met |
|---|---|---|---|
{check_rows}

**Seed-by-seed check** (each seed gives every variant the same traffic, so runs can be paired):

| Level | Predictive vs | Fewer drops | Lower RTT | Goodput within 5% |
|---|---|---|---|---|
{win_rows}

**Held-out check:** the model was trained (and chosen) on seeds 1-3 only. Results on seeds 1-3 vs the unseen seeds 4-{N_SEEDS}:

| Level | Seeds | Drops vs Reno | RTT vs Reno | Goodput vs Reno | Fairness |
|---|---|---|---|---|---|
{split_rows}

### 2.1 Statistical Significance (Phase 12)

Runs are paired by seed (same traffic for every variant). Difference = Predictive minus the baseline, in the metric's
own unit; 95% confidence interval of the mean per-seed difference; paired t-test (two-sided); exact sign test
(one-sided, in the direction of the difference). The exact two-sided Wilcoxon
signed-rank p-value is in `results/significance.csv`; with {N_SEEDS} seeds the smallest possible sign-test p-value is
{0.5 ** N_SEEDS:.4f}.

| Level | Predictive vs | Metric | Mean difference | 95% CI | Seeds lower | t-test p | Sign test p |
|---|---|---|---|---|---|---|---|
{sig_rows}

- **Every drop and RTT improvement over Reno and CUBIC is significant** (confidence intervals far from
  zero). The small goodput cost is significant too: it is real, but well inside the PRD limit (≥ 90% of Reno).
- **Against Tahoe, Vegas and BBR** (`results/significance.csv`), the differences that are *not* significant at
  p < 0.05 are: {sig_other_text}.

## 3. Loss-Based vs Delay-Based TCP (Vegas, BBR)

![Delay vs loss](graphs/tradeoff_delay_loss.png)

| Level | Variant | Goodput (Mbps) | RTT (ms) | Drops | Fairness |
|---|---|---|---|---|---|
{delay_rows}

- **BBR (v1)** keeps sending at its bandwidth estimate even when the queue is full, so it overflows the shallow
  50-packet buffer; this is a known BBRv1 weakness in shallow buffers. Change for Predictive TCP vs BBR: {fmt_rel("bbr")}.
- **Vegas** is the strongest baseline. Change for Predictive TCP vs Vegas: {fmt_rel("vegas")}.
  Vegas flows share unfairly at high load ({jain("vegas")}): flows that start later measure a base RTT that
  already includes queueing.
- **Vegas alone cannot fill the link:** with one flow it reaches {single("vegas")} Mbps on the 10 Mbps link
  (Reno {single("reno")}, Predictive TCP {single("predictive")}). Delayed ACKs add a few ms to every RTT sample,
  Vegas reads this as queueing and stops growing at about half the bandwidth-delay product. With an ACK for every
  packet it reaches 9.6 Mbps. All variants use the same (default) ACK settings so the comparison stays fair.
- **What remains open:** Vegas is known to lose bandwidth when it shares a link with loss-based TCP such as CUBIC.
  Phase 8 tests whether Predictive TCP has the same problem.

## 4. Behaviour Over Time (seed {EXAMPLE_SEED}, not used for training)

![Medium](graphs/timeseries_medium.png)

![High](graphs/timeseries_high.png)

## 5. Variant Validation (single long flow)

![Validation](graphs/validation_cwnd.png)

## 6. Congestion Prediction Model

**Trained on:** {", ".join(metrics["model_features"])}. **Used by the tree:** {", ".join(used)}.
**Tree:** depth {metrics["tree_depth"]}, {metrics["tree_leaves"]} leaves, labels {metrics["horizon_s"]} s ahead.
**Test set:** {metrics["test_samples"]:,} samples from seeds {metrics["test_seeds"]}, never seen in training.

| Model | Accuracy | Macro-F1 | Precision (High) | Recall (High) | Bursts warned ≥ 200 ms | False alarms |
|---|---|---|---|---|---|---|
| Decision Tree | {tree["accuracy"]:.3f} | {tree["macro_f1"]:.3f} | {tree["high_precision"]:.3f} | {tree["high_recall"]:.3f} | {warn["Decision Tree"]["warned_200ms_pct"]:.0f}% | {warn["Decision Tree"]["false_alarm_pct"]:.1f}% |
| Logistic Regression | {logreg["accuracy"]:.3f} | {logreg["macro_f1"]:.3f} | {logreg["high_precision"]:.3f} | {logreg["high_recall"]:.3f} | {warn["Logistic Regression"]["warned_200ms_pct"]:.0f}% | {warn["Logistic Regression"]["false_alarm_pct"]:.1f}% |
| Reactive (loss-based) | {reactive["accuracy"]:.3f} | {reactive["macro_f1"]:.3f} | {reactive["high_precision"]:.3f} | {reactive["high_recall"]:.3f} | {warn["Reactive (loss-based)"]["warned_200ms_pct"]:.0f}% | {warn["Reactive (loss-based)"]["false_alarm_pct"]:.1f}% |

![Confusion matrices](graphs/ml_confusion_matrices.png)

![Decision tree](graphs/ml_decision_tree.png)

![Feature importance](graphs/ml_feature_importance.png)

### 6.1 Feature Sets and Prediction Horizons (offline, test seeds 4-5)

| Horizon | Features | Depth | Leaves | Macro-F1 | Recall (High) | Bursts warned ≥ 200 ms | False alarms | Used by the tree |
|---|---|---|---|---|---|---|---|---|
{exp_rows}

![Feature sets](graphs/ml_feature_sets.png)

![Warning trade-off](graphs/ml_warning_tradeoff.png)

### 6.2 Choosing the Deployed Model Inside NS-3 (training seeds 1-3 only)

Offline scores do not show how a model behaves once it controls the sending rate, so each candidate was compiled
into Predictive TCP and simulated. **Rule:** keep candidates with goodput ≥ 95% of Reno and fairness ≥ 0.9 at both
levels, then pick the largest average reduction in drops plus RTT. **Chosen: {choice["chosen"]}.**

| Candidate | Level | Depth | Leaves | Drops vs Reno | RTT vs Reno | Goodput vs Reno | Fairness |
|---|---|---|---|---|---|---|---|
{sel_rows}

![Early warning](graphs/ml_early_warning.png)

### 6.3 Against a Trivial Guess (Phase 10)

{b.loc[("all", "Always High"), "high_share_%"]:.0f}% of the test samples are labelled High (almost all of them at high
load), so a model that always answers "High" already looks good on accuracy and on the High-class F1. Balanced
accuracy and the Matthews correlation coefficient (MCC: 0 = no better than a constant guess) cannot be gamed this
way. The task here is binary: will the bottleneck be congested (High) 0.5 s from now?

| Test samples | Model | Labelled High | Precision (High) | Recall (High) | F1 (High) | Balanced accuracy | MCC |
|---|---|---|---|---|---|---|---|
{base_rows}

- **Medium load is where prediction matters**, because congestion comes and goes. There the tree beats the trivial
  guess (MCC {b.loc[("medium", "Decision Tree"), "mcc"]:.2f}, balanced accuracy
  {b.loc[("medium", "Decision Tree"), "balanced_accuracy"]:.2f}), but its High-class F1
  ({b.loc[("medium", "Decision Tree"), "high_f1"]:.3f}) is no better than always answering "High"
  ({b.loc[("medium", "Always High"), "high_f1"]:.3f}).
- **At high load there is nothing to predict:** the queue is almost always congested. The tree answers "Medium" for a
  short time after the queue has been cut, which lowers its recall there; this is the intended control behaviour.
- **Macro-F1 ({tree["macro_f1"]:.2f}) is held down by the rare Medium class** ({100 * (1 - b.loc[("all", "Always High"), "high_share_%"] / 100):.0f}%
  of samples are not High, and Medium is the smaller part of those). The ablation (section 7) shows that the
  reaction to Medium barely changes the results, so the closed-loop numbers in sections 1-2 are the better measure
  of the predictor; the offline scores should be read with this table next to them.

## 7. Ablation Study

The competition detector is switched off in these runs, so they measure the prediction mechanism alone
(the detector is evaluated in sections 9.2-9.3).

| Level | Setting | Goodput (Mbps) | RTT (ms) | Drops | Fairness |
|---|---|---|---|---|---|
{abl_rows}

![Ablation](graphs/ablation_tradeoff.png)

## 8. Controller Tuning (training seeds 1-3 only)

How strongly to cut on a High prediction (β) and the window below which the predictor never acts (MinWindow)
were tuned in `analysis/tune_controller.py`. **Rule:** goodput ≥ 97% of Reno at medium load, at high load and
with a single flow, fairness ≥ 0.9; then the largest drop + RTT reduction (ties within 2 points: the fairest).
The single-flow check was added after the first version of the rule chose β = 0.5, which left a lone flow at
87% of Reno's goodput. **Chosen: β = {tune["beta"]}, MinWindow = {tune["min_window"]}**
({tune["eligible"]} of {tune["settings"]} settings passed the limits).

| β | MinWindow | Drops (med / high) | RTT (med / high) | Goodput (med / high / single) | Fairness (med / high) | Passes limits |
|---|---|---|---|---|---|---|
{tune_rows}

![Tuning](graphs/tuning_grid.png)

## 9. Robustness (Phase 8)

### 9.1 Other Buffer Sizes

The model was trained and the controller tuned with a 50-packet queue only (≈ 1.3× the bandwidth-delay product of
38 packets). Predictive TCP compared with Reno at each queue size (mean of {N_SEEDS} seeds):

| Queue | Level | Drops vs Reno | RTT vs Reno | Goodput vs Reno | Fairness | Seeds with fewer drops / lower RTT | Time in Reno mode (detector) |
|---|---|---|---|---|---|---|---|
{buffer_rows}

**Detector false alarms with a large buffer:** with a 100-packet queue at high load, the competition detector
(section 9.3) switches to Reno mode for {big_buffer_reno_mode:.0f}% of the time on average, although no CUBIC flow is
present. The false alarm feeds itself: a flow in Reno mode keeps the queue full, so the other flows also conclude
that a loss-based competitor is present. Predictive TCP still beats Reno in every seed, but by less than with the
detector off (with the detector off: drops {nodet_drops:+.0f}%, RTT {nodet_rtt:+.0f}% vs Reno).

![Buffer sweep](graphs/robustness_buffer.png)

### 9.2 Sharing the Link with CUBIC

At high load, 4 flows of each variant share the bottleneck with 4 CUBIC flows (even-numbered flows use the variant,
odd-numbered flows use CUBIC). A fair variant takes about 50% of the TCP goodput.

| 4 flows of | Share taken | Its 4 flows (Mbps) | 4 CUBIC flows (Mbps) | Mean RTT (ms) | Drops |
|---|---|---|---|---|---|
{mixed_rows}

![Competition](graphs/mixed_competition.png)

**Why delay-based senders lose to CUBIC:** Predictive TCP cuts its window whenever the queue grows, but CUBIC keeps
filling the queue until packets are lost, so the queue never empties and Predictive TCP keeps backing off. This is
the known weakness of delay-based congestion control (Vegas shows it too, at {vegas_share}). Without help,
Predictive TCP gets only {shares["predictive_nodetector"]:.0f}%.

### 9.3 Competition Detector (Phase 8b, base RTT fixed in Phase 10)

When only Predictive flows share the link, their cuts let the queue drain now and then. A loss-based sender keeps
it full until packets drop. So if the lowest RTT over the last *window* stays above *threshold* × base RTT, Predictive
TCP behaves like plain Reno, and stays so for at least *hold* seconds after the queue was last seen not draining.
The three values were tuned on training seeds 1-3 (`analysis/tune_competition.py`). **Rule:** the Phase 7 limits,
keep at least 50% fewer drops and 10% lower RTT than Reno with only Predictive flows, then the share against CUBIC
closest to 50%; within 2 points, the larger drop + RTT reduction. **Chosen: {comp["chosen"]}** (window
{comp["window_s"]:.0f} s, threshold {comp["threshold"]}, hold {comp["hold_s"]:.0f} s).

With the detector, Predictive TCP's share against CUBIC rises from {shares["predictive_nodetector"]:.0f}% to
{shares["predictive"]:.0f}%. **Phase 10 fix:** the Phase 8b detector took its base RTT from the lowest *smoothed* RTT and
reached only {shares["predictive_phase8b"]:.0f}%. Flows that started behind CUBIC's standing queue never saw a smoothed RTT
near the true 44 ms (they learned 60-85 ms), so their threshold sat above the RTT they measured and they never detected
the competitor. Given the true base RTT, the share reached about 45% (Reno's level) in a diagnostic run; the realistic
fix measures the base from raw RTT samples, which catch the brief dips of the queue. Settings with a lower threshold
or a longer hold can take a larger share, but some of them also switch to Reno mode when no competitor is present
(8 Predictive flows plus the UDP traffic keep the queue from fully draining at high load) and then lose most of the
gains:

| Setting | Share vs CUBIC | Reno mode, Predictive flows only (med / high) | Drops vs Reno (med / high) | RTT vs Reno (med / high) | Fairness (high) | Passes rule |
|---|---|---|---|---|---|---|
{comp_rows}

![Competition tuning](graphs/competition_tuning.png)

### 9.4 Other Link Speeds and Delays (Phase 10)

The model was trained and every setting tuned at 10 Mbps with a 20 ms bottleneck delay. Here the high-load scenario
(8 bulk flows + UDP) runs at 5, 10 and 50 Mbps with a 20 or 100 ms bottleneck delay; the queue is 1.3× the
bandwidth-delay product in each case (mean of {N_SEEDS} seeds; Reno and CUBIC under the same conditions).

| Link | Bottleneck delay | Drops vs Reno | RTT vs Reno | Goodput vs Reno | Fairness: Predictive | Reno | CUBIC | Time in Reno mode | Seeds with fewer drops / lower RTT |
|---|---|---|---|---|---|---|---|---|---|
{net_rows}

- **Drops:** fewer than Reno in every seed at every link speed and delay.
- **Fairness collapses on fast or long links** (Jain {n.loc[(50, 20), "jain_predictive"]:.2f} at 50 Mbps / 20 ms,
  {n.loc[(10, 100), "jain_predictive"]:.2f} at 10 Mbps / 100 ms), where Reno stays fair. The cause is delayed ACKs: the
  receiver ACKs every second segment, so the smoothed RTT of a flow with a small window includes time spent waiting
  for the ACK. Small flows therefore measure a higher RTT than a big flow on the same path, predict High, cut and stop
  growing, while the big flow measures a lower RTT and keeps growing. In diagnostic runs at 50 Mbps / 20 ms, turning
  delayed ACKs off brought fairness back to 0.98, and so did feeding the model the lowest raw RTT of each interval
  (`MinRttSignal`, off by default). The deployed tree was trained on the smoothed RTT, though. In Phase 11, models
  retrained on the new signal and tuned on seeds 1-3 were fair at 50 Mbps only with the full feature set and a hard
  cut, keeping about half of the main gain, so the deployed model was kept (README finding 21).
- **The detector false-alarms where the queue never drains on its own:** at 5 Mbps / 20 ms (the 2 Mbps UDP flow takes
  40% of the link) Predictive TCP spends {n.loc[(5, 20), "reno_mode_%"]:.0f}% of the time in Reno mode and keeps only a
  {n.loc[(5, 20), "drops_vs_reno_%"]:+.0f}% drop change; at 10 Mbps with a 49-packet queue it spends
  {n.loc[(10, 20), "reno_mode_%"]:.0f}% there (0% with the 50-packet queue it was tuned on).
"""
    (RESULTS / "RESULTS.md").write_text(page)


def main():
    GRAPHS.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(RESULTS / "comparison_runs.csv")
    for level in ["medium", "high"]:
        time_series(level)
    bar_charts(runs)
    tradeoff_chart(runs)
    improvement_chart()
    validation_chart()
    ablation_chart()
    table = final_table(runs)
    results_page(table)
    print(table)
    print(f"\nGraphs in {GRAPHS}\nResults page: {RESULTS / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
