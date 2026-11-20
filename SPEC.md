# Project specification (v1, 15 Oct 2026)

> Scope and IVHM system design are superseded by **[IVHM_SPEC.md](IVHM_SPEC.md)**. The research protocol in §4 still applies.

**Verdict: MODIFY.** The core idea is sound and buildable in 8 weeks, but four things in the original brief would not survive a viva:

1. **"Vehicle component" in the title.** The data come from a laboratory electromechanical drive test rig with 6203 ball bearings. Nothing in the project touches a vehicle. Drop "vehicle"; you may mention electric drives (including EV traction drives) only as motivation.
2. **"Reliability-aware fusion" is not novel by itself.** Missing-aware, reliability-guided multi-sensor bearing fusion was published in 2026 (Yan et al., MAEFF), and reliability-weighted decision fusion in 2025 (Jo et al.). The contribution has to be narrower (below).
3. **Leakage is the real problem with this dataset.** One audit of 55 Paderborn papers judged 10 likely affected by leakage and only 6 handling it properly (Wheat & Mohrenschildt, 2024). The one vibration+current fusion study we found that ran a bearing-disjoint check reported Macro-F1 ≈ 0.55 and **no** fusion benefit over vibration-only (Kaya & Jobani, 2026). Expect modest absolute numbers; that is fine if the protocol is clean.
4. **Objective 1 (hardware prototype) cannot be a validation source.** The rig is a demonstrator, evaluated only on its own labelled sessions. No Paderborn-trained model is claimed to work on it.

Labels used below: **[V]** verified from an official or primary source today; **[R]** read only as abstract/metadata; **[D]** our design decision; **[H]** hypothesis to test.

---

## 1. Title and research gap

**Title:** *Reliability-Gated Vibration–Current Fusion for Bearing Fault Diagnosis under Sensor Degradation: A Bearing-Disjoint Study on the Paderborn Dataset*

**Gap statement.** Vibration–current fusion on the Paderborn dataset has mostly been evaluated on clean signals, often with splits that reuse the same physical bearings in training and test. The one bearing-disjoint check we found showed no fusion benefit on clean data [R: Kaya & Jobani 2026]. Missing-aware, reliability-guided fusion exists, but the work we found evaluates heavier deep mixture-of-experts models on other datasets (Ottawa, KAIST) [R: Yan et al. 2026]. **We do not know whether a lightweight, label-free signal-quality gate makes vibration–current fusion more robust than conventional fusion when one sensor degrades, under bearing-disjoint evaluation, and for degradation types the model never saw in training.**

**Contribution (one, narrow):** a controlled, leakage-free test of that question: per-window late-fusion weights computed from label-free sensor-health indicators, compared with single-sensor, early, averaged and stacked fusion trained on *identical* corruption-augmented data, reported with calibration, false-alarm and miss rates, and with three corruption families withheld from training.

**What we will not claim:** a new architecture; first-ever reliability-aware fusion; predictive maintenance; remaining useful life; vehicle diagnosis; field or hardware accuracy.

**Hypotheses [H]** (each may be rejected; a negative result is reportable):
- H1: On clean data, bearing-disjoint, fusion ≈ vibration-only (replication of Kaya & Jobani).
- H2: Under single-sensor degradation, gated fusion > early fusion and > late average in Macro-F1.
- H3: H2 still holds for the withheld corruption families (clipping, spikes, stuck sensor).
- H4: Gated fusion has a lower false-alarm rate under degradation than early fusion.

## 2. Objectives (refined)

1. Build a leakage-controlled benchmark on the Paderborn data: verified labels, bearing-disjoint splits, per-window physics-informed features, and single-sensor plus three conventional fusion baselines.
2. Implement and test a lightweight reliability-gated late fusion that weights vibration and current experts per window from label-free signal-quality indicators.
3. Measure robustness under controlled sensor degradation (seen and withheld types): Macro-F1, worst case, calibration (ECE, NLL, Brier), false-alarm and miss rates, and replay alarm latency.
4. Deliver a replay dashboard on held-out bearings and a low-cost ESP32 vibration+current rig demonstrator evaluated only on its own labelled sessions.

## 3. Closest related work and differentiation

