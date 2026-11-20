"""OB2: validate the corrected label-free detector (reliability_v2) against the original.

Same folds and same held-out bearings as scripts/eval_quality.py (P1, all 15 folds).
For every fold:
  1. the v2 configuration is chosen by inner leave-one-TRAINING-bearing-out
     (clean false flags + seen-family detection only; see reliability_v2.select_config);
  2. v1 (original) and v2 are fitted on CLEAN windows of training bearings only;
  3. both are evaluated on held-out bearings: clean false flags (also split into
     healthy vs damaged bearings), detection per corruption tag on the corrupted
     sensor (seen AND withheld families), and cross-flags on the other sensor.

  python scripts/eval_quality_v2.py --features data/features_starter.npz --out results/ob2_v2/quality_v2.json
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS, HEALTHY  # noqa: E402
from pufusion.corruption import HELD_OUT_FAMILIES  # noqa: E402
from pufusion.dataset import load_tables, subset  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402
from pufusion.reliability_v2 import (build_baselines, fit_assessor, prepare, repetition,  # noqa: E402
                                    select_config)
from pufusion.splits import assert_disjoint, p1_folds  # noqa: E402


class _V1:
    """Adapter so v1 and v2 share one interface (v1 ignores the condition)."""

    def __init__(self, Q):
        self.a = ReliabilityAssessor().fit(Q)

    def flagged(self, Q, cond):
        return np.array([self.a.assess(q).status != "ok" for q in Q])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--folds", default="", help="comma-separated fold indices (for parallel shards)")
    a = ap.parse_args()
    t0 = time.time()
    t = load_tables(a.features)
    avail = set(np.unique(t["clean"]["bearing"]))
    acc = defaultdict(list)
    chosen = []
    keep = {int(x) for x in a.folds.split(",") if x} if a.folds else None
    for i_fold, fold in enumerate(p1_folds(a.repeats)):
        if keep is not None and i_fold not in keep:
            continue
        tr = [b for b in fold["train"] if b in avail]
        te = [b for b in fold["test"] if b in avail]
        if not tr or not te:
            continue
        assert_disjoint(tr, te)
        ctr = subset(t["clean"], np.isin(t["clean"]["bearing"], tr))
        rtr = subset(t["corr"], np.isin(t["corr"]["bearing"], tr))
        cfg, table = select_config(ctr, rtr, tr)
        chosen.append({"fold": fold["name"], "train": tr, "test": te, "selected": cfg.name, "inner": table})
        # held-out bearings: evaluation on repetitions >= 2 for every version; repetition 1
        # (clean, unlabelled) is the commissioning baseline used only by baseline configs
        cte_all = subset(t["clean"], np.isin(t["clean"]["bearing"], te))
        cte = subset(cte_all, repetition(cte_all["stem"]) != 1)
        cr_all = subset(t["corr"], np.isin(t["corr"]["bearing"], te))
        cr = subset(cr_all, repetition(cr_all["stem"]) != 1)
        bl = {k: {**build_baselines(ctr, k), **build_baselines(cte_all, k)} for k in ("qv", "qc")}
        healthy_te = np.array([BEARINGS[b][0] == HEALTHY for b in cte["bearing"]])
        fit_all = np.ones(len(ctr["y"]), bool)
        for ver in ("v1", "v2"):
            for s, k in (("vib", "qv"), ("cur", "qc")):
                if ver == "v1":
                    A, P = _V1(ctr[k]), (lambda tab, kk=k: tab[kk])
                else:
                    A = fit_assessor(cfg, ctr, k, fit_all, bl[k])
                    P = (lambda tab, kk=k: prepare(cfg, tab, kk, bl[kk]))
                f = A.flagged(P(cte), cte["condition"])
                acc[(ver, "clean", s, "false_flag")].append(f.mean())
                acc[(ver, "clean_healthy_bearings", s, "false_flag")].append(f[healthy_te].mean())
                acc[(ver, "clean_damaged_bearings", s, "false_flag")].append(f[~healthy_te].mean())
                for tag in np.unique(cr["tag"]):
                    m = cr["tag"] == tag
                    mod, fam, sev = str(tag).split(":")
                    sub = subset(cr, m)
                    rate = A.flagged(P(sub), sub["condition"]).mean()
                    hit = mod in (s, "both")
                    cond = ("both:" if mod == "both" else "") + f"{fam}:{sev}"
                    acc[(ver, cond, s, "detect" if hit else "cross_flag")].append(rate)
        print(f"{fold['name']}: selected {cfg.name}  ({time.time() - t0:.0f}s)", flush=True)

    res = {"features": str(a.features), "folds": len(chosen),
           "protocol": "P1 bearing-disjoint, all folds with >=1 train and test bearing (same as eval_quality.py); "
                       "held-out evaluation on repetitions >= 2; repetition 1 of each held-out bearing is an "
                       "unlabelled commissioning baseline used only by baseline configurations",
           "withheld_families": HELD_OUT_FAMILIES, "selection": chosen, "metrics": {},
           "raw": {"|".join(k): [round(float(x), 6) for x in v] for k, v in sorted(acc.items())}}
    for (ver, cond, s, kind), v in sorted(acc.items()):
        res["metrics"].setdefault(ver, {}).setdefault(cond, {})[f"{s}_{kind}"] = {
            "mean": round(float(np.mean(v)), 4), "sd": round(float(np.std(v)), 4)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    m1, m2 = res["metrics"]["v1"], res["metrics"]["v2"]
    print(f"\nfolds={len(chosen)}  selected configs: "
          f"{ {c: sum(x['selected'] == c for x in chosen) for c in {x['selected'] for x in chosen}} }")
    print(f"{'condition':26s} {'v1 vib':>8s} {'v2 vib':>8s} {'v1 cur':>8s} {'v2 cur':>8s}")
    for cond in m2:
        key = "false_flag" if cond.startswith("clean") else "detect"
        g = lambda d, s: f"{d[cond][f'{s}_{key}']['mean']:.3f}" if f"{s}_{key}" in d.get(cond, {}) else "-"
        print(f"{cond:26s} {g(m1, 'vib'):>8s} {g(m2, 'vib'):>8s} {g(m1, 'cur'):>8s} {g(m2, 'cur'):>8s}")


if __name__ == "__main__":
    main()
