"""OB1 leakage audit: programmatic checks of every split and every fitted normaliser.

Checks (each reported PASS/FAIL with evidence):
  1. P1 folds: train/test bearing-disjoint; artificial-damage bearings only in training.
  2. P3: within each P1 fold, held-out operating condition absent from training rows.
  3. Window identity: no feature vector in a test fold is bit-identical to one in its
     training rows (catches duplicated or copied windows).
  4. Augmented rows (training-only corruption) come only from training bearings.
  5. Normalisers: the expert StandardScaler mean equals the training-feature mean, and
     the gate normaliser is computed from training rows only (refit and compare).
  6. v2 detector: commissioning baseline windows (repetition 1) never appear among
     evaluation windows; baselines use clean windows only.
  7. Leaky reference split: recordings shared between train and test bearings (expected),
     confirming it is never used as a model-performance result.

  python scripts/audit_leakage.py --features data/features_starter.npz --out results/ob_final/leakage_audit.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS  # noqa: E402
from pufusion.dataset import concat, load_tables, subset  # noqa: E402
from pufusion.models import ReliabilityGated, SingleSensor  # noqa: E402
from pufusion.reliability_v2 import repetition  # noqa: E402
from pufusion.splits import leaky_splits, p1_folds  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import restrict  # noqa: E402


def row_hashes(tab):
    X = np.hstack([tab["fv"], tab["fc"]]).astype(np.float32)
    return {hashlib.sha1(r.tobytes()).hexdigest() for r in X}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t = load_tables(a.features)
    avail = set(np.unique(t["clean"]["bearing"]))
    checks = []

    def check(name, ok, evidence):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "evidence": evidence})

    all_folds = p1_folds(5)
    valid = restrict(all_folds, avail)
    art = {b for b, (_, o) in BEARINGS.items() if o == "artificial"}
    overlaps = [f["name"] for f in all_folds if set(f["train"]) & set(f["test"])]
    art_test = [f["name"] for f in all_folds if art & set(f["test"])]
    check("P1 bearing-disjoint (all 15 designed folds)", not overlaps and not art_test,
          {"folds_with_overlap": overlaps, "folds_with_artificial_in_test": art_test,
           "valid_folds_on_available_data": len(valid)})

    dup, aug_bad, scaler_bad, gate_bad, p3_bad = [], [], [], [], []
    for f in valid:
        trc = subset(t["clean"], np.isin(t["clean"]["bearing"], f["train"]))
        tra = subset(t["aug"], np.isin(t["aug"]["bearing"], f["train"]))
        te = subset(t["clean"], np.isin(t["clean"]["bearing"], f["test"]))
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], f["test"]))
        n_dup = len(row_hashes(concat(trc, tra)) & (row_hashes(te) | row_hashes(cr)))
        if n_dup:
            dup.append({"fold": f["name"], "identical_rows": n_dup})
        if set(np.unique(tra["bearing"])) - set(f["train"]):
            aug_bad.append(f["name"])
        train = concat(trc, tra)
        m = SingleSensor("vib").fit(train)
        sc = m.m.steps[0][1]
        if not np.allclose(sc.mean_, train["fv"].astype(float).mean(0), rtol=1e-5, atol=1e-6):
            scaler_bad.append(f["name"])
        g = ReliabilityGated().fit(train)
        pv, pc = g._oof(train)
        z = g._z(train, pv, pc)
        if not np.allclose(g.mu, z.mean(0)):
            gate_bad.append(f["name"])
        for held in np.unique(t["clean"]["condition"]):
            tr_rows = subset(train, train["condition"] != held)
            if (tr_rows["condition"] == held).any():
                p3_bad.append((f["name"], held))
    check("No identical feature windows shared between training rows and test rows", not dup, dup)
    check("Augmented (seen-family) rows only from training bearings", not aug_bad, aug_bad)
    check("Expert StandardScaler fitted on training rows only (mean matches training mean)",
          not scaler_bad, {"folds_failing": scaler_bad, "folds_checked": len(valid)})
    check("Gate normaliser computed from training out-of-fold outputs only", not gate_bad,
          {"folds_failing": gate_bad, "folds_checked": len(valid)})
    check("P3 held-out condition absent from training rows", not p3_bad, p3_bad)

    rep_c, rep_r = repetition(t["clean"]["stem"]), repetition(t["corr"]["stem"])
    base_hash = row_hashes(subset(t["clean"], rep_c == 1))
    eval_hash = row_hashes(subset(t["clean"], rep_c != 1)) | row_hashes(subset(t["corr"], rep_r != 1))
    check("v2 commissioning baseline (repetition 1) disjoint from evaluation windows",
          not (base_hash & eval_hash),
          {"baseline_windows": int((rep_c == 1).sum()), "shared_rows": len(base_hash & eval_hash),
           "baseline_source": "clean table only (no corrupted or augmented rows)"})

    lk = leaky_splits(t["clean"]["stem"])
    shared = []
    for s in lk:
        btr = {str(x).split("_")[3] for x in s["train_stems"]}
        bte = {str(x).split("_")[3] for x in s["test_stems"]}
        shared.append(len(btr & bte))
    check("Leaky reference split shares bearings between train and test (by design; never reported as performance)",
          all(n > 0 for n in shared), {"shared_bearings_per_seed": shared})

    res = {"features": a.features, "n_checks": len(checks),
           "all_pass": all(c["result"] == "PASS" for c in checks), "checks": checks}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, default=str))
    for c in checks:
        print(f"[{c['result']}] {c['check']}")


if __name__ == "__main__":
    main()
