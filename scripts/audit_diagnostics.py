"""Read-only diagnostics on the P1 protocol (no parameter changes, no tuning on test bearings).

(A) False-alarm audit: re-runs the exact P1 folds (same seeds / settings as run_experiments.py) for
    the main models and keeps per-window predictions on clean held-out windows, then breaks the
    healthy-window false-alarm rate down by held-out healthy bearing, operating condition and
    predicted class; checks how the window FAR propagates through the health-state rules.
(B) Quality-assessor audit: for clean vs corrupted *vibration* windows of held-out bearings,
    reports each indicator's value against the bounds learned from clean training windows
    (fraction outside bounds), and how wide the clean range is across training bearings.

  python scripts/audit_diagnostics.py --features data/features_starter.npz --out results/starter/audit
"""
import argparse
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from pufusion.config import BEARINGS, CLASS_NAMES, HEALTHY  # noqa: E402
from pufusion.dataset import concat, load_tables, subset  # noqa: E402
from pufusion.features import QUALITY_NAMES  # noqa: E402
from pufusion.health import HealthTracker  # noqa: E402
from pufusion.models import model_zoo  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402
from pufusion.splits import p1_folds  # noqa: E402
from run_experiments import restrict  # noqa: E402

MAIN = ["vib_only", "early_fusion", "late_average", "gated_both"]


class _Rel:
    status, score, reasons = "ok", 1.0, []


def far_audit(t, out):
    avail = set(np.unique(t["clean"]["bearing"]))
    folds = restrict(p1_folds(5), avail)
    per_bearing = defaultdict(lambda: defaultdict(list))   # model -> bearing -> [alarm flags]
    per_cond = defaultdict(lambda: defaultdict(list))
    pred_dist = defaultdict(lambda: np.zeros(3))
    train_healthy_counts = []
    health_rule = defaultdict(list)                         # model -> per-recording final state
    fold_rows = []
    for f in folds:
        tr = subset(t["clean"], np.isin(t["clean"]["bearing"], f["train"]))
        tr = concat(tr, subset(t["aug"], np.isin(t["aug"]["bearing"], f["train"])))
        te = subset(t["clean"], np.isin(t["clean"]["bearing"], f["test"]))
        train_healthy_counts.append(sum(BEARINGS[b][0] == HEALTHY for b in f["train"]))
        hm = te["y"] == HEALTHY
        row = {"fold": f["name"], "test": f["test"],
               "train_healthy": [b for b in f["train"] if BEARINGS[b][0] == HEALTHY]}
        for proto in model_zoo():
            if proto.name not in MAIN:
                continue
            m = copy.deepcopy(proto).fit(tr)
            p = m.predict_proba(te)
            yhat = p.argmax(1)
            alarm = yhat != HEALTHY
            row[proto.name] = round(float(alarm[hm].mean()), 3)
            for b in np.unique(te["bearing"][hm]):
                sel = hm & (te["bearing"] == b)
                per_bearing[proto.name][b] += list(alarm[sel])
                for c in np.unique(te["condition"][sel]):
                    per_cond[proto.name][c] += list(alarm[sel & (te["condition"] == c)])
                pred_dist[(proto.name, b)] += np.bincount(yhat[sel], minlength=3)
            # health rules on each healthy recording (8 windows, in order)
            for stem in np.unique(te["stem"][hm]):
                s = te["stem"] == stem
                order = np.argsort(te["win"][s])
                pf = (1 - p[s][:, HEALTHY])[order]
                tr_ = HealthTracker()
                states = [tr_.update(float(v), None, {"vib": _Rel(), "cur": _Rel()}).state for v in pf]
                health_rule[proto.name].append(states[-1])
        fold_rows.append(row)
    res = {"n_folds": len(folds), "folds": fold_rows,
           "far_by_heldout_healthy_bearing": {m: {b: round(float(np.mean(v)), 3) for b, v in d.items()}
                                              for m, d in per_bearing.items()},
           "far_by_condition": {m: {c: round(float(np.mean(v)), 3) for c, v in d.items()}
                                for m, d in per_cond.items()},
           "pred_class_share_on_healthy": {f"{m}|{b}": dict(zip(CLASS_NAMES, (v / v.sum()).round(3).tolist()))
                                           for (m, b), v in pred_dist.items()},
           "healthy_bearings_in_training_per_fold": train_healthy_counts,
           "health_rule_final_state_on_healthy_recordings": {
               m: {s: round(v.count(s) / len(v), 3) for s in sorted(set(v))} for m, v in health_rule.items()}}
    (out / "far_audit.json").write_text(json.dumps(res, indent=1))
    return res


def quality_audit(t, out):
    avail = set(np.unique(t["clean"]["bearing"]))
    folds = restrict(p1_folds(5), avail)
    stats = defaultdict(lambda: defaultdict(list))
    clean_spread = defaultdict(list)
    for f in folds:
        ctr = subset(t["clean"], np.isin(t["clean"]["bearing"], f["train"]))
        A = ReliabilityAssessor().fit(ctr["qv"])
        for k, n in enumerate(QUALITY_NAMES):
            per_b = [np.median(ctr["qv"][ctr["bearing"] == b, k]) for b in np.unique(ctr["bearing"])]
            clean_spread[n].append([float(A.lo[k]), float(A.hi[k]), float(np.min(per_b)), float(np.max(per_b))])
        cte = subset(t["clean"], np.isin(t["clean"]["bearing"], f["test"]))
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], f["test"]))
        groups = {"clean": cte["qv"]}
        for tag in np.unique(cr["tag"]):
            mod, fam, sev = str(tag).split(":")
            if mod == "vib" and fam in ("noise", "spikes", "gain"):
                groups[f"{fam}:{sev}"] = cr["qv"][cr["tag"] == tag]
        for g, Q in groups.items():
            for k, n in enumerate(QUALITY_NAMES):
                stats[g][f"{n}_median"].append(float(np.median(Q[:, k])))
                stats[g][f"{n}_out_of_bounds"].append(float(np.mean((Q[:, k] > A.hi[k]) | (Q[:, k] < A.lo[k]))))
    res = {"bounds_vs_per_bearing_medians_vib": {
               n: dict(zip(["lo", "hi", "min_bearing_median", "max_bearing_median"],
                           np.mean(v, 0).round(4).tolist())) for n, v in clean_spread.items()},
           "vib_indicators": {g: {k: round(float(np.mean(v)), 4) for k, v in d.items()} for g, d in stats.items()}}
    (out / "quality_audit.json").write_text(json.dumps(res, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t = load_tables(a.features)
    q = quality_audit(t, out)
    print(json.dumps(q, indent=1)[:4000])
    r = far_audit(t, out)
    for k in ("far_by_heldout_healthy_bearing", "far_by_condition", "healthy_bearings_in_training_per_fold",
              "health_rule_final_state_on_healthy_recordings"):
        print(k, json.dumps(r[k], indent=1))


if __name__ == "__main__":
    main()
