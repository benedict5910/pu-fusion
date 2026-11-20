# OB4 virtual testbed - demonstration guide (about 8 minutes)

Start: `scripts\windows\run_integrated_dashboard.bat`, open http://localhost:8520, choose view **Virtual Testbed**.
Set "Seconds per window" to 0.3 so the audience can follow.

Say first: "This is recorded-signal replay with controlled sensor-fault injection on a representative drivetrain.
The recordings are real and were never used in training; the sensor faults are synthetic; the CAD model shows
where each sensor sits - it is not a physics simulation and not either laboratory bench."

| # | Do | Point out |
|---|---|---|
| 1 | Subsystem **Bearing**, recording **KI18 (inner-race damage)**, sensor **none**. Press **Step** twice, then **Run** (stop after 12). | Test-bearing housing turns WARNING then INSPECT (orange, red). S1 and S2 green. Inner-race probability dominates; explanation lists the features. Timeline shows the transitions. |
| 2 | Press **Acknowledge INSPECT**. | State drops to WARNING, never NORMAL; the event log records the acknowledgement. |
| 3 | Sensor **vib**, fault **dropout**, press **Step** 3 times. | S1 turns red (failed), vibration weight 0.00, diagnosis continues on current only: single-sensor fallback. Waveform of S1 is flat. |
| 4 | Sensor **both**, fault **stuck**, **Step** 3 times. | Both sensors red, "Diagnosis suspended": no probabilities, no weights - the system abstains instead of guessing (INSPECT stays latched if it was latched). |
| 5 | Sensor **none**, **Step** 4 times. | Diagnosis resumes; state does not jump to NORMAL. |
| 6 | **Reset**, recording **K004 (healthy)**, **Run**. | Known limitation shown honestly: healthy K004 sits in WARNING (false alarm). |
| 7 | Subsystem **Gearbox**, recording **gear pitting**, **Run** (stop after 20). | Gearbox housing escalates to INSPECT; S3/S4 active, S1/S2 greyed. |
| 8 | Sensor **motor**, fault **dropout**, **Step** 3 times; then sensor **gearbox**, fault **noise**, **Step** 3. | Motor sensor weight 0 - gearbox sensor carries the diagnosis; noise down-weights (not excludes) the gearbox sensor. |
| 9 | Open **History & Reports**, pick the `vt-...` asset. | Every replayed window and state change is in the SQLite audit trail; CSV/HTML export. |
| 10 | Show `cad/out/drawings/ivhm_drivetrain_drawings.pdf` and the FCStd in FreeCAD. | Editable parametric assembly, STEP export, sensor map S1-S4 with dataset channels. |

If asked "is it validated?": the replay chain is the verified OB4 testbed (15 scenarios, 148 checks, reproduced
against the 15 Nov evidence); the interactive view reproduces those scenarios window for window (tests); the CAD
is checked for interference and against the parameter model. Model accuracy figures are the frozen OB1/OB2 results,
not something this view measures.
