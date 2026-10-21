# OB4 minimum hardware – final compatibility check and purchase list (rev. 3, 22 Oct 2026)

**Status.** This document supersedes the motor, adapter, fuse, unbalance-mass and procurement
sections of `HARDWARE_MIN_DEMO.md` (rev. 2). Wiring, the mechanical safety rules, the isolation
rule, flashing, the timing check and the demo procedure in rev. 2 still apply, with the values
changed below.

**Rule applied.** Before buying, every safety-relevant rating comes from the manufacturer's
datasheet or product page:
- motor stall current;
- adapter rating and overload behaviour;
- current-sensor and ADC limits.

Seller listings without a datasheet are not accepted for these ratings.

## 1. Verification results

| Item | Evidence (official source) | Result |
|---|---|---|
| **Rejected: RS775SH 12 V 6000 rpm (Robu SKU 1557392, "Orange")** | Seller page only: 1 A no-load, ≤ 3 A rated; **no stall current**, no datasheet link | **Rejected.** Stall current undocumented. Comparable 12 V 770/775 datasheets give 14–57 A stall, which no 5 A adapter can supply. |
| Rejected: other locally sold 775 / 3000 rpm motors | Seller pages only; inconsistent shaft data (2.3 mm vs 5 mm) | Rejected for the same reason |
| **Selected motor: Pololu #3225, 4.4:1 Metal Gearmotor 25Dx48L mm MP 12 V** | Pololu product page / 25D family table: 12 V, no-load **1800 rpm** (DigiKey lists 1700), no-load **80 mA**, **stall 1.8 A** (stall torque 0.71 kg·cm, extrapolated). Output shaft **Ø4 mm D, 12.5 mm**; two M3 face-plate holes, screws ≤ 6 mm deep. Pololu: keep current ≤ 25 % of stall (≈ 0.45 A); stalls can damage windings within seconds | **Pass.** Stall 1.8 A is 36 % of the adapter rating and inside the ACS712-05B linear range |
| Documented alternative: RS PRO 238-9715 (MFA RE-360 type) | RS PRO datasheet: stall **4.02 A at 12 V**, no-load 11,370 rpm, shaft Ø2.31 mm | Electrically acceptable (80 % of 5 A). **Not recommended**: 11k rpm, no 2.3 mm coupling sourced, RS India delivery estimate **1 Nov** |
| **Selected adapter: Mean Well GST60A12-P1J** (replaces the Pro-Range adapter, which has no datasheet) | Mean Well datasheet / element14: 12 V, 5 A, 60 W. Overload protection 105–150 % of rated power, **hiccup mode**, auto-recovery. Short-circuit, over-voltage (12.6–16.2 V) and over-temperature protected. **BIS IS13252**. Class I, IEC C14 inlet; output plug 2.1 × 5.5 mm, centre positive | **Pass.** Start/stall current (1.8 A) is supplied within the 5 A rating, so it never relies on the overload region |
| **ACS712ELCTR-05B** (on a module) | Allegro datasheet: VCC 4.5–5.5 V; 185 mV/A (180–190); VOUT(Q) = VCC/2; RLOAD ≥ 4.7 kΩ; 100 A / 100 ms transient tolerance; 2.4 kV isolation; 80 kHz bandwidth; 21 mV p-p noise (47 nF filter). No output clamp is specified, so assume the output can reach VCC | **Pass with the 10k/15k divider** (see 2.2) |
| ESP32 ADC / supply | Espressif ESP32 datasheet: VDD3P3 absolute max 3.6 V; ATTEN3 (12 dB) effective range **150–2450 mV**, total error ±60 mV | **Pass.** Pin ≤ 3.3 V worst case; signal inside 1.30–1.70 V |
| ACS712 module wiring (Probots PRO421) | Seller: VCC, GND, OUT pins; IP+/IP− screw terminals; "usually" a 1 nF filter cap. The chip suffix is not stated | Verify on receipt: chip marking ACS712**ELCTR-05B**, pinout by continuity, and OUT = VCC/2 ± 3 % at 0 A |

## 2. Compatibility (final values)

### 2.1 Power, start current, fuse
- **Circuit:** GST60A12 → 2.1 mm jack → **fuse T1 A** (5×20, slow-blow) → switch → ACS712 IP+ → IP− → motor.
- **Worst-case current:** start and stall are at most **1.8 A** (documented). That is below:
  - the adapter's 5 A rating;
  - 18 AWG wire;
  - the ACS712-05B's ±5 A linear range.
