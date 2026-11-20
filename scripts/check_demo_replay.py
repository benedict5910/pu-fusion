"""Reproducibility check: replay the committed demo model on the three committed held-out
recordings and compare against the values documented in docs/PROFESSOR_DEMO_WALKTHROUGH.md
(steps 1, 5 and 6, observed on the real dashboard on 23 Oct 2026).

Needs only files that are in the repository (models/demo_models.pkl, data/raw/{K004,KA22,KI18}).
Read-only: nothing is trained, written or changed.

  python scripts/check_demo_replay.py
Exit code 0 = every documented value reproduced; 1 = at least one mismatch.
"""
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion.data import load_mat, windows  # noqa: E402
from pufusion.dataset import corrupt_pair  # noqa: E402
from pufusion.health import HealthTracker  # noqa: E402
from pufusion.monitor import SOURCE_BENCHMARK, BenchmarkDiagnoser, MonitorEngine  # noqa: E402

# (bearing, sensor with dropout from window 1 or None) -> documented observations
EXPECTED = {
    ("KI18", None): {"first_WARNING": 2, "first_INSPECT": 4, "final_state": "INSPECT",
                     "final_class": "inner_race", "final_p": 0.84, "final_w_vib": 0.77},
    ("KA22", "vib"): {"final_state": "WARNING", "final_class": "outer_race", "final_p": 0.42,
                      "final_w_vib": 0.00},
    ("K004", None): {"final_state": "WARNING", "final_class": "outer_race", "final_p": 0.46},
}
TOL = 0.005   # values were documented to two decimals


def replay(model, assessors, bearing, dead):
    rec = load_mat(ROOT / "data" / "raw" / bearing / f"N15_M07_F10_{bearing}_1.mat")
    eng = MonitorEngine(BenchmarkDiagnoser(model, assessors), SOURCE_BENCHMARK, tracker=HealthTracker())
    trace = []
    for _, v, c in windows(rec):
        if dead:
            v, c = corrupt_pair(v, c, dead, "dropout", None, np.random.default_rng(0))
        r = eng.step({"vib": v, "cur": c, "fs": rec.fs, "condition": rec.condition})
        trace.append((r["state"], r["diagnosis"]["probs"], r["diagnosis"].get("weights", {})))
    return trace


def main():
    with open(ROOT / "models" / "demo_models.pkl", "rb") as f:
        pkg = pickle.load(f)
    print("demo model trained on:", ", ".join(map(str, pkg["trained_on"])))
    print("held out (replayed here):", ", ".join(pkg["holdout"]))
    model, ok = pkg["models"]["gated_both"], True
    for (bearing, dead), exp in EXPECTED.items():
        trace = replay(model, pkg["assessors"], bearing, dead)
        states = [s for s, _, _ in trace]
        state, probs, w = trace[-1]
        got = {"final_state": state, "final_class": max(probs, key=probs.get),
               "final_p": probs[exp["final_class"]], "final_w_vib": w.get("vib")}
        for s in ("WARNING", "INSPECT"):
            got[f"first_{s}"] = states.index(s) + 1 if s in states else None
        print(f"\n{bearing} {'dropout@' + dead if dead else 'clean'}: states {states}")
        for k, v in exp.items():
            g = got[k]
            match = abs(g - v) <= TOL if isinstance(v, float) else g == v
            ok &= match
            shown = f"{g:.3f}" if isinstance(g, float) else g
            print(f"  {k:14s} documented {v!s:10s} reproduced {shown!s:10s} {'OK' if match else 'MISMATCH'}")
    print("\nALL DOCUMENTED VALUES REPRODUCED" if ok else "\nMISMATCH FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
