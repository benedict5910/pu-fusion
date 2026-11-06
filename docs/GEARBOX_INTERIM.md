# IVHM interim evidence · 12–14 November 2026

## Presentation sequence

1. Run the existing bearing demo on the committed KI18 recording. Point out the sustained fault evidence and the transition from WARNING to INSPECT.
2. Open **Gearbox Pilot** and choose a held-out operating profile and a test recording. Run clean replay, repeat with motor dropout, and then repeat with both sensors dropped out. Compare sensor weights, diagnosis availability and the state trace. Export the replay CSV if needed.
3. Show the pilot evaluation beside the bearing rerun. Explain that both subsystems use the same health-state rules, with separate models and sensor calibration. Distinguish experimental recordings, simulated signal faults and offline model predictions.

## Paderborn recovery

The laptop's `Projects/pu-fusion/data` contained `features_starter.npz`, its metadata, 12 raw MAT recordings and the demo model. `Projects/ivhm-fusion` contained prototype source and notes. The inspected Paderborn downloads directory contained only logs from an unsuccessful download. The feature archive and metadata were copied into this checkout's ignored `data/` directory.

- Archive SHA-256 `E37E46EA89645E178663D75913F1FFCD8A9F56F0A6162ED2175FEFA3DB010670`.
- The archive contains 7,667 clean windows, 7,667 augmented windows and 36,480 corrupted windows. The clean set has 31 vibration and 30 current diagnosis features.
- All 3,861 rerun rows match the frozen P1 keys across 11 folds and nine model variants. Mean absolute macro-F1 difference was 0.00055 overall and 0.00038 on clean rows. The largest individual differences were 0.02646 overall and 0.00199 on clean rows. This is a rerun from recovered features. Raw-to-feature reconstruction still requires the complete input recordings and their provenance.
- Clean mean macro-F1 was 0.562 for vibration only, 0.568 for early fusion and 0.533 for reliability-gated fusion. The gated model remained below the two clean baselines.

```powershell
python scripts/run_experiments.py --features data/features_starter.npz --protocol p1 --repeats 5 --models all --out ../work/recovered_p1.csv
python scripts/check_demo_replay.py
```

## Gearbox pilot design

