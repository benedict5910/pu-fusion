"""Turn recordings into feature tables.

Three tables are produced in one pass over the raw files:
- ``clean``: every window, uncorrupted (training and clean testing)
- ``aug``:   ``n_aug`` corrupted copies of each window, TRAIN families only
- ``corr``:  ``eval_windows`` windows per file x the full test-time grid
Corruption seeds are derived from (file, window, grid entry), so the tables
are bit-reproducible and independent of processing order.
"""
from __future__ import annotations

import zlib
from collections import defaultdict

import numpy as np

from . import corruption as C
from .config import OPERATING_CONDITIONS
from .features import current_features, quality_indicators, vibration_features


def extract(vib, cur, fs, rpm) -> dict:
    return {
        "fv": vibration_features(vib, fs, rpm),
        "fc": current_features(cur, fs, rpm),
        "qv": quality_indicators(vib, fs),
        "qc": quality_indicators(cur, fs),
    }


def _seed(*parts) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def corrupt_pair(vib, cur, modality, family, severity, rng):
    if modality in ("vib", "both"):
        vib = C.apply(vib, family, severity, rng)
    if modality in ("cur", "both"):
        cur = C.apply(cur, family, severity, rng)
    return vib, cur


class TableBuilder:
    def __init__(self):
        self.rows = defaultdict(list)

    def add(self, rec, win, feats, tag):
        r = self.rows
        for k, v in feats.items():
            r[k].append(v)
        r["y"].append(rec.label)
        r["bearing"].append(rec.bearing)
        r["condition"].append(rec.condition)
        r["origin"].append(rec.origin)
        r["stem"].append(rec.stem)
        r["win"].append(win)
        r["tag"].append(tag)

    def arrays(self) -> dict:
        out = {}
        for k, v in self.rows.items():
            out[k] = np.stack(v) if k in ("fv", "fc", "qv", "qc") else np.asarray(v)
        return out


def process_recording(rec, builders, win_s=0.5, n_aug=1, eval_windows=1, grid=None):
    from .data import windows
    rpm = OPERATING_CONDITIONS[rec.condition][0]
    grid = grid if grid is not None else C.eval_grid()
    for i, v, c in windows(rec, win_s):
        builders["clean"].add(rec, i, extract(v, c, rec.fs, rpm), "clean")
        for a in range(n_aug):
            rng = np.random.default_rng(_seed(rec.stem, i, "aug", a))
            m, fam, sev = C.random_train_corruption(rng)
            vv, cc = corrupt_pair(v, c, m, fam, sev, rng)
            builders["aug"].add(rec, i, extract(vv, cc, rec.fs, rpm), f"{m}:{fam}:{sev}")
        if i < eval_windows:
            for m, fam, sev in grid:
                if fam == "clean":
                    continue
                rng = np.random.default_rng(_seed(rec.stem, i, m, fam, sev))
                vv, cc = corrupt_pair(v, c, m, fam, sev, rng)
                builders["corr"].add(rec, i, extract(vv, cc, rec.fs, rpm), f"{m}:{fam}:{sev}")


def save_tables(path, builders):
    flat = {}
    for name, b in builders.items():
        for k, v in b.arrays().items():
            flat[f"{name}__{k}"] = v
    np.savez_compressed(path, **flat)


def load_tables(path) -> dict[str, dict]:
    z = np.load(path, allow_pickle=False)
    out = defaultdict(dict)
    for key in z.files:
        name, k = key.split("__", 1)
        out[name][k] = z[key]
    return dict(out)


def subset(table: dict, mask) -> dict:
    return {k: v[mask] for k, v in table.items()}


def concat(*tables) -> dict:
    tables = [t for t in tables if t and len(t["y"])]
    return {k: np.concatenate([t[k] for t in tables]) for k in tables[0]}
