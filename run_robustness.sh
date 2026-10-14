#!/bin/bash
# Phase 8: robustness tests for the final Predictive TCP.
#   1. Buffer sweep: every variant at medium and high load with a 20- and a
#      100-packet bottleneck queue (the main runs use 50 packets).
#   2. Competition: at high load, even-numbered flows use one variant and
#      odd-numbered flows use CUBIC (4 vs 4), to see who gets the bandwidth
#      (Predictive TCP with and without its competition detector).
set -e
NS3_DIR="${NS3_DIR:-$HOME/ns-3}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$PROJECT_DIR/results/robustness"
SIM_TIME="${SIM_TIME:-60}"
cd "$NS3_DIR"

for queue in 20 100; do
  mkdir -p "$OUT/queue$queue"
  for level in medium high; do
    for variant in tahoe reno cubic vegas bbr predictive; do
      for seed in 1 2 3 4 5; do
        ./ns3 run --no-build "tcp-predictor --variant=$variant --level=$level --seed=$seed --simTime=$SIM_TIME --queue=$queue --outDir=$OUT/queue$queue"
      done
    done
  done
done

# 100-packet queue at high load with the competition detector off (it false-alarms there)
mkdir -p "$OUT/queue100_nodetector"
for seed in 1 2 3 4 5; do
  ./ns3 run --no-build "tcp-predictor --variant=predictive --level=high --seed=$seed --simTime=$SIM_TIME --queue=100 --outDir=$OUT/queue100_nodetector --ns3::TcpPredictive::CompetitionWindow=0s"
done

mkdir -p "$OUT/mixed" "$OUT/mixed_nodetector"
for variant in cubic reno vegas bbr predictive; do
  for seed in 1 2 3 4 5; do
    ./ns3 run --no-build "tcp-predictor --variant=$variant --mix=cubic --level=high --seed=$seed --simTime=$SIM_TIME --outDir=$OUT/mixed"
  done
done
# Predictive TCP without its competition detector, for comparison
for seed in 1 2 3 4 5; do
  ./ns3 run --no-build "tcp-predictor --variant=predictive --mix=cubic --level=high --seed=$seed --simTime=$SIM_TIME --outDir=$OUT/mixed_nodetector --ns3::TcpPredictive::CompetitionWindow=0s"
done
