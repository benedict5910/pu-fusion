# OB1 / OB2 completion report – bearing portion (15 Nov 2026)

**Verdict.** The bearing portions of OB1 and OB2 are complete: the experiments are reproducible,
leakage-audited and regression-checked, sensor-failure handling is verified end to end, and the
limitations are documented. The gearbox portion is **not** done (blocked by data; section 6).

Detailed reports: `docs/OB1_OB2_FULL_2026-11-15.md` (full-dataset run),
`results/gating_research/README.md` (gating research),
`results/gating_research/final_validation/README.md` (final validation).

## 1. Data

Paderborn bearing data set, Zenodo mirror (record 15845309), 28 archives, each MD5-verified.
28 bearings (6 healthy, 11 artificial damage, 11 real damage), 2,240 recordings, 4 operating
conditions; vibration and two phase currents at 64 kHz, 0.5 s windows: 17,877 clean, 17,877
augmented, 85,120 corrupted windows (38 corruption settings). KA08 is missing (not on the mirror;
training-only bearing). KB23 / KB24 / KB27 (combined damage) are excluded by design.
`data/features_full.npz`, SHA-256 `770b5e72…afad`.

## 2. Methods

* **Task:** healthy / outer-race / inner-race from hand-crafted features (31 vibration, 30 current)
  with logistic-regression experts per sensor.
* **Protocol (P1):** bearing-disjoint, 5 repeats × 3 folds = 15 runs. Each run tests 5–6 bearings
  the model never saw (2 per class, real damage only) and trains on the other 22–23. 17 distinct
  test bearings. Training uses clean + augmented windows of training bearings; augmentation uses
  only the "seen" corruption families (noise, dropout, intermittent, gain). Clipping, spikes and
  stuck are withheld for testing. Also run: P2 (artificial → real), P3 (unseen operating condition),
  and a deliberately leaky split as a reference.
* **OB1 models:** vibration-only, current-only, early fusion, late average, stacked fusion, learned
  reliability gate (`gated_both`) and three gate ablations.
* **OB2 detector (v2):** label-free sensor-quality check against each sensor's own first clean
  recording; configuration chosen per fold on training bearings.
* **OB2 fusion:** `gated_v2` (exclude every flagged sensor; abstain if both flagged) and the final
  `v3_strength`: each sensor weighted by its expert's out-of-fold skill in its current detector
  state (ok / degraded); a dead sensor gets weight 0; diagnosis is suspended (SENSOR_FAULT) only when
  both sensors are dead. One parameter, chosen per fold by inner bearing-disjoint validation on
  training bearings.
* **Statistics:** paired Wilcoxon over runs (n = 15) and over bearings (n = 17), Holm-corrected.
  Abstained windows count as wrong.

## 3. Results

### OB1 – diagnosis on unseen bearings (macro-F1, 15 runs)

| Model | Clean | Seen corruptions | Withheld corruptions |
|---|---|---|---|
| vib_only | 0.618 ± 0.109 | 0.589 | 0.566 |
| cur_only | 0.386 ± 0.158 | 0.339 | 0.293 |
| early_fusion | 0.604 ± 0.115 | 0.578 | 0.522 |
| late_average | 0.624 ± 0.114 | 0.597 | 0.520 |
| late_stacked | 0.565 ± 0.126 | 0.534 | 0.422 |
| gated_both | 0.605 ± 0.126 | 0.583 | 0.537 |

* No fusion model is significantly better than vibration alone.
* A leaky (non-bearing-disjoint) split scores 0.86–0.89: about 0.27 of apparent performance is
  leakage, which the protocol removes.
* P2 (artificial → real): 0.59–0.62 clean. P3 (unseen condition): vibration-only 0.593, others lower.
* Outer race is the hardest class (F1 ≈ 0.47). Healthy bearing K002 is misdiagnosed by every model
  and K005 in 55–83 % of windows; they cause most of the 32–36 % false-alarm rate.

### OB2 – sensor reliability

Detector (held-out bearings): gain errors 98–100 % detected (original detector 2–5 %), vibration
noise at −5 / 0 / 5 dB 100 / 100 / 84 %, withheld spikes 31–100 %; clean false flags 7 % on
vibration, 2.7 % on current.

Fusion (repetitions ≥ 2; macro-F1 / coverage):

