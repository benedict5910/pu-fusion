# Safety audit of health-state and dashboard behaviour (22 Oct 2026)

Scope: `src/pufusion/health.py`, `src/pufusion/monitor.py`, `app/dashboard.py`. Question: can the
system tell an operator, explicitly or by implication, that a component is healthy when the data do
not show that? Models, thresholds and the frozen OB1/OB2 results are unchanged; no tuning was done on
held-out bearings. Tests: 38/38 pass (`python -m unittest discover -s tests`).

## 1. INSPECT acknowledgement (finding: unsafe, fixed in commit 6d7401b)
**Before:** acknowledging a latched INSPECT set the state to **NORMAL** and cleared the evidence
history. The banner turned NORMAL / "no persistent fault evidence" although nothing about the bearing
had been checked, and the acknowledgement itself was not logged (UI validation issue 2).

**Now:**
- Acknowledge only acts on INSPECT. Otherwise the dashboard says "Nothing to acknowledge".
- The state drops to **WARNING, never NORMAL**.
- The event is logged with the rule "INSPECT acknowledged by operator - component condition NOT verified; monitoring continues", and the operator sees a warning saying the same thing.
- Escalation is then judged only on evidence recorded after the acknowledgement. If the fault persists, INSPECT re-latches within `inspect_k` = 4 windows.
- NORMAL needs `recover_n` = 6 consecutive quiet windows of new data.

**Tests:**
- `test_escalation_latch_and_ack`
- `test_ack_does_not_hide_persistent_fault`
- `test_ack_only_applies_to_inspect`

## 2. Sensor outage shortcut in WARNING recovery (finding: unsafe edge case, fixed 22 Oct)
**Before:** while a WARNING was being held for its 6 quiet windows, a total sensor outage changed the
state to SENSOR_FAULT. When the sensors came back, the "WARNING held" rule no longer applied, so the
first good window could return **NORMAL** after one quiet window instead of six.

**Now:** the tracker remembers the state from before the outage and resumes it, so the full recovery
requirement still applies. Test: `TestOutageRecovery`. It fails on the old code and passes on the fix.

## 3. Other dashboard behaviour (fixed in commit 6d7401b)
| Issue | Risk | Change |
|---|---|---|
| Sensor weights shown when both sensors had failed (UI issue 1) | Implies a diagnosis is based on data | The page shows "Diagnosis suspended"; weights and probabilities are hidden |
| Class probabilities shown during SENSOR_FAULT | Same | Hidden while `diagnosis_available` is false |
| Explanation computed on dead signals | Explains noise as if it were evidence | Explanation not shown while diagnosis is suspended |
| Tracker history carried across recordings (UI issue 4) | Evidence from one recording affects another | Tracker resets when the recording changes |
| Rig DS18B20 absent → −127 °C stored as a temperature | False reading in logs and reports | Stored as "no temperature" (`_temp_or_none`) |
| Event times shown as raw epoch seconds (UI issue 3) | Hard to audit | Formatted |
| `pyserial` missing from requirements | "Rig - live" would fail on a fresh laptop | Added to `requirements.txt` |

## 4. Reviewed and left as designed
- **A latched INSPECT stays during a total sensor outage.** The rule shows "no usable sensor" and the diagnosis is suspended. An outage never clears an alert.
- **One sensor failed:** the diagnosis continues on the other sensor, and the dashboard says "relies on … only (reduced redundancy)".
- **There is no remaining-useful-life estimate.** The data contain discrete damage states, not degradation trajectories.

## 5. Known limitations (not safety bugs, not changed)
- **False alarm on healthy bearing K004.** It reaches INSPECT on clean data, a model limitation shown in the OB1 audit. The window false-alarm rate is about 0.45, coming from K002/K004. It was not tuned away.
- **Vibration noise, spikes and gain faults are mostly not flagged by OB2.** The cause is the spectral-flatness bound issue in `AUDIT_2026-10-21.md`. Until that is fixed on training bearings only, a noisy accelerometer can pass as "ok".

## 6. Re-validation needed
The dashboard changes in §1–§3 were exercised with a scripted Streamlit stand-in and unit tests, not
yet on the real laptop UI. The OB3 UI validation of 21 Oct covered the pre-fix behaviour. Re-run steps 5–7 of
`UI_VALIDATION_2026-10-21.md` on the laptop (acknowledge → WARNING with warning text, event logged,
both-sensor dropout → "Diagnosis suspended" with no weights) and add the screenshots to `results/starter/ui/`.
