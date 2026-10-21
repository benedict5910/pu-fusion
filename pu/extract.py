"""Extract window features for every .mat file (clean + all corruption variants).

Usage: python -m pu.extract <mat_root> <out_dir> [--workers 2]
One pickle per input file is written to <out_dir>; already-processed files are skipped,
so extraction can run incrementally while files are still arriving.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd

from .data import load_mat, extract_channels, list_mat_files, label_of, damage_kind
from .features import (windows, corrupt, quality, vib_features, cur_features, SEEN, WITHHELD,
                       VIB_NAMES, CUR_NAMES, Q_NAMES)

VARIANTS = [("clean", "none")] + [(k, s) for s in ("vib", "cur") for k in SEEN + WITHHELD]


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "little")


def process_file(path: Path) -> tuple[pd.DataFrame, dict]:
    rec = load_mat(path)
    meta = rec["meta"]
    vib, cur, fs = extract_channels(rec)
    rows = []
    for wi, sl in enumerate(windows(vib, fs)):
        v0, c0 = vib[sl], cur[:, sl]
        fv0, fc0 = vib_features(v0, meta["rpm"], fs), cur_features(c0, meta["rpm"], fs)
        qv0, qc0 = quality(v0), quality(c0)
        for kind, sensor in VARIANTS:
            if kind == "clean":
                fv, fc, qv, qc = fv0, fc0, qv0, qc0
            else:
                rng = np.random.default_rng(_seed(path.stem, wi, kind, sensor))
                if sensor == "vib":
                    v = corrupt(v0, kind, rng)
                    fv, qv, fc, qc = vib_features(v, meta["rpm"], fs), quality(v), fc0, qc0
                else:
                    c = corrupt(c0, kind, rng)
                    fc, qc, fv, qv = cur_features(c, meta["rpm"], fs), quality(c), fv0, qv0
            rows.append([path.stem, meta["bearing"], meta["condition"], meta["run"], wi,
                         label_of(meta["bearing"]), damage_kind(meta["bearing"]), kind, sensor,
                         *fv, *fc, *qv, *qc])
    cols = (["file", "bearing", "condition", "run", "win", "label", "damage", "variant",
             "corrupted"] + VIB_NAMES + CUR_NAMES + [f"qv_{q}" for q in Q_NAMES]
            + [f"qc_{q}" for q in Q_NAMES])
    df = pd.DataFrame(rows, columns=cols)
    for c in cols[9:]:
        df[c] = df[c].astype(np.float32)
    info = {"file": path.stem, "fs": fs, "n_samples": int(vib.shape[0]),
            "n_windows": int(df.win.nunique()), "channels": meta["channels"]}
    return df, info


def _job(args):
    path, out = args
    t = time.time()
    try:
        df, info = process_file(path)
        df.to_pickle(out / f"{path.stem}.pkl")
        info["seconds"] = round(time.time() - t, 1)
        return info
    except Exception as e:  # keep going; record the failure
        return {"file": path.stem, "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=3)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mat_root")
    ap.add_argument("out_dir")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    todo = [p for p in list_mat_files(a.mat_root) if not (out / f"{p.stem}.pkl").exists()]
    print(f"{len(todo)} files to process", flush=True)
    log = out / "_extract_log.jsonl"
    with ProcessPoolExecutor(a.workers) as ex, open(log, "a") as fh:
        for info in ex.map(_job, [(p, out) for p in todo]):
            fh.write(json.dumps(info) + "\n")
            fh.flush()
            print(info.get("file"), info.get("error", info.get("seconds")), flush=True)


if __name__ == "__main__":
    sys.exit(main())
