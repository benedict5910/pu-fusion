# OB4 – Minimum hardware for a live-monitoring demonstration (22 Oct 2026)

Scope: the **smallest rig that shows live monitoring** with the existing firmware
(`firmware/rig_esp32/rig_esp32.ino`) and host code (`src/pufusion/rig.py`, `scripts/rig_*.py`,
dashboard mode "Rig - live"). Nothing here changes the frozen Paderborn results (OB1/OB2) or the
OB3 health layer. No new features.

Demo it supports: healthy run stays NORMAL → vibration sensor disconnected → reliability layer
flags it and diagnosis continues on current only → unbalance mass added → WARNING / INSPECT →
acknowledgement logged without claiming the component is healthy.

What it does **not** support (deliberately excluded): seeded bearing faults (the KP08 pillow
blocks carry their own insert bearing, not a 608), speed control, temperature, bus voltage.

## 1. Procurement list (minimum set)

Prices are approximate INR incl. GST, Bangalore retail/online (Probots, Robu, Zbotic, SP Road), checked 21–22 Oct 2026 where a
source is given; the rest are estimates from `IVHM_SPEC.md`. Stock changes daily – confirm before ordering.

| # | Item (exact spec) | Qty | ≈ ₹ |
|---|---|---|---|
| 1 | **ESP32-WROOM-32 DevKit V1** (classic ESP32, *not* S2/S3/C3; 30- or 38-pin; CP2102 or CH340 USB) | 1 | 450 |
| 2 | **GY-291 ADXL345** 3-axis accelerometer module (SPI/I²C, 3.3 V) | 1 | 300 |
| 3 | **ACS712-05B** current-sensor module (±5 A, 185 mV/A, 5 V supply, screw terminal) | 1 | 129 (Probots) |
| 4 | **A3144** Hall switch (TO-92) + 2 small neodymium disc magnets (≈ 5×2 mm) | 1 + 2 | 80 |
| 5 | Resistors ¼ W 1 %: 10 kΩ ×4, 20 kΩ ×2 · ceramic capacitor 10 nF ×2 | – | 50 |
| 6 | **775 brushed DC motor, 12 V, ≈ 3000 rpm rated**, ball bearing, 5 mm shaft. **Do not buy the 10 000–12 000 rpm variant** (see §2.4) | 1 | 450–700 (Zbotic 3000 rpm ≈ 444, out of stock) |
| 7 | 775 motor mounting bracket (L-type, steel) with 2× M4 screws | 1 | 120 |
| 8 | Flexible shaft coupling **5 mm × 8 mm** (aluminium, jaw or spiral, set screws) | 1 | 200 |
| 9 | 8 mm hardened steel shaft (linear rod), 150–200 mm long | 1 | 150 |
| 10 | **KP08** pillow-block bearing, 8 mm bore (centre height 15 mm, 42 mm hole spacing, M4) | 2 | 198 (Probots ₹99 each) |
| 11 | Unbalance disc: 8 mm-bore aluminium flange coupling (or pulley) with set screw and through-holes; M4×10 bolts + nuts as unbalance masses | 1 + 4 | 150 |
| 12 | **12 V 10 A enclosed SMPS** (terminal cover) + 3-pin mains cord with plug | 1 | 750 |
| 13 | Inline fuse holder (5×20 mm) + **T6.3 A slow-blow** fuses | 1 + 3 | 60 |
| 14 | Rocker/toggle switch rated ≥ 10 A 12 V DC | 1 | 40 |
| 15 | Base: 18 mm plywood or ≥ 5 mm aluminium plate ≈ 300×150 mm; spacer blocks to raise the KP08s; M4 screws/nuts/washers; rubber feet | – | 300 |
| 16 | Shaft guard: clear acrylic/polycarbonate cover over shaft and disc, screwed to the base | 1 | 250 |
| 17 | Wiring: female-female/male-female jumpers, 18 AWG wire for the motor loop, 2-pin screw terminals, small perfboard, heat-shrink | – | 300 |
| 18 | USB data cable for the DevKit (micro-USB or USB-C to match the board) – skip if one is on hand | 1 | 150 |
| | **Total (minimum)** | | **≈ 4,300** |
| | With ~15 % contingency / shipping | | **≈ 5,000** |

