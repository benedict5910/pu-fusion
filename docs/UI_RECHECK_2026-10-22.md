# Dashboard UI re-check after the safety fixes (22 Oct 2026, 01:19–01:34 IST)

**Setup.** The real Streamlit dashboard ran on the team laptop and was operated in Chrome at
http://localhost:8501.
- The server was restarted so it loaded the corrected code; the "Acknowledge INSPECT alert" label is the new one.
- Mode was Benchmark replay with the same demo model as on 21 Oct.
- Recording: KI18 (inner race, held out) `N15_M07_F10_KI18_1`. These are real Paderborn data, with sensor dropout injected where stated.
- No model, threshold or result was changed.

| # | Step | Expected | Observed | Result | Screenshot (`results/starter/ui/recheck_2026-10-22/`) |
|---|---|---|---|---|---|
| R1 | Clean run | INSPECT latched, as on 21 Oct | INSPECT "latched until acknowledged"; inner 0.84; weights vib 0.77 / cur 0.23. Identical to 21 Oct | PASS | `R1_KI18_INSPECT.jpg` |
| R2 | Acknowledge | WARNING, **not** NORMAL; clear statement that the condition is not verified | "INSPECT acknowledged and logged. This does NOT confirm the bearing is healthy: the state is now WARNING…" Event logged as INSPECT→WARNING, "component condition NOT verified" | PASS | `R2_ack_to_WARNING_not_verified.jpg` |
| R2b | Acknowledge again | no-op | "Nothing to acknowledge: current state is WARNING, not INSPECT." | PASS | – |
| R3 | Same faulty recording again | INSPECT re-latches on new evidence | WARNING→INSPECT, "fault evidence > 0.8 in 4/4 recent windows" | PASS | `R3_persistent_fault_relatches_INSPECT.jpg` |
| R4 | Both sensors dropped while INSPECT latched | latch kept; diagnosis suspended; no probabilities, weights or explanation | "INSPECT - no usable sensor"; both sensors failed; "Diagnosis suspended … No fault probabilities or sensor weights are shown"; no explanation | PASS | `R4_both_dropout_diagnosis_suspended_INSPECT_kept.jpg` |
| R5 | Acknowledge, then both sensors dropped | SENSOR_FAULT | WARNING→SENSOR_FAULT "no usable sensor"; fields hidden | PASS | `R5_after_ack_both_dropout_SENSOR_FAULT.jpg` |
| R6 | Sensors restored after the outage | **WARNING held, not NORMAL** (old code returned NORMAL here) | Event SENSOR_FAULT→WARNING "WARNING held: 0/6 quiet windows", then WARNING→INSPECT | PASS | `R6_…jpg`, `R7_event_log_ack_and_outage_recovery.jpg` |
| R7 | History trend during the outage | no fault evidence plotted while diagnosis is suspended | **FAIL on first run:** the trend plotted 0.67 (the class-prior value) during the outage, because the logger stored the suspended diagnosis. Fixed in `monitor.py` (suspended windows store no p_fault, fault type, confidence, weights or explanation) + unit test; server restarted | FAIL → fixed | – |
| R8 | Repeat R1, R2, R5, R6 on a new asset after the fix | gap in the evidence trend during the outage; same events | Evidence line has a gap for the outage windows; events NORMAL→WARNING→INSPECT→(ack)WARNING→SENSOR_FAULT→WARNING ("held 0/6")→INSPECT | PASS | `R8_after_fix_trend_gap_during_outage_and_events.jpg` |

## Remaining observations (not changed)
- After acknowledging, or after any sidebar change, the Live tab shows only the message and no state banner until the next run. The message states the state (WARNING), but an operator does not see the coloured banner in that idle view.
- The history chart's x-axis shows fewer points than windows run (8 per 24-window run). This is a display-sampling detail that does not affect the stored data.
- The K004 healthy false alarm (OB1 limitation) is unchanged and not re-tested here.
