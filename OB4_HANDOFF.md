# OB4 CAD and simulation handoff

Open this folder in Claude as the November 15, 2026 IVHM baseline.

- Source archive: `E:\ivhm-data\results\final_2026-11-15\pu-fusion_final_2026-11-15.zip`.
- Archive SHA-256: `c81db673744556f607b46453a21a2bfc954a963375abcd760ce5449b0b4e4168`.
- GitHub reference checkout: `C:\Users\Admin\Projects\pu-fusion-current`. The full checkout matches all five current remote tips. GitHub master is `8d0e952d75674e6ad5bf3fc72c0de31772181759`; gearbox-v0 is `2385a6c19432fdde6270bebe6980ae9f1292ef52`. The fetched history lacks the two OB4 entry points. This recovered baseline has archive provenance. Its three frozen model files are byte-identical to GitHub master, and the frozen gearbox model matches its SHA-256 manifest.

## Where to start

- Read `docs/FINAL_OB1_OB2_OB4_2026-11-15.md` for the validation scope and known behavior. See `IVHM_SPEC.md`, `docs/drawings/` and `docs/calcs/` for design references.
- Use `scripts/run_virtual_testbed.py`, `src/pufusion/testbed.py` and `src/pufusion/gearbox.py` to locate the replay and diagnosis interfaces.
- The verified baseline replays held-out Paderborn bearing and MCC5-THU gearbox recordings with synthetic sensor faults. Use this as the software regression baseline when adding CAD or physics-based simulated inputs. Report any new physical-model validation separately.
- Run `python -m unittest discover -s tests`. The Windows run completed with 75 passed, 10 skipped and zero failures out of 85.
- Run `python scripts/run_virtual_testbed.py --out verification/replay-next` from this folder, with a fresh output directory on each run. The runner replaces health.db in its selected output directory. Bearing recordings are under data/raw. For gearbox recordings, the runner searches data/mcc5, data/mcc5_demo, and the Windows temp cache ivhm_mcc5_demo in order. Use --gearbox-data to point to an explicit recordings folder if needed.

## Verification on Windows

Fresh replay outputs are under `verification/replay-16b073a39b454e8fbceb6623b2eb31e3/`. All 15 scenarios and 148 checks passed across 549 windows and 36 events. The parsed testbed JSON matches the November 15 results exactly. The event CSV and archived summary JSON are byte-identical to the saved copies. The trace differs in one vibration weight, from 0.15612733508114357 to 0.1561273350811436.
