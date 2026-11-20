# OB4 - CAD-supported virtual testbed

Status: implemented on top of the recovered 15 Nov 2026 baseline (`OB4_HANDOFF.md`). Evidence for every claim
below is produced by `scripts/verify_ob4.py` into a new `results/ob4_cad/verification_<timestamp>/` folder; the
numbers quoted here are only those that have been run (see "Evidence").

## 1. What OB4 is - and is not

* **Is:** recorded-signal replay with controlled sensor-fault injection, shown on a representative CAD model of an
  electric drivetrain. Each replayed window goes through the frozen diagnosis models, the label-free sensor-quality
  check, reliability-gated fusion, the health-state rules and the SQLite event log - the same chain as the dashboard.
* **Is not:** a physics simulation or a physics-validated digital twin. Nothing in the CAD model generates or
  alters a signal; the CAD view only shows *where* each recorded channel comes from and colours parts and sensors
  by the states the models computed.
* **Two benches, never fused.** Paderborn KAt (bearing: 1 vibration + 2 current channels, 64 kHz) and MCC5-THU
  (gearbox: motor and gearbox 3-axis vibration, 12.8 kHz) were recorded on two different test benches. The CAD
  assembly is a representative drivetrain, not a reconstruction of either. Bearing and gearbox replays run
  separately with their own frozen models; there is no cross-subsystem fusion.
* **Unchanged:** the three frozen models (SHA-256 checked), all earlier results, and the dashboard's fusion
  (reliability-gated `gated_both`). The experimental `v3_strength` fusion is not wired into any replay or live
  view (checked by `verify_ob4.py`).

## 2. Architecture

```
src/pufusion/drivetrain_cad.py   single source of truth: parameters, parts, sensors, sensor map, sizing checks,
                                 interference check, 2-D projections, SVG view for the dashboard
   |-- cad/build_freecad.py      FreeCAD (freecadcmd): parametric FCStd (spreadsheet Params + expressions),
   |                             STEP (assembly, per component, exploded), STL, self-check report
   |-- cad/make_drawings.py      4 A3 sheets (PDF + PNG): GA, sensor map, exploded view, details + checks
   `-- app/testbed_view.py       dashboard view "Virtual Testbed"
                                      |
src/pufusion/testbed_session.py  ReplaySession: run / pause / step / reset, fault changes between windows
   uses unchanged: testbed.Context (frozen models + held-out recordings), corruption / sensor_faults (fault
   injection), monitor.MonitorEngine + BenchmarkDiagnoser (bearing), gearbox.replay (gearbox), HealthTracker,
   HealthStore (SQLite)
