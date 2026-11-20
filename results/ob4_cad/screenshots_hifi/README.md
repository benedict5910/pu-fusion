# OB4 high-fidelity 3D viewer - screenshots (21 Nov 2026)

Real dashboard (`scripts\windows\run_integrated_dashboard.bat`, http://localhost:8520, view "Virtual Testbed") on
the project PC, captured from the Claude desktop app's browser pane (page emulated at 1280x800, captured at 800x500).
Every state, probability, quality status and weight shown comes from the frozen models' replay of real held-out
recordings; sensor faults are synthetic and injected from the sidebar. The CAD assembly is representative, not either
test bench, and the view is not a physics simulation.

| File | Scenario |
|---|---|
| 00_comparison_reference_before_after.jpg | the supplied visual reference, the earlier 19 Nov screenshot, the upgraded dashboard, and a full-resolution render |
| 01_bearing_KI18_INSPECT_iso.jpg | bearing, KI18 (inner race), Run to window 24: INSPECT latched; inner race 0.84, fault evidence 0.94; S1 ok, weight 0.77 |
| 02_gearbox_pitting_INSPECT_iso.jpg | gearbox, pitting recording, Run: INSPECT; gear pitting 0.83 |
| 03_gearbox_running_sensor_S3_selected.jpg | S3 (motor accelerometer) selected while the gearbox replay runs: channels, 12.8 kHz, quality ok, score 1.00, weight 0.50 |
| 04_gearbox_INSPECT_xray_exploded.jpg | X-ray + explode: gears, shafts and bearings lifted out of the housing |
| 05_bearing_K004_healthy_WARNING_known_false_alarm_xray_exploded.jpg | healthy K004 run: WARNING - the documented false alarm, shown as recorded |
| 06_bearing_vib_dropout_S1_failed_fallback_to_current.jpg | dropout on vib: S1 FAILED, weight 0.00, diagnosis continues on the current sensor |
| 07_bearing_both_sensors_dropout_SENSOR_FAULT_diagnosis_suspended.jpg | dropout on both: SENSOR_FAULT, no probabilities |
| 08_bearing_KI18_INSPECT_acknowledged_WARNING.jpg | Acknowledge: INSPECT -> WARNING "acknowledged by the operator (condition not verified)", 3D chip updated at once |
| 09_bearing_KI18_acknowledged_top_view.jpg | top view of the same state |
| 10_gearbox_both_sensors_dropout_SENSOR_FAULT_front.jpg | gearbox, dropout on both (S3, S4 FAILED): SENSOR_FAULT, front view |
| 11_viewer_fullres_harness_render_sample_frame.png | same viewer code and FreeCAD GLB rendered at 1280x680 in headless Chrome with a sample frame (not a replay; for detail only) |

Interaction checked on the live dashboard during these captures: Run, Pause (window held for 5 s), Step (exactly one
window), Reset, Acknowledge, view buttons, X-ray, explode, sensor and component selection, double-click focus, and
Bearing <-> Gearbox switching that keeps each replay's window.
