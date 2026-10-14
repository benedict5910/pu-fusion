# IVHM project specification (v2.1, 15 Oct 2026)

Supersedes the scope in `SPEC.md`; the research protocol in `SPEC.md` §4 is unchanged.

## Verdict: MODIFY

Keep the bearing-fusion study as the research core and wrap it in a small, honest IVHM loop: **sense → check sensor health → diagnose → decide → log and report**. Five of the six proposed deliverables stay (some trimmed). OBD-II and any "digital twin" claim are cut.

What remains unverified: **no Paderborn experiment has been run yet.** The data server is blocked from this build environment (`curl: (56) CONNECT tunnel failed, response 403`). Every number produced so far is from synthetic or simulated signals and is labelled as such. Step one in week 1 is `python scripts/run_all.py` on a student laptop.

## Title

**Sensor-Fault-Tolerant Bearing Health Monitoring for Electric Drive Components: Reliability-Gated Vibration–Current Fusion in an IVHM Prototype**

Why this wording: IVHM is named, the scope is a component (bearing in an electric drive), and the research idea (sensor-fault tolerance) is in the title. It does not claim vehicle-level diagnosis.

## Problem statement

IVHM systems decide maintenance actions from sensor data, but the sensors themselves fail: they drop out, saturate, pick up interference or freeze. A diagnostic model that silently trusts a broken sensor produces false alarms or misses faults. We test whether a lightweight, label-free sensor-health gate keeps vibration–current bearing diagnosis reliable when one sensor degrades, evaluated on bearings never seen in training. We then use the same sensor-health logic in a low-cost monitoring prototype that turns evidence into transparent maintenance states.

## Research gap (as verified so far)

- Vibration–current fusion on the Paderborn data exists. The one bearing-disjoint check we found showed **no** fusion gain on clean data (Kaya & Jobani, *Sensors* 2026).
- Missing-aware, reliability-guided fusion exists on other datasets with deeper models (Yan et al., MAEFF, 2026). Reliability-weighted decision fusion with static, per-sensor weights also exists (Jo et al., *Sensors* 2025).
- Leakage is common in Paderborn studies (Wheat & von Mohrenschildt 2024; arXiv:2509.22267).
- **Not yet checked:** Lin et al. 2025 (*Adv. Eng. Inform.* 68:103595, missing-signal fusion) and Zhao et al. 2024 (*IEEE TIM*, current-aided vibration fusion). Both publisher pages refused automated access. One student must read them through the library in week 1 before the novelty statement is final.

**Contribution (unchanged, narrow).** A controlled, bearing-disjoint test of label-free, per-window quality gating against single-sensor, early, averaged and stacked fusion. All models are trained on identical corruption-augmented data. Clipping, spikes and stuck sensors are withheld from training. Results are reported with calibration, false-alarm and miss rates. The IVHM prototype is an engineering deliverable, not a second research claim.

The required topics are covered as follows:

| Topic | Where it is handled |
|---|---|
| Clipping, spikes, stuck sensors | Test only; never used in training |
| Missing data | Dropout and intermittent loss in the corruption grid; NaN or link loss on the rig |
| Operating-condition change | Protocol P3 (bearings and condition both held out) |
| Bearing-disjoint evaluation | P1 (primary) and P2 |
| False alarms, calibration | Reported for every model and corruption |
| Detection latency | Replay of healthy-to-faulty windows with a 2-of-3 rule; on the rig, time to first non-NORMAL state |

## Four objectives

1. Benchmark vibration-only, current-only and three conventional fusion models against reliability-gated fusion on the Paderborn data. Use bearing-disjoint protocols and controlled sensor degradation, including types withheld from training.
2. Assess sensor reliability without labels, using indicators that work unchanged on both the benchmark data and the rig after refitting on each platform's healthy data.
3. Translate evidence into maintenance states (Normal / Warning / Inspect / Sensor fault) with explanations and evidence-based recommendations, logged and exportable.
4. Demonstrate the loop live on a ₹5–6k ESP32 motor rig, with a rig-trained healthy-baseline detector evaluated by recording session.

## Feasibility audit and decisions

