#!/bin/bash
# Run every baseline at every congestion level and seed:
#   Tahoe, Reno, CUBIC (loss-based; Phase 1, also used to train the model)
#   Vegas, BBR         (delay/model-based; Phase 5, comparison only)
set -e
NS3_DIR="${NS3_DIR:-$HOME/ns-3}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$PROJECT_DIR/results/raw"
VALID="$PROJECT_DIR/results/validation"
SIM_TIME="${SIM_TIME:-60}"
mkdir -p "$OUT" "$VALID"
cd "$NS3_DIR"

for level in low medium high; do
  for variant in tahoe reno cubic vegas bbr; do
    for seed in 1 2 3 4 5; do
      ./ns3 run --no-build "tcp-predictor --variant=$variant --level=$level --seed=$seed --simTime=$SIM_TIME --outDir=$OUT"
    done
  done
done

# Single long flow with every cwnd change logged (variant validation graphs)
for variant in tahoe reno cubic vegas bbr; do
  ./ns3 run --no-build "tcp-predictor --variant=$variant --level=single --seed=1 --simTime=30 --traceCwnd=1 --outDir=$VALID"
done
