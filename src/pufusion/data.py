"""Loading Paderborn .mat files and cutting them into windows.

Each .mat file holds one 4 s measurement. Inside is a struct named after the
file stem with a field ``Y``: an array of channel structs, each with ``Name``,
``Raster`` and ``Data``. We read the channels by name, never by position.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import scipy.io

from .config import BEARINGS, FS_HIGH, parse_filename

VIB = "vibration_1"
CUR = ("phase_current_1", "phase_current_2")


@dataclass
class Recording:
    stem: str
    condition: str
    bearing: str
    repetition: int
    label: int
    origin: str
    vib: np.ndarray            # (n,)
    cur: np.ndarray            # (2, n)
    fs: int = FS_HIGH


def _get(obj, name):
    return getattr(obj, name) if hasattr(obj, name) else obj[name]


def load_mat(path: str | Path) -> Recording:
    path = Path(path)
    meta = parse_filename(path.stem)
    if meta["bearing"] not in BEARINGS:
        raise KeyError(f"{meta['bearing']} is not part of the 3-class task")
    mat = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)
    keys = [k for k in mat if not k.startswith("__")]
    if not keys:
        raise ValueError(f"no data struct in {path}")
    root = mat[path.stem] if path.stem in mat else mat[keys[0]]
    channels = {}
    for ch in np.atleast_1d(_get(root, "Y")):
        channels[str(_get(ch, "Name"))] = np.asarray(_get(ch, "Data"), dtype=np.float32).ravel()
    missing = [c for c in (VIB, *CUR) if c not in channels]
    if missing:
        raise ValueError(f"{path.name}: missing channels {missing}; found {sorted(channels)}")
    n = min(len(channels[VIB]), *(len(channels[c]) for c in CUR))
    label, origin = BEARINGS[meta["bearing"]]
    return Recording(
        stem=path.stem, label=label, origin=origin, **meta,
        vib=channels[VIB][:n],
        cur=np.stack([channels[c][:n] for c in CUR]),
    )


def windows(rec: Recording, win_s: float = 0.5):
    """Yield (index, vib_window, cur_window) non-overlapping windows.

    Non-overlapping, and every window of a recording carries the recording's
    bearing id, so grouped splitting keeps all of them on one side.
    """
    w = int(win_s * rec.fs)
    for i in range(len(rec.vib) // w):
        sl = slice(i * w, (i + 1) * w)
        yield i, rec.vib[sl], rec.cur[:, sl]


def find_mat_files(root: str | Path) -> list[Path]:
    files = sorted(Path(root).rglob("*.mat"))
    keep = []
    for f in files:
        try:
            if parse_filename(f.stem)["bearing"] in BEARINGS:
                keep.append(f)
        except ValueError:
            continue
    return keep
