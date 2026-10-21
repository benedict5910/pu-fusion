# IVHM test rig – engineering design review (22 Oct 2026)

**Scope.**
- **Selected:** the physical OB4 rig and how it connects to the existing AI/IVHM software.
- **Decision basis:** measurement quality, safety, repeatability, compatibility and cost; delivery speed is not a criterion.
- **No purchases are made by this document.** The 28 Oct review is a reporting milestone.
- **Fixed constraints:**
  - The frozen benchmark results (OB1/OB2/OB3) remain the baseline evidence.
  - Benchmark and rig models stay separate unless transfer is validated independently.
  - Rev. 3 (`HARDWARE_FINAL_2026-10-22.md`) is superseded as a design. Its datasheet checks remain valid.

## 1. What the rig must do

1. Produce **repeatable** vibration and current data from a **replaceable test bearing** under **known, adjustable operating conditions**.
   - Speed and radial load, mirroring Paderborn's speed / torque / radial-force conditions.
   - Enables bearing-disjoint, session-disjoint and condition-hold-out (P3-style) evaluation on our own data.
2. Support **seeded faults** that are physically meaningful:
   - unbalance;
   - misalignment;
   - outer-race surface damage;
   - contamination;
   - lubricant loss.
3. Support **real sensor faults** (loose mount, intermittent cable), so OB2 is validated on physical faults rather than synthetic corruption only.
4. Stay low-voltage, current-limited and fully guarded. No mains wiring built by the team.
5. Reuse the existing pipeline (ESP32 → framed serial → host timing check → features → health layer → dashboard) with the fewest code changes.

## 2. Alternatives considered

| | A. Small gearmotor (rev. 3) | **B. Direct-drive brushed DC on a current-limited lab supply** (preferred) | C. Inverter-fed motor (BLDC/PMSM + driver, or induction motor + VFD) |
|---|---|---|---|
| Example | Pololu #3225 25D 4.4:1, 12 V, stall 1.8 A | 775-class 12 V brushed DC, Ø5 mm shaft, flexible coupling, speed set by supply voltage | 57 mm BLDC + Hall driver; or 0.18 kW 3-phase motor + VFD |
| Signal quality | Gear-mesh lines (≈ 1–2 kHz) fall inside the bearing-resonance band and contaminate envelope analysis | No gears; motor isolated by the coupling; brush/commutation lines are known and narrow | Closest to Paderborn (inverter-fed motor, phase current), but PWM switching noise needs careful filtering |
| Repeatability | Fixed speed (one condition) | 2 speeds × 2 radial loads = 4 conditions; speed held by CV supply and measured by tach | Best (closed-loop speed) |
| Safety | Good (≤ 1.8 A) | Good: the supply's documented CC limit bounds every current, including start and stall; ≤ 30 V | BLDC: good if documented (≈ ₹11k motor alone at DigiKey). Induction + VFD: 230 V mains, earthing, enclosure; not for a student-built rig |
| Documentation | Full (Pololu) | Supply: full. Motor: no manufacturer stall current, so it is **characterised by measurement** under the CC limit before use | Generic BLDC kits undocumented; documented ones exceed budget |
| Cost (drive only) | ≈ ₹4,600 | ≈ ₹600–1,200 (motor) + lab supply (dept) | ≈ ₹12k–20k+ |
| Verdict | Rejected: gear mesh and single condition limit the science | **Selected** | Rejected for budget/safety now; recorded as a future extension |

**Why B is defensible on safety:** in rev. 3 the concern was whether an adapter could carry an
undocumented start current. In B that question goes away. A lab supply in **constant-current
mode** physically limits the current to the set value (e.g. 2.0 A). The safety evidence is the
supply's documented CC regulation, not the motor's datasheet. The motor's no-load current,
speed–voltage curve and locked-rotor current at low voltage are then **measured** inside that limit
(stage S4) and recorded.

## 3. Preferred architecture (design B)