Source: Shijin Chen, Zeyi Liu, Xiao He, Dongliang Zou and Donghua Zhou (2024), [MCC5-THU v2, DOI 10.17632/p92gj2732w.2](https://data.mendeley.com/datasets/p92gj2732w/2), CC BY 4.0. Channel names, recording format and sampling frequency follow the [authors' dataset documentation](https://github.com/liuzy0708/MCC5-THU-Gearbox-Benchmark-Datasets).

- Inputs are both three-axis accelerometers at 12.8 kHz. Shaft pulse and torque are excluded from the pilot model. Each complete one-second window yields time and spectral features and seven quality indicators per axis.
- The three classes are healthy, medium-severity gear pitting and medium-severity gear wear. The four torque profiles are `1000rpm_10Nm`, `1000rpm_20Nm`, `2000rpm_10Nm` and `3000rpm_10Nm`. Each profile has one recording per class. Train on three profiles and test on the fourth, rotating through all four profiles. The complete test profile stays outside scaling, classifier fitting and sensor quality calibration.
- The comparisons are motor-only, gearbox-only, early fusion, equally weighted late fusion and quality-gated late fusion. A sensor's worst axis determines its reliability. Gated fusion excludes failed sensors or sensors below 0.5 and normalizes the remaining scores. The health tracker consumes the fused fault score and can suspend diagnosis when both sensors fail.
- Seven seeded faults are tested on held-out signals only: full dropout, stuck value, burst loss, clipping, additive noise, gain plus offset and spikes. Burst loss can overlap and spike locations can repeat. The simulation tests validate effects on the signal. Sensor status counts in the benchmark show detection performance separately. The sensor injector applies a scenario to all three axes of the selected accelerometer.
- Report macro-F1 and coverage together. An abstention counts as a missed true class in macro-F1. A recording gets a label when more than half its windows yield a prediction. The recording score uses averaged class probabilities over the accepted windows.
- This pilot uses 12 recordings from one bench. The experimental unit is the recording or operating profile, so the windows should not be treated as independent validation samples. Scores are descriptive, and the fitted class probabilities are uncalibrated. The pilot covers selected conditions and severities. It provides no field validation or evidence of remaining useful life.

## Reproduce the gearbox pilot

Place the 12 publisher CSVs, or gzip copies, in `data/mcc5/`. The matching stems are `{health,gear_pitting_M,gear_wear_M}_torque_circulation_{1000rpm_10Nm,1000rpm_20Nm,2000rpm_10Nm,3000rpm_10Nm}`. Raw datasets and recovered bearing features stay local. The dashboard trains on the selected training profiles when replay starts and caches the fitted model for that split.

```powershell
python scripts/evaluate_gearbox.py --data data/mcc5 --out results/test_runs/mcc5_interim.json --jobs 3
python -m streamlit run app/dashboard.py
```

## Verified replay and tests

Use `gear_pitting_M_torque_circulation_1000rpm_10Nm.csv` for the presentation. Its full 177-window [replay trace](../results/test_runs/mcc5_pitting_replay.csv) records three passes over the same 59 complete windows.

| Replay | First WARNING | First INSPECT | Diagnosis coverage | Final motor / gearbox weight |
| --- | ---: | ---: | ---: | --- |
| Clean | 2 | 7 | 100% | 0.50 / 0.50 |
| Motor dropout | 2 | 4 | 100% | 0.00 / 1.00 |
| Both sensors dropped | — | — | 0% | 0.00 / 0.00 |

The clean and motor-dropout passes ended with a pitting prediction. In the dual-dropout pass, all 59 windows reported SENSOR_FAULT and the model withheld both the class and fault score. This example verifies the replay and fallback behavior.

The Windows test run passed 56 tests and seven subtests, with two fallback dashboard tests skipped because Streamlit was installed. The three frozen bearing demo recordings reproduced their documented check values. No files under the tracked `data/`, `models/` or `results/starter/` changed.

A real Streamlit smoke test loaded the gearbox view and ran all three scenarios on the downloaded recording. It reproduced 100% diagnosis coverage for clean and motor dropout, and 0% with SENSOR_FAULT for dual dropout.

## Held-out results

The four folds evaluated 12 recordings and 708 complete windows. The table gives pooled **window macro-F1**. The [full evaluation](../results/test_runs/mcc5_interim.json) also includes recording scores, per-fold confusion matrices, sensor status counts and replay checkpoints.

| Replay | Motor only | Gearbox only | Early fusion | Equal late fusion | Gated late fusion | Gated coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Clean | 0.542 | 0.593 | 0.591 | 0.565 | 0.565 | 100% |
| Motor dropout | 0.167 | 0.593 | 0.167 | 0.167 | 0.593 | 100% |
| Gearbox dropout | 0.542 | 0.167 | 0.249 | 0.167 | 0.542 | 100% |
| Gearbox noise | 0.542 | 0.303 | 0.283 | 0.462 | 0.551 | 100% |
| Gearbox gain error | 0.542 | 0.526 | 0.573 | 0.495 | 0.504 | 100% |
| Both sensors dropped | 0.167 | 0.167 | 0.167 | 0.167 | 0.000 | 0% |

Gated fusion matched the surviving expert under each single-sensor dropout and abstained on all 708 dual-dropout windows. It improved over early fusion under gearbox noise and trailed early fusion under clean data and gearbox gain error. Clean recording-level macro-F1 was 0.579 for gated fusion and 0.589 for gearbox-only. Clean gated recording macro-F1 ranged from 0.167 to 1.000 across the four profiles, each with three test recordings.

The sensor check flagged all injected full dropouts, but flagged only 208 of 708 windows under the motor gain error. On clean data it marked 114 motor windows and five gearbox windows degraded, with zero failures. Use the presentation to demonstrate sensor fallback and explain the limits of detecting gradual calibration errors.
