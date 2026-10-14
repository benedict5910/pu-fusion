"""Independent validation of the label-free sensor-quality detector (ReliabilityAssessor).

Separate from fault classification: no fault labels are used. For each P1 fold the
assessor is fitted on CLEAN windows of training bearings only, then on held-out bearings:
  - false-flag rate: clean windows reported degraded/failed (per sensor)
  - detection rate: corrupted windows reported degraded/failed on the corrupted sensor,
    per corruption family and severity (including families never used anywhere in fitting)
  - cross-flag rate: the OTHER (healthy) sensor wrongly flagged

  python scripts/eval_quality.py --features data/features_all.npz --out results/all/quality.json
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.dataset import load_tables, subset  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402
from pufusion.splits import p1_folds  # noqa: E402


def flagged(assessor, Q):
    return np.array([assessor.assess(q).status != "ok" for q in Q])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t = load_tables(a.features)
    avail = set(np.unique(t["clean"]["bearing"]))
    acc = defaultdict(list)
    n_folds = 0
    for fold in p1_folds(a.repeats):
        tr = [b for b in fold["train"] if b in avail]
        te = [b for b in fold["test"] if b in avail]
        if not tr or not te:
            continue
        n_folds += 1
        ctr = subset(t["clean"], np.isin(t["clean"]["bearing"], tr))
        A = {"vib": ReliabilityAssessor().fit(ctr["qv"]), "cur": ReliabilityAssessor().fit(ctr["qc"])}
        cte = subset(t["clean"], np.isin(t["clean"]["bearing"], te))
        for s, k in (("vib", "qv"), ("cur", "qc")):
            acc[("clean", s, "false_flag")].append(flagged(A[s], cte[k]).mean())
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], te))
        for tag in np.unique(cr["tag"]):
            m = cr["tag"] == tag
            mod, fam, sev = str(tag).split(":")
            for s, k in (("vib", "qv"), ("cur", "qc")):
                rate = flagged(A[s], cr[k][m]).mean()
                hit = mod in (s, "both")
                acc[(("both:" if mod == "both" else "") + f"{fam}:{sev}", s, "detect" if hit else "cross_flag")].append(rate)
    res = {"source": json.loads(Path(a.features).with_suffix(".json").read_text()).get("source"),
           "folds": n_folds, "metrics": {}}
    for (cond, s, kind), v in sorted(acc.items()):
        res["metrics"].setdefault(cond, {})[f"{s}_{kind}"] = {"mean": round(float(np.mean(v)), 4),
                                                               "sd": round(float(np.std(v)), 4)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    print(f"folds={n_folds}  source={res['source']}")
    print(f"{'condition':22s} {'vib detect':>11s} {'cur detect':>11s} {'vib x-flag':>11s} {'cur x-flag':>11s}")
    for cond, d in res["metrics"].items():
        g = lambda k: f"{d[k]['mean']:.3f}" if k in d else "-"
        if cond == "clean":
            print(f"{'clean (false flag)':22s} {g('vib_false_flag'):>11s} {g('cur_false_flag'):>11s}")
        else:
            print(f"{cond:22s} {g('vib_detect'):>11s} {g('cur_detect'):>11s} {g('vib_cross_flag'):>11s} {g('cur_cross_flag'):>11s}")


if __name__ == "__main__":
    main()
