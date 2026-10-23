"""Phase 2, step 1: turn the baseline simulation CSVs into an ML dataset.

Features use only what a TCP sender can measure itself. Labels come from the
real bottleneck queue, looking HORIZON seconds into the future, so the model
learns to predict congestion before it happens.

Phase 6 added queue-trend features (how RTT is changing over 0.5 s and 1 s,
RTT relative to its recent average) and the time since the last loss.

Usage: .venv/bin/python analysis/build_dataset.py
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
OUT = ROOT / "results" / "dataset.csv"

VARIANTS = ["tahoe", "reno", "cubic"]
LEVELS = ["low", "medium", "high"]
SEEDS = [1, 2, 3, 4, 5]
SEGMENT = 1448
INTERVAL = 0.1
HORIZON = 0.5          # look-ahead for labels (seconds)
WARMUP = 3.0           # ignore start-up slow start
MEDIUM_THRESHOLD = 0.4
HIGH_THRESHOLD = 0.8

FEATURES = ["rtt_ratio", "rtt_grad", "est_queue_pkts", "cwnd_seg", "cwnd_rel", "thr_mbps",
            "loss_recent", "loss_2s",
            "rtt_trend_05", "rtt_trend_1", "rtt_vs_avg", "since_loss"]
HISTORY = 20           # samples (2 s) used for the window maximum
TREND_SHORT = 5        # samples (0.5 s) for the short RTT trend
TREND_LONG = 10        # samples (1 s) for the long RTT trend and the RTT average
LABEL_NAMES = ["Low", "Medium", "High"]
# RTT signal the features are computed from (Phase 11): "smoothed" (the socket's smoothed RTT)
# or "min" (lowest raw RTT sample per interval). Must match TcpPredictive::MinRttSignal.
RTT_SIGNAL = os.environ.get("RTT_SIGNAL", "smoothed")


def sender_features(df):
    """Per-flow features computed exactly as the sender will compute them."""
    df = df.sort_values(["flow", "time"]).copy()
    if RTT_SIGNAL == "min":
        # Lowest raw RTT sample of each 100 ms interval, and the lowest raw sample so far as
        # the base RTT (TcpPredictive::MinRttSignal): not inflated by delayed ACKs for small
        # windows, and the base reaches the true RTT for flows that start behind a queue
        rtt, base = df.rtt_min_int_ms, df.raw_min_rtt_ms
    else:
        rtt, base = df.srtt_ms, df.min_rtt_ms  # smoothed RTT and its lowest value so far
    prev_rtt = rtt.groupby(df.flow).shift(1)
    df["rtt_ratio"] = rtt / base
    df["rtt_grad"] = ((rtt - prev_rtt) / base).fillna(0.0)
    df["cwnd_seg"] = df.cwnd_bytes / SEGMENT
    df["est_queue_pkts"] = (df.cwnd_seg * (1 - base / rtt)).clip(lower=0)
    # Position in the saw-tooth: cwnd relative to its maximum over the last 2 s
    recent_max = df.groupby("flow").cwnd_bytes.transform(lambda x: x.rolling(HISTORY, min_periods=1).max())
    df["cwnd_rel"] = df.cwnd_bytes / recent_max
    df["loss_recent"] = df.loss_events_05s
    df["loss_2s"] = df.loss_events_2s
    # Queue trend: how much the RTT grew over the last 0.5 s and 1 s (in units of
    # the base RTT), and the RTT relative to its own 1 s average
    by_flow = rtt.groupby(df.flow)
    df["rtt_trend_05"] = ((rtt - by_flow.shift(TREND_SHORT)) / base).fillna(0.0)
    df["rtt_trend_1"] = ((rtt - by_flow.shift(TREND_LONG)) / base).fillna(0.0)
    df["rtt_vs_avg"] = rtt / by_flow.transform(lambda x: x.rolling(TREND_LONG, min_periods=1).mean())
    df["since_loss"] = df.since_loss_s
    return df


def future_labels(df, horizon=HORIZON):
    """Label each time step from the bottleneck queue over the next `horizon` seconds."""
    bottleneck = df.drop_duplicates("time").set_index("time").sort_index()
    occupancy = bottleneck.queue_pkts / bottleneck.queue_cap
    steps = int(round(horizon / INTERVAL))
    # Max occupancy and total drops over the NEXT `steps` intervals (excluding now)
    future_occ = occupancy[::-1].rolling(steps, min_periods=steps).max()[::-1].shift(-1)
    future_drops = bottleneck.drops[::-1].rolling(steps, min_periods=steps).sum()[::-1].shift(-1)
    current_occ = occupancy

    label = pd.Series(0, index=bottleneck.index)
    label[future_occ >= MEDIUM_THRESHOLD] = 1
    label[(future_occ >= HIGH_THRESHOLD) | (future_drops > 0)] = 2
    label[future_occ.isna()] = -1

    now = pd.Series(0, index=bottleneck.index)
    now[current_occ >= MEDIUM_THRESHOLD] = 1
    now[(current_occ >= HIGH_THRESHOLD) | (bottleneck.drops > 0)] = 2

    out = pd.DataFrame({"label": label, "label_now": now, "future_drops": future_drops,
                        "queue_now": current_occ, "drops_now": bottleneck.drops})
    return df.merge(out, left_on="time", right_index=True)


def build(horizon=HORIZON):
    """The full dataset with labels `horizon` seconds ahead."""
    parts = []
    for variant in VARIANTS:
        for level in LEVELS:
            for seed in SEEDS:
                df = pd.read_csv(RAW / f"samples_{variant}_{level}_s{seed}.csv")
                df = future_labels(sender_features(df), horizon)
                df["variant"], df["level"], df["seed"] = variant, level, seed
                parts.append(df)
    data = pd.concat(parts, ignore_index=True)

    # Keep active flows only: an idle flow receives no ACKs, so a real sender
    # would have nothing to predict from.
    data = data[(data.time >= WARMUP) & (data.label >= 0) & (data.thr_mbps > 0)]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES)
    keep = ["variant", "level", "seed", "time", "flow"] + FEATURES + [
        "label", "label_now", "future_drops", "queue_now", "drops_now"]
    return data[keep]


def main():
    data = build()
    data.to_csv(OUT, index=False)

    print(f"Saved {len(data):,} samples to {OUT}\n")
    counts = data.groupby(["level", "label"]).size().unstack(fill_value=0)
    counts.columns = [LABEL_NAMES[c] for c in counts.columns]
    print("Samples per congestion level and label (0.5 s ahead):")
    print(counts.to_string())
    print("\nOverall class share:")
    print((data.label.value_counts(normalize=True).sort_index() * 100).round(1)
          .rename(index=dict(enumerate(LABEL_NAMES))).to_string())


if __name__ == "__main__":
    main()
