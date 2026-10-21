"""SYNTHETIC test fixtures in the Paderborn .mat layout - for code testing ONLY.
Never use outputs computed from these files as research results."""
import sys
from pathlib import Path
import numpy as np
import scipy.io

FS, T = 64000, 4.0


def make_file(path, bearing, cond="N15_M07_F10", run=1, seed=0):
    rng = np.random.default_rng(seed)
    n = int(FS * T)
    t = np.arange(n) / FS
    fr = int(cond[1:3]) * 100 / 60
    vib = rng.normal(0, 0.3, n)
    rate = {"KA": 3.05, "KI": 4.95}.get(bearing[:2], 0) * fr
    if rate:
        for t0 in np.arange(0, T, 1 / rate):
            i = int(t0 * FS)
            L = min(400, n - i)
            vib[i:i + L] += 2.0 * np.exp(-np.arange(L) / 60) * np.sin(2 * np.pi * 6000 * np.arange(L) / FS)
    fe = 100.0
    mod = 0.02 * np.sin(2 * np.pi * rate * t) if rate else 0
    c1 = (1 + mod) * np.sin(2 * np.pi * fe * t) + rng.normal(0, 0.01, n)
    c2 = (1 + mod) * np.sin(2 * np.pi * fe * t - 2 * np.pi / 3) + rng.normal(0, 0.01, n)
    chans = [("force", rng.normal(size=16000), "Mech_4kHz"),
             ("phase_current_1", c1, "HostService"), ("phase_current_2", c2, "HostService"),
             ("speed", np.full(16000, fr * 60), "Mech_4kHz"),
             ("temp_2_bearing_module", np.full(4, 45.0), "Temp_1Hz"),
             ("torque", rng.normal(size=16000), "Mech_4kHz"), ("vibration_1", vib, "HostService")]
    dt = [("Name", object), ("Type", object), ("Unit", object), ("Raster", object), ("Data", object)]
    Y = np.zeros((1, len(chans)), dtype=dt)
    for i, (nm, d, r) in enumerate(chans):
        Y[0, i] = (nm, "x", "u", r, d[None, :])
    stem = f"{cond}_{bearing}_{run}"
    rec = np.zeros((1, 1), dtype=[("Info", object), ("X", object), ("Y", object), ("Description", object)])
    rec[0, 0] = ("synthetic", np.zeros((1, 0)), Y, "SYNTHETIC TEST FIXTURE")
    scipy.io.savemat(str(Path(path) / f"{stem}.mat"), {stem: rec})


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pu.data import ALL_BEARINGS, CONDITIONS
    conds = CONDITIONS if len(sys.argv) > 2 and sys.argv[2] == "all" else CONDITIONS[:1]
    k = 0
    for b in ALL_BEARINGS:
        for c in conds:
            make_file(out, b, c, 1, seed=k)
            k += 1
    print("wrote", k, "synthetic files")
