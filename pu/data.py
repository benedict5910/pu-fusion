"""Paderborn (KAt DataCenter) bearing data: metadata and .mat loader.

Dataset: Lessmeier et al. (2016), CC BY-NC 4.0. 32 bearings of type 6203.
File name pattern: N15_M07_F10_K001_1.mat  ->  speed / torque / radial force / bearing / run.
Combined-damage bearings (KB23, KB24, KB27) are excluded (3-class task).
"""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import scipy.io

HEALTHY = ["K001", "K002", "K003", "K004", "K005", "K006"]
OR_ARTIFICIAL = ["KA01", "KA03", "KA05", "KA06", "KA07", "KA08", "KA09"]
IR_ARTIFICIAL = ["KI01", "KI03", "KI05", "KI07", "KI08"]
OR_REAL = ["KA04", "KA15", "KA16", "KA22", "KA30"]
IR_REAL = ["KI04", "KI14", "KI16", "KI18", "KI21"]
ALL_BEARINGS = HEALTHY + OR_ARTIFICIAL + IR_ARTIFICIAL + OR_REAL + IR_REAL

CLASSES = ["healthy", "outer", "inner"]          # label index 0, 1, 2
CONDITIONS = ["N15_M07_F10", "N09_M07_F10", "N15_M01_F10", "N15_M07_F04"]


def label_of(bearing: str) -> int:
    if bearing in HEALTHY:
        return 0
    if bearing.startswith("KA"):
        return 1
    if bearing.startswith("KI"):
        return 2
    raise ValueError(f"unsupported bearing {bearing}")


def damage_kind(bearing: str) -> str:
    if bearing in HEALTHY:
        return "healthy"
    return "real" if bearing in OR_REAL + IR_REAL else "artificial"


_NAME = re.compile(r"^(N\d\d)_(M\d\d)_(F\d\d)_(K[AIB]?\d\d\d?)_(\d+)$")


def parse_name(stem: str) -> dict:
    m = _NAME.match(stem)
    if not m:
        raise ValueError(f"unexpected file name {stem}")
    n, mm, f, b, r = m.groups()
    return {"condition": f"{n}_{mm}_{f}", "bearing": b, "run": int(r),
            "rpm": int(n[1:]) * 100}


def _field(rec, name):
    v = rec[name]
    while isinstance(v, np.ndarray) and v.size == 1 and (v.dtype == object or v.dtype.kind in "US"):
        v = v.flat[0]
    return v


def load_mat(path: str | Path) -> dict:
    """Return {'meta':..., 'signals': {name: (data float32, n_samples)}}.

    Signals are located by channel *name* (not position) because channel order is
    not guaranteed across files.
    """
    path = Path(path)
    meta = parse_name(path.stem)
    raw = scipy.io.loadmat(str(path), squeeze_me=False, struct_as_record=True)
    keys = [k for k in raw if not k.startswith("__")]
    rec = raw[path.stem] if path.stem in raw else raw[keys[0]]
    rec = rec[0, 0]
    Y = rec["Y"]
    sig = {}
    for i in range(Y.size):
        ch = Y.flat[i]
        name = str(_field(ch, "Name")).strip()
        data = np.asarray(_field(ch, "Data"), dtype=np.float64).ravel()
        raster = str(_field(ch, "Raster")).strip()
        sig[name] = {"data": data, "raster": raster}
    meta["channels"] = {k: (len(v["data"]), v["raster"]) for k, v in sig.items()}
    return {"meta": meta, "signals": sig}


def extract_channels(rec: dict, duration_s: float = 4.0) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (vibration [n], current [2, n], fs) for the high-rate channels.

    Sampling rate is derived from sample count / nominal record length and
    checked to be ~64 kHz; mismatched lengths are trimmed to the shortest.
    """
    s = rec["signals"]
    vib = s["vibration_1"]["data"]
    c1 = s["phase_current_1"]["data"]
    c2 = s["phase_current_2"]["data"]
    n = min(len(vib), len(c1), len(c2))
    fs_est = n / duration_s
    # nominal 64 kHz; keep the nominal value when the record length agrees within 2 %
    fs = 64000.0 if abs(fs_est - 64000.0) / 64000.0 < 0.02 else fs_est
    return vib[:n], np.vstack([c1[:n], c2[:n]]), fs


def list_mat_files(root: str | Path) -> list[Path]:
    out = []
    for p in Path(root).rglob("*.mat"):
        try:
            m = parse_name(p.stem)
        except ValueError:
            continue
        if m["bearing"] in ALL_BEARINGS:
            out.append(p)
    return sorted(out)
