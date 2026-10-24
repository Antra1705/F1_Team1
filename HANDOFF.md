# Handoff: Where This Project Stands

## 1. The Project in Brief

- **Course:** BCSE308L Computer Networks, VIT, taught by Prof. Sreethar S.
- **Team:** Antra (24BDS0066), Anuska Sen (24BCE2219), Varshini Harikrishna (24BCE0780). The repository is https://github.com/Antra1705/CN.
- **Goal:** compare TCP Tahoe, Reno, CUBIC, Vegas and BBR in NS-3, then train a small decision tree that predicts bottleneck congestion 0.5 s ahead.
- **Proposed variant:** *Predictive TCP*, which uses that tree inside the sender to back off before the queue overflows.
- **User preferences:** work in phases, one phase per request ("build phase N"). Be honest about weak results; never overclaim.

**Final results so far** (10 seeds, compared with Reno; full tables in `results/RESULTS.md`):

| | Medium load | High load |
|---|---|---|
| Drops | −93% | −90% |
| RTT | −28% | −36% |
| Goodput | 97.4% | 99.6% |
| Fairness (Jain) | 0.99 (Reno 0.99) | 0.95 (Reno 1.00) |

- **Single flow:** Predictive TCP reaches 9.7 Mbps; Reno reaches 9.0.
- **Held-out seeds:** seeds 4–10 show the same gains (drops −94% / −90%, RTT −29% / −36%). Every drop and RTT gain vs Reno and CUBIC: p < 0.0001.
- **PRD criteria:**
  - Section 10.3 (Predictive TCP vs Reno and CUBIC): all 9 met.
  - Section 10.2 (prediction quality): 3 of 4 met. Macro-F1 is 0.61, against a target of 0.70.
- **Main weaknesses:**
  - **Sharing with CUBIC:** Predictive TCP gets 23% of the bandwidth without the detector and 40% with it (unseen seeds 4–10: 23% → 38%). It was 33% before the Phase 10 base-RTT fix (10 seeds).
  - **Detector false alarms** where the queue never drains on its own: 100-packet buffer, 5 Mbps (README finding 16).
  - **Unfair on fast or long links** (Jain 0.41 at 50 Mbps), caused by delayed ACKs (README finding 18).

---

## 2. Phase Status

| Phase | What | Status |
|---|---|---|
| 1 | Tahoe/Reno classes, dumbbell simulation, 45 baseline runs | ✅ |
| 2 | Dataset (106,354 samples), Decision Tree vs Logistic Regression, C++ export | ✅ |
| 3 | `TcpPredictive`, closed-loop runs, ablation | ✅ |
| 4 | Graphs, final table, `RESULTS.md`, README, `run_all.sh` | ✅ |
| 5 | Vegas + BBR baselines | ✅ |
| 6 | Delay-trend features, horizon comparison, model chosen *inside NS-3* (delay-only tree) | ✅ |
| 7 | Controller tuned on seeds 1–3 (β 0.8, MinWindow 4), with a single-flow check | ✅ |
| 8 | Robustness: buffer sweep (20/50/100 packets) + competition with CUBIC | ✅ |
| 8b | Competition detector (fix for losing to CUBIC) | ✅ (verified reproducible) |
| App | Interactive simulator (Streamlit, `app/`) | ✅ Tested headless and in Chrome |
| 10 | Weaknesses re-examined: detector base-RTT fix, link sweep, trivial-guess comparison | ✅ (see 3.0) |
| 12 | Significance: `analysis/significance.py` (paired t-test, 95% CI, sign test), RESULTS 2.1, in `run_all.sh`; 29 data files in the reference | ✅ |
| 11 | Fairness vs gain: 6 models × 18 settings with a 50 Mbps fairness limit; deployed model kept | ✅ (see 3.0b) |
| 13 | 10 seeds: every evaluation repeated on seeds 1–10 (seeds 6–10 new, never used for any choice); reference rebuilt | ✅ (see 3.0c) |
| 9 | Report + presentation | ⬜ Not started; format not yet chosen |

