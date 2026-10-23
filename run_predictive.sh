#!/bin/bash
# Run the proposed Predictive TCP at every congestion level and seed,
# plus a small ablation (which part of the mechanism matters).
set -e
NS3_DIR="${NS3_DIR:-$HOME/ns-3}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$PROJECT_DIR/results/raw"
ABL="$PROJECT_DIR/results/ablation"
SIM_TIME="${SIM_TIME:-60}"
# Seeds 1-3 train and tune; 4-10 are only ever used for evaluation (seeds 6-10 added in Phase 13)
SEEDS="${SEEDS:-1 2 3 4 5 6 7 8 9 10}"
mkdir -p "$OUT" "$ABL"
cd "$NS3_DIR"

for level in low medium high; do
  for seed in $SEEDS; do
    ./ns3 run --no-build "tcp-predictor --variant=predictive --level=$level --seed=$seed --simTime=$SIM_TIME --outDir=$OUT"
  done
done

# Single long flow with every cwnd change logged (validation graph)
./ns3 run --no-build "tcp-predictor --variant=predictive --level=single --seed=1 --simTime=30 --traceCwnd=1 --outDir=$PROJECT_DIR/results/validation"

# Ablation: change one part of the mechanism at a time
#   beta1    no proactive cut (only the growth hold on High/Medium remains)
#   phase6   the setting before Phase 7 tuning (Beta 0.85)
#   halving  the first tuning choice, before the single-flow check (Beta 0.5, MinWindow 6)
#   nohold   no reaction to Medium predictions
# The competition detector is switched off in the ablation runs: it is evaluated
# separately (run_robustness.sh), and with parts of the mechanism removed the
# queue stays high and the detector would fire, mixing two effects together.
for setting in "beta1:--ns3::TcpPredictive::Beta=1.0" \
               "phase6:--ns3::TcpPredictive::Beta=0.85" \
               "halving:--ns3::TcpPredictive::Beta=0.5 --ns3::TcpPredictive::MinWindow=6" \
               "nohold:--ns3::TcpPredictive::HoldOnMedium=false"; do
  name="${setting%%:*}"; arg="${setting#*:}"
  mkdir -p "$ABL/$name"
  for level in medium high; do
    for seed in $SEEDS; do
      ./ns3 run --no-build "tcp-predictor --variant=predictive --level=$level --seed=$seed --simTime=$SIM_TIME --outDir=$ABL/$name $arg --ns3::TcpPredictive::CompetitionWindow=0s"
    done
  done
done