| Work | What it did | How we differ |
|---|---|---|
| Kaya & Jobani 2026, *Sensors* 26:3829 [V abstract] | PU vibration+current; early, dual-branch and gated fusion; condition holdout; bearing-disjoint check: early fusion 0.5485 vs vibration 0.5616 Macro-F1, p = 0.20 | We test fusion **under sensor degradation**, with label-free quality gating, as the primary question; bearing-disjoint is our main protocol, not an add-on |
| Yan et al. 2026, *Ann. Oper. Res.* (MAEFF) [R] | Missing-aware adaptive expert fusion, reliability-guided; Ottawa + KAIST datasets; sensor dropout, gaps, point-wise loss | Different datasets and no vibration–motor-current pairing on PU; ours is a small linear gate on interpretable quality indicators, plus withheld corruption types, calibration and alarm metrics |
| Jo et al. 2025, *Sensors* 25:6887 [R] | Reliability-aware decision weighting from each sensor's classification performance (acoustic + vibration) | Their weights are per-sensor and static; ours are per window and react to the current signal state |
| Alam et al. 2025, arXiv 2502.17524 [R] | PU multimodal 1D-CNN with transfer learning | Clean data; no degradation study |
| Arxiv 2509.22267 (2025); Wheat & Mohrenschildt 2024 [R] | Leakage in bearing diagnosis; bearing-wise splitting; number of training bearings decisive | We adopt their protocol; we do not claim it |
| Lin et al. 2025, *Adv. Eng. Inform.* 68:103595; Zhao et al. 2024, *IEEE TIM* 73 [title only, from MAEFF references] | Missing-signal multi-sensor fusion; current-aided vibration fusion | **Must read in week 1** before the novelty statement is finalised |

## 4. Dataset and evaluation protocol

**Paderborn KAt bearing dataset** [V official pages, 15 Oct 2026]
- 32 bearings of type 6203: 6 healthy, 12 artificial damage, 14 real damage from accelerated lifetime tests.
- Synchronously measured motor currents and vibration, plus speed, torque, radial load and temperature.
- 4 operating conditions: N15_M07_F10 (1500 rpm, 0.7 Nm, 1000 N), N09_M07_F10 (900 rpm), N15_M01_F10 (0.1 Nm), N15_M07_F04 (400 N).
- 20 measurements × 4 s per bearing per condition, one MATLAB file each (e.g. `N15_M07_F10_KA01_1.mat`).
- Download: 32 RAR archives of 152–178 MB (≈ 5.1 GB) at groups.uni-paderborn.de/kat/BearingDataCenter/.
- **Licence: CC BY-NC 4.0.** Non-commercial academic use; cite Lessmeier et al. (PHME 2016) and the KAt-DataCenter.
- 64 kHz for vibration and currents is reported by Lessmeier et al. and many papers; the loader reads the channel's own raster field, so confirm on the first files.

**Labels [D].** 3 classes by damage location: healthy / outer race / inner race. KB23, KB24, KB27 (combined damage) are **excluded**, not relabelled. Labels follow Lessmeier et al. Tables 4–6 and **must be cross-checked against the fact sheets inside the archives in week 1.**

**Unit of analysis [D].** 0.5 s non-overlapping windows (8 per file). Every window carries its bearing ID; splits are by bearing.

**Features [D]** (per window only, no dataset statistics):
- Vibration (31): kurtosis, skewness, crest, shape; envelope-spectrum peaks at 1–3 × BPFO, BPFI and shaft frequency in dB over the local median (2–20 kHz band); 16 relative log-band powers; envelope kurtosis; high-frequency energy ratio.
- Current (30, averaged over 2 phases): fundamental frequency; phase imbalance; harmonics 2–7 relative to the fundamental; sidebands f₁ ± k·BPFO/BPFI; 12 relative log-band powers; residual kurtosis and power after notching the fundamental.
- Quality indicators (7 per sensor, label-free): NaN fraction, flat-line fraction, clipping fraction, log RMS, spectral flatness, spike level, spectral dominance.

