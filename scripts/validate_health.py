"""OB3 headless validation on REAL held-out Paderborn recordings, using the same components
as the dashboard (BenchmarkDiagnoser -> HealthTracker -> HealthStore, explanations).

For each demo bearing (never seen by the demo model) and each scenario, the recording windows of
all available files are replayed in order; a sensor fault is injected from the 5th window on.
Reports the health-state trace, SENSOR_FAULT behaviour, explanation faithfulness, and writes the
SQLite history plus CSV/HTML reports exactly as the dashboard does.

  python scripts/validate_health.py --model models/demo_models.pkl --raw data/raw --out results/starter/ob3
"""
import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import CLASS_NAMES  # noqa: E402
from pufusion.data import find_mat_files, load_mat, windows  # noqa: E402
from pufusion.dataset import corrupt_pair  # noqa: E402
from pufusion.health import HealthTracker  # noqa: E402
from pufusion.monitor import SOURCE_BENCHMARK, BenchmarkDiagnoser, MonitorEngine  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

SCENARIOS = [("none", None, None), ("vib", "dropout", None), ("vib", "stuck", None),
             ("vib", "spikes", 1000), ("cur", "dropout", None), ("both", "dropout", None)]
INJECT_AT = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-files", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bundle = pickle.load(open(a.model, "rb"))
    diag = BenchmarkDiagnoser(bundle["models"]["gated_both"], bundle["assessors"])
    db = out / "health_validation.db"
    if db.exists():
        db.unlink()
    store = HealthStore(db)
    rows = []
    faith = []
    for bearing in bundle["holdout"]:
        files = [f for f in find_mat_files(a.raw) if f.stem.split("_")[3] == bearing
                 and f.stem.startswith("N15_M07_F10")][: a.max_files]
        recs = [load_mat(f) for f in files]
        truth = CLASS_NAMES[recs[0].label]
        for mod, fam, sev in SCENARIOS:
            name = "clean" if mod == "none" else f"{fam}@{mod}"
            asset = f"{bearing}|{name}"
            eng = MonitorEngine(diag, SOURCE_BENCHMARK, asset, store, HealthTracker())
            states, preds, pf = [], [], []
            k = 0
            for rec in recs:
                for i, v, c in windows(rec):
                    if mod != "none" and k >= INJECT_AT:
                        v, c = corrupt_pair(v, c, mod, fam, sev, np.random.default_rng(k))
                    o = eng.step({"vib": v, "cur": c, "fs": rec.fs, "condition": rec.condition}, ts=1e9 + k)
                    states.append(o["assessment"].state)
                    preds.append(o["fault_type"] or "healthy")
                    pf.append(o["p_fault"])
                    e = o["diagnosis"].get("explanation")
                    if e and mod == "none":
                        faith.append([e["faithfulness_drop"]["vibration"], e["faithfulness_drop"]["current"]])
                    k += 1
            first = {s: (states.index(s) if s in states else None) for s in ("WARNING", "INSPECT", "SENSOR_FAULT")}
            post = states[INJECT_AT:] if mod != "none" else states
            rows.append({"bearing": bearing, "truth": truth, "scenario": name, "windows": len(states),
                         "state_counts": dict(Counter(states)), "final_state": states[-1],
                         "first_window": first, "frac_correct_type": float(np.mean(
                             [p == truth for p in preds])),
                         "frac_SENSOR_FAULT_after_injection": float(np.mean([s == "SENSOR_FAULT" for s in post])),
                         "mean_p_fault": float(np.nanmean([p if p is not None else np.nan for p in pf]))})
            store.export_csv(out / f"history_{bearing}_{name}.csv", asset)
            store.export_html(out / f"report_{bearing}_{name}.html", asset)
            print(f"{bearing:5s} ({truth:10s}) {name:15s} final={states[-1]:12s} counts={dict(Counter(states))}")
    fa = np.array(faith) if faith else np.zeros((0, 2))
    summary = {"model_trained_on": bundle["trained_on"], "demo_bearings_unseen": bundle["holdout"],
               "inject_from_window": INJECT_AT, "scenarios": rows,
               "explanation_faithfulness_mean_prob_drop": {"vibration": float(fa[:, 0].mean()) if len(fa) else None,
                                                           "current": float(fa[:, 1].mean()) if len(fa) else None,
                                                           "n_windows": int(len(fa))}}
    (out / "ob3_validation.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary["explanation_faithfulness_mean_prob_drop"]))


if __name__ == "__main__":
    main()