---

## 3. Exactly What Is Left

### 3.0 Phase 10: Done (23 Oct 2026)

- **Detector fix:** `DetectorRawBase` (default on) takes the base RTT from raw RTT samples. Phase 8b's smoothed base made late-starting flows learn 60–85 ms instead of 44 ms, so they never detected CUBIC. Re-tuned with the unchanged rule: `w2s_t1.4_h5s` (hold 5 s, was 10 s). Share vs CUBIC 36% → 41%, all 5 seeds better. A comparison row "Phase 8b detector" is in `mixed_competition.csv` (`results/robustness/mixed_phase8b/`).
- **Main results byte-identical** to Phase 8b (final table, model, tuning, ablation, PRD checks). Changed: competition tuning, mixed competition, buffer sweep (100-packet false alarm now 54% Reno mode, drops −54%).
- **New:** link sweep (`results/robustness/network/`, `network_sweep.csv`, RESULTS 9.4); `analysis/prediction_baselines.py` (RESULTS 6.3); README findings 17–20.
- **Experimental, off by default:** `MinRttSignal` (lowest raw RTT per interval as the model input). See 3.0b.
- **Rejected experiments:** detector evidence gated on recent loss (worse share).
- **Reference rebuilt:** archive 24 MB (Phase 11), 28 data files + 18 graphs in `SHA256SUMS`.

### 3.0b Phase 11: Done (23 Oct 2026)

