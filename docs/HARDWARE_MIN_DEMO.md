# OB4 – Minimum hardware for a live-monitoring demonstration (rev. 2, 22 Oct 2026)

**Scope.** This is the smallest rig that shows live monitoring with the existing firmware
(`firmware/rig_esp32/rig_esp32.ino`) and host code (`src/pufusion/rig.py`, `scripts/rig_*.py`,
dashboard mode "Rig - live"). Nothing here changes the frozen OB1/OB2 results or the OB3 health
layer. No new features.

**Rev. 2 changes** (safety review of 22 Oct):
- The supply is now a certified, enclosed 12 V adapter instead of the mains-wired SMPS.
- The motor is now a 6000 rpm 775 with a published Ø5 mm shaft. The only 3000 rpm 775 in stock lists a 2.3 mm shaft.
- The unbalance mass is reduced to keep the force small at that speed.
- The fuse is re-sized to T3.15 A.
- The current divider is now 10k/15k (0.6). The old 10k/20k divider could exceed 3.3 V at the ESP32 pin.
- The rotating parts are guarded, and power-isolation rules are made explicit.

**Demo it supports:**
1. A healthy run stays NORMAL.
2. Pulling the vibration sensor's data wire → the reliability layer flags it, and diagnosis continues on current only.
3. With the motor isolated, an unbalance mass is fitted → WARNING / INSPECT.
4. Acknowledging the alert is logged, and the dashboard does not claim the component is healthy.

**Excluded:** seeded bearing faults, speed control (PWM), temperature, bus voltage.

## 1. Procurement list

"Checked" prices were read from the seller's page on 22 Oct 2026, incl. GST. All other prices are estimates.
Stock changes daily. Probots has Bangalore pickup (Nagarabhavi / Koramangala).

| # | Item (exact spec) | Qty | ≈ ₹ | Source / status |
|---|---|---|---|---|
| 1 | ESP32 dev board, classic ESP32 (WROOM-32), CP2102 USB, 38-pin, USB-C | 1 | 469 | Robu, checked, in stock (very low) |
| 2 | **GY-291 ADXL345** (3.3 V regulator, **no MOSFET level shifters**: they can limit 4 MHz SPI) | 1 + 1 spare | 199–300 each | Robu ₹199 module advertises "level shifting", so confirm the board before buying |
| 3 | ACS712-05B current module (±5 A, 185 mV/A, 5 V) | 1 | 129 | Probots, checked, in stock |
| 4 | A3144 Hall switch + 2 small neodymium magnets | 1 + 2 | 59 + ~50 | Probots, checked (sensor) / estimate (magnets) |
| 5 | Resistors ¼ W 1 %: **10 kΩ ×4, 15 kΩ ×2**; ceramic capacitor 10 nF ×2 | – | ~50 | estimate |
| 6 | **RS775SH 12 V DC motor, 6000 rpm no-load, Ø5 mm × 10 mm shaft**; no-load current 1 A, rated current ≤ 3 A | 1 | 585 | Robu, checked, in stock |
| 7 | 775 motor L-bracket + M4 screws | 1 | ~120 | estimate |
| 8 | Flexible spider coupling **5 mm × 8 mm** bore, aluminium | 1 | 434 | Probots, checked, in stock (Robu ₹270, out of stock) |
| 9 | 8 mm chrome-plated steel rod (cut to 150–200 mm, ends deburred) | 1 | 369 (400 mm) | Probots, checked, in stock |
| 10 | KP08 pillow block, 8 mm bore, centre height 15 mm | 2 | 198 | Probots, checked, in stock |
| 11 | Unbalance disc: 8 mm-bore aluminium flange coupling or pulley with set screw and tapped/through holes; **M3×6 screws + nyloc nuts** as masses | 1 + 4 | ~150 | estimate |
| 12 | **Certified 12 V 5 A enclosed adapter**: Pro-Range, BIS, short-circuit and overload protection, 100–240 V input, 5.5 × 2.5 mm plug | 1 | 1,199 | Robu, checked, in stock |
| 13 | Female DC jack **5.5 × 2.5 mm** to screw terminal | 1 | ~40 | estimate; must match the 2.5 mm plug |
| 14 | Inline 5×20 mm fuse holder + **T3.15 A slow-blow** fuses | 1 + 3 | ~60 | estimate |
| 15 | Toggle/rocker switch rated ≥ 5 A DC | 1 | ~40 | estimate |
| 16 | Base: 18 mm plywood or ≥ 5 mm aluminium, ≈ 300 × 150 mm; spacer blocks for the KP08s; M4 screws, washers, nuts; rubber feet | – | ~300 | estimate |
| 17 | Guard: **polycarbonate** (not acrylic, which can shatter) cover over the coupling, shaft and disc, screwed to the base; wire slot on the sensor side | 1 | ~300 | estimate |
| 18 | Wiring: jumpers, 18 AWG for the motor loop, screw terminals, small perfboard, heat-shrink, cable ties | – | ~300 | estimate |
| 19 | USB-C data cable (skip if one is on hand) | 1 | ~150 | estimate |
| | **Total** (checked items ≈ ₹3,640; estimates ≈ ₹1,560) | | **≈ 5,200** | ≈ ₹6,000 with 15 % contingency |

