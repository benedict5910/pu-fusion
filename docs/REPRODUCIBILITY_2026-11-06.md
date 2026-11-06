# Reproducibility report (6 Nov 2026)

Branch `gearbox-v0`, created from `master` at `68b1eade0681fe85d565840f6eb59742980a545b`. Everything below was
checked in a cloud copy of the GitHub repository. **The team laptop was not inspected**: the folders
`~/Projects/pu-fusion` and `~/Projects/ivhm-fusion` exist there, but read access was not granted in this
session. Anything listed as "not in the repository" may still exist on the laptop and must not be treated as lost
until those folders are checked (section 4).

## 1. Artifacts in the repository

| Artifact | Path | Size | SHA-256 (first 16) | What it is |
|---|---|---|---|---|
| Demo models | `models/demo_models.pkl` | 12 KB | `150f6b41c040417a` | vib_only, cur_only, early_fusion, gated_both + vib/cur reliability assessors; trained on K001-K003, KA04, KA15, KA16, KI04, KI14, KI16; K004, KA22, KI18 held out; scikit-learn 1.9.1 |
| Simulated rig model | `models/rig_models_simulated.pkl` | 13 KB | `e8a703428f5cdbab` | SIMULATED sessions only; not a result |
| Demo recording K004 | `data/raw/K004/N15_M07_F10_K004_1.mat` | 8.7 MB | `4fbe5c88b56c0a2e` | healthy, held out |
| Demo recording KA22 | `data/raw/KA22/N15_M07_F10_KA22_1.mat` | 8.7 MB | `9e39532276f79b1a` | real outer race, held out |
| Demo recording KI18 | `data/raw/KI18/N15_M07_F10_KI18_1.mat` | 8.7 MB | `f7bfc841ba0c66c0` | real inner race, held out |
| Frozen results | `results/starter/` | 7.2 MB | - | p1/p3/leaky CSV + logs, quality.json, SUMMARY.txt, figures, audit, OB3 replay, UI screenshots |
| Archive verification | `docs/data_verification_starter.json` | - | - | MD5, layout, 64 kHz and fact-sheet checks for the 12 starter archives |
| Feature metadata | `results/starter/features_meta.json` | - | - | options and row counts of the feature file (7,667 clean / 7,667 aug / 36,480 corr rows, 0 errors) |

Size and hash of the `.pkl` and `.mat` files were measured with `sha256sum` on 6 Nov.

## 2. Artifacts not in the repository

| Artifact | Last known location | Needed for | Status |
|---|---|---|---|
| Starter archives (12 x ~160 MB RAR, ~1.9 GB) and extracted `.mat` files (960) | cloud workspace `/home/claude/data/raw` and `/home/claude/data/raw_ka16` (21 Oct); possibly the laptop | rebuilding features | Not in repo (by design, `.gitignore`). Re-downloadable from Zenodo record 15845309 with MD5 check (`scripts/windows/zenodo_15845309_md5.txt`) |
| Feature files `features_starter11.npz`, `features_ka16.npz`, merged file | cloud workspace `/home/claude/data/` (21 Oct) | re-running P1/P3/leaky, OB2 eval, audit, demo-model training | Not in repo, no hash recorded. That workspace no longer exists. Laptop not checked |
| Per-window predictions of the P1 runs | never saved | bearing-level bootstrap CIs | Would need a re-run |
| Full Paderborn dataset (32 archives, ~5.1 GB) | never downloaded | full P1, P2 | Not available |
| Rig recordings | none | OB4 | No hardware exists |
| MCC5-THU gearbox data | not downloaded | gearbox module | Deliberately not downloaded yet |

## 3. What can be re-run, and with what

| Check or experiment | Inputs needed | Re-runnable from the repo alone? | 6 Nov result |
|---|---|---|---|
| Unit tests | repo | Yes (4 AppTest tests also need Streamlit) | 54 tests: 50 passed, 4 skipped; `results/test_runs/2026-11-06_cloud_unittest.txt` |
| `SUMMARY.txt` tables and Wilcoxon/Holm tests | committed CSVs | Yes | Identical; `results/test_runs/2026-11-06_cloud_summary_recompute.txt` |
| Figures (10) | committed CSVs + quality.json | Yes | All 10 regenerated in a scratch folder (not pixel-compared); frozen figures untouched |
| Professor demo values (steps 1, 5, 6) | demo model + 3 recordings | Yes, `scripts/check_demo_replay.py` | All documented values reproduced; `results/test_runs/2026-11-06_cloud_demo_replay.txt` |
| OB3 headless replay (`validate_health.py`) | demo model + recordings | Partly: the frozen run used up to 3 files per bearing (24 windows); the repo holds 1 per bearing (8 windows) | Ran with `--max-files 1` into a scratch folder and compared with the first 8 windows of all 18 frozen histories (144 windows): every health state identical; fault evidence within 0.0012. The only differences are the 12 windows during a both-sensor outage, where the frozen 21 Oct run stored a prior-based value (0.667) and current code stores none; that is the documented 22 Oct safety fix. Frozen `results/starter/ob3/` not overwritten |
| Dashboard | repo + Streamlit | Yes | Not launched in this environment (no Streamlit); last verified 23 Oct (PC) and 25 Oct (cloud) |
| P1, P3, leaky experiments | feature file | **No** | Needs starter archives -> `build_features.py` (+ `merge_features.py` if built in parts) -> `run_experiments.py` |
| OB2 quality evaluation, diagnostic audit | feature file | **No** | as above |
| Retraining the demo model | feature file | **No** | as above; would also need scikit-learn 1.9.1 to match the pickle |
| P2, full 15-fold P1 | full dataset | **No** | never run |
| Rig evaluation | rig sessions | **No** (only `--simulate`) | SIMULATED only |

A rebuilt feature file should give the same tables bit for bit: corruption seeds are derived from (file, window,
grid entry) and windows are cut deterministically (`dataset.py`). This has not been demonstrated, because no
second build has been made. When the feature file is rebuilt, compare its row counts with `features_meta.json`
and its P1 output with `results/starter/p1.csv` before using it for anything new.

## 4. To close the gaps

1. Connect the laptop folders `~/Projects/pu-fusion` and `~/Projects/ivhm-fusion` and list `data/`, `models/`,
   `results/` and `git status` there. If the feature file exists, record its SHA-256 here.
2. If it does not: download the 12 starter archives (MD5-verified), rebuild features, and re-run P1 on one fold
   to confirm the committed CSV is reproduced before any new experiment.
3. Keep the frozen `results/starter/` and `models/demo_models.pkl` read-only; new work writes to new paths.

## 5. Environment of this check
Python 3.13, numpy 2.5.3, scipy 1.18.1, scikit-learn 1.9.1; Streamlit not installed; no network access for
package installs. The dashboard's pinned environment is Python 3.11.9 with `requirements.txt`.
