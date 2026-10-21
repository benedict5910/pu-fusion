# IVHM project - objective-by-objective evidence log

Status key: **VALIDATED** = measured on real data / real hardware, artefact linked ·
**CODED + TESTED (synthetic)** = code runs end-to-end, unit/plumbing tests only, *no result* ·
**NOT STARTED** · **BLOCKED** (reason given).

Rule: numbers from synthetic signals are never reported as results. Every figure carries a
data-source stamp in its corner.

## Audit - 19 Oct 2026 (start of the 12-day push)

| Item | Finding |
|---|---|
| Code repository | None found on GitHub (12 repos checked), `Projects`, `Desktop` or `Downloads`. The earlier pipeline lived in a temporary cloud workspace and is gone. Rebuilt 19 Oct from the approved synopsis/deck (no new features). |
| Paderborn data | Not downloaded (`Downloads\paderborn` absent). The download script `pu_download.bat` exists. The cloud workspace cannot reach the Paderborn server (proxy 403), so data must come through the laptop. |
| Hardware | No evidence of a purchased or assembled rig. Firmware was described as "compiled" in the deck, but no firmware file exists. |
| Results | None existed before 19 Oct (consistent with the deck: "No Paderborn experiment has been run yet"). |

## OB1 - Benchmark vibration-current fault diagnosis (Paderborn, bearing-disjoint)

| Evidence item | Status | Artefact |
|---|---|---|
| Loader (channels located by name, fs check), 3-class labels, KB23/24/27 excluded | CODED + TESTED (synthetic) | `pu/data.py` |
| 0.5 s windows; vibration envelope features at BPFO/BPFI; current sideband/residual features | CODED + TESTED (synthetic) | `pu/features.py` |
| Six models: vib, current, early, average, stacked, per-window gated | CODED + TESTED (synthetic) | `pu/models.py` |
| P1 (5x3 bearing-disjoint), P2 (artificial -> real), P3 (+ condition hold-out), random-split leakage demo | CODED + TESTED (synthetic) | `pu/experiments.py` |
| Macro-F1, ECE, NLL, Brier, false-alarm, miss; Wilcoxon + Holm | CODED + TESTED (synthetic) | `pu/experiments.py` |
| Figures (bars, family heatmap, confusion matrices, leakage) | CODED + TESTED (synthetic) | `pu/figures.py` |
| Real Paderborn data verified (file counts, channels, rates) | BLOCKED: download not yet run | - |
| Measured P1/P2/P3 results | BLOCKED: needs data | `results/` |

## OB2 - Sensor quality and robust diagnosis under degradation

| Evidence item | Status | Artefact |
|---|---|---|
| 7 label-free quality indicators per sensor | CODED + TESTED (synthetic) | `pu/features.py::quality` |
| Assessor fitted on clean training windows only (no labels) | CODED + TESTED (synthetic) | `pu/models.py::QualityAssessor` |
| Seen faults (noise x3, dropout, intermittent x2, gain/offset x2); withheld (clipping x2, spikes x2, stuck x2) | CODED + TESTED (synthetic) | `pu/features.py::corrupt` |
| Clean false-flag rate, detection per family/severity, wrong flags on healthy sensor | CODED + TESTED (synthetic) | `pu/figures.py::quality_table` |
| Gate ablations: quality-only, confidence-only, no mask | CODED + TESTED (synthetic) | `pu/models.py` |
| Measured OB2 results | BLOCKED: needs data | - |

## OB3 - Explainable health decision layer, dashboard, logging, reports

| Evidence item | Status | Artefact |
|---|---|---|
| Policy: WARNING 2-of-6 > 0.5; INSPECT 4-of-6 > 0.8, latched until acknowledged; 6 quiet windows clear; SENSOR_FAULT suspends diagnosis | CODED + TESTED (synthetic) | `health/engine.py` |
| Exact linear explanations + deletion faithfulness check | CODED + TESTED (synthetic) | `health/engine.py`, `health/validate.py` |
| SQLite history, CSV + HTML report | CODED + TESTED (synthetic) | `health/store.py` |
| Portable (numpy) model export, checked against sklearn | CODED + TESTED (synthetic): max prob diff 4.6e-7 | `pu/export_demo.py` |
| Streamlit dashboard | CODED, not yet launched (Streamlit can't be installed in the cloud workspace) | `dashboard/app.py` |
| Dashboard launched on laptop with real held-out data; screenshots | NOT STARTED (needs data) | - |

## OB4 - ESP32 rig with rig-specific anomaly detection (parallel track)

| Evidence item | Status | Artefact |
|---|---|---|
| Firmware (ADXL345 SPI 3.2 kHz FIFO, ACS712 ADC-DMA 10->5 kHz, Hall RPM, CRC framing) | WRITTEN, not compiled (no toolchain here), not run on hardware | `rig/firmware/ivhm_rig/ivhm_rig.ino` |
| Host parser/logger, timing acceptance test | CODED + TESTED (synthetic byte stream; corrupted link correctly FAILS) | `rig/rigio.py`, `rig/logger.py` |
| Healthy-baseline Mahalanobis detector (fit H1, threshold H2, test H3/H4 + faults) | CODED + TESTED (synthetic) | `rig/detector.py` |
| Components purchased / rig assembled / sessions recorded | NOT STARTED | - |

## Change log
- 2026-10-19: audit; pipeline, health layer, dashboard and rig host software rebuilt from the approved spec; all plumbing tests pass on synthetic fixtures.