Three kinds of claim are kept strictly separate throughout:

- **Validated benchmark diagnosis:** Paderborn, bearing-disjoint, statistics reported.
- **Live hardware measurement:** rig signals, sensor health and anomaly evidence; nothing is claimed beyond what is measured.
- **Hardware fault diagnosis:** needs rig-specific training and session-split validation. We do only anomaly detection here (healthy baseline), not fault-type classification.

### Mandatory

**A. Robust fault diagnosis (Paderborn)**
- Feasibility: high.
- Hardware: laptop.
- Software: existing pipeline.
- Data: Paderborn, about 5.1 GB.
- Effort: about 1 week of compute and analysis.
- Cost: ₹0.
- Validation: P1, P2, P3 and the leaky reference.
- Risk: no gain is found. That is reportable.
- Role: **research**.

**B. Rig monitoring (vibration, current, speed)**
- Feasibility: medium.
- Hardware: ESP32, ADXL345, ACS712, Hall sensor.
- Software: firmware plus parser (written).
- Data: rig sessions.
- Effort: 2–3 weeks for one student.
- Cost: about ₹5.3k.
- Validation: measured sample rates, checksum error count, a known-frequency check.
- Risk: ADC nonlinearity, FIFO overruns.
- Role: demonstration.

**B'. Rig anomaly detection**
- Feasibility: medium.
- Hardware and software: rig plus `RigAnomalyDetector`.
- Data: at least 3 healthy and at least 2 fault sessions.
- Effort: 1 week.
- Cost: included in B.
- Validation: session-disjoint false alarms, detection and latency.
- Risk: a seeded fault too weak to detect. The unbalance mass is the guaranteed-visible case.
- Role: demonstration with its own small evaluation.

**C. IVHM dashboard (extended Streamlit)**
- Feasibility: high.
- Software: Streamlit over a tested engine.
- Effort: 1 week.
- Cost: ₹0.
- Validation: engine unit tests. The UI flow has been exercised with a stand-in, not real Streamlit.
- Risk: polish eats time. The dashboard stays a thin layer.
- Role: demonstration.

**D. Explanations**
- Feasibility: high.
- Method: exact linear contributions, which equal linear SHAP for standardised linear models, so no SHAP dependency is needed. Gate drivers show why a sensor was trusted. Faithfulness is checked with a deletion test, reported separately from confidence.
- Effort: done.
- Validation: unit test shows contributions reconstruct the logits exactly.
- Risk: explanations look plausible but are uninformative. The faithfulness score exposes this.
- Role: supports research (interpretability of the gate).

**E. Health states and recommendations**
- Feasibility: high.
- Method: rule-based with persistence (k-of-n windows), a latched INSPECT state that needs operator acknowledgement, and a SENSOR_FAULT state. Thresholds are fixed in advance.
- No remaining-useful-life estimate: the data hold discrete damage states, not degradation trajectories.
- Validation: unit tests, plus replay false-alarm events per hour.
- Role: IVHM decision layer.

**F. Fault history and reports**
- Method: SQLite (stdlib), CSV and HTML report.
- Effort: done.
- Validation: unit tests.
- Role: demonstration.

### Optional (only after week 5, only if the mandatory items are done)

- **Temperature (DS18B20) and bus voltage.** Logged and displayed only (lubrication or overheating trend; supply sag). No model or rule uses them. Cost about ₹200; already in the firmware.
- **Component schematic** in the dashboard, coloured by state and sensor health. It is a picture, **not a digital twin**. Done.
- **Gradient-boosting or small 1D-CNN expert** under the same protocol, as a robustness check.
- **Rig fault-type classification.** Only with at least 2 independent seeded bearings per class, split by session and bearing. Otherwise report anomaly detection only.

### Excluded

