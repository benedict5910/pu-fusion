"""OB4 acceptance verification: one command, one new evidence folder (nothing existing is overwritten).

    python scripts/verify_ob4.py                    ->  results/ob4_cad/verification_<YYYYmmdd-HHMMSS>/

Checks, each recorded in verification.json / verification.md:
  1. frozen models unchanged (SHA-256 against the Nov 15 baseline; gearbox model also against its manifest)
  2. regression replay: the 15 testbed scenarios re-run and compared with results/final/ob4_testbed/testbed.json
     (summaries must be identical; per-window traces equal within 1e-12)
  3. interactive session (ReplaySession, used by the Virtual Testbed view) reproduces every available scenario
  4. single-sensor fallback and dual-sensor abstention observed in the session runs
  5. CAD model: no unexpected interference, sensor map consistent with the replay code, FreeCAD report (if built)
  6. the dashboard and the testbed view do not use the experimental v3_strength fusion
Gearbox items run only when the held-out MCC5-THU recordings are present (data/mcc5, data/mcc5_demo or the
dashboard's temp cache); otherwise they are reported as "not run", never as passed.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion import drivetrain_cad as D  # noqa: E402
from pufusion import testbed as T  # noqa: E402
from pufusion import testbed_session as S  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

BASELINE_SHA256 = {   # recorded from the recovered Nov 15 baseline (OB4_HANDOFF.md: byte-identical to GitHub master)
    "demo_models.pkl": "150f6b41c040417a5f0d386f593dcad053dc140695bf1b6e24d9386b5168ff71",
    "gearbox_demo_1000rpm_10Nm.pkl": "44853e3164e779e98856138f3acdccea3ffedbee5817fde14b0c7ddcae374dc6",
    "rig_models_simulated.pkl": "e8a703428f5cdbab763f0929a081be42fe91a7ed5fbf4384281b4c16d3663d15",
}
REFERENCE = ROOT / "results" / "final" / "ob4_testbed"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _num_equal(a, b, tol=1e-12):
    if a in ("", None) or b in ("", None):
        return a == b
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a == b
    return math.isclose(x, y, rel_tol=0, abs_tol=tol)


def _trace_equal(a, b):
    for ka in a:
        va, vb = a[ka], b.get(ka)
        if isinstance(va, str) and va.startswith("{"):
            da, db = json.loads(va), json.loads(vb)
            if da.keys() != db.keys() or not all(_num_equal(da[k], db[k]) if not isinstance(da[k], str) else da[k] == db[k]
                                                  for k in da):
                return False
        elif not _num_equal(va, vb):
            return False
    return True


def check_models():
    out = []
    man = json.loads((ROOT / "models" / "gearbox_demo_manifest.json").read_text(encoding="utf-8"))
    for name, ref in BASELINE_SHA256.items():
        got = sha256(ROOT / "models" / name)
        out.append({"check": f"frozen model {name} unchanged", "passed": got == ref, "detail": got})
    out.append({"check": "gearbox model matches its manifest",
                "passed": sha256(ROOT / "models" / man["model_file"]) == man["model_sha256"], "detail": man["model_file"]})
    return out


def regression_replay(outdir):
    """Re-run the 15 scenarios exactly as scripts/run_virtual_testbed.py does and compare with the Nov 15 evidence."""
    rdir = outdir / "replay"
    (rdir / "reports").mkdir(parents=True)
    store = HealthStore(rdir / "health.db")
    ctx = T.Context()
    results, traces, skipped = [], [], []
    for scn in T.default_scenarios():
        if scn.subsystem == "gearbox" and (ctx.gearbox is None or scn.recording not in ctx.gearbox_recs):
            skipped.append(scn.name)
            continue
        run = T.run_scenario(scn, ctx, store)
        results.append(T.summarize(scn, run, T.check(scn, run, store)))
        traces += [{"scenario": scn.name, **{k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in w.items()}}
                   for w in run["trace"]]
    events = store.events()
    with open(rdir / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0])); w.writeheader(); w.writerows(events)
    with open(rdir / "traces.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(traces[0])); w.writeheader(); w.writerows(traces)
    store.close()
    n_checks = sum(len(s["checks"]) for s in results)
    n_pass = sum(c["passed"] for s in results for c in s["checks"])
    (rdir / "testbed.json").write_text(encoding="utf-8", data=json.dumps({"scenarios": len(results), "checks": n_checks,
                                                   "checks_passed": n_pass, "results": results}, indent=2))
    ref = json.loads((REFERENCE / "testbed.json").read_text(encoding="utf-8"))
    ref_by = {r["name"]: r for r in ref["results"]}
    same = [r["name"] for r in results if json.dumps(r, sort_keys=True) == json.dumps(ref_by[r["name"]], sort_keys=True)]
    with open(REFERENCE / "traces.csv", newline="", encoding="utf-8") as f:
        ref_tr = [r for r in csv.DictReader(f)]
    with open(rdir / "traces.csv", newline="", encoding="utf-8") as f:
        new_tr = list(csv.DictReader(f))
    ran = {r["name"] for r in results}
    ref_tr = [r for r in ref_tr if r["scenario"] in ran]
    trace_ok = len(ref_tr) == len(new_tr) and all(_trace_equal(a, b) for a, b in zip(new_tr, ref_tr))
    full = not skipped
    return {"scenarios_run": len(results), "scenarios_passed": sum(r["passed"] for r in results),
            "checks": n_checks, "checks_passed": n_pass, "windows": len(new_tr), "events": len(events),
            "skipped_no_data": skipped, "summaries_identical_to_nov15": len(same) == len(results),
            "traces_equal_to_nov15_within_1e-12": trace_ok,
            "matches_documented_15_148": (len(results) == 15 and n_checks == 148 and n_pass == 148) if full else None}


def session_equivalence(tmp):
    ctx = T.Context()
    rows, fallback, abstain = [], [], []
    for scn in T.default_scenarios():
        if scn.subsystem == "gearbox" and (ctx.gearbox is None or scn.recording not in ctx.gearbox_recs):
            rows.append({"scenario": scn.name, "status": "not run (no data)"})
            continue
        rs, ss_ = HealthStore(tmp / f"r-{scn.name}.db"), HealthStore(tmp / f"s-{scn.name}.db")
        ref = T.run_scenario(scn, ctx, rs, asset="a")
        ses = S.run_plan(S.ReplaySession(ctx, scn.subsystem, scn.recording, ss_, "a"), scn)
        got = [S.trace_row(f) for f in ses.frames]
        exact = all(g[k] == r[k] for g, r in zip(got, ref["trace"])
                    for k in ("state", "diagnosis_available", "fault_type", "rule", "status"))
        tol = {"bearing": 1e-9, "gearbox": 1e-6}[scn.subsystem]     # float64 bearing / float32 gearbox data
        dps = [abs(g["p_fault"] - r["p_fault"]) for g, r in zip(got, ref["trace"])
               if g["p_fault"] is not None and r["p_fault"] is not None]
        close = all((g["p_fault"] is None) == (r["p_fault"] is None) for g, r in zip(got, ref["trace"])) and \
            all(d <= tol for d in dps)
        ev = [(e["from_state"], e["to_state"], e["rule"]) for e in rs.events("a")] == \
             [(e["from_state"], e["to_state"], e["rule"]) for e in ss_.events("a")]
        checks = T.check(scn, {"asset": "a", "trace": got, "acks": ses.acks}, ss_)
        rows.append({"scenario": scn.name, "windows": len(got), "states_labels_status_identical": exact,
                     "evidence_tolerance": tol, "evidence_max_abs_diff": max(dps) if dps else 0.0,
                     "evidence_within_tolerance": close, "events_identical": ev,
                     "testbed_checks_on_session_log": f"{sum(p for _, p, _ in checks)}/{len(checks)}",
                     "status": "pass" if exact and close and ev and all(p for _, p, _ in checks) else "FAIL"})
        for g in got:
            failed = [s for s, st in g["status"].items() if st == "failed"]
            if len(failed) == 1:
                fallback.append(g["diagnosis_available"] and (g["weights"][failed[0]] or 0.0) == 0.0)
            elif len(failed) == len(g["status"]):
                abstain.append((not g["diagnosis_available"]) and g["p_fault"] is None
                               and all(v is None for v in g["weights"].values()))
        rs.close(); ss_.close()
    return rows, {"single_sensor_failed_windows": len(fallback), "fallback_ok": all(fallback) and bool(fallback),
                  "all_sensors_failed_windows": len(abstain), "abstention_ok": all(abstain) and bool(abstain)}


def cad_checks():
    inter = D.interference_check(step=0.5)
    fc = ROOT / "cad" / "out" / "freecad_report.json"
    rep = json.loads(fc.read_text(encoding="utf-8")) if fc.exists() else None
    out = {"interference_pairs_checked": inter["pairs_checked"], "unexpected_overlaps": inter["unexpected"],
           "intended_overlaps": inter["overlaps"], "sensor_map": D.sensor_map(),
           "freecad_report": None if rep is None else {k: rep.get(k) for k in (
               "freecad_version", "passed", "all_parts_valid", "bbox_max_deviation_mm", "exports", "step_reimport",
               "edit_test")} | {"brep_unexpected_overlaps": rep["interference"]["unexpected"]}}
    return out


def v3_not_wired():
    files = [ROOT / "app" / "testbed_view.py", ROOT / "src" / "pufusion" / "testbed_session.py",
             ROOT / "src" / "pufusion" / "testbed.py", ROOT / "src" / "pufusion" / "monitor.py"]
    hits = {str(f.relative_to(ROOT)): bool(re.search(r"fusion_v3|v3_strength", f.read_text(encoding="utf-8"))) for f in files}
    dash = (ROOT / "app" / "dashboard.py").read_text(encoding="utf-8")
    imports_v3 = bool(re.search(r"^\s*(from|import)\s+.*fusion_v3", dash, re.M))
    live_model = 'bundle["models"]["gated_both"]' in dash
    return {"no_v3_in_replay_code": not any(hits.values()), "files": hits,
            "dashboard_imports_fusion_v3": imports_v3, "live_views_use_gated_both": live_model}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(a.out) if a.out else ROOT / "results" / "ob4_cad" / f"verification_{stamp}"
    if outdir.exists():
        raise SystemExit(f"{outdir} exists; refusing to overwrite evidence")
    outdir.mkdir(parents=True)
    t0 = time.time()
    rep = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
           "gearbox_data": str(T.gearbox_data_dir()) if T.gearbox_data_dir() else None}
    rep["models"] = check_models()
    rep["regression_replay"] = regression_replay(outdir)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        rep["session_equivalence"], rep["fallback_abstention"] = session_equivalence(Path(tmp))
    rep["cad"] = cad_checks()
    rep["v3_strength"] = v3_not_wired()
    rr, fa, v3 = rep["regression_replay"], rep["fallback_abstention"], rep["v3_strength"]
    verdict = {
        "frozen models unchanged": all(c["passed"] for c in rep["models"]),
        "regression replay: all run scenarios pass": rr["scenarios_passed"] == rr["scenarios_run"] and rr["checks"] == rr["checks_passed"],
        "regression replay identical to Nov 15 evidence": rr["summaries_identical_to_nov15"] and rr["traces_equal_to_nov15_within_1e-12"],
        "documented 15 scenarios / 148 checks reproduced": rr["matches_documented_15_148"],
        "interactive session reproduces every scenario run": all(r["status"] == "pass" for r in rep["session_equivalence"] if r["status"] != "not run (no data)"),
        "single-sensor fallback verified": fa["fallback_ok"],
        "dual-sensor abstention verified": fa["abstention_ok"],
        "CAD: no unexpected interference": not rep["cad"]["unexpected_overlaps"],
        "CAD: FreeCAD build report passed": (rep["cad"]["freecad_report"] or {}).get("passed"),
        "v3_strength not used by replay or live views": v3["no_v3_in_replay_code"] and not v3["dashboard_imports_fusion_v3"] and v3["live_views_use_gated_both"],
    }
    rep["verdict"] = verdict
    rep["seconds"] = round(time.time() - t0, 1)
    (outdir / "verification.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    lines = [f"# OB4 verification {rep['generated']}", "",
             f"Python {rep['python']}; gearbox recordings: {rep['gearbox_data'] or 'NOT PRESENT (gearbox items not run)'}", "",
             "| Item | Result |", "|---|---|"]
    lines += [f"| {k} | {'PASS' if v is True else ('NOT RUN' if v is None else 'FAIL')} |" for k, v in verdict.items()]
    lines += ["", f"Regression replay: {rr['scenarios_passed']}/{rr['scenarios_run']} scenarios, {rr['checks_passed']}/{rr['checks']} "
              f"checks, {rr['windows']} windows, {rr['events']} events; not run (no data): {rr['skipped_no_data'] or 'none'}.",
              f"Fallback windows: {fa['single_sensor_failed_windows']}; abstention windows: {fa['all_sensors_failed_windows']}.", "",
              "| Scenario | Session vs batch |", "|---|---|"]
    lines += [f"| {r['scenario']} | {r['status']} {r.get('testbed_checks_on_session_log', '')} |" for r in rep["session_equivalence"]]
    (outdir / "verification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nevidence: {outdir}")
    hard_fail = [k for k, v in verdict.items() if v is False]
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
