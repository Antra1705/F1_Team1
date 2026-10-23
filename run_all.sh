#!/bin/bash
# Reproduce the whole project.
#
#   ./run_all.sh               simulate everything with NS-3 on this machine (~18 minutes):
#                              baselines -> dataset -> model selection -> train -> export tree to C++ ->
#                              tune controller -> tune competition detector -> Predictive TCP ->
#                              robustness tests -> compare -> graphs
#   ./run_all.sh --reference   use the macOS reference simulation data in reference/ instead of
#                              simulating (~2 minutes, NS-3 not needed). Every table, model, graph and
#                              RESULTS.md then comes out identical to the macOS results, on any system.
#
# Both modes finish by comparing the results with the macOS reference (analysis/verify_reference.py).
# A network simulation cannot be bit-identical across operating systems / compilers / CPUs (tiny
# floating-point differences change which packet is dropped), so to match macOS exactly on Linux or
# Windows (WSL), use --reference.
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Python environment missing. Create it first:"
  echo "  uv venv .venv --python 3.13 && uv pip install --python .venv/bin/python -r requirements.txt"
  echo "  (or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"
  exit 1
fi

REFERENCE=0
[ "${1:-}" = "--reference" ] && REFERENCE=1
export PTCP_REFERENCE=$REFERENCE

if [ $REFERENCE = 1 ]; then
  echo "== Reference mode: using the macOS simulation data (no NS-3 runs)"
  echo "== 1/9 Check and unpack reference/simulation_data.tar.xz"
  $PY - <<'EOF'
import hashlib, tarfile
from pathlib import Path
archive = Path("reference/simulation_data.tar.xz")
expected = next(l.split()[0] for l in Path("reference/SHA256SUMS").read_text().splitlines()
                if l.endswith("archive"))
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit("reference/simulation_data.tar.xz is corrupted (checksum mismatch)")
with tarfile.open(archive) as tar:
    tar.extractall("results", filter="data")
print("   archive OK, simulation data unpacked into results/")
EOF
  STEP=2; TOTAL=9
else
  echo "== 1/12 Build the NS-3 simulation"
  ./build.sh > /dev/null
  echo "== 2/12 Baseline simulations: Tahoe, Reno, CUBIC, Vegas, BBR (150 runs)"
  ./run_baseline.sh | grep -c goodput | xargs echo "   runs completed:"
  STEP=3; TOTAL=12
fi
step() { echo "== $STEP/$TOTAL $1"; STEP=$((STEP + 1)); }

step "Build the ML dataset"
$PY analysis/build_dataset.py | head -1
step "Feature-set and horizon experiments, model selection (seeds 1-3)"
$PY analysis/ml_experiments.py > results/model/experiments_log.txt 2>&1
$PY analysis/select_model.py > results/model/selection_log.txt 2>&1
grep "Chosen" results/model/selection_log.txt
step "Train and evaluate the deployed models"
$PY analysis/train_model.py > results/model/train_log.txt 2>&1
grep -E "Model features|Decision Tree:|WARNING" results/model/train_log.txt
$PY analysis/prediction_baselines.py > results/model/baselines_log.txt 2>&1
step "Export the decision tree to C++"
$PY analysis/export_tree.py
[ $REFERENCE = 0 ] && ./build.sh > /dev/null
step "Tune the controller (Beta, MinWindow) on seeds 1-3"
$PY analysis/tune_controller.py > results/model/tuning_log.txt 2>&1
grep -E "Chosen|WARNING" results/model/tuning_log.txt
step "Tune the competition detector on seeds 1-3"
$PY analysis/tune_competition.py > results/model/competition_log.txt 2>&1
grep -E "Chosen|WARNING" results/model/competition_log.txt
if [ $REFERENCE = 0 ]; then
  step "Predictive TCP simulations + ablation"
  ./run_predictive.sh | grep -c goodput | xargs echo "   runs completed:"
  step "Robustness: buffer sizes, competition with CUBIC, link speeds and delays"
  ./run_robustness.sh | grep -c goodput | xargs echo "   runs completed:"
fi
$PY analysis/robustness.py > results/robustness/robustness_log.txt 2>&1
step "Compare variants and draw graphs"
$PY analysis/compare_variants.py | sed -n '/PRD 10.3/,/^$/p'
$PY analysis/significance.py > results/significance_log.txt 2>&1
$PY analysis/make_graphs.py | tail -2
step "Compare with the macOS reference"
if [ $REFERENCE = 1 ]; then
  $PY analysis/verify_reference.py --strict
else
  $PY analysis/verify_reference.py
fi
echo "Done. Open results/RESULTS.md for the full results."