- **Fuse role:** the T1 A fuse carries the 1.8 A start surge. It protects the wiring; the adapter's own short-circuit and overload protection is primary.
- **What does *not* protect against a stall:** the fuse opens only slowly at 1.8× its rating. A stall is therefore a motor-damage risk, not an electrical hazard (≤ 21.6 W).
- **Operating rule:** if the shaft is not turning, switch off immediately. Never leave the rig running unattended.
- **Steady current:** must stay ≤ 0.45 A, Pololu's 25 %-of-stall guideline (acceptance E2).

### 2.2 ACS712 → ESP32
- **Divider:** 10 kΩ top / 15 kΩ bottom (×0.6), 25 kΩ load ≥ 4.7 kΩ.
  - Worst-case pin voltage: 5.5 V × 0.6 = **3.30 V**. That is below the 3.6 V maximum supply rating; with real USB VBUS ≤ 5.25 V it is ≤ 3.15 V.
  - Zero current ≈ 1.5 V. At the 1.8 A stall, 1.5 ± 0.20 V. Both are well inside 150–2450 mV.
- **Software:** `RigConfig.divider = 25/15` (already committed).
- **Known limitation:** at this motor's small running current, the ACS712-05B noise (≈ 21 mV p-p datasheet, more with the module's 1 nF filter) is about 0.1 A after the divider. That is comparable to the running current.
  - The current channel will be **noisy**.
  - The vibration channel carries the unbalance demo.
  - The "accelerometer disconnected → diagnosis on current only" step may show reduced or no fault evidence. Report it as measured.
  - The ADC's ±60 mV total error (≈ ±0.5 A) is mostly offset and is removed by zero calibration. Current limits are still checked with a multimeter.
- **Grounding:** unchanged from rev. 2. The ACS712 isolates the motor loop; never connect the adapter's negative to ESP32/laptop ground.