**Tool required for acceptance:** a digital multimeter with a 10 A DC range (≈ ₹500 if the lab has none).

Not bought for the minimum demo: PWM driver, DS18B20, bus-voltage divider, spare 608 bearings, mains SMPS.

## 2. Electrical design and checks

### 2.1 Power, start current and fuse coordination
- **Supply:** a certified enclosed 12 V 5 A adapter. No exposed mains terminals anywhere on the rig.
- **Motor loop:** adapter → fuse T3.15 A → switch → ACS712 IP+ → IP− → motor → adapter negative.
- **Motor current (RS775SH 6000 rpm):** the seller gives 1 A no-load and ≤ 3 A rated. **The seller gives no stall current.**
  Datasheet values for comparable 12 V 770/775 motors are 14.1 A stall (4550 rpm variant) and 56.9 A stall (9700 rpm variant). So expect about 20–40 A stall, far above the adapter's 5 A.
- **What happens at start:** the adapter limits the start surge, so the motor speeds up more slowly or the adapter's overload protection trips and restarts. With only two bearings and a small disc to turn, it should start, **but this must be shown on the bench** (acceptance E1).
- **Fuse coordination, in order of rating:**
  - Steady current ≈ 1–1.5 A (expected).
  - Fuse T3.15 A. It survives the adapter-limited start surge (≤ ~1.6–2.2× its rating for < 1 s) and opens on a sustained overload.
  - Adapter 5 A, with its own overload and short-circuit protection. This is the primary protection.
  - Wiring is 18 AWG (≥ 10 A).
  - The ACS712 primary is rated well above the adapter's maximum output.
  - If the adapter cannot start the motor reliably, that is an **unresolved item** (see §6). Do not substitute a larger supply, a bigger fuse or a mains SMPS without a new review.

### 2.2 ACS712 output, ESP32 ADC limits, divider
- **Sensor output:** the ACS712 is powered from the ESP32's 5 V pin (USB VBUS, ≈ 4.6–5.25 V). Its output is Vcc/2 + 0.185 V/A and can swing almost to Vcc at overload.
- **Old divider (10k/20k, ×0.667):** could put up to ≈ 3.5 V on GPIO34. That is above the 3.3 V supply and close to the 3.6 V absolute maximum. **Rejected.**
- **New divider: 10 kΩ top / 15 kΩ bottom (×0.6)** to GPIO34 (ADC1_CH6, 12 dB attenuation):
  - Worst case: 5.25 V × 0.6 = **3.15 V** at the pin.
  - Zero current ≈ 1.5 V; ±5 A → 0.95–2.06 V, inside the useful ≈ 0.15–2.45 V range.
  - Resolution ≈ 0.111 V/A at the pin.
  - Source impedance 6 kΩ; with the optional 10 nF to GND this gives a ≈ 2.7 kHz anti-alias pole.