- **OBD-II.** An ELM327 dongle (about ₹400–900) plus python-OBD could read engine RPM, speed, coolant temperature and stored trouble codes, with PID support varying by car. But it supplies no bearing, vibration or motor-current data, needs a car, and would add an unrelated data stream. That would mix a vehicle's data with a bench rig's as if they were one system. No research value, real time cost.
- **"Digital twin".** No physical model of the rig is calibrated or updated from data, so the term would be a false claim.
- **Remaining-useful-life prediction.** No run-to-failure trajectories with motor current exist in this dataset.
- **Paderborn model applied to rig signals.** Different machine, sensors and sampling rates (64 kHz vs 3.2 kHz). Incompatible by design.
- **LLM explanations.** Not needed; templated, evidence-based text is more faithful.

## Architecture

```
               ┌──────────── Benchmark path (validated) ────────────┐
Paderborn .mat → windows → features + quality → gated fusion ──┐     │
               └─────────────────────────────────────────────────┘     │
                                                               ▼     │
ESP32 rig ─serial frames─→ parser → windows → rig features ─→ healthy-baseline
 (vib, current,  (checksum,    (gaps → NaN)   + quality       anomaly detector
  rpm, temp, V)   resync)                                          │
                                                                   ▼
                            ReliabilityAssessor (label-free, refit per platform)
                                                                   ▼
                    HealthTracker: NORMAL / WARNING / INSPECT (latched) / SENSOR_FAULT
                                                                   ▼
                    explanations · recommendations · SQLite log · CSV/HTML report
                                                                   ▼
                    Streamlit: Benchmark replay | Rig simulated | Rig live
```

`MonitorEngine` runs this per window for both paths. The two diagnosers share an interface but never share models.

## Rig sensors and sampling

| Signal | Sensor | Rate | Purpose | Notes |
|---|---|---|---|---|
| Vibration (radial) | ADXL345, SPI mode 3 at **4 MHz**, ±16 g full-resolution, 3.9 mg/LSB typ. (3.5–4.3) | 3200 Hz output (1600 Hz bandwidth) | Bearing defect and unbalance signatures | For the 608 bearing at 1500–3000 rpm, BPFO ≈ 64–129 Hz and BPFI ≈ 111–222 Hz, with harmonics inside the band. MPU6050 rejected (1 kHz accelerometer rate). |
| Motor current | ACS712-05B via 10k/20k divider to GPIO34 (ADC1_CH6) | ADC DMA at 10 kHz per channel, averaged in pairs to **5000 Hz** | Load and commutation ripple; second modality | Zero offset calibrated with the motor off (`--calibrate-zero`). ESP32 ADC nonlinearity accepted for anomaly use. |
| Speed | A3144 Hall sensor + magnet | 4 updates/s, rate from the measured frame time | Fault frequencies; operating-condition context | Required for the frequency-based features. |
| Temperature | DS18B20 on bearing housing | 1 Hz | Trend only | Optional; logged and displayed. |
| Bus voltage | 100k/22k divider to GPIO35 (ADC1_CH7) | Same DMA scan, averaged per frame | Separates supply sag and motor-off from faults | Optional; logged and displayed. |

### Hardware corrections verified on 15 Oct 2026

Checked against the ADXL345 datasheet and the ESP32 Arduino core 3.3.12 source. The firmware compiles (arduino-cli, `esp32:esp32:esp32`: 22 % flash, 18 % RAM, no warnings in the sketch). **It has not yet been run on hardware.**

1. **ADXL345 SPI clock: 4 MHz.**
   - The datasheet requires at least 2 MHz SPI for 3200 Hz or 1600 Hz output, or samples are missed; the maximum is 5 MHz at 100 pF.
   - The earlier sketch used 5 MHz, the absolute limit, on breadboard wiring. 4 MHz keeps margin both ways.
2. **ADXL345 FIFO reads.**
   - At least 5 µs must pass between reading one FIFO entry and the next read. The firmware now waits explicitly.
   - Each entry is popped by one 6-byte multi-byte burst.
   - The INT_SOURCE overrun bit is checked on every drain and counted.
   - DEVID is checked at boot (0xE5) and reported in every frame.
3. **ADXL345 rate accuracy is not specified in the datasheet.**
   - The true output rate is therefore **measured, not assumed**. Every frame carries an (index, time) reference per stream.
   - The host fits the true rate and computes features at the measured rate.
   - `scripts/rig_check_timing.py` reports the rate error in ppm.
