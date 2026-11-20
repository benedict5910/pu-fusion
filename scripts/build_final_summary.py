"""Collect the verified final results into one small file the dashboard reads (results/final/summary.json).

Only copies numbers from result files written by the evaluation scripts; nothing is recomputed:
  results/full_2026-11-15/ob_final/ob_final_results.json, leakage_audit.json     bearing, full Paderborn set
  results/gating_research/gating_research_results.json, final_validation/*        reliability-aware fusion
  results/final/gearbox/*.json                                                    gearbox
  results/final/ob4_testbed/testbed.json                                          virtual testbed

  python scripts/build_final_summary.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
J = lambda p: json.loads((R / p).read_text())  # noqa: E731


def main():
    full = J("full_2026-11-15/ob_final/ob_final_results.json")["run_level"]
    gr = J("gating_research/gating_research_results.json")
    fv = J("gating_research/final_validation/final_tables.json")
    val = J("gating_research/final_validation/validation.json")
    leak = J("full_2026-11-15/leakage_audit.json")
    order = ["vib_only", "cur_only", "early_fusion", "late_average", "late_stacked", "gated_both", "gated_v2", "v3_strength"]
    rows = []
    for m in order:
        src = gr["run_level"].get(m) or full[m]
        rows.append({"model": m, **{g: src[g]["macro_f1"]["mean"] for g in ("clean", "seen", "withheld")},
                     "clean_sd": src["clean"]["macro_f1"]["sd"], "coverage_seen": src["seen"]["coverage"]["mean"],
                     "false_alarm_clean": src["clean"]["false_alarm_rate"]["mean"]})
    t = {(x["unit"], x["group"], x["vs"]): x for x in gr["tests"] if x["model"] == "v3_strength"}
    dual = {m: {"coverage": fv["scenario_table"][m]["dual_failure"]["coverage"]["mean"],
                "fault_class_issued": fv["scenario_table"][m]["dual_failure"]["fault_class_issued"]["mean"]}
            for m in fv["scenario_table"]}
    n_leak = f"{leak['n_checks']}/{leak['n_checks']}" if leak["all_pass"] else "FAILED"
    bearing = {
        "data": "Paderborn, 28 bearings, 2,240 recordings; 15 bearing-disjoint runs, 17 held-out bearings",
        "windows_per_model": gr["eval_windows_per_model"], "models": rows,
        "v3_vs_vib_only": {g: {"diff": t[("run", g, "vib_only")]["mean_diff"], "p_holm": t[("run", g, "vib_only")]["p_holm"]}
                           for g in ("clean", "seen", "withheld")},
        "v3_vs_hard_gating_seen": {"diff": t[("run", "seen", "gated_v2")]["mean_diff"], "p_holm": t[("run", "seen", "gated_v2")]["p_holm"]},
        "dual_failure": {"windows": fv["windows_per_model"]["dual_failure"], "models": dual},
        "raw_end_to_end_recordings": val["raw_end_to_end"]["recordings"] if val.get("raw_end_to_end") else None,
        "leakage_checks_passed": n_leak,
        "note": "v3_strength results are exploratory: the rule was designed after analysing this test set.",
    }
    ga, gb = J("final/gearbox/ob1_pilot_summary.json"), J("final/gearbox/ob2_heldout_profile.json")
    methods = ["motor", "gearbox", "early", "late_average", "gated"]
    pilot = [{"scenario": sc, **{m: v[m]["window_macro_f1"] for m in methods}, "gated_coverage": v["gated"]["coverage"],
              "gated_fold_min": v["gated"]["fold_min"], "gated_fold_max": v["gated"]["fold_max"]}
             for sc, v in ga["scenarios"].items()]
    sweep = [{"scenario": sc, "motor_flagged": v["flagged"]["motor"], "gearbox_flagged": v["flagged"]["gearbox"],
              **{m: v["methods"][m]["macro_f1"] for m in methods}, "gated_coverage": v["methods"]["gated"]["coverage"],
              "gated_false_alarms": v["methods"]["gated"]["false_alarm_rate"]}
             for sc, v in gb["severity_sweep"].items()]
    cl = ga["scenarios"]["clean"]
    gearbox = {
        "pilot": {"folds": len(ga["folds"]), "recordings": ga["recordings"], "windows": cl["gated"]["windows"], "rows": pilot,
                  "clean": {m: {k: cl[m][k] for k in ("window_macro_f1", "fold_min", "fold_max", "accuracy",
                                                      "false_alarm_rate", "missed_fault_rate", "recording_macro_f1")}
                            for m in methods},
                  "flag_rate": ga["flag_rate"]},
        "heldout_profile": {"condition": gb["condition"], "recordings": len(gb["test_recordings"]),
                            "windows": gb["severity_sweep"]["clean"]["windows"],
                            "reproduction": gb["reproduction_of_stored_fold"], "rows": sweep},
        "note": "12 pilot recordings, one bench, medium-severity pitting and wear only; descriptive, no significance test. "
                "The raw re-evaluation covers one of the four held-out profiles (the easiest one).",
    }
    tb = J("final/ob4_testbed/testbed.json")
    testbed = {k: tb[k] for k in ("scenarios", "scenarios_passed", "checks", "checks_passed", "windows", "events_logged", "data")}
    testbed["rows"] = [{"scenario": s["name"], "subsystem": s["subsystem"], "purpose": s["purpose"], "windows": s["windows"],
                        "segments": " → ".join(f"{g['fault']} [{g['end_state']}, {g['diagnosis_coverage']:.0%} diagnosed]"
                                               for g in s["segments"]),
                        "first WARNING": s["first_WARNING"], "first INSPECT": s["first_INSPECT"],
                        "first SENSOR_FAULT": s["first_SENSOR_FAULT"], "final state": s["final_state"],
                        "checks passed": f"{sum(c['passed'] for c in s['checks'])}/{len(s['checks'])}"}
                       for s in tb["results"]]
    out = {"generated": "2026-11-15", "bearing": bearing, "gearbox": gearbox, "testbed": testbed}
    (R / "final").mkdir(exist_ok=True)
    (R / "final" / "summary.json").write_text(json.dumps(out, indent=2))
    print("wrote results/final/summary.json", {k: len(json.dumps(v)) for k, v in out.items() if k != "generated"})
    print("leakage checks passed:", n_leak)


if __name__ == "__main__":
    main()