- **Software:** `RigConfig.divider` changed to 25/15 to match. The firmware is unchanged apart from a comment, and the tests pass.
- **ADC accuracy:** the host converts raw counts with a nominal 3.3 V / 4095 scale and no ESP32 ADC calibration. Zero calibration removes the offset, but the current scale is only approximate (a few %). That is enough for anomaly detection, but **current limits are checked with the multimeter**, not with the ESP32 reading.
- **GPIO35** (bus voltage, not fitted): tie it to GND through 10 kΩ.

### 2.3 Grounding and separation of motor power from measurement wiring
- The ESP32 is powered **only** from the laptop USB.
- The motor circuit is galvanically isolated from it by the ACS712 (isolated primary).
- **Never connect the adapter's negative to the ESP32/laptop ground.**
- The ACS712 module's GND/VCC/OUT go to the ESP32 side only.
- **Route the wiring as two separate bundles:**
  - The 12 V motor loop (18 AWG, twisted pair, cable-tied to the base).
  - The 3.3/5 V sensor wiring (SPI ≤ 15–20 cm, Hall sensor, ACS712 output).
  - Cross them at right angles, and never in the same tie.
- The ESP32 and perfboard sit **outside the guard**. The point where the vibration sensor's data wire (MISO) is pulled for the demo is at the ESP32 header, so nobody reaches near the rotating parts.

### 2.4 ADXL345 (SPI) and Hall sensor
- **ADXL345:**
  - Supply from **3V3**, so logic is 3.3 V on both sides.
  - Wiring: CS→GPIO5, SCL→GPIO18, SDO→GPIO19, SDA→GPIO23. SPI mode 3, 4 MHz.
  - Mount it so its **Y axis is radial** (firmware `AXIS_OFFSET = 2`).
  - The firmware's boot check needs DEVID = 0xE5.
- **A3144 Hall sensor:**
  - Power from 5 V. Its open-collector output takes a **10 kΩ pull-up to 3.3 V only**, to GPIO27. Its output never sees 5 V.
  - One magnet on the disc (`PULSES_PER_REV = 1`), 1–3 mm from the sensor.

## 3. Mechanical safety requirements (all mandatory before first power-up)
1. **Base:** screwed or clamped to the bench, not free-standing.
2. **Motor:** held in a steel bracket by its screws, not cable ties or glue.
3. **KP08s:**
   - Bolted with M4 screws and washers onto rigid spacer blocks, so the shaft lines up with the motor axis (within ≈ 0.5 mm).
   - Both set screws tightened on the shaft.
4. **Coupling:** both set screws tight; on the motor's flat if the motor has one.
5. **Disc:**
   - Fitted **between** the bearings, never overhung.
   - Set screw tight.
   - The unbalance mass is **one M3×6 screw + nyloc nut (≈ 0.7 g) at ≤ 15 mm radius**. At 6000 rpm that is a force of ≈ 4 N.
   - No heavier masses and no larger radius.
6. **Guard:**
   - Polycarbonate cover over the coupling, shaft and disc, screwed to the base.
   - It must be fitted whenever the adapter is plugged in.
7. **Accelerometer:** fixed to the KP08 housing with a screw on a small bracket, or epoxy (no tape or hot glue). Its leads leave the guard through the wire slot and are strain-relieved.
8. **Hand check before every power-up:** with the guard removed and the adapter **unplugged**, turn the shaft by hand. It must rotate freely with no rubbing; then refit the guard.

**Isolation rule (applies to every step that touches the rotating assembly or the unbalance mass).**
Switch OFF → **unplug the adapter from the wall** → wait until the shaft has stopped → remove the guard → work → refit the guard → plug the adapter in → switch ON.
Never attach, remove or adjust anything on the rotating assembly while the adapter is plugged in.

## 4. Firmware flashing
1. Install Arduino IDE 2.x and esp32 by Espressif 3.x (compile-checked with 3.3.12). Then install the libraries **OneWire** and **DallasTemperature**.
2. Install the CP210x USB driver. Connect **USB only**, with no 12 V connected.
3. Open `firmware/rig_esp32/rig_esp32.ino`. Check `AXIS_OFFSET` and change nothing else.
4. Board **"ESP32 Dev Module"**, Port COMx → Upload. Hold BOOT if it reports "Failed to connect".
5. Close the Serial Monitor. Then on the laptop run `pip install -r requirements.txt` (includes pyserial).

