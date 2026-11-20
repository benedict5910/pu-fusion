"""OB2 gating research: evaluate soft / strength-aware / severity-aware fusion (fusion_v3).

Same P1 folds, same evaluation windows (held-out bearings, repetitions >= 2, clean +
every corruption tag) and same per-fold v2 detector configuration as ob_final_eval.py.
Per fold: tau / beta / theta are chosen by inner bearing-disjoint validation on training
bearings (clean + seen families only); the model is then refitted on all training
bearings and applied to the held-out bearings. Baseline predictions are NOT recomputed:
report script reads them from results/full_2026-11-15/ob_final/predictions.npz.

  python scripts/gating_research_eval.py --features data/features_full.npz \
      --selection results/full_2026-11-15/ob2_v2/quality_v2.json \
      --out results/gating_research/shard_a.npz [--folds P1_r0_f0,...]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.dataset import concat, load_tables, subset  # noqa: E402
from pufusion.fusion_v3 import METHODS, GatedV3, combine, select_params  # noqa: E402
from pufusion.reliability_v2 import CANDIDATES, build_baselines, repetition  # noqa: E402
from pufusion.splits import assert_disjoint, p1_folds  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import restrict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--folds", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    t = load_tables(a.features)
    sel = {s["fold"]: s["selected"] for s in json.loads(Path(a.selection).read_text())["selection"]}
    by_name = {c.name: c for c in CANDIDATES}
    folds = restrict(p1_folds(a.repeats), set(np.unique(t["clean"]["bearing"])))
    if a.folds:
        folds = [f for f in folds if f["name"] in set(a.folds.split(","))]
    rec = {k: [] for k in ("fold", "model", "tag", "bearing", "condition", "y", "pred", "abstain", "p", "w_vib")}
    meta = []
    for fold in folds:
        assert_disjoint(fold["train"], fold["test"])
        cfg = by_name[sel[fold["name"]]]
        in_tr = lambda tab: np.isin(tab["bearing"], fold["train"])
        trc = subset(t["clean"], in_tr(t["clean"]))
        train_tabs = {"clean": trc, "aug": subset(t["aug"], in_tr(t["aug"])),
                      "corr": subset(t["corr"], in_tr(t["corr"]))}
        te_all = subset(t["clean"], np.isin(t["clean"]["bearing"], fold["test"]))
        bl_tr = {k: build_baselines(trc, k) for k in ("qv", "qc")}
        # ---- parameter selection: training bearings only (test rows are not passed in)
        chosen = select_params(train_tabs, fold["train"], cfg, bl_tr)
        # ---- final fit on all training bearings, evaluation on held-out bearings
        bl = {k: {**bl_tr[k], **build_baselines(te_all, k)} for k in ("qv", "qc")}
        model = GatedV3(cfg, bl).fit(concat(trc, train_tabs["aug"]))
        te = subset(te_all, repetition(te_all["stem"]) != 1)
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], fold["test"]))
        cr = subset(cr, repetition(cr["stem"]) != 1)
        evalset = concat(te, cr)
        pk = model.pack(evalset)
        for m in METHODS:
            p, ab, w = combine(m, chosen[m]["param"], pk)
            n = len(p)
            rec["fold"] += [fold["name"]] * n
            rec["model"] += [f"v3_{m}"] * n
            rec["tag"] += list(evalset["tag"]); rec["bearing"] += list(evalset["bearing"])
            rec["condition"] += list(evalset["condition"])
            rec["y"].append(evalset["y"]); rec["pred"].append(p.argmax(1)); rec["abstain"].append(ab)
            rec["p"].append(p.astype(np.float32)); rec["w_vib"].append(w[:, 0].astype(np.float32))
        meta.append({"fold": fold["name"], "train": fold["train"], "test": fold["test"], "v2_config": cfg.name,
                     "selected": chosen, "skill_vib_ok_degraded": model.skill[0].round(4).tolist(),
                     "skill_cur_ok_degraded": model.skill[1].round(4).tolist()})
        print(f"{fold['name']}: " + " ".join(f"{m}={chosen[m]['param']}" for m in METHODS)
              + f"  skill vib={model.skill[0].round(2)} cur={model.skill[1].round(2)}  ({time.time() - t0:.0f}s)",
              flush=True)
    out = {k: (np.concatenate(v) if k in ("y", "pred", "abstain", "p", "w_vib") else np.array(v))
           for k, v in rec.items()}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, **out)
    Path(a.out).with_suffix(".json").write_text(json.dumps({"features": a.features, "selection": a.selection,
                                                            "folds": meta}, indent=2))
    print(f"wrote {len(out['y'])} rows -> {a.out}")


if __name__ == "__main__":
    main()
