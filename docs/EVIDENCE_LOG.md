# Evidence log (objective by objective)

## Objective status (21 Oct 2026, preliminary, starter subset of 12 bearings)
| Objective | Status |
|---|---|
| OB1 benchmark | **Experimentally evaluated (preliminary).** P1 11/15 folds, P3 8 runs, leaky reference. The gated model scores higher than early (+0.049) and average fusion (+0.057) under withheld sensor faults, but does not beat vibration-only (-0.015) and no difference is statistically significant after Holm correction. Details: `docs/P1_RUNS.md`. |
| OB2 sensor quality | **Experimentally evaluated (preliminary).** Clean false-flag 1.6 % / 1.2 %; dropout, intermittent, stuck, clipping caught 96-100 %; vibration noise/spikes/gain largely missed (cause in `docs/AUDIT_2026-10-21.md`). |
| OB3 health layer | **Engine validated headless on real held-out data; complete only after the Streamlit UI is validated on the laptop (pending).** |
| OB4 rig | **Pending** (code tested on simulated rig only; no hardware). |

Status: **VALIDATED** = measured on real data/hardware, artefact linked · **TESTED (synthetic)** = code
runs, unit/pipeline tests only, no result · **BLOCKED** = reason given. Synthetic numbers are never results.

| Obj | Evidence item | Status (21 Oct 2026) | Artefact |
|---|---|---|---|
| OB1 | Loader, features, 6 models, P1/P2/P3, leaky reference, metrics, Wilcoxon + Holm | TESTED (synthetic) | `src/pufusion/*`, `scripts/run_experiments.py`, `scripts/summarize.py` |
| OB1 | Confusion matrices + figures | TESTED (synthetic) | `scripts/make_figures.py` |
| OB1 | Real Paderborn data obtained (Zenodo mirror 10.5281/zenodo.15845309; official host unreachable) | VALIDATED: 12/12 starter archives (MD5 = Zenodo; 80 .mat each = 4 conditions x 20; 0 unreadable; 64 kHz; fact-sheet primary damage = config label); 960 recordings, 7,667 clean windows, 0 feature errors | `scripts/verify_archives.py`, `docs/data_verification_starter.json` |
| OB1 | Measured P1 (+P3, leaky) results, starter subset (4 healthy / 4 real OR / 4 real IR) | VALIDATED (21 Oct): P1 11 bearing-disjoint runs, clean macro-F1 vib 0.562, early 0.567, average 0.558, gated 0.533, current 0.323; withheld faults gated 0.455 vs early 0.405 / average 0.398 / vib 0.470; no gated-vs-baseline difference significant after Holm. Window false-alarm rate ~0.45. Leaky random split 0.95-0.98 vs 0.53-0.57 bearing-disjoint. P3 (condition hold-out) 8 runs, similar pattern. | `results/starter/SUMMARY.txt`, `results/starter/figures/` |
| OB2 | Label-free reliability assessor; seen vs withheld fault families; ablations | TESTED (synthetic) | `src/pufusion/reliability.py`, `scripts/eval_quality.py` |
| OB2 | Measured detection / false-flag / cross-flag rates (15 folds, held-out bearings) | VALIDATED (21 Oct): clean false-flag vib 1.6 %, cur 1.2 %; dropout, intermittent, stuck, clipping (withheld) detected 96-100 % on both sensors; current noise/spikes 100 %; vibration noise (2-15 %), spikes (2-11 %) and gain (2-16 %) largely undetected; cross-flag on the healthy sensor = clean rate (1.3-1.5 %) | `results/starter/quality.json`, `figures/ob2_quality_detector.png` |
| OB3 | Health states (latched INSPECT, SENSOR_FAULT), explanations + faithfulness, SQLite, CSV/HTML reports | TESTED (unit tests) | `src/pufusion/health.py`, `explain.py`, `store.py`, `monitor.py` |
| OB3 | Same engine as dashboard replayed on real held-out bearings K004/KA22/KI18 (demo model trained on the other 9), 6 sensor scenarios each | VALIDATED headless (21 Oct): NORMAL/WARNING/latched INSPECT/SENSOR_FAULT all exercised; both-sensor dropout -> SENSOR_FAULT; SQLite history + CSV/HTML reports written; explanation deletion check mean prob. drop vib 0.28 / cur 0.05. Finding: healthy K004 reaches INSPECT on clean data (false alarm). | `results/starter/ob3/` |
| OB3 | Streamlit dashboard launched on laptop + screenshots | PENDING: run `scripts\windows\run_dashboard.bat` | `app/dashboard.py` |
| OB4 | Firmware, frame protocol, host clock fitting, timing self-test, rig detector, simulated rig | TESTED (simulated rig only); firmware not flashed | `firmware/`, `src/pufusion/rig.py`, `scripts/rig_*.py` |
| OB4 | Rig assembled, timing test PASS, H1-H4 + fault sessions | NOT STARTED (no hardware) | - |

## Change log
- 2026-10-15: original pu-fusion pipeline (3 commits, 34 tests).
- 2026-10-19: cloud workspace lost; pipeline rebuilt from the spec (preserved on branch `rebuild-2026-10-19`).
- 2026-10-21: original recovered from zip and adopted as the base. From the rebuild: confusion-matrix counts in metrics, presentation figures, Holm correction actually applied in `summarize.py` (it was claimed but not computed), and a curl download (starter / all) verified against the official file list (the old list missed KI17, KB23, KB24, KB27).
- 2026-10-21: official host groups.uni-paderborn.de unreachable from our network (curl error 7). Switched to Zenodo mirror record 15845309: all 31 archives match the official listing sizes to the MiB (KA08 absent); every archive is checked against Zenodo MD5 and by content after extraction. Open item: KA22 fact sheet gives pitch diameter 29.05 mm vs 28.55 mm in config.py (Lessmeier 2016); to be checked across all fact sheets before any change.
- 2026-10-21: fact-sheet checks. KI04 and KI14 list a primary inner-ring fatigue pitting (damage 1) plus a secondary outer-ring plastic deformation (damage 2, no measurable extent); labelled inner race as in Lessmeier et al. 2016 (combined-pitting bearings KB23/24/27 remain excluded). Pitch diameter is 29.05 mm on some fact sheets (K001-K004, KA22, KI04, KI14, KI18) and 28.55 mm on others (KA04, KA15, KI16); config uses 28.55 mm. The resulting BPFO/BPFI shift (0.5 % / 0.3 %) is inside the feature search tolerance (2 %), so no method change; reported as a limitation.
- 2026-10-21: diagnostic audit (`docs/AUDIT_2026-10-21.md`): the ~0.45 window false-alarm rate comes from two of the four healthy bearings (K002, K004: 0.75-0.87) that are unlike the healthy bearings seen in training (2-3 per fold); K001/K003 ~0-0.06. Not an evaluation error (audit reproduces every reported fold FAR exactly); health rules propagate it. Vibration noise/spikes go undetected because the learned clean ranges are wide (flatness bound 1.20 > attainable max ~1; spike bound 19.6 dB vs 12.5 dB under heavy spikes). P1 fold accounting and power: `docs/P1_RUNS.md`.