## 5. Bring-up, timing verification and live demo
The first steps are done **with the motor adapter unplugged**.
1. Power-off multimeter checks (acceptance A2).
2. USB only: `python scripts/rig_check_timing.py --port COMx --seconds 120 --out results/rig/timing_motor_off.json` → must report PASS.
3. USB only: `python scripts/rig_record.py --calibrate-zero --port COMx`. This stores the current-sensor zero.
4. Guard on, then plug in the adapter. Switch on with the DMM in series on the 10 A range: check the start (5 times) and the steady current (acceptance E). Switch off and remove the DMM per the isolation rule.
5. Motor on: `rig_check_timing.py ... --out results/rig/timing_motor_on.json` → must report PASS.
6. **Healthy recordings:**
   - `rig_record.py --port COMx --session H1 --label healthy --minutes 5`, then H2 and H3.
   - Between sessions, follow the isolation rule and re-seat the disc.
   - H3 is recorded after a remount.
7. **Unbalance recording:** isolate, fit one M3 mass, refit the guard, power up. Then `rig_record.py ... --session F1 --label unbalance --minutes 3`.
8. **Train and evaluate:** `rig_train.py --fit H1 --cal H2 --test-healthy H3 --test-fault F1`.
   - The thresholds were fixed in advance: 99.5th percentile on H2, default `HealthPolicy`.
   - Report the result as measured. Do not tune on H3/F1.
9. **Live:** `scripts\windows\run_dashboard.bat` → **Rig - live**. Then, in order:
   - Healthy run, 2 min.
   - Pull MISO at the ESP32 header, then re-insert it.
   - Isolate and fit the mass, then power up → WARNING/INSPECT.
   - Acknowledge.
   - Isolate and remove the mass, then power up → recovery.
   - Export the history.
10. **Save evidence:** `data/rig/*.json`, `results/rig/*`, screenshots and photos; then update `docs/EVIDENCE_LOG.md`.

## 6. Minimum hardware acceptance criteria
| ID | Criterion | Pass condition | Evidence |
|---|---|---|---|
| A1 | Mechanical safety | Every item in §3 met; shaft turns freely by hand; guard fitted and screwed down | photos |
| A2 | Electrical (power off, DMM) | No continuity between the adapter's negative and ESP32 GND. Fuse T3.15 A and switch are in the motor loop. With USB only: GPIO34 at 1.35–1.6 V (zero current); GPIO27 ≈ 3.3 V without magnet, low with magnet, never > 3.4 V; no GPIO above 3.3 V | photos + notes |
| B | Firmware | Flashes; `sensors_detected` = true (DEVID 0xE5, ADC running) | timing JSON |
| C | Timing | `rig_check_timing.py` 120 s → **PASS on all six checks**, with the motor off and with it on | `results/rig/timing_*.json` |
| D | Current zero | `--calibrate-zero` stores 2.3–2.65 V (sensor-side value, = ACS712 supply / 2) | `configs/rig.json` |
| E1 | Start | Motor starts from the adapter **5 out of 5 times** without the fuse opening or the adapter staying in protection | notes |
| E2 | Steady current | DMM-measured steady current **< 3.0 A**, the motor's rated current (< 4 A is the ACS712 margin) | DMM photo |
| E3 | Speed | Rig rpm stable within ±3 % over 60 s, in 4,500–6,500 rpm | session JSON |
| F | Recordings | H1–H3 healthy and F1 unbalance recorded; every session's `acquisition_checks` all true | `data/rig/*.json` |
| G | Session-disjoint detection | H3 `ever_non_normal` = false; F1 first non-NORMAL ≤ 30 s | `results/rig_eval.json` |
| H | Live demo | **Rig - live:** healthy 2 min NORMAL; MISO pulled → vibration flagged ≤ 10 s with no fault probabilities from it; mass fitted → WARNING/INSPECT ≤ 30 s; acknowledgement shown as WARNING with "condition NOT verified"; events exported | screenshots + exports |

A–F prove the hardware is safe and acquiring correctly; G–H prove live monitoring. If G fails on
real data, it is reported as a measured negative result.
