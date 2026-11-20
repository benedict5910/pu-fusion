"""OB1 + OB2 final evaluation on the available Paderborn data (P1, bearing-disjoint).

For every valid P1 fold (same restriction rule as run_experiments.py) all models are
fitted on training bearings only (clean + seen-family augmentation) and evaluated
on held-out bearings, clean and under every corruption tag. Per-window predictions
are saved so that per-class metrics, pooled confusion matrices, bearing-level
scores and abstention can be computed afterwards (scripts/ob_final_report.py).

Evaluation windows are repetitions >= 2 of each held-out bearing for EVERY model:
repetition 1 is reserved as the unlabelled commissioning baseline that the
baseline-type v2 detector may use. The v2 detector configuration for each fold is
read from the selection made on training bearings only by eval_quality_v2.py.

  python scripts/ob_final_eval.py --features data/features_starter.npz \
      --selection results/ob2_v2/quality_v2.json --out results/ob_final/predictions.npz
"""
import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS  # noqa: E402
from pufusion.dataset import concat, load_tables, subset  # noqa: E402
from pufusion.fusion_v2 import GatedV2  # noqa: E402
from pufusion.models import model_zoo  # noqa: E402
from pufusion.reliability_v2 import CANDIDATES, build_baselines, repetition  # noqa: E402
from pufusion.splits import assert_disjoint, p1_folds  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import restrict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--selection", required=True, help="quality_v2.json with per-fold selected configs")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--folds", default="", help="comma-separated fold names to run (default: all valid folds)")
    a = ap.parse_args()
    t0 = time.time()
    t = load_tables(a.features)
    sel = {s["fold"]: s["selected"] for s in json.loads(Path(a.selection).read_text())["selection"]}
    by_name = {c.name: c for c in CANDIDATES}
    folds = restrict(p1_folds(a.repeats), set(np.unique(t["clean"]["bearing"])))
    if a.folds:
        folds = [f for f in folds if f["name"] in set(a.folds.split(","))]
    rec = {k: [] for k in ("fold", "model", "tag", "bearing", "condition", "y", "pred", "abstain", "p")}
    meta = []
    for fold in folds:
        assert_disjoint(fold["train"], fold["test"])
        cfg = by_name[sel[fold["name"]]]
        trc = subset(t["clean"], np.isin(t["clean"]["bearing"], fold["train"]))
        train = concat(trc, subset(t["aug"], np.isin(t["aug"]["bearing"], fold["train"])))
        te_all = subset(t["clean"], np.isin(t["clean"]["bearing"], fold["test"]))
        bl = {k: {**build_baselines(trc, k), **build_baselines(te_all, k)} for k in ("qv", "qc")}
        te = subset(te_all, repetition(te_all["stem"]) != 1)
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], fold["test"]))
        cr = subset(cr, repetition(cr["stem"]) != 1)
        evalset = concat(te, cr)
        models = model_zoo("logreg") + [GatedV2(cfg, bl)]
        for proto in models:
            m = copy.deepcopy(proto)
            m.fit(train)
            if isinstance(m, GatedV2):
                p, ab = m.predict_with_abstain(evalset)
            else:
                p = m.predict_proba(evalset)
                ab = np.zeros(len(p), bool)
                if m.name == "gated_both":            # original hard mask: both sensors dead
                    ab = m._dead(evalset["qv"]) & m._dead(evalset["qc"])
            n = len(p)
            rec["fold"] += [fold["name"]] * n
            rec["model"] += [m.name] * n
            rec["tag"] += list(evalset["tag"])
            rec["bearing"] += list(evalset["bearing"])
            rec["condition"] += list(evalset["condition"])
            rec["y"].append(evalset["y"]); rec["pred"].append(p.argmax(1)); rec["abstain"].append(ab)
            rec["p"].append(p.astype(np.float32))
        meta.append({"fold": fold["name"], "train": fold["train"], "test": fold["test"], "v2_config": cfg.name})
        print(f"{fold['name']}: {len(evalset['y'])} eval windows x {len(models)} models  ({time.time() - t0:.0f}s)",
              flush=True)
    out = {k: (np.concatenate(v) if k in ("y", "pred", "abstain", "p") else np.array(v)) for k, v in rec.items()}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, **out)
    Path(a.out).with_suffix(".json").write_text(json.dumps(
        {"features": a.features, "selection": a.selection, "folds": meta,
         "eval_windows": "held-out bearings, repetitions >= 2, clean + every corruption tag",
         "bearing_classes": {b: int(BEARINGS[b][0]) for b in sorted({x for f in meta for x in f["test"]})}},
        indent=2))
    print(f"wrote {len(out['y'])} prediction rows -> {a.out}")


if __name__ == "__main__":
    main()