- **Question:** can Predictive TCP be fair on fast links (Phase 10: Jain 0.45 at 50 Mbps) and keep its gains?
- **Code kept:** the sample logger writes two extra columns (`rtt_min_int_ms`, `raw_min_rtt_ms`); `build_dataset.py` has `RTT_SIGNAL` (env, default `smoothed`, byte-identical dataset). Every result table is unchanged.
- **Experiment:** `analysis/signal_tradeoff.py` (optional, ~40 min, not in `run_all.sh`). 6 models × the Phase 7 grid, seeds 1–3, rule fixed before running with an extra limit Jain ≥ 0.9 at 50 Mbps / 20 ms. Table: `results/model/signal_tradeoff.csv`.
- **Result:** the deployed model fails 50 Mbps fairness at every eligible setting (0.24–0.74). The rule's pick (min signal, full set 0.2 s, β 0.5, MinWindow 2) is fair (0.92) but keeps about half the gain (drops −53% / −69%, RTT −6% / −9% vs −92% / −90%, −26% / −36%).
- **Decision (user's choice):** keep the deployed model; the 50 Mbps limit was dropped after seeing its price, stated openly in README finding 21.
- **Correction made:** README finding 18 previously quoted "−74% / −25%" for a retrained model; that run used untuned controller defaults, so it was replaced by the Phase 11 result.
- **Next idea, not tried:** a per-flow queue-share target (Vegas / FAST / Copa style) instead of the same multiplicative cut for every flow.

### 3.0c Phase 13: Done (23 Oct 2026)

- **What changed:** `SEEDS` in `run_baseline.sh`, `run_predictive.sh`, `run_robustness.sh` (env-overridable, default `1 … 10`), `compare_variants.py`, `robustness.py` and `make_graphs.py` (`N_SEEDS`). The dataset, model, model selection and all tuning still use seeds 1–3 / 1–5 and are byte-identical; no choice was re-made.
- **Results (10 seeds):** drops −93% / −90%, RTT −28% / −36%, goodput 97.4% / 99.6%, Jain 0.99 / 0.95; all 9 PRD criteria met. Seed wins 10/10 vs Tahoe, Reno, CUBIC, BBR for drops and RTT at both loads. vs Vegas: medium drops 0/10 (Vegas lower), high drops 7/10 (p = 0.08), RTT 10/10.
- **Significance:** all Reno/CUBIC drop and RTT comparisons p < 0.0001 (Wilcoxon 0.002, sign 0.001). Medium goodput cost −0.22 Mbps (p = 0.009). `significance.csv` now also has `wilcoxon_p`.
- **Shifts vs 5 seeds, stated openly:** share vs CUBIC 41% → 40% (Phase 8b 33%, Phase 10 better in 10/10, p = 0.0006); 100-packet / high-load false alarm worse (71% Reno mode, drops −40%, RTT −13%; detector off −86% / −49%).
- **Runtime:** `run_all.sh` ~28 min (step 2 is 150 runs).

### 3.1 Phase 8b: Done

**State:**
- **Detector:** in `ns3/tcp-variants.cc` with defaults 2 s / 1.4 / 10 s, tuned by `analysis/tune_competition.py`. The choice is in `results/model/competition_choice.json`: `w2s_t1.4_h10s`.
- **Results:** share against CUBIC 23% → 36% (unseen seeds 22% → 35%).
- **Main results unchanged:** same md5 as before the detector. Ablation runs use "detector off", and their md5 also matches Phase 8.
- **Documentation:** the false alarms with a 100-packet buffer are in README finding 16 and `RESULTS.md` section 9.1.
- **Docs updated:** README (headline, how it works, options, findings 15–16, limitations, structure), `PROJECT_PLAN.md` (Phase 8b block), `PRD.md` (M8b) and both PDFs.

**One check may still be pending:** the final end-to-end reproducibility run.
1. Record the md5 of these files: `results/final_table.md`, `results/model/metrics.json`, `results/comparison_runs.csv`, `results/model/selection.csv`, `results/model/tuning.csv`, `results/model/competition_tuning.csv`, `results/ablation_summary.csv`, `results/robustness/buffer_sweep.csv`, `results/robustness/mixed_competition.csv`, `ns3/predictive-model.h` and `results/RESULTS.md`.
2. Run `./run_all.sh` (about 28 minutes).
3. Compare the md5s.
4. In zsh, list the files explicitly; a variable holding the list is not split into separate names.
5. If the check is marked as passed in the line below, skip this.

**Reproducibility check:** ✅ passed on 13 Oct 2026. A full `./run_all.sh` (16 min) reproduced all 11 files byte-for-byte.

### 3.1b Interactive Simulator App: Done

**What it is:**
- `app/app.py` is a Streamlit app that runs the compiled NS-3 binary directly (about 1.3 s per 60 s simulation) and plots the results.
- **Tabs:**
  - Live simulation: compare variants, or share the link with CUBIC.
  - Project results.
  - How Predictive TCP works.

**How it is set up:**
- **Own environment:** `app/.venv`, Python 3.12 with Streamlit 1.65 (`app/requirements.txt`). It is kept separate so the analysis environment, and its exact reproducibility, is never touched.
- **Start:** `./app/run_app.sh`.
- **Cache:** runs are saved in `app/runs/`, which is in `.gitignore`.
- **Visual design: powder-blue broadsheet.** The user rejected a light Swiss version, a dark neon one ("looks AI-made") and a warm-newsprint one ("don't like the bg"). They asked for powder blue.
  - **Page:** powder blue #C4E0E8, sidebar #B2D3DD, panels #D5EAF0.
  - **Text is tonal:** darker shades of the page's own hue (~195°): ink #0D2B36, muted #254D5B, faint #375C67. The user said the earlier navy and slate text didn't go with the blue.
  - **Status colours:** good is sea green #0F5C4D, worse is deep indigo #2F2580 (the user disliked rust).
  - **Indigo-violet #4B3BA8 is reserved for Predictive TCP;** #3F3294 is used when it's text. The user picked it over raspberry and plum after rejecting coral/rust.
  - **Baselines in deep inks:** Reno cerulean #225081, CUBIC bronze #7A5200, Vegas rose #8A365E (was plum, too close to the indigo), BBR #1F6338, Tahoe #4B626C.
  - **Contrast:** all text and series colours ≥ 4.5:1 on the page, checked with a script.
  - **Where the palette came from:** the skill had no powder-blue palette, so it is hand-made, and this was said openly.
  - **Fonts:** IBM Plex Sans for everything (masthead, headline numbers, labels, chart titles, diagram) and IBM Plex Mono for table figures and deltas. Chosen from a rendered specimen of three skill pairings (Plex, Fira, Exo); the user disliked the earlier Newsreader serif.
  - **Kept from the broadsheet design:** dateline strip, double rule, "Fig. n —" chart titles, square controls.
  - **Backups:** the earlier versions' `app.py` were saved only in the session scratchpad, not in the project.
  - **Gotcha: the CSS block must start with `<style>`,** load fonts by `@import` inside it, and contain no blank lines. Otherwise Streamlit prints the CSS as text.
  - **Gotcha: don't set `font-family` on `[class*="st-"]`.** It would also override the code block's monospace font.
  - **Gotcha for screenshots:** `text-transform: uppercase` changes `innerText`, so screenshot scripts must match button labels case-insensitively.
  - **Run order:** the simulation runs before the header is drawn, so the topology diagram can show the measured mean queue. Cells past 80% are drawn in the accent colour.
  - **Launch:** `run_app.sh` must start Streamlit from inside `app/` so the theme file is used.

### 3.1c README Instructions: Done

`README.md` now has the full instructions:
- quick start and a contents bar;
- setup step by step from a fresh Mac (Command Line Tools, Homebrew, NS-3, both Python environments, sizes);
- a `run_all.sh` step table with timings;
- single-run examples, a reproducibility check, and PDF regeneration;
- the app: install, start/stop, usage, demo sequence, cache;
- a troubleshooting table.

All anchors, file links and code fences were checked. Keep it in sync when scripts or options change.

**Portability:**
- The README has macOS, Linux (Ubuntu/Debian) and Windows-via-WSL2 setup. Linux and WSL are documented but **not tested** on those systems; the README says so.
- **Code made portable:** `build.sh` falls back to `cp` when `rsync` is missing; `export_tree.py` uses `$CXX`, then clang++, g++ or c++. Both changes were verified on the Mac with identical output.
- **`.gitattributes`** forces LF line endings so the bash scripts work in WSL.

### 3.1d Same Results on Every OS: Reference Mode

The user wanted results equal to macOS everywhere.

**Why re-simulation can't do it:** a re-simulation cannot be bit-identical across OS, compiler or CPU. libm, clang/gcc and ARM/x86 differ in the last bit, and the simulation amplifies it.

**The solution:**
- **`reference/simulation_data.tar.xz`** (39 MB since Phase 13, 10 seeds, xz -9): all NS-3 output from the verified Mac run.
- **`reference/expected/`:** the 24 result tables, `RESULTS.md` and the header.
- **`reference/SHA256SUMS`:** checksums of results, dataset, graphs and the archive.

**How it works:**
- **`./run_all.sh --reference`** checks the archive checksum, unpacks it into `results/`, sets `PTCP_REFERENCE=1` and skips all NS-3 runs and builds. In `select_model.py`, `tune_controller.py` and `tune_competition.py` the `ns3_run` and build calls are gated by this variable.
- **`analysis/verify_reference.py --strict`** runs at the end. Normal mode also runs the verifier, without `--strict`, as a report.

**Tested (Phase 13):** a fresh-clone copy (61 MB) with `NS3_DIR=/nonexistent` gave 29/29 data files and 18/18 graphs identical, in 58 s. The full 10-seed `./run_all.sh` took 28 min.

**If the Mac results are ever regenerated on purpose** (code change), rebuild `reference/` (archive, expected/ and SHA256SUMS) from the new verified results.

### 3.2 GitHub (waiting on the user)

1. **Before uploading,** wait for the user to give a repository URL and say whether it is private or public. Private is recommended until grading.
2. **`.gitignore` is done.** It excludes `.venv/`, the raw run folders, `results/dataset.csv`, `results/model/test_predictions.csv` and `results/v1/`. All of these are regenerated by `run_all.sh`. It keeps the code, docs, `RESULTS.md`, graphs, summary CSVs, the small model files and this file.
3. **The `gh` CLI is not installed.** The user creates an empty repository on github.com (no README) and gives its URL.
4. **The git identity is already configured** (Antra1705).
5. **Then run:**
   ```bash
   git init -b main && git add . && git commit -m "..."
   git remote add origin <URL> && git push -u origin main
   ```
   Commit and push only after the user agrees.
6. **Not yet done:** `git init`.

### 3.3 Phase 9: Report + Presentation

- **Questions for the user before starting:**
  - Format: Word + PowerPoint, PDF + PowerPoint, or a faculty template?
  - Is a report structure required?
  - What is the deadline?
- **Content to cover:** problem, background (Tahoe, Reno, CUBIC, Vegas, BBR), design, ML, Predictive TCP, results, robustness, limitations and the 15 findings in the README.
- **Slides:** about 12–15.
- **Never** use Claude Artifacts or Claude Docs for this user. Their global rule says to write documents as local files.

---

## 4. Rules This Project Follows (do not break them)

- **Seeds 1–3 for every choice; seeds 4–10 only for final numbers.** This applies to model selection (Phase 6), controller tuning (Phase 7) and detector tuning (Phase 8b).
- **Selection rules are written in the script before running.** If a rule is changed after seeing a result, say so openly in the code docstring and the README (as was done for the Phase 7 single-flow check).
- **Earlier phases are pinned to their settings so the pipeline reproduces:**
  - `select_model.py` passes Beta 0.85, MinWindow 4 and CompetitionWindow 0s.
  - `tune_controller.py` passes CompetitionWindow 0s.
- **Model inputs exclude the sender's own throughput and absolute cwnd.** Phase 3 showed these create a feedback loop.
- **Same TCP settings for every variant:** SACK on, MinRto 1 s, 1448-byte segments, default delayed ACKs.
- **Reproducibility is checked by md5 after every phase.** Every run is deterministic.
- **Results text in `RESULTS.md` is generated from data** by `make_graphs.py`. The README numbers are written by hand, so update them whenever results change.

---

## 5. Environment Setup (new machine or after cloning)

1. **Build tools and NS-3.48** in `~/ns-3`, using the commands in the README "Setup" section (`brew install cmake ninja`, then download, configure with the module list, and build). If NS-3 lives elsewhere, set `NS3_DIR`.
2. **Python environment:** `uv venv .venv && uv pip install -r requirements.txt`.
3. **Compile:** `./build.sh` copies `ns3/` into `~/ns-3/scratch/tcp-predictor` and compiles it.
4. **Regenerate everything:** `./run_all.sh`, about 28 minutes. This recreates every ignored results folder.
5. **PDFs of the plan and PRD:**
   ```bash
   python3 -m venv /tmp/mdvenv && /tmp/mdvenv/bin/pip install markdown
   /tmp/mdvenv/bin/python tools/md2html.py docs/PRD.md /tmp/PRD.html PRD
   "/Applications/Google Chrome 2.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
     --no-pdf-header-footer --print-to-pdf="$PWD/docs/PRD.pdf" file:///tmp/PRD.html
   ```
   Do the same for `PROJECT_PLAN`. On this Mac, Chrome is installed as "Google Chrome 2.app".

---

## 6. Gotchas Met So Far

- **Do not edit `ns3/` while `run_all.sh` runs.** `build.sh` runs at steps 1, 4 and 6 and would compile half-edited code. Edits are safe after step 6.
- **The safety system blocks some deletes.** It blocks `rm -rf` on wide paths and globbed deletes. Use explicit paths.
- **macOS:** port 5000 is used by AirPlay (relevant only to the separate Java lab). Xcode Command Line Tools must be the active developer directory.
- **CUBIC without SACK misbehaves in NS-3,** and a 200 ms MinRto deadlocks Tahoe. Both are already handled; see README findings 2 and 3.
- **Vegas reaches only about 5 Mbps alone.** This is real behaviour caused by delayed ACKs (finding 9), not a bug.
