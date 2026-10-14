# Lightweight Predictive Congestion Estimator for TCP

A college networking project that compares **TCP Tahoe, Reno, CUBIC, Vegas and BBR** in NS-3, trains a **lightweight decision tree** to predict bottleneck congestion **0.5 s before it happens**, and uses that prediction inside a new TCP variant, **Predictive TCP**. Predictive TCP backs off *before* the router queue overflows.

**Author:** Antra (24BDS0066) · **Course:** BCSE308L Computer Networks, VIT
**Tools:** NS-3.48 (C++), Python 3.13, scikit-learn, pandas, NumPy, Matplotlib, Streamlit (interactive app)

**Contents:** [About](#about-the-project) · [What was done](#what-was-done) · [Quick start](#quick-start) · [Results](#headline-results) · [How it works](#how-predictive-tcp-works) · [Setup](#setup-step-by-step) · [Running](#running-the-experiments) · [Same results on every OS](#getting-results-identical-to-macos-on-any-system) · [Interactive app](#interactive-simulator-app) · [Troubleshooting](#troubleshooting) · [Findings](#key-findings-and-design-decisions) · [Limitations](#limitations)

---

## About the Project

### The problem

When many computers send data through the same link, packets queue up in the router in front of that link (the *bottleneck*). When the queue is full, the router **drops** packets. Classic TCP (Tahoe, Reno, CUBIC) only slows down **after** it notices a loss. By then the queue has already overflowed: packets are lost and must be resent, and every packet waits in a long queue, which adds delay (*latency*). TCP keeps filling the queue until it overflows, so these drops and delays happen again and again.

### The idea

A sender can see congestion **coming** before any packet is lost: as the queue fills, the round-trip time (RTT) rises. This project:

1. **Measures** what happens with five well-known TCP versions (Tahoe, Reno, CUBIC, Vegas, BBR) in the NS-3 network simulator.
2. **Trains a small machine-learning model** (a decision tree with only 4 rules) to predict, from the sender's own RTT measurements, whether the bottleneck will be congested **0.5 seconds from now**.
3. **Builds a new TCP version, Predictive TCP,** that runs this model inside the sender every 100 ms and gently reduces its sending rate *before* the queue overflows.
4. **Tests it honestly:** against all five TCP versions, on runs the model never saw, with different buffer sizes, and while sharing the link with CUBIC.

### Why it matters

Fewer drops mean fewer retransmissions and less wasted bandwidth. A shorter queue means lower delay, which matters for video calls, gaming and web pages. The model is tiny (4 if/else rules, exported to C++), so it adds almost no cost to the sender.

### In one sentence

> Predictive TCP cuts packet drops by about **90%** and delay by **26–37%** compared with Reno, while keeping **98–100%** of Reno's throughput. Its main weakness is that it gives up bandwidth when it shares a link with aggressive CUBIC flows.

---

## What Was Done

The project was built in phases. Each one was checked before moving on, and every result can be reproduced exactly with `./run_all.sh`.

| Phase | What was done | Outcome |
|---|---|---|
| **1. Simulation** | Built a dumbbell network in NS-3 (senders → router → 10 Mbps / 20 ms bottleneck → router → receiver) with low, medium and high congestion. NS-3 has no Tahoe or classic Reno, so both were **written from scratch** as C++ classes. | 45 baseline runs; Tahoe/Reno behaviour validated with window traces |
| **2. Dataset + ML** | Logged every flow every 100 ms (RTT, window, losses) and labelled each moment with the **real router queue 0.5 s later**. Trained a Decision Tree and compared it with Logistic Regression and a simple loss-counting rule. The tree is exported automatically to C++. | 106,354 samples; the C++ export matches scikit-learn on all 42,235 test samples |
| **3. Predictive TCP** | Wrote `TcpPredictive`, a new TCP version that runs the tree inside the sender and reduces its window on a "High" prediction. Found and fixed two real problems: a **feedback loop** (the model reacting to its own slowdown) and a **delayed-ACK trap** at very small windows. | All 9 success criteria in the PRD met |
| **4. Results** | Graphs, the final comparison table, the results page (`results/RESULTS.md`) and the one-command pipeline (`run_all.sh`). | Whole project reproducible, byte-for-byte |
| **5. Stronger baselines** | Added **Vegas** (delay-based) and **BBR** (Google's model-based TCP). | Beats BBR on every metric; Vegas remains the strongest rival |
| **6. Stronger ML** | Added RTT-trend features, compared prediction horizons (0.2 / 0.5 / 1.0 s), and chose the model by **testing 5 candidates inside the simulator**, not by offline accuracy alone. | Drops −88%, RTT −24% to −34% vs Reno |
| **7. Controller tuning** | Tuned how strongly to cut (β) and the minimum window over 18 settings, on training seeds only. A single-flow check was added after the first choice turned out to under-use an empty link. | Drops −91% / −90%, RTT −26% / −37%, fairness 0.96 |
| **8. Robustness** | Tested other buffer sizes (20 and 100 packets) and competition with CUBIC. | Gains hold for every buffer size; loses bandwidth to CUBIC (23%) |
| **8b. Competition detector** | Added a detector that switches to normal Reno behaviour while a loss-based sender keeps the queue full. | Share against CUBIC rose from 23% to 36%, with no cost when only Predictive flows share the link |
| **App** | An interactive web app (Streamlit) that runs real NS-3 simulations live in the browser, for demos. | `./app/run_app.sh` |
| **9. Report + slides** | Not started yet. | – |

**Rules followed throughout:**
- **No peeking at the test data:** every choice (model, settings, detector) was made on seeds 1–3, and seeds 4–5 were kept untouched for the final numbers.
- **No hiding weaknesses:** every weakness found is reported in [Key findings](#key-findings-and-design-decisions) and [Limitations](#limitations).
- **Planning documents:** [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) and [`docs/PRD.md`](docs/PRD.md); [`HANDOFF.md`](HANDOFF.md) says exactly where the project stands.

---

## Quick Start

If everything is already installed (see [Setup](#setup-step-by-step) for a fresh machine; this works the same on macOS, Linux and Windows-via-WSL):

```bash
cd ~/Desktop/Antra/VIT/CN/TCP-Congestion-Predictor   # always run commands from the project folder
./build.sh                                           # compile the simulation into NS-3
./run_all.sh                                         # reproduce every result (~18 minutes)
./app/run_app.sh                                     # open the interactive simulator in the browser
```

Then open `results/RESULTS.md` in VS Code and press **Cmd + Shift + V** to see every table and graph.

**On Linux or Windows, or without NS-3:** `./run_all.sh --reference` rebuilds every result from the macOS simulation data in about 1 minute, and the results come out **identical to macOS**. See [Same results on every OS](#getting-results-identical-to-macos-on-any-system).

---

## Headline Results

Mean of 5 seeds, 60 s simulations, 10 Mbps / 20 ms bottleneck, 50-packet FIFO queue:

| Compared with Reno | Medium congestion | High congestion |
|---|---|---|
| Bottleneck drops | **−91%** | **−90%** |
| Retransmissions | **−91%** | **−89%** |
| Average RTT | **−26%** (59 vs 80 ms) | **−37%** (64 vs 101 ms) |
| Goodput | 98.0% of Reno | 99.6% of Reno |
| Fairness (Jain index) | 0.98 | 0.96 (Reno 0.99) |

- **Every seed:** Predictive TCP has fewer drops and a lower RTT than Reno, CUBIC and Tahoe in all 5 seeds at both load levels.
- **Not overfitted:** the model was trained and chosen, and the controller tuned, on seeds 1–3 only. On the unseen seeds 4–5 the gains are the same size (drops −92% / −90%, RTT −26% / −37%).
- **Alone on the link** it reaches 9.7 Mbps of 10 (Reno 9.0).
- **All 9 success criteria** in the PRD (section 10.3) are met.
- **Costs:** about 2% less goodput at medium load, and slightly lower fairness at high load (0.96 vs 0.99).
- **Other buffer sizes:** with a 20- or 100-packet queue (trained on 50 only), it still has fewer drops (−86% to −96%) and a lower RTT than Reno in every seed. The RTT gain grows with the buffer: −10% / −17% at 20 packets and −43% / −50% at 100.
- **Main weakness: it loses bandwidth to CUBIC.** When 4 Predictive TCP flows share the link with 4 CUBIC flows (fair = 50%):
  - **Without help** they get only 23% of the bandwidth.
  - **A competition detector** (switch to Reno behaviour while a loss-based sender keeps the queue full) raises this to **36%**, the same as Vegas (35%). Reno gets 45%.
  - **Unseen seeds 4–5** hold up: 22% → 35% (findings 15–16).

**Against delay-based and model-based TCP:**

| | Medium congestion | High congestion |
|---|---|---|
| **vs BBR (v1)** | drops −97%, RTT −32% | drops −98%, RTT −40%, fairness 0.96 vs 0.85 |
| **vs Vegas** | Vegas has fewer drops (9 vs 61); Predictive has lower RTT (59 vs 65 ms) | Predictive is better in all 5 seeds: drops −41%, RTT −40% (64 vs 106 ms), fairness 0.96 vs 0.88 |

- **Vegas is the strongest baseline** and still loses fewer packets at medium load. Alone on the link, though, it reaches only 5.3 Mbps of 10, while Predictive TCP reaches 9.7 (finding 9).
- **BBR (v1) overflows the shallow 50-packet buffer** (finding 10).
- **Full results:** see [`results/RESULTS.md`](results/RESULTS.md).

---

## How Predictive TCP Works

Every 100 ms the sender measures its own RTT and runs this tree. The tree was learned from 106,354 samples of Tahoe, Reno and CUBIC traffic and exported automatically to C++:

| RTT ÷ minimum RTT | RTT ÷ its 1 s average | Prediction (0.5 s ahead) | Action |
|---|---|---|---|
| ≤ 1.23 | – | **Low** | Normal Reno growth |
| > 1.23 (queue building) | ≤ 0.85 (queue draining fast) | **Medium** | Grow at 25% of Reno's rate |
| > 1.23 (queue building) | > 0.85 | **High** | Cut cwnd by 20% (at most once per RTT) and stop growing |

- **What the tree learned:** congestion is coming when queueing delay is above about 23% of the base RTT (≈ 10 ms, or about 8 packets in the queue) and the queue is not draining.
- **How the model was chosen:** 5 candidate models (different feature sets and horizons) were compiled into NS-3 and tested on the training seeds. The one with the largest drop and RTT reduction was chosen (Phase 6). It was *not* the best on offline scores (finding 11).
- **How the reaction was tuned:** the size of the cut (β = 0.8) and the minimum window (4 segments) were chosen from 18 settings on the training seeds (Phase 7, finding 13).
- **Competition detector:** when only Predictive flows share the link, their cuts let the queue drain now and then. If the lowest RTT over 2 s stays above 1.4 × the base RTT, the queue never drained, so a loss-based sender such as CUBIC is assumed. Predictive TCP then behaves like plain Reno, until 10 s after the queue was last seen not draining. The three values were tuned on the training seeds (Phase 8b). With only Predictive flows and the 50-packet buffer, it never fires.
- **Safety net:** Reno's normal loss response (halving) still applies.
- **Minimum window:** the predictor never acts below a 4-segment window.
- **Inputs:** the model uses **only measurements the sender can make itself**. The router's queue length is used only to label the training data.

---

## Project Structure

```
TCP-Congestion-Predictor/
├── ns3/                       NS-3 C++ code (copied into ~/ns-3/scratch/tcp-predictor by build.sh)
│   ├── tcp-predictor.cc         dumbbell simulation, 6 variants, congestion levels, 100 ms CSV tracing
│   ├── tcp-variants.h/.cc       TcpTahoe(+Recovery), TcpReno(+Recovery), TcpPredictive
│   └── predictive-model.h       decision tree as C++ if/else (generated)
├── analysis/                  Python pipeline
│   ├── build_dataset.py         features + labels 0.5 s ahead → results/dataset.csv
│   ├── ml_experiments.py        feature sets × prediction horizons (offline)
│   ├── select_model.py          candidate models tested inside NS-3 (seeds 1–3); picks the deployed one
│   ├── tune_controller.py       tunes β and MinWindow inside NS-3 (seeds 1–3)
│   ├── tune_competition.py      tunes the competition detector inside NS-3 (seeds 1–3)
│   ├── train_model.py           Decision Tree vs Logistic Regression vs loss-based detector
│   ├── export_tree.py           tree → predictive-model.h, verified against scikit-learn
│   ├── compare_variants.py      metrics, PRD criteria check, per-seed wins, ablation
│   ├── robustness.py            buffer-size sweep and competition with CUBIC
│   ├── make_graphs.py           all graphs, final table, results/RESULTS.md
│   └── verify_reference.py      compares this machine's results with the macOS reference
├── results/
│   ├── raw/                     per-run CSVs (samples_*, flowmon_*, runinfo_*)
│   ├── v1/                      snapshot of the results before Phases 5–7 (for before/after)
│   ├── validation/              single-flow cwnd traces
│   ├── ablation/                ablation runs
│   ├── model_selection/         NS-3 runs of each candidate model
│   ├── tuning/                  NS-3 runs of each controller setting
│   ├── competition_tuning/      NS-3 runs of each competition-detector setting
│   ├── robustness/              buffer sweep (queue20/, queue100/) and mixed runs (mixed/)
│   ├── model/                   trained models, metrics.json, logs
│   ├── graphs/                  all PNG graphs
│   ├── RESULTS.md               results page (tables + graphs)
│   └── *.csv                    comparison and summary tables
├── reference/                 macOS reference results: simulation data (15 MB), expected tables, checksums
├── docs/                      PROJECT_PLAN and PRD (.md + .pdf)
├── app/                       interactive simulator (Streamlit): app.py, run_app.sh, requirements.txt
├── tools/md2html.py           Markdown → HTML for the PDF versions of the docs
├── HANDOFF.md                 where the project stands and what is left (read this to resume)
├── build.sh                   copy ns3/ into NS-3 and compile
├── run_baseline.sh            75 baseline runs (5 variants) + validation traces
├── run_predictive.sh          15 Predictive TCP runs + ablation
├── run_robustness.sh          buffer sweep (120 runs) + competition with CUBIC (25 runs)
├── run_all.sh                 everything, end to end (~18 min); --reference: from the macOS data (~1 min)
└── requirements.txt
```

---

## Setup (step by step)

| Your system | Follow |
|---|---|
| **macOS** | [macOS](#macos) below |
| **Linux** (Ubuntu / Debian; other distributions similar) | [Linux](#linux-ubuntu--debian), then the shared steps |
| **Windows 10 / 11** | [Windows (WSL2)](#windows-1011-via-wsl2), then the Linux steps inside WSL |

**Tested on:** macOS (Apple Silicon) with Homebrew 7, Apple clang 17, CMake 4.4, Ninja 1.13, uv 0.11, Python 3.13 (analysis) and Python 3.12 (app). The Linux and Windows steps follow NS-3's documented requirements and use the same scripts, but they have not been run on those systems for this project. The scripts were made portable for them: the C++ compiler is detected automatically, and `rsync` is optional.

### What you need (all systems)

| Item | Why | Disk |
|---|---|---|
| Xcode Command Line Tools | C++ compiler (clang) and git | ~1 GB |
| Homebrew | installs CMake, Ninja and uv | – |
| CMake + Ninja | build NS-3 | small |
| uv (or Python 3.12+ with `venv`) | Python environments | small |
| NS-3.48 in `~/ns-3` | the network simulator | ~190 MB |
| `.venv` (analysis) | scikit-learn, pandas, NumPy, Matplotlib | ~260 MB |
| `app/.venv` (app) | Streamlit | ~320 MB |
| `results/` after `run_all.sh` | all simulation output | ~250 MB |
| Google Chrome (optional) | only to regenerate the PDF versions of the docs | – |

### macOS

#### Step 1: Command Line Tools and Homebrew

```bash
xcode-select --install                    # installs clang, make and git (skip if already installed)
xcode-select -p                           # should print /Library/Developer/CommandLineTools (or an Xcode path)
```

If you don't have Homebrew, install it from https://brew.sh. Then:

```bash
brew install cmake ninja uv
```

#### Step 2: Get the project

```bash
git clone <repository-url> TCP-Congestion-Predictor
cd TCP-Congestion-Predictor
chmod +x *.sh app/run_app.sh              # make the scripts executable (needed after some downloads)
```

A fresh clone has no simulation output yet. The raw-data folders are listed in `.gitignore` because `run_all.sh` regenerates them exactly (Step 6). The summary tables, graphs and `results/RESULTS.md` are included.

#### Step 3: Install NS-3.48 (about 10–15 minutes, once)

```bash
mkdir -p ~/ns-3 && cd ~/ns-3
curl -L https://gitlab.com/nsnam/ns-3-dev/-/archive/ns-3.48/ns-3-dev-ns-3.48.tar.gz | tar xz --strip-components=1
./ns3 configure -d optimized \
  --enable-modules="core;network;internet;point-to-point;applications;traffic-control;flow-monitor" \
  --disable-examples --disable-tests
./ns3 build
cd -                                       # back to the project folder
```

If NS-3 lives somewhere else, export its path before running any script: `export NS3_DIR=/path/to/ns-3`.

#### Step 4: Python environment for the analysis

Run this from the project folder:

```bash
uv venv .venv --python 3.13 && uv pip install --python .venv/bin/python -r requirements.txt
# without uv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The versions are pinned in `requirements.txt` (scikit-learn 1.9.1, pandas 3.0.6, NumPy 2.5.4, Matplotlib 3.11.2), so every result reproduces exactly.

#### Step 5: Compile the simulation

```bash
./build.sh
```

This copies `ns3/` into `~/ns-3/scratch/tcp-predictor/` and compiles it. Run it again after **any** change to the files in `ns3/`.

#### Step 6: Reproduce everything

```bash
./run_all.sh
```

It runs 12 steps in about 16–18 minutes and prints each one as it goes. Every result is deterministic: running it twice gives byte-identical files.

#### Step 7: Look at the results

- **`results/RESULTS.md`:** the full results page. In VS Code, open it and press **Cmd + Shift + V**.
- **`results/graphs/`:** every graph as a PNG.
- **`results/final_table.md` / `.csv`:** the main comparison table (mean ± std over 5 seeds).
- **`results/model/`:** the trained models, `metrics.json` and the logs of every tuning step.

### Linux (Ubuntu / Debian)

The project's scripts are plain `bash` and run unchanged on Linux. Only the installation differs.

**Step 1: Build tools.** NS-3.48 needs a C++20 compiler (g++ 11 or newer) and CMake 3.13+. Ubuntu 22.04 and 24.04 have both.

```bash
sudo apt update
sudo apt install -y g++ cmake ninja-build python3 python3-venv git curl rsync
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv (installs Python 3.13 for you in Step 4)
source ~/.bashrc                                    # or open a new terminal, so `uv` is found
```

On Fedora use `sudo dnf install gcc-c++ cmake ninja-build python3 git curl rsync`; on Arch use `sudo pacman -S gcc cmake ninja python git curl rsync`.

**Steps 2–7:** exactly as in the macOS section ([get the project](#step-2-get-the-project), [install NS-3](#step-3-install-ns-348-about-1015-minutes-once), [Python environment](#step-4-python-environment-for-the-analysis), `./build.sh`, `./run_all.sh`, view results). The commands are identical.

**Linux differences:**

| On macOS | On Linux |
|---|---|
| `md5 file` | `md5sum file` (see [Checking reproducibility](#checking-reproducibility)) |
| Chrome at `/Applications/Google Chrome.app/…` | `google-chrome` or `chromium` (only for regenerating PDFs) |
| VS Code Markdown preview: **Cmd + Shift + V** | **Ctrl + Shift + V** |

**Results on Linux:** use `./run_all.sh --reference` to get results **identical to macOS** ([why and how](#getting-results-identical-to-macos-on-any-system)). A plain `./run_all.sh` re-simulates on your machine. That gives the same conclusions and very close numbers, but not byte-identical files, and the run ends by reporting exactly how close they are.

### Windows 10/11 (via WSL2)

NS-3 does not officially support running natively on Windows, and the project's scripts are `bash`. The reliable way is **WSL2**, Microsoft's built-in Linux layer. Everything then runs inside Ubuntu, and you use your normal Windows browser and VS Code.

**Step 1: Install WSL2 with Ubuntu.** Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart when asked. Then open **Ubuntu** from the Start menu and create a Linux username and password.

**Step 2: Follow the [Linux](#linux-ubuntu--debian) steps inside the Ubuntu window,** from "Build tools" onward.

**Windows tips:**
- **Keep the project inside the Linux file system** (for example `~/TCP-Congestion-Predictor`), not under `/mnt/c/…`. Building and running on `/mnt/c` is many times slower.
- **VS Code:** install the **WSL** extension, then run `code .` in the project folder inside Ubuntu. VS Code opens the files with full editing and Markdown preview.
- **The app:** run `./app/run_app.sh` inside Ubuntu, then open **http://localhost:8501** in your Windows browser. WSL2 forwards localhost automatically.
- **Line endings:** the repository's `.gitattributes` forces Unix line endings for scripts, so this should not happen. If a script still fails with `bad interpreter: /bin/bash^M`, the files were checked out with Windows line endings. Run `git config --global core.autocrlf input` and clone again inside Ubuntu, or run `sed -i 's/\r$//' *.sh app/run_app.sh`.
- **Native Windows without WSL** (Visual Studio or MSYS2) is possible for NS-3 itself, but the project's `.sh` scripts would have to be rewritten. That is not covered here.

---

## Running the Experiments

### Everything at once

```bash
./run_all.sh
```

| Step | What it does | Time |
|---|---|---|
| 1 | Compile the simulation | ~20 s |
| 2 | 75 baseline runs (Tahoe, Reno, CUBIC, Vegas, BBR × 3 loads × 5 seeds) + validation traces | ~1.5 min |
| 3 | Build the ML dataset (106,354 samples) | ~10 s |
| 4 | Feature-set/horizon experiments, then pick the model inside NS-3 (seeds 1–3) | ~1.5 min |
| 5 | Train and evaluate the deployed tree vs Logistic Regression vs a loss rule | ~10 s |
| 6 | Export the tree to C++, check it matches scikit-learn exactly, recompile | ~30 s |
| 7 | Tune β and the minimum window inside NS-3 (seeds 1–3) | ~3 min |
| 8 | Tune the competition detector inside NS-3 (seeds 1–3) | ~7 min |
| 9 | Predictive TCP runs + ablation | ~1 min |
| 10 | Robustness: buffer sizes and competition with CUBIC (155 runs) | ~3.5 min |
| 11 | Comparison tables, all graphs and `results/RESULTS.md` | ~30 s |
| 12 | Compare every result with the macOS reference (`analysis/verify_reference.py`) | ~5 s |

### Step by step

Run these from the project folder, in this order:

```bash
./build.sh                                     # compile the simulation
./run_baseline.sh                              # Tahoe, Reno, CUBIC, Vegas, BBR × 3 levels × 5 seeds
.venv/bin/python analysis/build_dataset.py     # features + labels
.venv/bin/python analysis/ml_experiments.py    # feature sets × horizons (offline)
.venv/bin/python analysis/select_model.py      # test candidate models inside NS-3 (seeds 1–3)
.venv/bin/python analysis/train_model.py       # train and evaluate the deployed model
.venv/bin/python analysis/export_tree.py       # tree → C++ (verified)
./build.sh                                     # recompile with the new tree
.venv/bin/python analysis/tune_controller.py   # tune β and MinWindow inside NS-3 (seeds 1–3)
.venv/bin/python analysis/tune_competition.py  # tune the competition detector (seeds 1–3)
./run_predictive.sh                            # Predictive TCP + ablation
./run_robustness.sh                            # other buffer sizes + competition with CUBIC
.venv/bin/python analysis/robustness.py
.venv/bin/python analysis/compare_variants.py
.venv/bin/python analysis/make_graphs.py       # graphs, final table, results/RESULTS.md
```

Always use `.venv/bin/python`, not the system `python3`, so the pinned library versions are used.

### A single simulation

```bash
cd ~/ns-3
./ns3 run "tcp-predictor --variant=predictive --level=high --seed=1 --outDir=/tmp"
```

It prints a one-line summary (goodput, retransmissions, drops, proactive cuts, time in competitive mode). It also writes three CSV files to `--outDir`: `samples_*` (one row per flow every 100 ms), `flowmon_*` (per-flow totals) and `runinfo_*` (run totals).

| Option | Values | Default |
|---|---|---|
| `--variant` | `tahoe`, `reno`, `cubic`, `vegas`, `bbr`, `predictive` | `reno` |
| `--level` | `low`, `medium`, `high`, `single` | `medium` |
| `--seed` | random run number | `1` |
| `--simTime` | seconds | `60` |
| `--rate`, `--delay`, `--queue` | bottleneck rate, one-way delay, queue size (packets) | `10Mbps`, `20ms`, `50` |
| `--mix` | second variant for a mixed run: odd-numbered flows use it (e.g. `--variant=predictive --mix=cubic`) | none |
| `--traceCwnd` | log every cwnd change of flow 0 | `false` |
| `--ns3::TcpPredictive::Beta` | window multiplier on High | `0.8` |
| `--ns3::TcpPredictive::MediumGrowth` | fraction of Reno's growth on Medium | `0.25` |
| `--ns3::TcpPredictive::MinWindow` | segments below which the predictor never acts | `4` |
| `--ns3::TcpPredictive::CompetitionWindow` | competition detector window (`0s` turns it off) | `2s` |
| `--ns3::TcpPredictive::CompetitionThreshold` | lowest RTT ÷ base RTT above which a competitor is assumed | `1.4` |
| `--ns3::TcpPredictive::CompetitionHold` | stay in Reno mode this long after the last evidence | `10s` |

**More examples:**

```bash
cd ~/ns-3
./ns3 run "tcp-predictor --variant=cubic --level=medium --seed=4 --outDir=/tmp"                 # a baseline
./ns3 run "tcp-predictor --variant=predictive --level=high --queue=100 --outDir=/tmp"           # bigger buffer
./ns3 run "tcp-predictor --variant=predictive --mix=cubic --level=high --outDir=/tmp"           # share with CUBIC
./ns3 run "tcp-predictor --variant=predictive --level=high --outDir=/tmp --ns3::TcpPredictive::CompetitionWindow=0s"  # detector off
./ns3 run "tcp-predictor --PrintHelp"                                                           # all options
```

### Checking reproducibility

Record checksums, rerun everything, and compare:

```bash
md5 results/final_table.md results/model/metrics.json results/comparison_runs.csv > /tmp/before.md5    # Linux/WSL: md5sum
./run_all.sh > /dev/null
md5 results/final_table.md results/model/metrics.json results/comparison_runs.csv | diff - /tmp/before.md5 && echo "identical"
```

### Regenerating the PDF versions of the docs

`docs/PROJECT_PLAN.pdf` and `docs/PRD.pdf` are made from the Markdown files with `tools/md2html.py` and Chrome:

```bash
python3 -m venv /tmp/mdvenv && /tmp/mdvenv/bin/pip install markdown
for f in PROJECT_PLAN PRD; do
  /tmp/mdvenv/bin/python tools/md2html.py docs/$f.md /tmp/$f.html $f
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
    --no-pdf-header-footer --print-to-pdf="$PWD/docs/$f.pdf" file:///tmp/$f.html
done
```

On this project's Mac, Chrome is installed as `Google Chrome 2.app`, so adjust the path if needed. On Linux or WSL, replace the Chrome path with `google-chrome` or `chromium`.

---

## Getting Results Identical to macOS on Any System

### Why a re-simulation can't be bit-identical across systems

NS-3 computes with floating-point numbers, and its random traffic generators use maths functions (`log`, `pow`, `cbrt`). Apple's maths library and Linux's glibc, clang and gcc, and ARM and Intel processors can differ in the **last bit** of these results. A network simulation amplifies such a tiny difference: one packet arriving a nanosecond earlier changes which packet the router drops, and from then on the two runs follow different paths. The *averages* stay very close, but the output files are not identical. This is a general property of discrete-event simulation, not a bug in this project. On the **same** machine, every run is identical.

### The solution: reference mode

The exact simulation output from the Mac is included in the repository: `reference/simulation_data.tar.xz` (15 MB compressed, about 180 MB unpacked). Reference mode rebuilds **everything else** from it: the dataset, model selection, the trained tree, the C++ export check, both tuning steps, every comparison table, every graph and `RESULTS.md`.

```bash
./run_all.sh --reference
```

- **Time:** about 1 minute.
- **No NS-3 needed:** only the Python environment (Setup Step 4) and a C++ compiler for the tree-export check.
- **Built-in check:** it verifies the archive's checksum before unpacking, and finishes by comparing every result with the macOS originals. You should see:

  ```
  Data files identical to the macOS reference: 26/26
  RESULT: every result is IDENTICAL to the macOS reference.
  ```
- **Tested:** in a fresh copy of the repository (as after `git clone`, 19 MB) with NS-3 deliberately unavailable, it produced 26/26 identical data files and 18/18 identical graphs.

### Which mode to use

| Goal | Command | Identical to macOS? |
|---|---|---|
| See or present the exact project results on any computer | `./run_all.sh --reference` | **Yes**, byte for byte |
| Re-run the simulations yourself (e.g. to check the method) | `./run_all.sh` | On macOS (Apple Silicon): yes. Elsewhere: very close, and the final step reports how close |
| Check any results folder against macOS | `.venv/bin/python analysis/verify_reference.py` | Prints IDENTICAL, or the largest difference per table |

### What is in `reference/`

| File | Contents |
|---|---|
| `simulation_data.tar.xz` | Every NS-3 output from the Mac: baselines, validation traces, model-selection runs, tuning runs, ablation and robustness runs |
| `expected/` | The 24 result tables, `RESULTS.md` and `predictive-model.h` exactly as produced on the Mac |
| `SHA256SUMS` | Checksums of all results, the dataset, the 18 graphs and the archive |

**Graphs** are compared too, but only for information. The PNG files depend on the font-rendering library, so on another system a graph can show the same picture without being byte-identical.

---

## Interactive Simulator (app)

A Streamlit web app that runs the real NS-3 simulation live in the browser. It's meant for demos and for trying your own settings.

### Install (once)

The app has its **own** Python environment. Streamlit needs its own versions of pandas and NumPy, and keeping it separate leaves the analysis environment, and its exact reproducibility, untouched.

```bash
uv venv app/.venv --python 3.12 && uv pip install --python app/.venv/bin/python -r app/requirements.txt
```

NS-3 must already be built (`./build.sh`). The app calls the compiled program directly.

### Start and stop

```bash
./app/run_app.sh                  # from the project folder
# or from anywhere:
~/Desktop/Antra/VIT/CN/TCP-Congestion-Predictor/app/run_app.sh
```

- **Opening:** the browser opens **http://localhost:8501** by itself. If it doesn't (always the case on WSL), open the address manually in any browser.
- **Stopping:** press **Ctrl + C** in the terminal.
- **Another port** (if 8501 is busy): `./app/run_app.sh --server.port 8502`.
- **Theme:** the colours and fonts come from `app/.streamlit/config.toml`. `run_app.sh` starts Streamlit from inside `app/` so this file is picked up.

### Using it

1. **Live simulation tab:** the default experiment runs automatically when the page opens.
   - **Mode → Compare variants:** choose any of the 6 TCP variants.
   - **Mode → Share with CUBIC:** 4 flows of one variant share the link with 4 CUBIC flows. A fair split is 50%.
   - **Congestion level:** Low, Medium, High or Single (one flow alone).
   - **Seed / Duration:** seeds 1–3 were used for training and tuning; 4 and above were never seen.
   - **Bottleneck link:** bandwidth, delay and queue size. The sidebar shows the bandwidth-delay product.
   - **Predictive TCP parameters** (expander): β, minimum window, and the competition detector (on/off, window, threshold, hold).
   - **Press Run simulation.** Each 60 s simulation takes about 1–2 s, and variants run in parallel.
2. **What you see:**
   - Headline figures for Predictive TCP against Reno in the same run.
   - A results table with the best value in each column in green.
   - Four charts over time (goodput, RTT, bottleneck queue, cwnd): drag to pan, scroll to zoom, hover for values.
   - A CSV download.
   - The network diagram at the top fills its queue boxes to the measured average queue of the last run.
3. **Project results tab:** the final 5-seed table and all report graphs.
4. **How it works tab:** the decision-tree rules, the competition detector and the generated C++ code.

### A good demo sequence

1. **Compare variants, High load, seed 4** (the default): Predictive TCP has about 90% fewer drops and about 37% lower RTT than Reno, and the queue chart shows why.
2. **Add Vegas and BBR:** BBR floods the queue; Vegas loses fewer packets but has a higher RTT.
3. **Queue size → 100:** the RTT gap grows (bufferbloat).
4. **Share with CUBIC → Predictive, detector on:** about 35% share. Then turn the detector off in *Predictive TCP parameters* and run again: about 22%.

### Cache

Each finished run is saved in `app/runs/`, so repeating the same settings is instant (the page says "from cache"). To clear it, delete the folder: `rm -r app/runs`.

---

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `zsh: no such file or directory: ./app/run_app.sh` (or `./run_all.sh`) | You're not in the project folder. Run `cd ~/Desktop/Antra/VIT/CN/TCP-Congestion-Predictor` first, or use the full path. |
| `permission denied: ./run_all.sh` | Scripts lost their executable flag: `chmod +x *.sh app/run_app.sh`. |
| `xcrun: error: invalid active developer path` | Command Line Tools missing or not selected: `xcode-select --install`, then `sudo xcode-select -s /Library/Developer/CommandLineTools`. |
| `cmake: command not found` / `ninja: command not found` | `brew install cmake ninja`. |
| Scripts can't find NS-3, or the app says "NS-3 program not found" | NS-3 isn't in `~/ns-3`, or `./build.sh` wasn't run. Build it, or `export NS3_DIR=/path/to/ns-3`. |
| Changes to `ns3/*.cc` have no effect | Run `./build.sh` again; the scripts use `--no-build`. |
| `ModuleNotFoundError: No module named 'sklearn'` (or pandas) | You used the system Python. Use `.venv/bin/python …`, or create the environment (Setup, Step 4). |
| Results differ slightly from this README | You're using different library versions. Install exactly `requirements.txt` into `.venv`. |
| App: "Port 8501 is already in use" | Another copy is running. Stop it with Ctrl + C, or use `./app/run_app.sh --server.port 8502`. |
| App opens but looks unstyled, or fonts look plain | The fonts load from Google Fonts. Without internet the app falls back to system fonts but still works. |
| App shows old numbers after changing the C++ code | Cached runs: `rm -r app/runs`, and run `./build.sh`. |
| `run_all.sh` stopped halfway | Simply run it again. Every step overwrites its outputs, and the results are deterministic. |
| Numbers on Linux/Windows differ slightly from this README | Expected after a re-simulation on another system ([why](#why-a-re-simulation-cant-be-bit-identical-across-systems)). Use `./run_all.sh --reference` for identical results. |
| `reference/simulation_data.tar.xz is corrupted` | The archive didn't download completely. Re-clone, or `git checkout reference/`. |
| Linux: `No C++ compiler found` while exporting the tree | Install one: `sudo apt install g++`, or set `CXX=/path/to/compiler`. |
| Linux: NS-3 configure says the compiler is too old | Use Ubuntu 22.04+ (g++ 11+), or `sudo apt install g++-12` and `export CXX=g++-12` before configuring NS-3. |
| Linux/WSL: `uv: command not found` right after installing it | Open a new terminal, or run `source ~/.bashrc`. |
| WSL: `bad interpreter: /bin/bash^M` | Windows line endings. See the [Windows tips](#windows-1011-via-wsl2). |
| WSL: building or running is very slow | The project is under `/mnt/c/…`. Move it into your Linux home folder (`~`). |
| WSL: the app runs but the browser shows nothing | Open http://localhost:8501 manually in the Windows browser. If that fails, use the "Network URL" that Streamlit prints. |

---

## Experiment Setup

- **Topology:** N senders → R1 → **10 Mbps, 20 ms** → R2 → receiver. Access links are 100 Mbps, 1 ms. Base RTT is 44 ms.
- **Bottleneck queue:** FIFO, 50 packets.
- **Congestion levels:**

  | Level | Traffic | Load |
  |---|---|---|
  | Low | 3 on/off TCP flows at 2 Mbps | ~30% |
  | Medium | 6 on/off TCP flows at 3 Mbps | ~90%, bursty |
  | High | 8 long-lived TCP flows + 2 Mbps on/off UDP | Saturated |

- **TCP settings, the same for all variants:** 1448-byte segments, SACK on, minimum RTO 1 s (RFC 6298), 4 MB buffers, NS-3's default delayed ACKs (one ACK per 2 segments).
- **Loss recovery:** Tahoe and Reno use their own classes; CUBIC and Vegas use NS-3's classic (NewReno-style) recovery; BBR uses PRR with pacing, as in NS-3's BBR example; Predictive TCP uses Reno's.
- **Training data:** only Tahoe, Reno and CUBIC runs are used to train the model. Vegas and BBR are for comparison only.
- **Train/test split:** the model is trained on seeds 1–3 and tested on seeds 4–5.

---

## Key Findings and Design Decisions

1. **NS-3 has no Tahoe or classic Reno,** so both are implemented here as small recovery classes:
   - **Tahoe:** cwnd → 1 segment, then slow start.
   - **Reno:** fast recovery; a partial ACK halves the window again.
   - **Validation:** single-flow cwnd traces (`results/graphs/validation_cwnd.png`).
2. **NS-3's CUBIC misbehaves without SACK.** One flow reached 4.66 Mbps with 10,315 needless retransmissions, versus 9.48 Mbps with SACK. SACK is therefore on for all variants.
3. **A 200 ms minimum RTO deadlocks Tahoe.** It equals the receiver's delayed-ACK timer, so a one-segment window times out on every packet. The project uses the RFC 6298 value of 1 s.
4. **Reno can lose to Tahoe with a single flow.** Two drops in one window make Reno halve twice, the known multiple-loss weakness.
5. **Feedback loop.** A model that uses the sender's *own* throughput reads its own slowdown as congestion once it controls the rate, which throttled one run to 0.6 Mbps. The deployed model therefore uses only network-state features.
6. **Delayed-ACK trap.** At a 1-segment window, delayed ACKs inflate RTT to ~240 ms, which looks like congestion. That is why the predictor has a 4-segment minimum window.
7. **Fairness versus loss trade-off (Phase 3 model).** Freezing cwnd on Medium gave the fewest drops but unfair sharing (Jain 0.78). Growing at 25% restored fairness (0.99) and kept most of the gain.
8. **What matters in the ablation** (current model):
   - **The proactive 20% cut** is the main mechanism. Without it, drops at high load rise from 163 to 267, RTT from 64 to 106 ms, and fairness falls to 0.82.
   - **Medium handling barely matters,** because the delay tree rarely predicts Medium.
9. **Vegas is hurt by delayed ACKs.** Alone on the link, Vegas stops at a 21-segment window (5.3 Mbps), about half the bandwidth-delay product:
   - **Why:** delayed ACKs add a few ms to every RTT sample, and Vegas reads that as packets queueing.
   - **Check:** with an ACK for every packet it reaches 9.6 Mbps; with larger thresholds (alpha 4, beta 6) it reaches 9.5 Mbps.
   - **At high load,** Vegas flows share unfairly (Jain 0.88). Flows that start later measure a base RTT that already includes queueing, a known Vegas problem.
   - **All variants keep the same default ACK settings,** so the comparison stays fair.
10. **BBR (v1) floods shallow buffers.** BBR sends at its bandwidth estimate and does not slow down on loss, so with 8 flows and a 50-packet queue it has 7,886 drops at high load (5× Reno). This is consistent with published BBRv1 measurements, where several BBR flows keep about one extra bandwidth-delay product in flight and overflow small buffers (Hock et al., 2017).

---

11. **The best offline model is not the best controller.** Phase 6 compared feature sets and horizons:
    - **Offline,** the full feature set at 0.2 s scored best (macro-F1 0.68), and the delay-only model scored lowest at 0.5 s (0.61).
    - **Inside NS-3,** the delay-only model gave the largest gain of all 5 candidates: drops −88% (next best −64%) and RTT −24% / −32% (next best −9% / −14%).
    - **Why:** it warns of 95% of drop bursts at least 200 ms ahead (vs 67% for the loss-based models). That early warning matters more than getting the rare Medium class right.
    - **The cost:** more false alarms (21% vs 12%), which shows up as slightly lower goodput.
12. **Loss features only describe the past.** Loss counts tell the sender congestion *already happened*. RTT growth shows the queue filling *before* it overflows. This is why the delay-only model warns earlier (95% vs 67% of drop bursts warned ≥ 200 ms ahead).

13. **Tuning on multi-flow traffic alone can hide a single-flow cost.** The first version of the Phase 7 rule checked only medium and high load, and chose β = 0.5 (halve on High):
    - **On multi-flow traffic it looked best:** drops at medium load −99%, fairness 0.99.
    - **Alone on the link,** though, a flow reached only 87% of Reno's goodput, because halving whenever a small queue forms pushes the window below the bandwidth-delay product.
    - **The fix:** a single-flow goodput check (≥ 97% of Reno, the same limit as the other levels) was added to the rule, still on the training seeds only, and the rule then chose β = 0.8.
    - **The trade-off:** a gentler cut keeps the link full alone, at the cost of some drops at medium load (61 vs 15).

14. **The design also works with other buffer sizes, and helps most with large ones.**
    - **Drops:** with a 20- or 100-packet queue (0.5× and 2.6× the bandwidth-delay product), Predictive TCP still cuts drops by 86–96% vs Reno, in every seed.
    - **RTT:** the gain grows with the buffer (−17% at 20 packets, −50% at 100, high load), because Predictive TCP keeps the queue short whatever its size, while loss-based TCP fills it ("bufferbloat").
    - **Fairness** stays ≥ 0.92.
15. **Predictive TCP loses bandwidth to CUBIC.** Sharing the link 4 against 4 at high load, Predictive TCP gets 23% of the goodput, against 35% for Vegas, 45% for Reno and 48% for CUBIC itself:
    - **Why:** CUBIC keeps filling the queue until packets are lost. Predictive TCP sees the queue growing and backs off, so CUBIC takes the freed space.
    - **Context:** this is the classic weakness of delay-based congestion control (Vegas, and published work since). BBR shows the opposite problem: it takes 94%.
    - **The fix (Phase 8b): a competition detector.** If the queue never drains, assume a loss-based competitor and behave like Reno. Related ideas: Copa switches to a "competitive mode" when it detects loss-based flows, and Compound TCP adds a delay-based window on top of a loss-based one, so it never falls below Reno.
    - **Result:** the share rises from 23% to 36% (unseen seeds: 22% → 35%). With only Predictive flows and the 50-packet buffer it never fires, so the main results are unchanged.
    - **Why not 50%:** settings that reach 40–44% also fire when *no* competitor is present. At high load, 8 Predictive flows plus the UDP traffic never fully drain the queue, which looks like a competitor. Those settings then lose most of the gains (drops only −17% instead of −90%). The tuning rule therefore chose the setting with no false alarms on the training runs.
16. **The competition detector can false-alarm, and the alarm feeds itself.** With a 100-packet buffer at high load (a setting it was not tuned on), it switched to Reno mode for 60–83% of the time in 3 of 5 seeds:
    - **Why it feeds itself:** one flow in Reno mode keeps the queue full, so the other flows also conclude a competitor is present.
    - **Effect:** Predictive TCP still beats Reno in every seed, but by less: drops −62% and RTT −24%, instead of −87% and −50% with the detector off.
    - **Possible improvement:** while in Reno mode, briefly drain the queue now and then (as BBR's ProbeRTT does) to check whether a competitor is really there.

## Limitations

- **Simulation only:** one bottleneck and a FIFO queue. Results may differ on real networks.
- **Offline macro-F1 is 0.61, below the 0.70 target.** The Medium class is rarely predicted correctly (F1 0.20). At medium load, congestion often starts when *another* flow switches on, which a single sender cannot foresee. Recall for High (0.86) and early warning do meet their targets.
- **The learned rule is close to a delay-based controller.** It acts on queueing delay, like Vegas. The differences are that the threshold and the "draining" test are learned from data, and the reaction is a 20% multiplicative cut on top of Reno, not Vegas's ±1 segment adjustments.
- **Fairness at high load is slightly lower than Reno's** (0.96 vs 0.99), though above the 0.9 target.
- **The controller was tuned for this one topology.** It held up for 20- and 100-packet buffers, but β and the minimum window may need different values for other link speeds or RTTs.
- **Vegas still has fewer drops at medium load** when every flow runs Vegas.
- **Still not fully competitive against loss-based TCP:** with CUBIC on the same link, Predictive TCP gets 36% of the bandwidth with the detector (23% without), below Reno's 45% (finding 15). It suits networks where most senders behave similarly, such as a data centre or a managed network, better than the open Internet.
- **The competition detector is tuned to one buffer size:** with a 100-packet buffer it false-alarms and gives up part of the gain (finding 16). It can be switched off with `CompetitionWindow=0s`.
- **One topology and one traffic mix:** buffer sizes were varied (20–100 packets), but link speed, RTT and the number of flows were not.

---

## References

- V. Jacobson, "Congestion Avoidance and Control," *ACM SIGCOMM*, 1988.
- K. Fall and S. Floyd, "Simulation-based Comparisons of Tahoe, Reno, and SACK TCP," *ACM CCR*, 1996.
- L. Brakmo and L. Peterson, "TCP Vegas: End to End Congestion Avoidance on a Global Internet," *IEEE JSAC*, 1995.
- J. Mo, R. La, V. Anantharam and J. Walrand, "Analysis and Comparison of TCP Reno and Vegas," *IEEE INFOCOM*, 1999.
- N. Cardwell, Y. Cheng, C. S. Gunn, S. H. Yeganeh and V. Jacobson, "BBR: Congestion-Based Congestion Control," *ACM Queue*, 2016.
- M. Hock, R. Bless and M. Zitterbart, "Experimental Evaluation of BBR Congestion Control," *IEEE ICNP*, 2017.
- V. Arun and H. Balakrishnan, "Copa: Practical Delay-Based Congestion Control for the Internet," *USENIX NSDI*, 2018.
- K. Tan, J. Song, Q. Zhang and M. Sridharan, "A Compound TCP Approach for High-Speed and Long Distance Networks," *IEEE INFOCOM*, 2006.
- R. Jain, D. Chiu and W. Hawe, "A Quantitative Measure of Fairness and Discrimination," DEC-TR-301, 1984.
- RFC 5681 (TCP Congestion Control), RFC 6298 (Computing TCP's Retransmission Timer), RFC 9438 (CUBIC).
- NS-3 Network Simulator, https://www.nsnam.org
