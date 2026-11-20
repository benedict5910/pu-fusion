"""Train the models used by the dashboard, holding out demo bearings.

The dashboard must only replay bearings the model never saw, otherwise the demo
shows memorisation. The held-out list is saved inside the pickle and the
dashboard refuses to replay any other bearing.

  python scripts/train_demo_model.py --features data/features.npz --holdout K004 KA22 KI18
"""
import argparse
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.dataset import concat, load_tables, subset  # noqa: E402
from pufusion.models import EarlyFusion, ReliabilityGated, SingleSensor  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--holdout", nargs="+", default=["K004", "KA22", "KI18"])
    ap.add_argument("--out", default="models/demo_models.pkl")
    a = ap.parse_args()
    t = load_tables(a.features)
    train = concat(*(subset(t[k], ~np.isin(t[k]["bearing"], a.holdout)) for k in ("clean", "aug") if k in t))
    models = {m.name: m.fit(train) for m in
              (SingleSensor("vib"), SingleSensor("cur"), EarlyFusion(), ReliabilityGated())}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "wb") as f:
        clean = subset(t["clean"], ~np.isin(t["clean"]["bearing"], a.holdout))
        assessors = {"vib": ReliabilityAssessor().fit(clean["qv"]), "cur": ReliabilityAssessor().fit(clean["qc"])}
        pickle.dump({"models": models, "holdout": a.holdout, "assessors": assessors,
                     "trained_on": sorted(set(train["bearing"]))}, f)
    print("saved", a.out, "| demo bearings (unseen):", a.holdout)


if __name__ == "__main__":
    main()