```

Changes to existing files: `app/dashboard.py` only (+10 lines: the fifth view "Virtual Testbed" and its module
in the reload list). No other existing file was modified.

### Interactive testbed (dashboard, view "Virtual Testbed")

1. Select **Bearing** or **Gearbox**; the CAD view highlights the monitored component (test bearing or gearbox)
   and shows that subsystem's sensors (S1/S2 or S3/S4); the other subsystem's sensors are greyed out.
2. Select a real held-out recording (bearing K004 healthy, KA22 outer race, KI18 inner race; gearbox healthy,
   pitting, wear at 1000 rpm / 10 Nm).
3. **Run / Pause / Step / Reset.** Run replays up to "Stop after window" (recordings loop as in the testbed);
   Run replays one window per script run and then calls `st.rerun()`, so Pause, Step, Reset and Acknowledge
   take effect between windows; Step replays exactly one window; Reset starts a new run under a new asset name.
4. **Inject** noise, clipping, stuck, dropout (also spikes, intermittent loss, gain error) on one sensor or both;
   a change applies from the next window, so onset and recovery can be shown in one run.
5. Per window: health state banner, CAD colours (component = health state; sensor = quality status), sensor table
   (quality status, score, reasons, fusion weight), class probabilities and fault evidence, waveforms of every
   channel of the active sensors, health-state/evidence/weight timeline, recommendations, explanation (bearing
   model), and the event history from the SQLite log (full history in "History & Reports").

## 3. CAD model

Representative bench drivetrain: IEC-90-proportioned motor on a riser, jaw coupling, stepped line shaft on two
6203 deep-groove ball bearings (support bearing and monitored test bearing) in block housings, second coupling,
single-stage spur gearbox (pinion z = 20, gear z = 50, m = 2, a = 70 mm, ratio 2.5) with four 6203 shaft bearings
in the housing walls, removable cover, third coupling and a brake/load unit, all on a 1160 x 340 x 20 mm base plate.
Shaft centre height 140 mm. Since 21 Nov 2026 (high-fidelity upgrade, `docs/OB4_HIFI_CAD_2026-11-21.md`) the
parts carry engineering detail fused into the same solids: TEFC motor with 26 axial cooling fins, fan cowl with a
ventilation grille, terminal box with lid, cable gland and blanking plug, lifting eye, bearing cap, end-shield and
foot bolts; flanged jaw couplings with six bolts per hub; locking collars with set screws on the line shaft; bearing
housings with bore bosses, cap bolts, gussets, grease nipples and hold-down bolts; gearbox housing with split-line
and foot flanges, vertical ribs, bearing bosses and blind caps with bolts, inspection cover, breather, lifting eyes
and cover bolts; involute gear teeth (20 deg, 0.1 mm backlash, polygonal) with hubs and lightening holes; finned
load unit with end bells, terminal box and a cradle pedestal; base plate with anchor nuts and six levelling feet.
Bearings have rings and balls but no raceway grooves or cage. 90 solids + 4 sensors (one new part: the motor fan
cowl). Fins, ribs, gussets and bolt heads are prisms with a fixed section whose position follows `Params`.

Editable: every primitive in the FCStd is a parametric FreeCAD feature whose dimensions and placement are
expressions on the spreadsheet `Params` (same names as below); changing `shaft_h`, for example, moves every shaft,
coupling, bearing, gear and sensor that depends on it (checked by the build: `edit_test`).

| Parameter | Value (mm unless stated) | Meaning |
|---|---|---|
| `shaft_h` | 140 | shaft centre height above the base plate |
| `base_x0` | -30 | base plate start (x) |
| `base_l` | 1160 | base plate length |
| `base_y0` | -140 | base plate start (y) |
| `base_w` | 340 | base plate width |
| `base_t` | 20 | base plate thickness |
| `mot_x0` | 40 | motor body start (non-drive end) |
| `mot_l` | 240 | motor body length |
| `mot_d` | 180 | motor body diameter |
| `mot_shaft_d` | 24 | motor shaft diameter |
| `es_t` | 15 | drive-end shield thickness |
| `es_d` | 170 | drive-end shield diameter |
| `riser_h` | 50 | motor riser height (shaft centre height minus the 90 mm IEC shaft height) |
| `tb_l` | 90 | terminal box length |
| `tb_w` | 90 | terminal box width |
| `tb_h` | 60 | terminal box height |
| `cable_d` | 12 | motor supply cable diameter |
| `cable_l` | 75 | motor supply cable length shown |
| `cpl_d` | 65 | coupling hub diameter |
| `cpl_hub` | 30 | coupling hub length |
| `cpl_gap` | 10 | coupling spider (elastomer) length |
| `spider_d` | 55 | spider diameter |
| `brg_d` | 17 | bearing bore = journal diameter |
| `brg_od` | 40 | bearing outer diameter |
| `brg_b` | 12 | bearing width |
| `ball_d` | 6.747 | ball diameter (6203) |
| `ball_n` | 8 | number of balls |
| `shaft_d` | 20 | line shaft diameter at the couplings |
| `shoulder_d` | 22 | line shaft diameter between bearings |
| `brg_a_x` | 450 | support bearing centre (x) |
| `brg_b_x` | 610 | test bearing centre (x) |
| `hsg_t` | 24 | bearing housing thickness (x) |
| `hsg_w` | 110 | bearing housing width (y) |
| `hsg_top` | 45 | bearing housing height above the shaft centre |
| `gb_x0` | 780 | gearbox housing start (x) |
| `gb_l` | 140 | gearbox housing length (x) |
| `gb_wall` | 12 | gearbox wall thickness (= bearing width) |
| `gb_y0` | -45 | gearbox housing start (y) |
| `gb_w` | 182 | gearbox housing width (y) |
| `gb_z0` | 70 | gearbox housing bottom (z) |
| `gb_top` | 210 | gearbox housing top (z) |
| `gb_cover_t` | 12 | gearbox cover thickness |
| `gear_m` | 2 | gear module |
| `z_pinion` | 20 | pinion teeth |
| `z_gear` | 50 | gear teeth |
| `gear_b` | 20 | gear face width |
| `gear_x` | 840 | gear face start (x) |
| `load_x0` | 1030 | load unit start (x) |
| `load_l` | 70 | load unit length |
| `load_d` | 140 | load unit diameter |

Sizing checks (`design_checks()`, textbook formulas, assumed duty 1.1 kW at 1500 rpm, 1000 N radial on the test
bearing; plausibility only, not a validated design): motor torque 7.0 N m; shaft shear stress at d 17 mm 7.3 MPa;
6203 L10 985 Mrev = 10,945 h; output 600 rpm, 17.5 N m; pinion tangential load 350 N, Lewis bending stress
27.4 MPa; line-shaft first lateral critical speed about 52,400 rpm (35x running speed).

Mechanical coherence: a sampled interference check (0.5 mm grid, every pair of overlapping bounding boxes, sensors
included) finds no shared volume between any two of the 94 solids, and it is shown to detect planted clashes
(oversize shaft shoulder vs housings, oversize gear vs housing, gear teeth rotated half a pitch). The FreeCAD build
repeats the check on the B-rep solids (`common()` volume).

## 4. Sensor placement and data mapping

| ID | Sensor | Subsystem / code key | Dataset channels | Mounted on | Position x, y, z (mm) |
|---|---|---|---|---|---|
| S1 | Bearing accelerometer | bearing / `vib` | `vibration_1` | top face of the test-bearing housing, above the bearing | 610, 0, 192 |
| S2 | Motor current sensors (phases 1, 2) | bearing / `cur` | `phase_current_1`, `phase_current_2` | clamp-on current transducers on the motor supply cable | 185, 83, 260 |
| S3 | Motor accelerometer (3-axis) | gearbox / `motor` | `motor_vibration_x`, `motor_vibration_y`, `motor_vibration_z` | top of the motor frame at the drive end | 260, 0, 237 |
| S4 | Gearbox accelerometer (3-axis) | gearbox / `gearbox` | `gearbox_vibration_x`, `gearbox_vibration_y`, `gearbox_vibration_z` | side wall of the gearbox housing, at the input-shaft bearing | 798, -52, 140 |

`code key` is the dictionary key the replay code uses for that sensor's quality status, score and fusion weight;
`channels` are the names the loaders read (`data.VIB`, `data.CUR`, `gearbox.SENSORS` x `gearbox.AXES`). Both are
tested against the code (`tests/test_cad_model.py`). Positions are representative mounting locations on this
assembly, not measured positions on either bench. Machine-readable: `cad/out/sensor_map.json`.

## 5. Methods and tests

| Test file | What it verifies |
|---|---|
| `tests/test_testbed_session.py` | Session vs batch testbed for every scenario: identical states, availability, labels, sensor status, rules, events and SQLite history; evidence and weights within 1e-9 (bearing, float64) or 1e-6 (gearbox: float32 recordings, machine epsilon 1.2e-7; measured maximum difference 1.8e-7); testbed safety checks pass on the session's log; run/step/reset/fault-change/ack/dual-failure behaviour |
| `tests/test_testbed_view.py` | CAD colours are a pure function of the replay frame; dashboard flow Step -> Run -> Ack -> fault on S1 -> dual failure -> Reset through the dashboard script (stand-in Streamlit); other views unchanged |
| `tests/test_testbed_apptest.py` | Same flow on the real Streamlit app (AppTest), bearing and gearbox |
| `tests/test_cad_model.py` | Sensor map vs loader channel names and code keys, sample rates, sensor-to-mount contact, expressions, interference (and its sensitivity), parametric propagation; FreeCAD report (validity, bbox agreement < 0.05 mm, sensors, B-rep interference, STEP re-import, spreadsheet edit) |
| `scripts/verify_ob4.py` | One evidence folder: model hashes, 15-scenario regression vs Nov 15, session equivalence, fallback/abstention counts, CAD checks, v3 not wired |

## 6. Evidence

Run on the analysis workspace (Linux, Python 3.13; bearing recordings only - the gearbox recordings and FreeCAD
were not available there), 19 Nov 2026:

* Frozen models: 3/3 SHA-256 unchanged; gearbox model matches its manifest.
* Regression replay, bearing: 7/7 scenarios, 70/70 checks, 161 windows, 15 events; summaries identical and traces
  equal (1e-12) to `results/final/ob4_testbed`.
* Interactive session: reproduces all 7 bearing scenarios; single-sensor fallback in all 16 single-failure windows;
  abstention (no probabilities, no weights, SENSOR_FAULT or latched INSPECT) in all 16 all-failed windows.
* CAD: 0 unexpected overlaps (198 candidate pairs); planted clashes detected.
* Unit tests: 127 run, 0 failures, 21 skipped (9 real-Streamlit AppTests, 6 gearbox-data tests, 6 FreeCAD-report
  tests - all three need the project PC).

### Windows PC, 19 Nov 2026 - full run `results/ob4_cad/pc_run_20261119-233548/`

Windows 11, PowerShell 5.1, Python 3.11.9, Streamlit 1.66.0, FreeCAD 1.1.4 (`E:\freecad\bin`). Started by
double-clicking `scripts\windows\ob4_finish.bat` in Explorer (preflight: cmd, python, git and freecadcmd all
start; parent chain explorer -> cmd -> powershell; not a restricted token). Final verdict of the script: PASS on all
seven items.

* Gearbox recordings: the three held-out MCC5-THU recordings in `data\mcc5_demo` match the manifest (size and
  SHA-256); none generated or modified.
* Frozen models: 3/3 SHA-256 unchanged; gearbox model matches its manifest.
* **Regression replay: 15/15 scenarios, 148/148 checks**, 549 windows, 36 events; summaries identical and traces
  equal (1e-12) to the 15 Nov evidence; nothing skipped for missing data.
* Interactive session reproduces all 15 scenarios window by window (bearing within 1e-9; gearbox within 1e-6,
  measured maximum 1.8e-7; states, labels, rules, sensor status and events identical).
* Single-sensor fallback verified in 46 windows; dual-sensor abstention in 51 windows.
* v3_strength is not used by the replay or the live views.
* FreeCAD build report passed: 89 solids + 4 sensors, all valid, bounding boxes equal to the Python model (maximum
  deviation 0.0 mm), no unexpected B-rep interference (227 candidate pairs), STEP re-import 93/93 solids with relative
  volume difference 0.0, spreadsheet edit test moves the dependent parts by the edited 10 mm. TechDraw GA (DXF and
  PDF) and the four A3 drawing sheets (`cad/make_drawings.py`) were produced.
* **Unit tests: 127 run, 0 failures, 12 skipped.** The real-Streamlit AppTests ran and passed (four
  `TestDashboardAppTest`, three `TestVirtualTestbedAppTest`), as did all CAD, sensor-map and session tests.
* Real dashboard (http://localhost:8520) exercised by hand in a browser: bearing and gearbox, Run / Pause / Step /
  Reset / Acknowledge, noise/clipping/dropout on one and both sensors, quality, weights, the four health states,
  explanations and events. 13 screenshots with an index: `results/ob4_cad/screenshots/`.

Defects found during that check, fixed afterwards (they need the re-run listed below):

1. During Run the waveform charts were appended once per window instead of replaced. Fixed, and the AppTest now
   asserts one waveform set after a 12-window run.
2. Pause did not interrupt a long gearbox Run (the click was handled only at the stop window). Run now replays one
   window per script run and calls `st.rerun()`; verified on the live dashboard (paused at window 29 and held for
   10 s; Step then advanced exactly one window).
3. After Acknowledge the banner and CAD colour still showed the INSPECT recorded for the last window. They now show
   the acknowledged state (WARNING, "condition not verified") at once; covered by the headless test.
4. The four assembled FreeCAD GUI renders (iso, front, top, right) were blank white images although the report
   marked them as present; only the exploded render had content. The renders are now made from the exported STEP
   files and the report records each image's non-white pixel fraction, flagging blank images as errors. The
   TechDraw GA views overlapped at scale 1:4; the layout is now 1:5 with separated views.

**Still to run on the PC after these fixes:** `scripts\windows\ob4_finish.bat` once more, to rebuild the renders
and repeat verification and the full test suite with the changed view code. Until that run passes, items 1-4 above
are verified only by the workspace tests and the live dashboard check, not by a complete Windows run.

### The 12 skipped Windows tests (127 run)

None is a hidden failure. Eight are skipped by design when real Streamlit is installed, because they drive the
dashboard through the headless stand-in and the AppTest suite covers the same flows on real Streamlit
(`TestDashboardHeadless`, `TestCloudSessionIsolation`, `TestStaleModulesAfterUpdate`, three `TestDashboardSimulation`
tests, two `TestTestbedViewHeadless` tests). Four need all 12 MCC5-THU pilot recordings in `data/mcc5`, which are not
on the PC (only the three demo recordings of the held-out profile are): `TestGearboxAppTest`,
`TestGearboxDemoModeAppTest`, `TestGearboxDemoMode`, `TestGearboxHeadless`. They can be enabled by fetching the 12
pilot recordings into `data/mcc5`. (The 15 Nov baseline had 10 skips; the two new ones are the OB4 headless tests.)

## 7. Limitations

* Not a physics model: no dynamics, no load or speed coupling between CAD parts and signals; the animation is a
  colour mapping of model outputs.
* CAD is representative: dimensions are engineering choices (sizing checks are plausibility checks), not either
  bench; gear teeth are a polygonal involute for display and clearance checks (not for load or contact analysis);
  no raceway grooves, cages, seals, keys, threads or tolerances beyond the bore callout. Fasteners are represented
  by their heads and washers, fused into the part they fasten, and drawn in that part's finish.
* Two separate benches: bearing and gearbox replays cannot be combined into one machine-level diagnosis.
* All sensor faults are synthetic; no physical sensor fault has been tested.
* Gearbox: one recording per class at the held-out profile; model accuracy across speeds is poor (frozen pilot
  results); explanations exist only for the bearing model.
* Health states inherit the known false-alarm behaviour (healthy K004 sits in WARNING; healthy gearbox recording
  shows WARNING in part of the run); the testbed exposes this, it does not fix it.
* The gearbox model is evaluated one window at a time in the interactive session; its evidence equals the batch
  result to within 1e-6 (float32 recordings; measured maximum 1.8e-7) and the states are identical. Bearing: 1e-9.
* Sensor-quality gating does not catch every injected fault: on the healthy K004 recording a clipped accelerometer
  (severity 0.2) is rated DEGRADED (score 0.71), keeps a 0.53 fusion weight, and the frozen model then reports outer
  race 0.71, so the state rises to WARNING (screenshot 08). This is a false alarm caused by the synthetic fault and
  is reported as observed, not tuned away.

## 8. Reproduce

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\ob4_finish.ps1   (all PC steps: CAD build + renders, verification, tests, dashboard, git with confirmation)
scripts\windows\build_cad.bat          (FreeCAD model, STEP, drawings; python cad/make_drawings.py alone needs no FreeCAD)
scripts\windows\verify_ob4.bat         (evidence folder + full unit-test log under results\ob4_cad\)
scripts\windows\run_integrated_dashboard.bat  -> view "Virtual Testbed"  (see docs/OB4_DEMO_GUIDE.md)
scripts\windows\ob4_hifi_run.bat      (21 Nov hi-fi upgrade: rebuild + export + verify + tests + dashboard, no prompts)
```
