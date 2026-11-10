"""Export the gearbox pilot model for one held-out operating profile, for deployments without data/mcc5.

The model is fitted exactly as the dashboard fits it (pufusion.gearbox.fit_records on the three other
profiles); nothing is tuned. The manifest records the SHA-256 of the model and of the held-out test
recordings, which the dashboard verifies before use. Run with the pinned requirements (same versions as
Streamlit Cloud):

    python scripts/export_gearbox_demo.py --data data/mcc5 --condition torque_circulation_1000rpm_10Nm
"""
import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion import gearbox as G  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "mcc5"))
    ap.add_argument("--condition", default="torque_circulation_1000rpm_10Nm")
    ap.add_argument("--release-url", default="https://github.com/benedict5910/pu-fusion/releases/download/mcc5-demo-v1/")
    args = ap.parse_args()
    import numpy
    import pandas
    import sklearn
    recs = G.discover(args.data)
    if len(recs) != 12:
        raise SystemExit(f"expected the 12 MCC5-THU pilot recordings in {args.data}, found {len(recs)}")
    train, test = G.condition_split(recs, args.condition)
    model = G.fit_records(train, {r.id: G.extract(r) for r in train})
    short = args.condition.replace("torque_circulation_", "")
    out = ROOT / "models" / f"gearbox_demo_{short}.pkl"
    bundle = {"model": model, "condition": args.condition, "train": [r.id for r in train],
              "test": [r.id for r in test], "seeds": {r.id: 42 + recs.index(r) for r in test},
              "versions": {"python": sys.version.split()[0], "numpy": numpy.__version__,
                           "pandas": pandas.__version__, "scikit-learn": sklearn.__version__}}
    with open(out, "wb") as f:
        pickle.dump(bundle, f)
    manifest = {
        "source": "MCC5-THU v2, Chen, Liu, He, Zou and Zhou (2024), DOI 10.17632/p92gj2732w.2",
        "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); recordings redistributed unchanged "
                   "(gzip-compressed copies of the publisher's CSV files)",
        "condition": args.condition, "model_file": out.name, "model_sha256": sha256(out),
        "release_url": args.release_url,
        "recordings": {r.path.name: {"sha256": sha256(r.path), "bytes": r.path.stat().st_size, "label": r.label}
                       for r in test},
        "versions": bundle["versions"],
    }
    (ROOT / "models" / "gearbox_demo_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