4. **Aliasing.** The ADXL345 has no documented anti-aliasing filter. Bearing resonances above 1.6 kHz can fold into the band. This is acceptable for anomaly detection against the rig's own baseline; it is one more reason Paderborn models are never applied to the rig.
5. **Current sampling replaced.**
   - The old design was a busy-wait `analogRead()` task at priority 3 on core 1. It would starve the Arduino `loop()` task (priority 1, same core) that sends the serial frames.
   - The new design uses the ESP-IDF continuous ADC (DMA). On ESP32-classic it supports **20 kHz minimum** total rate, on ADC1 only.
   - The scan alternates current and bus voltage at 10 kHz each. Current is averaged in pairs to 5 kHz.
   - Bus voltage moved into the same scan, because one-shot `analogRead` and DMA cannot share ADC1.
   - DMA pool overflows are counted by callback, and samples tagged with an unexpected channel are counted.
6. **Synchronisation.**
   - Vibration (ADXL345 oscillator) and current (ESP32 clock) run on independent clocks.
   - Each frame now sends, for each stream, the absolute index of its first sample plus a consistent (index, time) pair for the newest sample.
   - The host fits each stream's clock and cuts both streams on the **same 0.5 s time grid**. A few-percent ADXL345 rate error cannot slowly misalign the two sensors.
   - Residual alignment error is the reference jitter: about 2 ms for the vibration FIFO drain, up to 12.8 ms for the current DMA frame. The least-squares fit reduces this.
7. **Dropped samples are explicit.** Ring-buffer drops, ADXL345 overruns, DMA overflows, checksum errors and lost frames all show up as index gaps (filled with NaN, reported as link loss) or as counters. Nothing is silently skipped.
8. **Link budget.** About 4.1 kB per 0.25 s frame (16.4 kB/s) against about 92 kB/s at 921 600 baud, using a 16 kB TX buffer.

**Bring-up acceptance test (week 2).** Run `python scripts/rig_check_timing.py --port COMx --seconds 120`. It must PASS:
- no checksum errors, sample gaps or device overruns;
- vibration rate within 5 % of nominal and current rate within 0.5 %;
- ADXL345 and ADC detected.

Record the measured rates in the report.

## Bill of materials (INR, estimates to confirm at purchase)

| Item | ₹ |
|---|---|
| ESP32-WROOM dev board | 450 |
| ADXL345 module | 300 |
| ACS712-05B module | 200 |
| A3144 Hall sensor + magnets | 80 |
| DS18B20 (probe type) | 150 |
| Resistors and dividers | 50 |
| 12 V 775 DC motor | 500 |
| BTS7960 motor driver (or PWM speed controller) | 450 |
| 8 mm shaft + 2 KP08 pillow blocks | 600 |
| 4 spare 608 bearings (2 for seeded faults) | 200 |
| Flexible coupling | 250 |
| Unbalance disc + bolts | 150 |
| 12 V 10 A SMPS (enclosed, certified) | 750 |
| Base plate, mounts, guard | 600 |
| Wires, connectors, perfboard, USB cable | 550 |
| **Total** | **≈ 5,280** |
| With 15 % contingency | **≈ 6,100** |

Seeded faults:
- **Outer-race scratch** on one 608 bearing (engraving tool; eye protection).
- **Grit contamination** on another 608 bearing.
- **Unbalance** from a bolt on the disc.

Safety: a guard over the rotating shaft. No exposed mains wiring.

## Team responsibilities

- **Student 1 (research/ML):** Paderborn runs, statistics, ablations, results chapter.
- **Student 2 (IVHM software):** health policy, explanations, dashboard, logging and reports, integration tests.
- **Student 3 (hardware):** rig build, firmware flashing and verification, calibration, session recording, rig evaluation.

## Eight-week schedule (weeks 1–4 put core ML first)