**Protocols [D]**
- **P1 (primary): bearing-disjoint.** Test pool = 6 healthy + 5 real OR + 6 real IR. 5 repeats × 3 folds; each fold tests on ~2 healthy, ~2 OR, 2 IR unseen bearings. Artificial bearings are training-only.
- **P2: artificial → real.** Train on artificial + 3 healthy; test on real damage + the other 3 healthy; swap.
- **P3 (diagnostic): bearing- and condition-disjoint.** P1 with one operating condition held out.
- **Leaky reference (teaching figure only):** a random window split, to show how much leakage inflates scores.
- Normalisation is fit inside each training fold (sklearn pipeline). Gate and stacker weights are fit on out-of-fold expert outputs from bearing-grouped inner folds.

**Models [D]** (same expert, same training rows, same augmentation)
- Expert: standardise → clip ±8 → logistic regression (C = 0.1, balanced). Gradient-boosting variant as a robustness check.
- Baselines: vibration-only, current-only, early fusion (concatenation), late average, late stacked (static learned weights).
- **Proposed:** p = w_vib·p_vib + w_cur·p_cur with w = softmax(zA + b), where z = both sensors' quality indicators + each expert's entropy and max probability. A and b are fit by L2-penalised maximum likelihood. A hard mask zeroes a plainly dead sensor.
- Ablations: quality-only gate, confidence-only gate, no hard mask.
- Optional week-5 extra: a small 1D-CNN (≈ 70k parameters) under the same protocol, only if the core is finished.

**Degradation [D].** Training augmentation uses one random corruption per window, from noise (SNR 20 to −5 dB), dropout, intermittent loss (5–50 %) and gain/offset error. Test grid: every family × severity × sensor, plus both-sensor noise. **Clipping, impulsive spikes and stuck-at-value are never used in training.**

**Metrics [D].**
- **Primary:** Macro-F1 averaged over the single-sensor degradation grid, P1, reported separately for seen and withheld families.
- **Secondary:** clean Macro-F1; worst-case Macro-F1; balanced accuracy; ECE, NLL and Brier; false-alarm rate (healthy windows flagged faulty) and miss rate.
- **Replay alarm:** a 2-of-3 window rule on concatenated healthy → faulty windows gives latency in seconds and false-alarm events per hour.
- **Statistics:** mean ± sd over 15 runs; the main test is paired across the 5 repeats (fold-averaged), with Wilcoxon over 15 folds as secondary (folds overlap, so p-values are optimistic); bearing-level bootstrap CIs; Holm correction across baselines.

**Hyperparameters are frozen now** (window 0.5 s, C = 0.1, gate L2 = 0.01, alarm 2-of-3 at 0.5) and are not tuned on test bearings.

## 5. Architecture

```
Paderborn .mat ──► loader (by channel name) ──► 0.5 s windows ──► features + quality ─┐
                                   corruption injector (seeded) ──────────────────────┤
                                                                                       ▼
       vibration expert ──► p_vib ─┐                                    feature cache (.npz)
       current expert   ──► p_cur ─┼─► gate(quality, confidence) ──► fused p ──► k-of-n alarm
                                   └─────────────────────────────────────────────► dashboard (Streamlit)
ESP32 rig (demo): ADXL345 + ACS712 ──► USB serial ──► same feature code (rig-specific bands) ──► rig-only model
```

- Software: Python 3.11+, NumPy, SciPy, scikit-learn; Streamlit for the dashboard; PyTorch only for the optional CNN.
- The rig cannot sample at 64 kHz: an ADXL345 tops out at 3.2 kHz output rate, so resonance-band envelope analysis does not transfer. Rig features use a lower band, and the rig model is trained and tested on rig data only.

## 6. Eight-week plan (A = data/features, B = models/experiments, C = rig/dashboard)

| Wk | A | B | C |
|---|---|---|---|
| 1 | Download starter subset; verify labels against fact sheets; confirm sample rates | Read Lin 2025 and Zhao 2024; finalise novelty text; P1 run on starter subset | Order rig parts |
| 2 | Full download; full feature build | Baselines on P1 + leaky-split figure | Assemble rig; ESP32 firmware (serial streaming) |
| 3 | Feature sanity plots per class and condition | Fusion models, gated model, ablations on P1 | Rig data-collection protocol |
| 4 | — | **Full P1/P2/P3 runs, statistics, results frozen** | Rig: collect healthy and seeded-fault sessions |
| 5 | Error analysis per bearing | Optional 1D-CNN; HGB expert check | Train/test rig model on separate sessions |
| 6 | Figures | Inference timing on a laptop CPU | Dashboard on held-out bearings |
| 7 | Report | Report | Demo video |
| 8 | Buffer, viva rehearsal | | |