```
[Lab DC supply, CV/CC, current limit 2 A] ─ fuse T2A ─ E-stop (latching) ─ current sensor ─ motor
      (floating output, documented)                                                       │
                                                               jaw coupling 5→8 mm
                                                                                          │
 base plate (steel 6 mm, on rubber feet, clamped)                                         │
   ├─ support bearing 1 (KP08) ── 8 mm shaft ── support bearing 2 (KP08) ── TEST BEARING (608-2Z)
   │                                   │                                    in floating Al housing
   │                             unbalance disc                             ├─ IIS3DWB (radial, load axis)
   │                                                                        ├─ dead-weight radial load (2–5 kg)
   │                                                                        └─ anti-rotation pin
   ├─ Hall/optical tach on disc (1 ppr)
   └─ polycarbonate guard over coupling, shaft, disc, test housing
ESP32 (USB to laptop) ← SPI ← IIS3DWB · ADC ← current sensor (isolated) · GPIO ← tach
```

### 3.1 Motor and drive
- **Motor:** 775-class 12 V brushed DC, ball-bearing front, **Ø5 mm shaft**.
  - Prefer a ≈ 3,000–4,500 rpm @ 12 V winding, so 900 and 1,500 rpm need about 3.5–6 V (well above brush drop). A 6,000 rpm part (Robu RS775SH, ₹585) is acceptable.
  - Buy two of the same model; one is a spare.
- **Supply:** the department's regulated DC supply (≥ 30 V / ≥ 3 A, CV/CC, floating output). If none is available, buy a documented linear CV/CC supply (e.g. Korad KA3005DS, ₹7,999 at Probots, currently out of stock).
  - **No PWM:** speed is set by voltage, which keeps switching ripple out of both the current and vibration channels.
- **Protection chain:**
  1. CC limit 2.0 A (primary).
  2. Fuse T2A in series (wiring backup).
  3. Latching mushroom **E-stop** in the motor loop.
  4. Guard fitted before power.
  5. Supply output OFF during any work.
