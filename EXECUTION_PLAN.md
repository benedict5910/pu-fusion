# Execution plan: 19 Oct to 28 Oct 2026 progress presentation

**Target for 28 Oct:** OB1, OB2 and OB3 completed with measured evidence on real Paderborn data.
OB4 shown as a hardware-ready package with as much bring-up evidence as the parts allow.
**Critical path:** Paderborn data on the laptop. Everything in OB1-OB3 is waiting on it.

| Date | Benchmark (OB1/OB2) | Health layer (OB3) | Rig (OB4, parallel) | Gate / evidence by end of day |
|---|---|---|---|---|
| Mon 19 | Audit; pipeline rebuilt to spec; synthetic plumbing tests pass | Engine, store, dashboard coded | Firmware + host software written; host tested on synthetic stream | **Download started** (laptop) |
| Tue 20 | Extract RARs; verify 32 bearings x 4 conditions x 20 runs, channel names, 64 kHz; feature extraction | - | Buy parts (ESP32, ADXL345, ACS712, A3144, motor + bearings, PSU) | Data verification report |
| Wed 21 | Full P1 + P2 + P3 + leakage run; figures; Wilcoxon/Holm | Export demo model from P1 fold-0 training bearings | Flash firmware; ADXL345 DEVID check | `results/RESULTS_SUMMARY.md` v1 |
| Thu 22 | OB2 table + ablations; sanity checks (vib-only vs ref [9]); **freeze benchmark config - no tuning on test results** | OB3 headless validation on held-out streams | Wire current + Hall; first timing test | OB1 + OB2 evidence complete |
| Fri 23 | Buffer for reruns / bug fixes only | Launch dashboard on laptop; screenshots of each state, report, history | Timing acceptance test PASS (target) | OB3 evidence complete |
| Sat 24 | - | Guide/team dry-run of the demo | Record H1, H2 (healthy) | Demo checklist signed off |
| Sun 25 | - | - | Record H3, H4 + fault session(s) if a faulty bearing is available; run detector | OB4 bring-up evidence (whatever exists) |
| Mon 26 | Progress deck: methods recap, results, figures, honest limitations | Screenshots into deck | Rig photos/timing report into deck | Deck v1 |
| Tue 27 | Final evidence log + remaining-work summary; rehearsal x2 | Backup video of dashboard | - | **All deliverables frozen 6 pm** |
| Wed 28 | **Presentation** | | | |

## Rules
- Never present synthetic outputs as results. Every figure is stamped with its data source.
- Benchmark configuration is frozen on 22 Oct. Later changes are bug fixes only, logged in the evidence log.
- A negative finding (gate does not beat vibration-only) is reported as it is.
- No new features, no topic change.

## Blockers to watch
1. Paderborn download (several GB) and RAR extraction run on the laptop. Owner: team.
2. Streamlit runs on the laptop only (the cloud workspace has no package access).
3. OB4 depends on parts arriving. If they arrive late, OB4 is presented as "firmware + host software ready; bring-up pending".