| Wk | Student 1 | Student 2 | Student 3 |
|---|---|---|---|
| 1 | `run_all.py` on the starter subset; check labels against fact sheets; confirm 64 kHz from the files; read Lin 2025 and Zhao 2024 | Run dashboard in benchmark mode on starter models; review recommendation texts | Order parts; bench-test sensors on breadboard |
| 2 | `run_all.py --subset all`; leaky-vs-disjoint figure | Explanation faithfulness summary over test bearings | Assemble rig; flash firmware; **`rig_check_timing.py` must PASS**; zero calibration |
| 3 | P3 and ablations; HGB expert check | Replay false alarms per hour per model; report polish | Record healthy sessions H1–H4 on different days |
| 4 | **Freeze benchmark results and statistics** | Integrate rig mode with real sessions | Record seeded-fault sessions; run `rig_train.py` |
| 5 | Write methods and results | Dashboard with all three modes on real models | Live-link robustness (unplug and replug, frame loss) |
| 6 | Optional extras if ahead | Demo rehearsal script | Rig evaluation write-up |
| 7 | Report, poster, video | Report, poster, video | Report, poster, video |
| 8 | Buffer, viva rehearsal | | |

## Evaluation methodology

- **Benchmark:** exactly as `SPEC.md` §4.
  - Primary metric: Macro-F1 over the single-sensor degradation grid, P1, with seen and withheld families reported separately.
  - Secondary metrics: clean Macro-F1, worst case, ECE, NLL, Brier, false-alarm rate, miss rate, replay latency.
  - Statistics: paired over 5 repeats; Wilcoxon over 15 folds as secondary (optimistic, since folds overlap); Holm correction.
  - The leaky split is reported only to show inflation.
- **Health layer:** policy thresholds fixed in advance (0.5 / 0.8, 2 and 4 of the last 6 windows, 6 quiet windows to clear a warning). Report state-level false-alarm events per hour on held-out healthy bearings and time to INSPECT on held-out faulty bearings.
- **Explanations:** faithfulness (deletion drop) reported next to confidence. The two are never merged.
- **Sensor-quality detector:** validated on its own, without fault labels (`scripts/eval_quality.py`). It is fitted on clean windows of training bearings only. On held-out bearings it reports the false-flag rate on clean data, the detection rate per corruption family and severity, and the cross-flag rate on the healthy sensor.
- **Rig:** session-disjoint (fit H1, threshold H2, test H3+ and fault sessions). Report window alarm rate, whether the state ever left NORMAL, time to first non-NORMAL, and rig sample-rate and checksum statistics. No accuracy claims transfer between platforms.

## Demo scenario (about 5 minutes)

1. **Benchmark replay** of an unseen real-damage bearing.
   - The state rises WARNING → INSPECT, with outer- or inner-race evidence and gate drivers shown.
   - Inject vibration dropout: the vibration sensor shows *failed*, the weight moves to current, and the recommendation notes reduced redundancy.
   - Inject clipping (withheld from training) and show the effect.
2. **Results slide** with real P1 numbers only. A placeholder until they exist.
3. **Live rig.**
   - Healthy run: NORMAL.
   - Unplug the accelerometer: sensor fault flagged, no bearing alarm.
   - Bolt on the unbalance mass: anomaly evidence rises to WARNING, then INSPECT.
   - The seeded-bearing sessions are shown as recorded replays, because a bearing swap takes minutes.
4. **History tab:** export the HTML report with state changes and recommendations.

## Five biggest risks

| Risk | Mitigation |
|---|---|
| Real results show no gain from gating (H2 rejected) | Pre-registered hypotheses; a negative result with a clean protocol is still a valid finding; the IVHM prototype stands either way |
| Bearing-disjoint scores are low and noisy (only 6 healthy bearings) | Per-bearing analysis; P2 as a second view; the claim is the robustness difference, not absolute accuracy |
| Firmware timing (ADXL345 FIFO overruns, ADC jitter, clock drift) | DMA-paced ADC; explicit 5 µs FIFO gaps; per-stream sample indices make every loss visible; measured rates used for features; `rig_check_timing.py` acceptance test; fall back to 1600 Hz vibration if overruns persist |
| Seeded bearing faults too weak to detect on the rig | Unbalance as the guaranteed-visible case; report detection per session honestly; anomaly detection, not classification |
| Time lost to integration or polish | Engine is unit-tested; dashboard is thin; optional items locked until week 5; OBD-II excluded |