- **Operating points:**
  - 900 and 1,500 rpm (matching Paderborn's N09/N15 speeds).
  - 2 kg and 5 kg dead weight (≈ 20 / 50 N).
  - 4 conditions in total.
- **Speed stability:** target ±1 % over 10 min at fixed voltage and load (measured, S4). Because speed is open-loop, every window carries measured rpm and features are speed-normalised (already done via `rig_features`).

### 3.2 Shaft mechanics and guarding
- **Shaft:** 8 mm hardened rod, 200 mm, on 2 × KP08 support blocks.
- **Test bearing:** 608-2Z (7 balls, d = 3.969 mm, pitch Ø ≈ 15 mm; already the default in `RigConfig`).
  - Held in a **machined aluminium floating housing**: 22 mm H7 bore, M3 tapped sensor seat, load hook, anti-rotation slot.
  - Bearing changes are repeatable: the housing is re-seated against a stop, and fastener torque is recorded.
- **Defect frequencies** at 1,500 rpm (25 Hz): BPFO ≈ 64 Hz, BPFI ≈ 111 Hz.
  - Envelope analysis needs the structural resonance band (≈ 1.5–6 kHz on small housings).
  - This is the main reason for the accelerometer upgrade (§4.2).
- **Alignment:**
  - Shim the motor until coupling misalignment is below the coupling's rated limits.
  - Use a dial indicator if the lab has one; otherwise a straight-edge and feeler gauge.
  - Record shim stacks so misalignment can later be used as a *controlled* fault.
- **Unbalance disc:**
  - Aluminium Ø60 mm with tapped holes at r = 20 mm.
  - Masses: M4 screws (≈ 1–3 g).
  - At 1,500 rpm, 3 g at 20 mm gives ≈ 1.5 N.
- **Guard:**
  - Polycarbonate box on an aluminium-angle frame, screwed to the base.
  - Slot for the sensor cable; no openings near rotating parts.
- **Isolation rule (unchanged):** supply OFF and E-stop pressed → shaft stopped → guard off → work → guard on → power.

### 3.3 Base and repeatability
- **Base:** 6 mm steel plate (≈ 300 × 200 mm) on four rubber feet, clamped to the bench.
- **Stiffness:** a stiff, heavy base keeps structural resonances repeatable across sessions.
- **Recorded every session:** fastener torques, shim stacks, weight, voltage, measured rpm, bearing serial (bearings marked), ambient temperature.

## 4. Sensors

### 4.1 Current sensing: is ACS712 adequate, and is an upgrade justified?

| | ACS712ELCTR-05B (have) | **ACS724LLCTR-2P5AB** (Pololu #4040) | INA240A2 + 20 mΩ shunt |
|---|---|---|---|
| Sensitivity | 185 mV/A | 800 mV/A (4.3×) | 1 V/A (gain 50) |
| Noise (datasheet) | 21 mV p-p at 2 kHz BW ≈ 0.11 A p-p (≈ 18 mA rms) | 150 µA/√Hz → ≈ 6.7 mA rms at 2 kHz | Input noise negligible; ESP32 ADC (~2–3 mV rms) dominates → ≈ 2–3 mA rms |
| Isolation | Yes | Yes | **No.** Motor return shares ESP32/laptop ground |
| Range | ±5 A | ±2.5 A (fits the 2 A CC limit) | Set by shunt |
| Firmware change | – | None (same analog path; config only) | None (analog), but grounding redesign |
| Cost | ₹129 | ₹951 + shipping (DigiKey Marketplace) | ₹681 (Evelta breakout) + shunt |

**Effective noise at the ESP32 pin** (ESP32 ADC noise of ~2–3 LSB rms included):
- ACS712 via the ×0.6 divider: ≈ 25 mA rms.
- ACS724 via the ×0.6 divider (≈ 480 mV/A): ≈ 8 mA rms, about **3× better**.

**Signal to be measured:** the 775's running current (≈ 0.5–1.5 A) with its commutation ripple (narrow lines at slots × rpm), plus slow load changes from radial load, friction and unbalance.

**Assessment:**
- **Bearing-fault signatures are not expected to be measurable in DC-motor current.** On Paderborn, with 64 kHz phase current from an inverter-fed PMSM, our current-only model reached only macro-F1 0.32.
- The rig's current channel is therefore justified for three things:
  - load and speed context;
  - mechanical-drag anomalies (contamination, lubricant loss, misalignment);
  - the OB2 redundancy and reliability demonstration.
- It is **not** expected to support current-based bearing diagnosis.

**Decision (staged, no premature purchase):**
- **Start with the ACS712** you already budget for.
- Stage S5 measures its noise floor against the commutation ripple and the load response.
- Buy the **ACS724 (#4040)** only if S5 shows the load or drag signals are within 3× of the ACS712 noise floor.
- INA240 is not selected: its gain in SNR does not outweigh losing galvanic isolation between the motor loop and the laptop.

### 4.2 Accelerometer: upgrade justified

| | ADXL345 (current firmware) | **IIS3DWB** (ST, STEVAL-MKI208V1K adapter) |
|---|---|---|
| Purpose | General-purpose tilt/motion | **Designed for vibration monitoring** |
| Output rate / bandwidth | 3,200 Hz / 1,600 Hz | 26,667 Hz / flat to 6 kHz (±3 dB 6.3 kHz) |
| Noise density | 290 µg/√Hz (X/Y) at 100 Hz ODR; rises ≈ √2 per ODR doubling | 60 µg/√Hz (single-axis mode, X/Y) |
| Resolution | 3.9 mg/LSB (13-bit full-res) | 0.061–0.488 mg/LSB (16-bit) |
| Interface | SPI ≤ 5 MHz, 32-sample FIFO | SPI ≤ 10 MHz, 3 KB FIFO |
| Sensor resonance | – | 6.9–7.0 kHz |
| Cost | ₹269 | ₹3,163 + GST (DigiKey India, 40 in stock) |

**Justification:**
- With ADXL345 the envelope band is capped at 300–1,500 Hz, which is below typical housing resonances. The fault impulses that make bearing defects detectable are therefore mostly lost.
- The IIS3DWB lifts the usable band to ~6 kHz, with ≈ 5× lower noise density and 16-bit resolution.
- This is the single largest measurement-quality improvement available, and it is within budget.
- The **ADXL345 is kept** as the reference/fallback sensor (existing firmware path), on the support housing for bring-up and cross-checks.

**Sampling fidelity and link budget:**
- Single-axis mode on the load axis at 26.667 kHz × 16 bit = 53.3 kB/s.
- Plus current at 5 kHz (10 kB/s), plus frame headers: ≈ 65 kB/s.
- That is ≈ 70 % of the 921,600-baud link (92 kB/s), within the CP2102's capability.
- The timing self-test (`rig_check_timing.py`) must PASS with zero gaps at this rate.
- Fallback if it does not: decimate by 2 in firmware with a proper FIR before sending. Bandwidth is still ≈ 6 kHz after decimation to 13.3 kHz.

**Mounting:**
- The adapter PCB is bonded with thin rigid epoxy to a 10 mm aluminium cube, which is screwed (M3, torque recorded) into the tapped seat on the test housing, sensing axis = load axis.
- No tape, no hot glue, no long flexible standoffs.
- Cable: short, shielded/twisted, strain-relieved to the base so cable whip does not load the sensor.
- **Acceptance:** a tap test on the housing, with the IIS3DWB and the ADXL345 side by side. No spurious mount resonance below 6 kHz, and the same results after a remount (spectral peaks within ±5 %).

**Synchronization:**
- All streams are sampled by one ESP32 and stamped with its µs clock at FIFO/DMA read. The existing host clock fit (index ↔ µs pairs) measures each stream's true rate, drift, jitter and gaps.
- Cross-stream alignment is bounded by the FIFO read interval (≤ 1 ms). That is adequate for 0.5–1 s feature windows.
- Planned improvement within scope: timestamp **each tach edge** (instead of counting pulses per frame). This gives per-revolution speed and enables computed order tracking (angle-domain resampling), so fault orders stay aligned under the small speed drift of an open-loop drive.

### 4.3 Speed
- The A3144 Hall sensor, 1 ppr, is kept; its edges are timestamped (4.2).
- In S4 it is validated once against a handheld optical tachometer (lab or ≈ ₹1,200).

## 5. Firmware and host changes (all within OB4 scope)

1. **IIS3DWB driver:**
   - SPI 8–10 MHz, single-axis, FIFO watermark reads.
   - Selected by a compile-time switch; the ADXL345 path is unchanged.
2. **Frame protocol:**
   - Version bump RIG2 → RIG3, carrying the nominal vibration rate and sensor ID.
   - The parser keeps RIG2 support; new tests are added.
3. **Tach edge timestamps** in the frame.
4. **Host:**
   - New `RigConfig` fields: `fs_vib = 26667`, `vib_band = (1500, 6000)`, `vib_g_per_lsb`, sensor ID.
   - Current scaling for ACS724 if adopted.
   - Timing thresholds unchanged (rate within 5 % / 0.5 %, zero gaps).
5. **No change to benchmark models, features used for OB1, or frozen results.** The rig detector (`RigAnomalyDetector`) is trained only on rig sessions.

## 6. Cost-efficient BOM (preferred design)

Prices were checked 22 Oct where a link is given; the rest are estimates. Probots and Robu prices include GST. DigiKey prices exclude GST (+18 %, shown) and exclude Marketplace shipping.

| Group | Item | Qty | ≈ ₹ (incl. GST) | Source |
|---|---|---|---|---|
| Electronics | ESP32 30-pin CP2102 (ESP-WROOM-32) | 1 | 499 | [Probots](https://probots.co.in/esp32-30-pin-cp2102-development-board.html) |
| | **IIS3DWB adapter STEVAL-MKI208V1K** | 1 | 3,732 | [DigiKey India](https://www.digikey.in/en/products/detail/stmicroelectronics/STEVAL-MKI208V1K/11501282) |
| | ADXL345 GY-291 (reference/fallback) | 1 | 269 | [Robu](https://robu.in/product/adxl345-tripple-axis-accelerometer-board/) |
| | ACS712-05B (stage S5 decides on an upgrade) | 1 | 129 | [Probots](https://probots.co.in/current-sensor-ac-dc-module-with-analog-output-acs712-5a.html) |
| | A3144 + magnets | 1 | 110 | [Probots](https://probots.co.in/hall-effect-sensor-magnet-detector-switch-for-arduino-a3144e-44e.html) |
| | Passives (10k/15k, 10 nF), perfboard, headers, shielded cable, connectors | – | 600 | local |
| Drive | 775-class 12 V brushed DC, Ø5 mm (identical pair) | 2 | 1,200 | e.g. [Robu RS775SH](https://stg.robu.in/product/rs775sh-12v-6000rpm-high-speed-dc-motor-dia-5-shaft-length-10mm) |
| | Fuse holder + T2A fuses; latching mushroom E-stop (DC-rated) | – | 400 | local |
| | Lab DC supply 30 V / 5 A CV/CC | – | **0 (dept)** | buy only if the dept has none (Korad KA3005DS ₹7,999) |
| Mechanics | Jaw coupling 5 → 8 mm | 1 | 434 | [Probots](https://probots.co.in/5mm-to-8mm-flexible-spider-shaft-coupler.html) |
| | 8 mm rod 400 mm (cut to 200) | 1 | 369 | [Probots](https://probots.co.in/400-mm-length-chrome-plated-smooth-rod-diameter-8-mm.html) |
| | KP08 support blocks | 2 | 198 | [Probots](https://probots.co.in/kp08-8mm-pillow-block-insert-bearing-zinc-alloy.html) |
| | **SKF 608-2Z test bearings**, pack of 10 (one batch) | 1 | 1,040 | [Moglix](https://www.moglix.com/skf-8x22x7mm-deep-groove-ball-bearing-608-2z-pack-of-10/mp/msno5wn2ndgr51) (availability "on request") |
| | Aluminium test housing (machined), sensor cube, unbalance disc | – | 1,750 | college workshop (material + machining, estimate) |
| | Dead weights 2 kg + 5 kg + hanger | – | 500 | local |
| | Steel base plate 6 mm, rubber feet, clamps | – | 900 | local fabricator |
| | Polycarbonate guard + aluminium angle | – | 800 | local |
| | Fasteners, shim set (0.1/0.2/0.5 mm), threadlocker | – | 400 | local |
| Fault seeding | Electric engraver with diamond tips | 1 | 1,000 | local / online |
| **Total** | | | **≈ ₹14,330** | within ₹10–15k, excluding a lab supply |

**Conditional additions (justify with S-stage data before buying):**
- ACS724 carrier #4040: ≈ ₹1,122 + shipping, if S5 fails.
- Second pack of 608-2Z: ₹1,040, if fault experiments need ≥ 4 bearings per class.
- Optical tachometer: ≈ ₹1,200, if the lab has none.
- Lab supply: ₹7,999, only if the department cannot lend one.

## 7. Staged build and validation (each stage has a pass gate; no stage starts before the previous passes)

| Stage | Work | Pass gate (recorded as evidence) |
|---|---|---|
| **S0 Design freeze** | Freeze this design. Write the **rig experiment protocol** before any data: conditions, bearings per class, session plan, splits, metrics, thresholds | Protocol committed to git with a date, before the first recording |
| **S1 Electronics bench** (existing firmware) | ESP32 + ADXL345 + ACS712 + Hall on the bench | `rig_check_timing.py` 120 s PASS; noise floors recorded; current zero calibrated; tach counts a magnet |
| **S2 IIS3DWB integration** | Driver, RIG3 framing, host parser, unit tests (RIG2 still passing) | Timing PASS at 26.667 kHz, 0 gaps, 10 min; measured noise density within 2× of the datasheet; all existing tests pass |
| **S3 Mechanical build (unpowered)** | Base, supports, coupling, housing, disc, guard; alignment by shims | Shaft turns freely by hand; misalignment within coupling rating; disc run-out recorded; guard complete; photos |
| **S4 Powered commissioning** | Supply CV with CC 2 A, E-stop tested. Motor characterisation: no-load current vs V; rpm vs V; locked-rotor current at ≤ 2 V under CC; 30 min thermal run | E-stop cuts power; speed stable ±1 % over 10 min; motor case temperature rise < 40 K; Hall rpm matches optical tach within 1 % |
| **S5 Signal-quality acceptance** | Tap test (mount response); remount repeatability; current-channel SNR vs commutation ripple and load steps | No mount resonance < 6 kHz; healthy-spectrum repeatability after remount (band RMS within ±10 %); **ACS724 decision** recorded |
| **S6 Healthy baseline** | ≥ 4 healthy bearings × 4 conditions × 2 sessions (remount between sessions; randomised order) | Every session's `acquisition_checks` PASS; metadata complete |
| **S7 Seeded faults** | Unbalance (2 masses); misalignment (2 shim levels); outer-race damage by engraver (≥ 3 bearings); contamination (≥ 2); lubricant removal (≥ 2). **Real sensor faults:** loose accelerometer, intermittent cable, sensor disconnect | Each fault session PASSES acquisition checks; fault bearings photographed and measured before use |
| **S8 Evaluation** | Rig detector trained on healthy sessions only. Thresholds set on a separate healthy calibration set. Test is **bearing-disjoint and session-disjoint**. Condition hold-out (train 3 conditions, test the 4th) | Results reported as measured, with bearing-level CIs; no threshold or feature change after seeing the test sessions |
| **S9 Dashboard integration** | Live mode with the rig model; provenance shown; physical sensor-fault demo | Live run reproduces S8 behaviour on a held-out bearing; events and exports correct |

## 8. Strengthening the research results (no leakage, no tuning on held-out bearings)

All of the below are new, pre-registered analyses. The frozen 21 Oct results stay as baseline v1 and are always reported alongside.

1. **Complete P1 as designed.**
   - Four folds were skipped only because the 12-bearing subset lacked a class.
   - Download the remaining Paderborn archives (same Zenodo mirror, MD5-verified) and run the **full 15-fold P1** with the frozen code version (git tag).
   - Test-fold membership is defined before running.
   - This increases training bearings (≈ 20 incl. artificial damages) and gives proper per-class test coverage.
2. **Bearing-level statistics.**
   - Report bearing-level metrics with bootstrap confidence intervals over bearings, instead of treating overlapping runs as independent.
   - The Wilcoxon results on 11 non-independent runs overstate evidence (already documented).
3. **False alarms on unlike healthy bearings (K002/K004).**
   - Calibrate decision thresholds with leave-one-healthy-bearing-out *inside the training fold* only.
   - Report healthy-bearing false-alarm rate per bearing.
   - No threshold may be chosen using test bearings.
4. **OB2 flatness-bound defect.**
   - Fix the 25 % range padding (`ReliabilityAssessor`) by selecting the padding rule with inner cross-validation on training bearings.
   - Re-evaluate once on held-out bearings and report as v2 next to frozen v1.
5. **Physical sensor faults** (rig S7). Validate OB2 detectors on real loose-mount, cable and disconnect faults. This is the first non-synthetic test of OB2.
6. **Rig dataset protocol.** Bearing- and session-disjoint splits, randomised recording order, remounts, and a hold-out condition, mirroring P1/P3 on our own hardware.
7. **Transfer (separate, optional).**
   - A Paderborn-trained model tested on rig data is reported **only as a transfer experiment**.
   - Rig labels are never used to select benchmark models, and the reverse.
   - Different sensors, sampling rates and bearings mean no transfer claim without this test.

## 9. Integration with the IVHM dashboard

| Layer | Benchmark path (frozen) | Rig path |
|---|---|---|
| Data | Paderborn .mat (64 kHz) | ESP32 RIG2/RIG3 frames (IIS3DWB 26.7 kHz, current 5 kHz, tach edges) |
| Quality (OB2) | ReliabilityAssessor fitted on benchmark training bearings | ReliabilityAssessor fitted on rig healthy sessions |
| Diagnosis | Gated fusion classifier (healthy / OR / IR) | `RigAnomalyDetector` (healthy-baseline anomaly score); fault *type* only once enough labelled rig faults exist |
| Health layer (OB3) | **Shared** HealthTracker / HealthPolicy (incl. the 22 Oct safety fixes) | Same |
| Store / reports | SQLite HealthStore, CSV/HTML | Same, plus session metadata (sensor IDs, rates, condition, bearing serial) |
| Dashboard | "Benchmark replay" | "Rig – live" and "Rig – simulated" (labelled SIMULATED) |

- **Model separation:** the two model files are never mixed.
  - `models/demo_models.pkl` (benchmark) vs `models/rig_models.pkl` (rig).
  - Each model file already records what it was trained on; the dashboard header shows that provenance.
- **Shared logic:** the health layer, explanations of sensor reliability, acknowledgement rules and logging are common to both paths. Every safety fix applies to both.

## 10. Decisions requested from the team
1. Confirm a department lab DC supply (CV/CC, floating output) can be assigned to the rig. Otherwise approve ₹7,999.
2. Confirm college workshop access for the aluminium test housing, sensor cube and disc.
3. Approve design B and the IIS3DWB upgrade. The ACS724 is decided by S5 data.