## 7. Bill of materials (rig, estimates to verify at purchase)

| Item | ₹ |
|---|---|
| ESP32-WROOM dev board | 400–500 |
| ADXL345 accelerometer (SPI) | 250–350 |
| ACS712-5A current sensor (or INA219 for DC) | 150–250 |
| 12 V 775 DC motor | 400–600 |
| Motor driver (BTS7960) | 400–500 |
| 8–12 mm shaft, 2 pillow-block bearings, 2 spare bearings | 700–1,000 |
| Flexible coupling | 200–300 |
| IR/Hall speed sensor | 80–150 |
| 12 V 10 A SMPS | 600–800 |
| Base plate, mounts, fasteners, wiring | 800–1,200 |
| **Total** | **≈ 4,000–5,650** (≈ 6,500 with 15 % contingency) |

Seeded faults: one spare bearing with an outer-race scratch (engraving tool, eye protection) and one contaminated with fine grit. Mains-powered parts go only through a certified enclosed SMPS.

## 8. Top five engineering risks

| Risk | Mitigation |
|---|---|
| Bearing-disjoint scores are low and noisy (only 6 healthy bearings) | Physics-based features; per-bearing error analysis; P2 as a second view; the claim is the **robustness difference**, not absolute accuracy |
| Label or file problems (combined damage, unreadable files) | Verify fact sheets in week 1; skipped files are logged, never guessed; KB* excluded |
| Gate overfits to the corruptions used in training | Out-of-fold fitting; withheld corruption families; three ablations |
| Feature extraction time (≈ 100k windows, ~80 ms each) | Feature cache; `--jobs`; starter subset first |
| Rig gives misleading demo numbers (sampling limits, domain gap) | Rig model trained and tested only on rig sessions, split by session; no transfer claim |

## References

- Lessmeier, C., Kimotho, J. K., Zimmer, D., & Sextro, W. (2016). Condition monitoring of bearing damage in electromechanical drive systems by using motor current signals of electric motors: A benchmark data set for data-driven classification. *PHM Society European Conference*.
- KAt-DataCenter, Paderborn University: https://mb.uni-paderborn.de/en/kat/research/bearing-datacenter/data-sets-and-download (licence and data description verified 15 Oct 2026).
- Kaya, Ş. M., & Jobani, A. E. (2026). IoT-driven robust bearing fault diagnosis for induction motors under operating-condition shift. *Sensors, 26*(12), 3829. https://doi.org/10.3390/s26123829
- Yan, L., Du, S., Wang, S., Luo, H., Li, S., & Chen, X. (2026). MAEFF: Missing-aware adaptive expert fusion framework for multi-sensor bearing fault diagnosis. *Annals of Operations Research*. https://doi.org/10.1007/s10479-026-07381-w
- Jo, H., Yoo, Y., Dai, M., & Ban, S.-W. (2025). An upper-probability-based softmax ensemble model for multi-sensor bearing fault diagnosis. *Sensors, 25*(22), 6887. https://doi.org/10.3390/s25226887
- Wheat, L., & von Mohrenschildt, M. (2024). *Impact of data leakage in vibration signals used for bearing fault diagnosis*. McMaster University. https://macsphere.mcmaster.ca/handle/11375/31458
- *Towards a more realistic evaluation of machine learning models for bearing fault diagnosis* (2025). arXiv:2509.22267.
- Alam et al. (2025). *Multimodal bearing fault classification under variable conditions: A 1D CNN with transfer learning*. arXiv:2502.17524.
- Lin, T., Ren, Z., Huang, K., Zhu, Y., & Karimi, H. R. (2025). A novel multi-sensor information fusion method for fault diagnosis of rotating machinery with missing signals. *Advanced Engineering Informatics, 68*, 103595. (not yet read)
- Zhao, R., Jiang, G., He, Q., Jin, X., & Xie, P. (2024). Current-aided vibration fusion network for fault diagnosis in electromechanical drive system. *IEEE TIM, 73*. (not yet read)
