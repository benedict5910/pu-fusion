# Evidence log (objective by objective)

Status: **VALIDATED** = measured on real data/hardware, artefact linked · **TESTED (synthetic)** = code
runs, unit/pipeline tests only, no result · **BLOCKED** = reason given. Synthetic numbers are never results.

| Obj | Evidence item | Status (21 Oct 2026) | Artefact |
|---|---|---|---|
| OB1 | Loader, features, 6 models, P1/P2/P3, leaky reference, metrics, Wilcoxon + Holm | TESTED (synthetic) | `src/pufusion/*`, `scripts/run_experiments.py`, `scripts/summarize.py` |
| OB1 | Confusion matrices + figures | TESTED (synthetic) | `scripts/make_figures.py` |
| OB1 | Real Paderborn data obtained (Zenodo mirror 10.5281/zenodo.15845309; official host unreachable) | IN PROGRESS: 11/12 starter archives VERIFIED (MD5 = Zenodo; 80 .mat each = 4 conditions x 20; 0 unreadable; 64 kHz; fact-sheet primary damage = config label); KA16 downloading | `scripts/verify_archives.py`, `docs/data_verification_starter.json` |
| OB1 | Measured P1 (+P3, leaky) results | BLOCKED: needs data | `results/starter/` |
| OB2 | Label-free reliability assessor; seen vs withheld fault families; ablations | TESTED (synthetic) | `src/pufusion/reliability.py`, `scripts/eval_quality.py` |
| OB2 | Measured detection / false-flag / cross-flag rates | BLOCKED: needs data | `results/starter/quality.json` |
| OB3 | Health states (latched INSPECT, SENSOR_FAULT), explanations + faithfulness, SQLite, CSV/HTML reports | TESTED (unit tests) | `src/pufusion/health.py`, `explain.py`, `store.py`, `monitor.py` |
| OB3 | Dashboard running on real held-out bearings; screenshots | BLOCKED: needs data + demo model | `app/dashboard.py` |
| OB4 | Firmware, frame protocol, host clock fitting, timing self-test, rig detector, simulated rig | TESTED (simulated rig only); firmware not flashed | `firmware/`, `src/pufusion/rig.py`, `scripts/rig_*.py` |
| OB4 | Rig assembled, timing test PASS, H1-H4 + fault sessions | NOT STARTED (no hardware) | - |

## Change log
- 2026-10-15: original pu-fusion pipeline (3 commits, 34 tests).
- 2026-10-19: cloud workspace lost; pipeline rebuilt from the spec (preserved on branch `rebuild-2026-10-19`).
- 2026-10-21: original recovered from zip and adopted as the base. From the rebuild: confusion-matrix counts in metrics, presentation figures, Holm correction actually applied in `summarize.py` (it was claimed but not computed), and a curl download (starter / all) verified against the official file list (the old list missed KI17, KB23, KB24, KB27).
- 2026-10-21: official host groups.uni-paderborn.de unreachable from our network (curl error 7). Switched to Zenodo mirror record 15845309: all 31 archives match the official listing sizes to the MiB (KA08 absent); every archive is checked against Zenodo MD5 and by content after extraction. Open item: KA22 fact sheet gives pitch diameter 29.05 mm vs 28.55 mm in config.py (Lessmeier 2016); to be checked across all fact sheets before any change.
- 2026-10-21: fact-sheet checks. KI04 and KI14 list a primary inner-ring fatigue pitting (damage 1) plus a secondary outer-ring plastic deformation (damage 2, no measurable extent); labelled inner race as in Lessmeier et al. 2016 (combined-pitting bearings KB23/24/27 remain excluded). Pitch diameter is 29.05 mm on some fact sheets (K001-K004, KA22, KI04, KI14, KI18) and 28.55 mm on others (KA04, KA15, KI16); config uses 28.55 mm. The resulting BPFO/BPFI shift (0.5 % / 0.3 %) is inside the feature search tolerance (2 %), so no method change; reported as a limitation.
