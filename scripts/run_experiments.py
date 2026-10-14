"""Run a protocol over a feature file and write one CSV row per (fold, model, corruption).

  python scripts/run_experiments.py --features data/features.npz --protocol p1 --out results/p1.csv
  python scripts/run_experiments.py --features data/features.npz --protocol p2 --out results/p2.csv
  python scripts/run_experiments.py --features data/features.npz --protocol p1 --condition-holdout --out results/p3.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS  # noqa: E402
from pufusion.dataset import load_tables  # noqa: E402
from pufusion.experiment import run  # noqa: E402
from pufusion.models import ablation_zoo, model_zoo  # noqa: E402
from pufusion.splits import p1_folds, p2_folds  # noqa: E402


def restrict(folds, available):
    """Keep only bearings present in the feature file; drop folds whose test set
    lacks a class (metrics would be meaningless)."""
    out = []
    for f in folds:
        tr = [b for b in f["train"] if b in available]
        te = [b for b in f["test"] if b in available]
        if {BEARINGS[b][0] for b in te} == {0, 1, 2} and {BEARINGS[b][0] for b in tr} == {0, 1, 2}:
            out.append({**f, "train": tr, "test": te})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--protocol", choices=["p1", "p2"], default="p1")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--condition-holdout", action="store_true")
    ap.add_argument("--models", choices=["main", "ablation", "all"], default="main")
    ap.add_argument("--expert", choices=["logreg", "hgb"], default="logreg")
    ap.add_argument("--no-aug", action="store_true")
    ap.add_argument("--max-folds", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    tables = load_tables(a.features)
    meta_path = Path(a.features).with_suffix(".json")
    source = json.loads(meta_path.read_text())["source"] if meta_path.exists() else "unknown"
    available = set(np.unique(tables["clean"]["bearing"]))
    folds = p1_folds(a.repeats) if a.protocol == "p1" else p2_folds()
    folds = restrict(folds, available)
    if a.max_folds:
        folds = folds[: a.max_folds]
    if not folds:
        raise SystemExit("no valid folds: the feature file must contain every class among held-out bearings")
    models = {"main": model_zoo, "ablation": ablation_zoo,
              "all": lambda k: model_zoo(k) + ablation_zoo(k)}[a.models](a.expert)
    print(f"source={source} folds={len(folds)} models={[m.name for m in models]}")
    rows = run(tables, folds, models, use_aug=not a.no_aug, condition_holdout=a.condition_holdout)
    for r in rows:
        r["data_source"] = source
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {a.out}")


if __name__ == "__main__":
    main()
