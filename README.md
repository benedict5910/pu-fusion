# Sensor-fault-tolerant bearing health monitoring (IVHM prototype)

Final-year IVHM project. System scope, hardware, plan: **[IVHM_SPEC.md](IVHM_SPEC.md)**. Research protocol: **[SPEC.md](SPEC.md)**. Leakage guards: **[docs/LEAKAGE.md](docs/LEAKAGE.md)**. Evidence by objective: **[docs/EVIDENCE_LOG.md](docs/EVIDENCE_LOG.md)**. What can be re-run from this repository: **[docs/REPRODUCIBILITY_2026-11-06.md](docs/REPRODUCIBILITY_2026-11-06.md)**.

## Status (6 Nov 2026)

- **Preliminary real-data results exist** for the Paderborn *starter subset* (12 bearings: K001-K004, KA04, KA15, KA16, KA22, KI04, KI14, KI16, KI18; 960 recordings; 7,667 clean 0.5 s windows). They are frozen in `results/starter/` (summary: `results/starter/SUMMARY.txt`). They are not final: the full dataset has not been downloaded.
  - P1 bearing-disjoint: 11 of 15 folds ran (4 folds lack a class in the starter subset; `docs/P1_RUNS.md`).
  - P3 condition hold-out: **2 bearing folds x 4 held-out conditions = 8 runs** (`run_all.py` uses `--repeats 1`; only folds P1_r0_f0 and P1_r0_f2 are valid on the starter subset). It is a narrow diagnostic, not a full P3.
  - P2 (artificial -> real): not run; it needs the artificial-damage bearings.
  - Leaky random split: 3 seeds, teaching reference only.
- **Headline:** reliability-gated fusion does not beat vibration-only, and no gated-vs-baseline difference survives Holm correction. The healthy-window false-alarm rate is about 0.45, concentrated in bearings K002 and K004 (`docs/AUDIT_2026-10-21.md`).
- **Synthetic numbers** from `pufusion/synthetic.py` and the simulated rig are pipeline checks only and are labelled SYNTHETIC / SIMULATED wherever they appear.

## Known limitations (current)

- Starter subset only; P1 runs share bearings, so Wilcoxon p-values overstate the evidence.
- Sensor-quality check (OB2): the learned vibration flatness bound (1.20) exceeds the attainable maximum (~1), so that indicator never fires; vibration noise and spikes are mostly missed.
- The feature file behind `results/starter/` (`features_starter11.npz` merged with `features_ka16.npz`) was built in a cloud workspace and is **not in this repository**. Re-running the experiments needs the starter archives and a feature rebuild (see the reproducibility report).
- ESP32 rig (OB4): designed (Design B, rev A) but no hardware bought; firmware never flashed; rig results are SIMULATED only.
- No digital-twin, vehicle-level or remaining-useful-life claim is supported by this repository (`IVHM_SPEC.md`).

## Layout
```
src/pufusion/   config, data (loader), features, corruption, dataset, splits, models,
                metrics, experiment, synthetic        <- benchmark research
                reliability, explain, health, store, rig, monitor   <- IVHM layer
scripts/        run_all.py (one command), download_pu.py, verify_archives.py, extract_rar.py,
                build_features.py, merge_features.py, run_experiments.py, summarize.py,
                eval_quality.py, audit_diagnostics.py, make_figures.py, train_demo_model.py,
                validate_health.py, check_demo_replay.py, rig_record.py, rig_train.py,
                rig_check_timing.py, design/ (rig calculations and drawing), windows/ (.bat launchers)
firmware/       rig_esp32/rig_esp32.ino (ESP32 streamer; not yet flashed)
app/            dashboard.py, ui.py, research.py (Streamlit: overview | live diagnostics |
                history | research lab | guided professor demo)
models/         demo_models.pkl (trained on 9 starter bearings; K004, KA22, KI18 held out),
                rig_models_simulated.pkl (SIMULATED sessions only)
data/raw/       only the three held-out demo recordings (CC BY-NC 4.0, see README_DATA.md)
results/        starter/ (frozen real-data results), ui_tests/, test_runs/, rig_eval_SIMULATED.json
tests/          unit tests (stdlib unittest; pytest also works)
```

## Quick start
```bash
pip install -r requirements-dev.txt   (cloud/dashboard only: requirements.txt)
python -m unittest discover -s tests -v
#   54 tests. The 4 tests in test_dashboard_apptest.py run the real Streamlit app and skip
#   when Streamlit is not installed. Logs: results/test_runs/, results/ui_tests/.
python scripts/check_demo_replay.py              # demo model vs documented demo values (repo files only)

# Benchmark study, one command (download -> features -> P1/P2/P3/leaky -> summary -> demo model)
python scripts/run_all.py                         # starter subset, ~1.9 GB (Windows: scripts\windows\pu_download.bat, then --skip-download)
python scripts/run_all.py --subset all            # full dataset, ~5.1 GB, final results

# Rig (or --simulate without hardware)
python scripts/rig_record.py --calibrate-zero --port COM5     # motor off
python scripts/rig_record.py --port COM5 --session H1 --label healthy --minutes 5
python scripts/rig_train.py --fit H1 --cal H2 --test-healthy H3 --test-fault F1 F2

streamlit run app/dashboard.py
```
With the starter subset, P1 keeps only folds whose test set still contains all three classes.

## Deployment
The dashboard is deployed on Streamlit Community Cloud from branch `master`, main file `app/dashboard.py` (public URL and rollback steps: `docs/PROFESSOR_DEMO_WALKTHROUGH.md`). Every push to `master` redeploys it; work on other branches (for example `gearbox-v0`) does not. As of 6 Nov 2026 GitHub reports this repository as **public**; earlier docs called it private. Whether it should stay public is a team decision.

## Data licence
Paderborn KAt-DataCenter data are CC BY-NC 4.0. Cite Lessmeier et al. (PHME 2016) and the KAt-DataCenter. Do not commit raw data beyond the three demo recordings.
