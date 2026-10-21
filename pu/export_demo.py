"""Train the dashboard model on P1 repeat-0 fold-0 *training* bearings and export:
  demo/model.json       portable parameters (numpy-only inference)
  demo/stream.csv.gz    held-out test-bearing windows (clean + all corruption variants)
  demo/export_check.json numpy-vs-sklearn agreement on the held-out windows

Usage: python -m pu.export_demo <features_dir> <demo_dir> [--runs 5]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import numpy as np

from .experiments import load_features, training_rows, p1_splits
from .features import VIB_NAMES, CUR_NAMES, Q_NAMES
from .models import FusionSuite, QV, QC


def lin(pipe, names):
    sc, lr = pipe.steps[0][1], pipe.steps[1][1]
    return {"mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(), "coef": lr.coef_.tolist(),
            "intercept": lr.intercept_.tolist(), "names": names}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("features_dir")
    ap.add_argument("demo_dir")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--label", default="REAL PADERBORN DATA")
    a = ap.parse_args(argv)
    out = Path(a.demo_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = load_features(a.features_dir)
    _, _, train_b, test_b = next(iter(p1_splits()))
    tr = df[df.bearing.isin(train_b)]
    suite = FusionSuite(seed=0).fit(training_rows(tr, 0), tr[tr.variant == "clean"])
    gv, gc = suite.gates["gated"]
    model = {
        "meta": {"train_bearings": train_b, "test_bearings": test_b, "data_label": a.label,
                 "classes": ["healthy", "outer", "inner"], "protocol": "P1 repeat 0 fold 0"},
        "vib": lin(suite.vib, VIB_NAMES), "cur": lin(suite.cur, CUR_NAMES),
        "gate_v": gv if isinstance(gv, float) else lin(gv, None),
        "gate_c": gc if isinstance(gc, float) else lin(gc, None),
        "qa_vib": suite.qa_v.to_dict(), "qa_cur": suite.qa_c.to_dict()}
    for k in ("qa_vib", "qa_cur"):  # json cannot store inf
        model[k]["lo"] = [x if np.isfinite(x) else -1e30 for x in model[k]["lo"]]
    (out / "model.json").write_text(json.dumps(model))
    te = df[df.bearing.isin(test_b) & (df.run <= a.runs)].copy()
    te.to_csv(out / "stream.csv.gz", index=False, compression="gzip")
    # agreement check
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from health.engine import PortableModel
    pm = PortableModel(str(out / "model.json"))
    r = pm.predict(te[VIB_NAMES].to_numpy(), te[CUR_NAMES].to_numpy(), te[QV].to_numpy(),
                   te[QC].to_numpy())
    sk, _ = suite.predict_all(te)
    chk = {"n_windows": len(te), "max_abs_prob_diff": float(np.abs(r["P"] - sk["gated"]).max()),
           "argmax_agreement": float((r["P"].argmax(1) == sk["gated"].argmax(1)).mean()),
           "test_bearings": test_b}
    (out / "export_check.json").write_text(json.dumps(chk, indent=1))
    print(chk)


if __name__ == "__main__":
    sys.exit(main())