Recommended spare (deadline risk, not a feature): a second GY-291 ADXL345 (≈ ₹300).

**Removed from the spec BOM for the minimum demo:** BTS7960 driver (no PWM – see §2.3), DS18B20,
bus-voltage divider, spare 608 bearings. The firmware needs no change for this: it still compiles
with the DallasTemperature library, an absent DS18B20 reads −127 °C and the host now records that
as "no temperature" (`monitor._temp_or_none`), and an unfitted bus-voltage input is just an unused channel.

## 2. Compatibility checks

### 2.1 ADXL345 over SPI
- Supply the GY-291 from the ESP32 **3V3** pin (the module's regulator also accepts 3.3 V). Logic is then 3.3 V on both sides; no level shifting.
- Wiring (firmware constants): CS→GPIO5, SCL/SCLK→GPIO18, SDO/MISO→GPIO19, SDA/MOSI→GPIO23, GND→GND.
  Firmware selects 4-wire SPI, mode 3, 4 MHz (ADXL345 max 5 MHz; ≥ 2 MHz needed for 3200 Hz ODR).
- Keep the SPI leads **≤ 15–20 cm**, twisted with a ground lead if possible; 4 MHz on long loose jumpers is the most likely cause of checksum or overrun failures.
- Firmware streams one axis (`AXIS_OFFSET = 2` = **Y**). Mount the module so its **Y axis is radial** (perpendicular to the shaft), or change `AXIS_OFFSET` (0 = X, 4 = Z) before flashing.
- Boot check: firmware reads DEVID; `0xE5` sets the "ADXL OK" flag (`sensors_detected` in the timing report).

### 2.2 Current sensing and the ESP32 ADC
- ACS712-05B on **5 V** (ESP32 VIN/5V pin from USB). Output = 2.5 V + 0.185 V/A (ratiometric to its supply).
- That output is above the ESP32 ADC range, so it goes through the **10 kΩ (top) / 20 kΩ (bottom)** divider (×0.667) to **GPIO34** (ADC1_CH6, input-only, 12 dB attenuation).
  Zero current → ≈ 1.67 V; ±5 A → 1.05…2.28 V. This is inside the useful 12 dB range (~0.15–2.45 V). Resolution ≈ 0.123 V/A at the pin → ≈ 6–7 mA per ADC step.
- Optional 10 nF from GPIO34 to GND: with the 6.7 kΩ divider source impedance this is a ≈ 2.4 kHz anti-alias pole (current channel sampled at 10 kHz, output 5 kHz) and steadies the ADC sample capacitor.
- **GPIO35** (bus voltage, not fitted): tie to GND through 10 kΩ so the second DMA channel does not float.
- **Isolation:** the motor loop passes only through the ACS712 primary. Do **not** connect the 12 V supply's negative to the ESP32 ground. The laptop USB ground stays separate from the motor circuit.
- **Range:** the 05B is linear to ±5 A. A 775 motor's start/stall current is far above that; the output clips briefly on start (the device survives large short overloads), which is acceptable. The **steady running current must be < 4 A** (acceptance E). If it is not, stop and use an ACS712-20A (100 mV/A; set `acs_v_per_a` = 0.100 in `configs/rig.json`).

### 2.3 Motor and power supply
- Motor runs directly from the **12 V SMPS → fuse (T6.3 A) → switch → ACS712 → motor**. No PWM driver in the minimum demo: PWM ripple at kHz rates would alias into the 5 kHz current channel and the 3.2 kHz vibration channel and turn the current sensor into a PWM detector.
- A 10 A SMPS covers a ≈ 3000 rpm 775 running at light load. If the supply hiccups on the start-up surge, the slow-blow fuse and the SMPS's own protection handle it; do not up-rate the fuse.
- Keep the SMPS mains side covered (terminal cover or enclosure). Never work on the motor wiring with mains connected.

### 2.4 Speed, Hall sensor, safety
- **Why ≈ 3000 rpm:** an M4 bolt + nut (≈ 3 g) at 20 mm radius gives F = m·r·ω² ≈ 6 N at 3000 rpm but ≈ 95 N at 12 000 rpm on a cheap pillow block. The low-speed motor keeps the unbalance demo safe and puts 1× (≈ 50 Hz) well inside the ADXL345 band.
- A3144 on **5 V**; its output is open-collector → pull it up with **10 kΩ to 3.3 V only** (ESP32 pins are not 5 V tolerant), to GPIO27. One magnet on the disc/shaft (`PULSES_PER_REV = 1`), the sensor 1–3 mm from it, fixed to the base.
- If the tachometer fails, features fall back to 1500 rpm (`rig_features`), which mislabels the shaft-order features – so the Hall sensor is part of the minimum set.

### 2.5 Mechanical mounting
- Order on the base: motor in bracket → 5×8 coupling → 8 mm shaft in two KP08s (≈ 80–100 mm apart) → disc **between** the bearings (not overhung).
- KP08 shaft centre is 15 mm above its feet; the 775 axis in its bracket is higher. **Raise the KP08s on spacer blocks** so both axes are level (within ≈ 0.5 mm), check with a straightedge, then tighten. The flexible coupling only absorbs small misalignment.
- Tighten both KP08 set screws on the shaft and the coupling set screws (on the motor's flat if it has a D-shaft).
- **ADXL345 on the motor-side KP08 housing**, rigidly: M3 screw on a small bracket under the KP08 bolt, or epoxy/cyanoacrylate. Not double-sided tape or hot glue (they damp exactly the band we measure).
- Base clamped or screwed to the bench, guard fitted, before the first powered run.

## 3. Firmware flashing
1. Arduino IDE 2.x → Boards Manager → install **esp32 by Espressif Systems 3.x** (compile-checked with 3.3.12).
   Library Manager → **OneWire** and **DallasTemperature** (needed to compile, even with no DS18B20 fitted).
2. USB driver: CP210x or CH340, matching the DevKit's USB chip. The board appears as COMx.
3. Open `firmware/rig_esp32/rig_esp32.ino`. Check `AXIS_OFFSET` matches the mounting (§2.1). Change nothing else.
4. Tools → Board **"ESP32 Dev Module"**, Port COMx → Upload. If it reports "Failed to connect", hold BOOT while the upload starts.
   (CLI: `arduino-cli compile --fqbn esp32:esp32:esp32 firmware/rig_esp32` then `arduino-cli upload -p COMx --fqbn esp32:esp32:esp32 firmware/rig_esp32`.)
5. Close the IDE's Serial Monitor (frames are binary at 921600 baud; only one program can open the port).
6. Laptop Python: `pip install -r requirements.txt` (now includes **pyserial**, which the rig code needs).

## 4. Sensor timing verification
Run from the project folder on the laptop (Windows), board on USB:
```
python scripts/rig_check_timing.py --port COMx --seconds 120 --out results/rig/timing_motor_off.json
python scripts/rig_check_timing.py --port COMx --seconds 120 --out results/rig/timing_motor_on.json   (motor running at 12 V)
```
The script fits sample index against the ESP32's own timestamps and reports measured rates, drift,
jitter, gaps and device overruns. Six checks must all be true: `no_checksum_errors`,
`no_sample_gaps`, `no_device_overruns`, `vib_rate_within_5pct` (ADXL345 internal oscillator, nominal 3200 Hz),
`cur_rate_within_0.5pct` (ADC DMA, nominal 5000 Hz), `sensors_detected`. Final line: `ACQUISITION CHECK: PASS`.
Most likely causes of a failure: long SPI leads (checksum/overrun) → shorten; USB hub or power-saving → use a direct port.
Pipeline rehearsed on 22 Oct with `--simulate` (PASS); that is a code check only, not a hardware result.

## 5. Live demo procedure (when components arrive)
Unbalance bolts are added or removed **only with the motor switched off and stopped.**
1. Motor off: `python scripts/rig_record.py --calibrate-zero --port COMx` (stores the current-sensor zero in `configs/rig.json`).
2. Healthy sessions, motor on, no unbalance bolt (≥ 5 min each; power-cycle and re-seat the disc between them; H3 after a remount or on a different day):
   `python scripts/rig_record.py --port COMx --session H1 --label healthy --minutes 5` … `H2`, `H3`.
3. Fault session: switch off, add one M4 bolt+nut to the disc, switch on:
   `python scripts/rig_record.py --port COMx --session F1 --label unbalance --minutes 3`.
4. Train and evaluate by session (thresholds fixed in advance: 99.5th percentile on H2, default `HealthPolicy`):
   `python scripts/rig_train.py --fit H1 --cal H2 --test-healthy H3 --test-fault F1` → `results/rig_eval.json`, `models/rig_models.pkl`.
   Report the result as measured. Do **not** change thresholds or features after looking at H3/F1.
5. Live: `scripts\windows\run_dashboard.bat` → mode **Rig - live**, port COMx → Start.
   a. Healthy, 2 min → NORMAL. b. Pull the ADXL345 **MISO** jumper (module stays powered and configured) → vibration flagged, diagnosis continues on current only; re-insert → recovers.
   (Pulling the module's VCC instead would reset its configuration until the ESP32 is reset.)
   c. Switch off, add the bolt, switch on → WARNING then INSPECT. d. Acknowledge → state shows WARNING with "condition NOT verified"; INSPECT re-latches while the bolt stays.
   e. Switch off, remove the bolt, switch on → WARNING held until 6 quiet windows, then NORMAL. f. History tab → CSV and HTML export.
6. Save `data/rig/*.json`, `results/rig/*.json`, `results/rig_eval.json`, screenshots → `results/rig/` and update `docs/EVIDENCE_LOG.md`.

## 6. Minimum hardware acceptance criteria
All must hold; each is recorded with its artefact. Any failure is reported as a failure, not tuned away.

| ID | Criterion | Pass condition | Evidence |
|---|---|---|---|
| A1 | Mechanical | Shaft turns by hand without binding; axes level within ≈ 0.5 mm; all set screws tight; accelerometer rigidly fixed with Y radial; guard fitted | photo |
| A2 | Electrical (power off / multimeter) | No continuity between motor circuit and ESP32 GND; fuse and switch in the motor loop; GPIO27 high (≈ 3.3 V, never > 3.4 V) without magnet and low with magnet; GPIO35 tied to GND | photo + notes |
| B | Firmware | Flashes; ADXL345 DEVID = 0xE5 and ADC running (`sensors_detected` = true) | timing JSON |
| C | Timing | `rig_check_timing.py` 120 s → **PASS on all six checks**, both motor off and motor on | `results/rig/timing_*.json` |
| D | Current zero | `--calibrate-zero` stores 1.55–1.78 V | `configs/rig.json` |
| E | Motor | Steady running current **< 4.0 A**; rpm stable within ±3 % over 60 s and in 2,000–4,500 rpm | session JSON / dashboard |
| F | Recordings | H1, H2, H3 healthy and F1 unbalance recorded; every session's `acquisition_checks` all true | `data/rig/*.json` |
| G | Session-disjoint detection | H3: `ever_non_normal` = false. F1: first non-NORMAL ≤ 30 s | `results/rig_eval.json` |
| H | Live demo | Dashboard "Rig - live": healthy 2 min NORMAL; MISO pulled → vibration flagged ≤ 10 s, no fault probabilities from it; bolt → WARNING/INSPECT ≤ 30 s; acknowledgement logged and shown as WARNING, not NORMAL; events exported to CSV/HTML | screenshots + exports |

A–F prove the acquisition hardware; G–H prove live monitoring. If G fails on real data, the demo
still runs (A–F, H) and G is reported as a measured negative result.