| Model | Clean | Seen | Withheld | Mild corruption | Vibration dead | Both dead |
|---|---|---|---|---|---|---|
| vib_only | 0.618 | 0.589 | 0.566 | 0.614 | 0.175 | diagnoses anyway |
| late_average | 0.623 | 0.597 | 0.519 | 0.599 | 0.389 | diagnoses anyway (47 % fault class) |
| gated_both | 0.604 | 0.583 | 0.536 | 0.580 | 0.393 | withheld |
| gated_v2 | 0.605 | 0.480 (cov. 0.90) | 0.509 (cov. 0.95) | 0.519 | 0.382 | withheld |
| v3_strength | 0.613 | 0.594 | 0.577 | 0.609 | 0.393 | withheld, SENSOR_FAULT 100 % |

* Hard gating (`gated_v2`) is significantly **worse** than the baselines under seen corruptions: it
  discards mildly corrupted vibration that is still more informative than clean current.
* `v3_strength` removes that regression (+0.114 seen vs `gated_v2`, p_holm 0.004) and handles dead
  sensors, but is **not significantly different from vibration-only** (clean −0.005, seen +0.005,
  withheld +0.011; p_holm ≥ 0.58) or from the original gate.
* Sensor-failure verification (25,840 both-dead windows, 17 held-out bearings, 15 folds; plus 456
  recordings from raw signals through the monitoring engine): diagnosis withheld in 100 %, no fault
  class issued, SENSOR_FAULT raised in 100 % from a non-latched state. Single-sensor failures keep
  full coverage on the surviving sensor.

**The v3 results are exploratory.** The rule was designed after analysing failures on this same
test set; only its parameter was tuned leakage-free. They are not an independent confirmation.

## 4. Verification

| Check | Result |
|---|---|
| Leakage audit (8 checks, full data, re-run) | 8 / 8 PASS |
| Stored predictions reproduced (5 models × 297,070 rows) | 0 mismatches, max \|Δp\| = 0 |
| Frozen parameter selection reproduced | 15 / 15 folds |
| Raw-signal features vs stored features | identical (16,416 vectors) |
| Statistics recomputed | identical to stored results |
| Unit tests | 75 run, 67 passed, 8 skipped (Streamlit absent), 0 failed |
| Historical results (`results/starter`, `repro`, `ob2_v2`, `ob_final`, `full_2026-11-15`) | untouched |
| Dashboard / deployment | untouched; `v3_strength` is **not** wired into the dashboard |

## 5. Limitations

* Absolute accuracy is modest (macro-F1 ≈ 0.62 on unseen bearings) and the false-alarm rate is
  high (≈ 0.33), dominated by two healthy bearings.
* The research hypothesis "reliability-gated fusion improves diagnosis" is not supported; the
  supported claim is safe behaviour under sensor failure at no accuracy cost.
* With vibration dead, the current-only fallback is weak (macro-F1 0.39, 54 % false alarms).
* v3 results exploratory (above); 17 test bearings; several models compared.
* Corruptions are synthetic; "dead" = zeros or constant. No real sensor faults.
* Logistic-regression experts only; one data set; KA08 missing.
* A latched INSPECT stays displayed during a sensor outage (diagnosis suspended) by design.

## 6. Remaining for gearbox validation (not started here)

* **Data:** only 3 MCC5-THU demo recordings are available; the full set (or at least the earlier
  12-recording pilot) must be downloaded to `E:\ivhm-data` and checksummed.
* **Protocol:** define a leakage-resistant split for MCC5-THU (it has no multiple physical units per
  fault like Paderborn, so hold out operating profiles / recordings) and run the leakage audit.
* **Experiments:** repeat OB1 (single-sensor vs fusion of motor and gearbox accelerometers) and OB2
  (v2 detector, `v3_strength`, sensor-failure tests) under that protocol with the same metrics.
* **Independent confirmation:** the gearbox data would be the first test of `v3_strength` on data
  that did not influence its design.
* Until then, gearbox claims rest on the pilot / demo only.

## 7. Reproduction

Commands for each stage are listed at the end of the three detailed reports. Result directories:
`results/full_2026-11-15/`, `results/gating_research/`, `results/gating_research/final_validation/`
(copies on the project PC under `E:\ivhm-data\results\`). Code is on the local branch
`ob1-ob2-completion` (new files uncommitted, nothing pushed).
