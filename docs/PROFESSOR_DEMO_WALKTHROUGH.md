# Professor demo walkthrough (IVHM dashboard v2, 23 Oct 2026)

Reproducible sequence, rehearsed on the real app (Streamlit 1.66, Windows 11 PC, Brave).
Screenshots: `results/starter/ui/dashboard_v2_2026-10-23/` (numbers in brackets below).

## Start
1. Double-click `scripts\windows\run_dashboard.bat`. First run also builds
   `models\rig_models_simulated.pkl` from SIMULATED sessions (pipeline check only).
2. Open http://localhost:8501. Overview shows OB1–OB4 status, pipeline, frozen headline
   results and the honest-reading alert [01, 02].
3. Sidebar → **▶ Start professor demo**. The demo bar appears at the top of every view [03].
   Each step has one button; "Say" is the narration, "Look for" is what was observed in rehearsal.

Every run step replays a **real held-out Paderborn recording** (K004, KA22, KI18 — never used in
training). A recording is 4 s = 8 windows of 0.5 s. Asset names are `demo-<bearing>-<HHMM>`.

| Step | Button | Data | Observed on the real UI |
|---|---|---|---|
| 1 | Inner-race damage detected | KI18 `N15_M07_F10_KI18_1`, clean | WARNING at window 2 (evidence > 0.5 in 2/2), INSPECT at window 4 (> 0.8 in 4/4); inner race 0.84; gate vib 0.77 / cur 0.23; explanation + inspection advice [04–06] |
| 2 | Operator acknowledges | same bearing | INSPECT → **WARNING** (never NORMAL); rule "component condition NOT verified"; warning that ack does not confirm health [07] |
| 3 | Both sensors lost | KI18, dropout on both | SENSOR FAULT for all 8 windows; both sensors FAILED; no probabilities, weights or explanation ("Diagnosis suspended"); advice to check both sensors [08, 09] |
| 4 | Sensors restored | KI18, clean | SENSOR_FAULT → WARNING "WARNING held: 0/6 quiet windows" (not NORMAL), then INSPECT re-latches at window 4 (visible in the audit trail [15]) |
| 5 | Outer-race bearing, vibration failed | KA22 `N15_M07_F10_KA22_1`, vib dropout | Vibration FAILED; gate vib 0.00 / cur 1.00; WARNING; outer race only 0.42; vibration features marked "excluded - sensor failed"; "reduced redundancy" advice [10–12] |
| 6 | Healthy bearing - known false alarm | K004 `N15_M07_F10_K004_1`, clean | WARNING although healthy ('outer race' 0.46): the documented false-alarm limitation [13] |
| 7 | History, audit trail and reports | SQLite log of the KI18 asset | 24 windows, 6 state changes with formatted times and rules, trend with state band, HTML + CSV export [14, 15] |
| 8 | Research evidence and limitations | frozen results/starter | No Holm-significant fusion gain; gated 0.455 vs vib-only 0.470 under withheld faults; confusion matrices; OB2 misses vibration noise; FAR concentrated in K002/K004 [16–21] |

Then **✓ Demo complete - end demo**. The two identical rehearsals (20:50 and 21:15) produced the
same state sequence, so the run is deterministic for these recordings.

## Optional extras
- Live Diagnostics → Mode **Rig - simulated** → condition outer_race → Run: labelled SIMULATED,
  model trained on SIMULATED sessions, asset `sim-rig-1` (not a result) [22].
- Mode **Rig - live**: "Rig not connected" — the physical rig is at design stage; no model, no data [23].
- Switching mode switches the asset name (`bearing-1`, `sim-rig-1`, `rig-1`) so sources never share a log.

## What to say about the negative results
- **False alarms (47 %):** concentrated in two of four healthy bearings (K002 0.75, K004 0.82–0.87);
  each fold trained on only 2–3 healthy bearings; healthy bearings differ from each other about as
  much as from damaged ones. The health rules turn persistent misclassification into alarms.
- **Fusion not significant:** gated fusion beats early (0.405) and average (0.398) fusion under
  withheld sensor faults but not vibration-only (0.470); 0 of 24 paired Wilcoxon tests survive Holm;
  11 overlapping runs on 12 bearings give low power.
- Nothing is re-trained or re-tuned in the dashboard; it reads results/starter unchanged.

## Verification done
- PC: `scripts\windows\run_tests.bat` → 52 tests, OK (1 skipped: the stand-in UI test, replaced by
  the real AppTest suite on the PC). Log: `results/ui_tests/test_log.txt`.
- Downloads: both buttons delivered files whose sizes match the server-side exports
  (HTML 2,707 B, CSV 25,249 B); the HTML report was saved to Downloads.
- Acknowledgement and sensor-failure behaviour checked in steps 2–4 above and in the audit trail.

## Cloud deployment (25 Oct 2026)

- **Public demo URL:** https://ivhm-bearing-health.streamlit.app — opens without sign-in; no PC,
  Python or dataset needed. Click **▶ Start professor demo** and follow the steps above.
- **Hosting:** Streamlit Community Cloud, Python 3.11, from the private GitHub repo
  `benedict5910/pu-fusion`, branch `master`, main file `app/dashboard.py`. Every push to `master`
  redeploys automatically. Manage it at https://share.streamlit.io (app settings → Sharing).
- **Dependencies:** `requirements.txt` (streamlit 1.66.0, altair 6.3.0, pandas 3.0.6, numpy 2.4.6,
  scikit-learn 1.9.1 exactly, scipy 1.x).
- **Verified on the hosted URL:** all eight steps give the same states, probabilities, gate weights
  and audit trail as the PC; HTML and CSV exports download; a second, signed-out browser session
  starts empty and cannot see the first session's history; "Rig - live" shows "Rig not connected".
  Screenshots: `results/starter/ui/cloud_2026-10-25/`.
- **Cloud limitations:** each viewer's history and reports live in a temporary per-session folder
  and are lost when the tab closes or the app restarts (free hosting has no persistent disk). The
  app sleeps after a few days without visitors; the first visit then takes about a minute to wake.
  Free tier: about 1 GB memory (the app needs far less). Times are shown in IST.
- **Data:** only three held-out Paderborn recordings are online (CC BY-NC 4.0, attribution in
  `data/raw/README_DATA.md` and in the app sidebar). Non-commercial academic use only.

### Rollback
- Local app: unchanged; `scripts\windows\run_dashboard.bat` still runs from the PC.
- Code: `git revert <commit>` (or `git reset --hard 62a27b3` for the pre-deployment dashboard) and
  push `master`; the cloud app redeploys. Backup bundles: `C:\Users\Admin\Projects\pu-fusion-*.bundle`.
- Take the demo offline: share.streamlit.io → app ⋮ → Settings → Sharing → "Only specific people",
  or ⋮ → Delete.
