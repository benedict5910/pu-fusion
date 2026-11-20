# OB3 dashboard UI validation (21 Oct 2026, 22:15-22:22 IST)

**Setup:** Streamlit dashboard (`app/dashboard.py`) on the team laptop, launched with
`scripts\windows\run_dashboard.bat`, and operated through Chrome at http://localhost:8501.
- **Demo model:** trained on the laptop from `data/features_starter.npz`, using 9 bearings.
- **Replayed bearings:** K004 (healthy), KA22 (outer race) and KI18 (inner race). The model never
  saw these during training.
- **Data:** real Paderborn recordings, mode "Benchmark replay".

| # | Step | Expected | Observed | Result | Screenshot |
|---|---|---|---|---|---|
| 1 | KI18 (inner race), N15_M07_F10 run 1, no injected fault | warning, then latched INSPECT; inner race | INSPECT latched; healthy 0.06 / outer 0.09 / **inner 0.84**; both sensors ok; gate vib 0.77 / cur 0.23; advice to inspect the inner ring | PASS | `results/starter/ui/01_KI18_clean_INSPECT.jpg` |
| 2 | Explanation panel | top features + faithfulness | top vibration evidence `env_1xfr, band7, env_1xbpfi`; top current evidence `h3_db, band2, resid_kurt`; gate drivers vib flatness/entropy/dominance; deletion drop vib 0.39 / cur 0.02 | PASS | `02_KI18_explanation_and_advice.jpg` |
| 3 | Acknowledge INSPECT | back to NORMAL | "Acknowledged - state reset to NORMAL" | PASS | `03_acknowledge_INSPECT_reset_NORMAL.jpg` |
| 4 | Same recording, vibration dropout injected | vibration flagged, diagnosis on current only | vib **failed** (dead or stuck); gate vib 0.00 / cur 1.00; WARNING; advice to check the accelerometer; "diagnosis relies on current only". Fault type misread with current alone (outer 0.41 vs inner 0.31), consistent with the weak current-only benchmark score | PASS (behaviour); diagnosis degraded as expected | `04_vib_dropout_WARNING_current_only.jpg` |
| 5 | Both sensors dropped | SENSOR_FAULT, diagnosis suspended | SENSOR_FAULT "no usable sensor"; class probabilities fall back to the prior (0.33 each); advice for both sensors | PASS (see issue 1) | `05_both_dropout_SENSOR_FAULT.jpg` |
| 6 | K004 (healthy), new asset, no fault | ideally NORMAL | **WARNING** (evidence > 0.5 in 6/6 windows; outer 0.46 vs healthy 0.27). This is the known false alarm on an unlike healthy bearing (`docs/AUDIT_2026-10-21.md`) | Known limitation, shown openly | `06_K004_healthy_false_alarm_WARNING.jpg` |
| 7 | History & reports tab, both downloads | trend, event table, CSV + HTML | evidence/reliability trend; event table NORMAL→WARNING with rule; both downloads succeed | PASS | `07_history_events_and_report_downloads.jpg` |
| 8 | Persistence check (files written by the app) | SQLite + exports contain the session | `health.db`: 32 windows, 5 state-change events (NORMAL→WARNING, WARNING→INSPECT, NORMAL→WARNING after acknowledge, WARNING→SENSOR_FAULT; K004 NORMAL→WARNING). CSV: 24 rows for bearing-1 covering all four states. HTML report: time in each state, state changes with rule and advice, data-source note | PASS | `results/starter/ui/exports/` |

**Verdict:** OB3's dashboard, health states, explanations, logging and report export are validated
end to end on real held-out recordings. The diagnostic quality behind them is the OB1 result, false
alarm on K004 included.

## Known issues found (logged, not changed before the review)
1. **Misleading weights display.** With both sensors failed, the "Sensor weights" line still shows
   the gate's raw weights (vib 0.78 / cur 0.22). The prediction itself correctly uses the class
   prior. The hard mask in `ReliabilityGated.weights` covers only the one-sensor-dead cases.
2. **Acknowledgement not logged.** An operator acknowledgement resets the state but is not written
   as its own event; it shows only indirectly, as a new NORMAL→WARNING.
3. **Raw timestamps.** The event table shows raw epoch seconds. The HTML report formats them
   correctly.
4. **Tracker scoped to the asset name, not the recording.** Changing only the recording keeps the
   previous state history. The demo therefore uses a new asset name per bearing.
