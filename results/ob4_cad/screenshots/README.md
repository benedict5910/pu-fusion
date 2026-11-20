# OB4 Virtual Testbed: real-Streamlit dashboard screenshots (19 Nov 2026)

Taken from the real Streamlit dashboard on the project PC (http://localhost:8520, started by
`scripts/windows/ob4_finish.bat`, run `pc_run_20261119-233548`), driven in a browser. Every value on screen comes
from the frozen models replaying the held-out recordings; the injected sensor faults are synthetic.
The CAD view is a representative assembly, not the Paderborn or MCC5-THU bench, and it is not a physics simulation.

| File | What it shows |
|---|---|
| 01_bearing_ready_cad.jpg | Bearing subsystem, K004 selected, CAD front view with S1-S4 before any window |
| 02_bearing_KI18_inspect.jpg | KI18 (inner race) clean replay: INSPECT latched, test bearing coloured by state |
| 03_bearing_KI18_quality_weights_probs.jpg | Sensor quality (OK, score 1.00), fusion weights vib 0.77 / cur 0.23, class probabilities (inner race 0.84) and waveforms |
| 04_bearing_KI18_timeline_explanation_events.jpg | Health-state timeline, recommendation, model explanation and the event log (NORMAL -> WARNING -> INSPECT) |
| 05_bearing_both_sensors_dropout_latched.jpg | KI18, dropout on both sensors after INSPECT: rule "no usable sensor", latched INSPECT kept |
| 06_bearing_both_sensors_failed_diagnosis_suspended.jpg | Same window: S1 and S2 FAILED, no probabilities or weights shown ("Diagnosis suspended") |
| 07_bearing_K004_both_sensors_SENSOR_FAULT.jpg | Healthy K004 with both sensors dropped out: SENSOR FAULT state, diagnosis suspended |
| 08_bearing_K004_vib_clipping_degraded.jpg | Healthy K004, accelerometer clipped (severity 0.2): S1 DEGRADED (0.71), weight 0.53, the model reports outer race 0.71 and the state goes to WARNING: a false alarm (see limitations) |
| 09_gearbox_pitting_inspect_running.jpg | Gearbox, gear-pitting recording during Run: INSPECT, gearbox housing coloured |
| 10_gearbox_motor_dropout_after_pause_step.jpg | After Pause (held at window 29) and one Step (window 30) with motor-sensor dropout |
| 11_gearbox_motor_dropout_fallback_weights.jpg | Single-sensor fallback: S3 FAILED weight 0.00, S4 weight 1.00, gear pitting 0.93 |
| 12_gearbox_inspect_acknowledged_warning.jpg | Acknowledge INSPECT: logged, state WARNING shown immediately (condition not verified) |
| 13_gearbox_both_sensors_SENSOR_FAULT.jpg | Gearbox, both accelerometers dropped out: SENSOR FAULT, both FAILED, diagnosis suspended |

Defects found during this session and fixed in `app/testbed_view.py` (the screenshots after each fix were taken with
the fixed code; the dashboard reloads changed project modules):

1. Waveform charts were appended once per window during Run (24 copies after 24 windows). Fixed before 03.
2. Pause did not interrupt a gearbox Run until the stop window. Run now replays one window per script run and calls
   `st.rerun()`. Verified live before 10: Pause held at window 29 for 10 s and Step advanced exactly one window.
3. After Acknowledge the banner still showed the INSPECT recorded for the last window. Fixed before 12.