### 2.3 Mechanical
- **Motor and coupling:** the motor sits in a Pololu 25D bracket (#2676), M3 screws ≤ 6 mm into the face plate. It drives through a **4 mm → 8 mm flexible coupler** (Probots PRO4361) into the 8 mm shaft on 2× KP08.
- **Shaft height:** raise the KP08s or the motor on spacer blocks until the shaft axes line up within ≈ 0.5 mm.
- **Speed:** 1.7–1.8k rpm (≈ 30 Hz shaft rate), much lower than rev. 2.
- **Unbalance mass:** **one M4 × 10 screw + nyloc nut (≈ 3 g) at ≤ 20 mm radius**, giving ≈ 2 N at 1800 rpm. Fitted only under the isolation rule (adapter unplugged, shaft stopped, guard off).
- **Guard:** polycarbonate, screwed to the base, fitted whenever the adapter is plugged in.

## 3. Purchase-ready list

Prices were read today. Probots shows GST-inclusive prices; element14 and DigiKey show prices excluding GST.

### Batch 1 – Bengaluru, now (sensors and mechanics, no mains or rotating hazard)

| # | Item | Qty | Price | Link | Bengaluru availability |
|---|---|---|---|---|---|
| 1 | ESP32 30-pin CP2102 dev board (ESP-WROOM-32, micro-USB) | 1 | ₹499 | https://probots.co.in/esp32-30-pin-cp2102-development-board.html | In stock; **pickup today** at Nagarabhavi and Koramangala |
| 2 | ACS712 5 A current module | 1 | ₹129 | https://probots.co.in/current-sensor-ac-dc-module-with-analog-output-acs712-5a.html | In stock; **pickup today** at both stores |
| 3 | A3144 Hall sensor | 1 | ₹59 | https://probots.co.in/hall-effect-sensor-magnet-detector-switch-for-arduino-a3144e-44e.html | **Pickup today at Nagarabhavi only** |
| 4 | 4 mm → 8 mm flexible coupler (D19 × L25) | 1 | ₹149 | https://probots.co.in/4mm-to-8mm-flexible-coupler-for-3d-printer-cnc-shaft-metal.html | In stock; **pickup today** at both stores |
| 5 | KP08 pillow block, 8 mm | 2 | ₹198 | https://probots.co.in/kp08-8mm-pillow-block-insert-bearing-zinc-alloy.html | In stock (pickup not shown on the page; confirm) |
| 6 | 8 mm rod, 400 mm (cut to 150–200 mm) | 1 | ₹369 | https://probots.co.in/400-mm-length-chrome-plated-smooth-rod-diameter-8-mm.html | In stock (pickup not shown; confirm) |
| 7 | ADXL345 module, GY-291 type (Robu SKU 33070) | 2 (1 spare) | ₹538 | https://robu.in/product/adxl345-tripple-axis-accelerometer-board/ | Online, ships from Pune (stock and transit time not shown; confirm at checkout). **Probots GY-291 is out of stock** |
| | **Batch 1 subtotal** | | **₹1,941** | | |

### Batch 2 – documented motor and power (order today)

| # | Item | Qty | Price (excl. GST) | Link | Availability |
|---|---|---|---|---|---|
| 8 | Pololu #3225 25D MP 12 V 4.4:1 gearmotor (DigiKey 2183-3225-ND) | 1 | ₹2,861.72 | https://www.digikey.in/en/products/detail/pololu/3225/10450091 | DigiKey **Marketplace**: 83 in stock, ships from Pololu in ≈ 1 day; separate shipping fee; international transit, **arrival date not stated** |
| 9 | Pololu #2676 25D bracket pair (DigiKey 2183-2676-ND) | 1 | ₹1,046.27 | https://www.digikey.in/en/products/detail/pololu/2676/10449897 | Same as above (481 in stock) |
| 10 | Mean Well GST60A12-P1J 12 V 5 A adapter (element14 2815913) | 1 | ₹1,890.51 | https://in.element14.com/mean-well/gst60a12-p1j/ac-dc-power-supply-12v-5a/dp/2815913 | 119 from Singapore stock, **3–5 business days**, so delivered 27–29 Oct |
| | **Batch 2 subtotal** | | **₹5,798.50** (≈ ₹6,842 incl. 18 % GST) + Marketplace shipping | | |

### Batch 3 – local consumables (Probots / SP Road; estimates)

| Item | ≈ ₹ |
|---|---|
| IEC C13 mains cord (Indian 3-pin plug) for the GST60A12 | 150 |
| 2.1 × 5.5 mm female DC jack to screw terminal | 40 |
| Inline 5×20 fuse holder + T1 A slow-blow fuses (×3) | 60 |
| Switch ≥ 2 A DC | 40 |
| Resistors 10 kΩ ×4, 15 kΩ ×2; 10 nF ×2; 2 small magnets | 100 |
| 8 mm-bore flange or pulley (disc), M4 × 10 screws + nyloc nuts, M3 × 6 screws | 200 |
| Base, spacer blocks, M4 hardware, rubber feet | 300 |
| Polycarbonate guard | 300 |
| Jumpers, 18 AWG wire, perfboard, terminals, micro-USB data cable | 450 |
| **Subtotal (estimate)** | **≈ ₹1,640** |

**Total ≈ ₹10,400 incl. GST** (₹1,941 + ₹6,842 + ₹1,640), plus DigiKey Marketplace shipping.
Add ≈ ₹500 if the lab has no multimeter with a 10 A range; one is needed for acceptance.

## 4. Schedule consequence (honest)
- **Before 28 Oct (Batch 1 + bench):** acceptance B, C (motor-off timing), D and the USB-only part of A2 are achievable.
  - ESP32 flashed.
  - ADXL345 detected and timed.
  - ACS712 zero calibrated.
  - Hall sensor checked with a magnet.
  - Live dashboard streaming real sensor data, with the accelerometer tapped by hand and the motor off.
- **Motor demo (E–H):** needs Batch 2.
  - The adapter is due 27–29 Oct.
  - The Pololu motor's arrival is unconfirmed (international Marketplace shipment) and is **likely after 28 Oct**.
  - No motor with a documented stall current was found for pickup or next-day delivery in Bengaluru.
  - The documented RS PRO option is estimated for 1 Nov.
- If the review needs a spinning rig by 28 Oct, the only route is a locally available, undocumented motor whose start and stall current is **measured** first on a current-limited bench supply. That would replace "documented" with "measured" for one rating, so it is a team decision, not something this plan assumes.

## 5. Acceptance criteria changed from rev. 2
| ID | New pass condition |
|---|---|
| A2 | Fuse **T1 A** and switch in the motor loop; other checks unchanged |
| E1 | Motor starts from the GST60A12 **5 out of 5 times**; the adapter LED never drops out (no hiccup) |
| E2 | Multimeter-measured steady current **≤ 0.45 A** (Pololu 25 %-of-stall guideline) |
| E3 | Rig rpm stable within ±3 % over 60 s, in **1,500–1,900 rpm** |
| M  | ACS712 chip marked ELCTR-05B; OUT at 0 A = VCC/2 ± 3 %; GY-291 board without MOSFET level shifters (otherwise C will show it) |
