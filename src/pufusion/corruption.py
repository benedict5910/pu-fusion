"""Controlled sensor-degradation models applied to one modality's raw window.

Families are split into TRAIN (may be used for augmentation) and HELD_OUT
(only ever used at test time) so we can report robustness to corruption types
the model never saw. Every function is deterministic given ``rng``.
"""
from __future__ import annotations

import numpy as np


def gaussian_noise(x, rng, snr_db):
    p = np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-12
    return x + rng.normal(0, np.sqrt(p / 10 ** (snr_db / 10)), size=x.shape)


def dropout(x, rng, _sev=None):
    """Whole channel lost (disconnected sensor reads zero)."""
    return np.zeros_like(x)


def intermittent(x, rng, frac):
    """Burst packet loss: about ``frac`` of samples zeroed in bursts of 1-10 ms."""
    y = np.array(x, copy=True)
    n = y.shape[-1]
    burst = max(1, int(n * 0.005))
    n_bursts = int(np.ceil(frac * n / burst))
    for s in rng.integers(0, max(1, n - burst), size=n_bursts):
        y[..., s:s + burst] = 0
    return y


def gain_offset(x, rng, gain):
    """Calibration error: gain change plus a DC offset of 0.5 x std."""
    off = 0.5 * np.std(x) * rng.choice([-1, 1])
    return np.asarray(x) * gain + off


# ---- held-out families (never used for training augmentation)
def clipping(x, rng, frac_of_peak):
    lim = frac_of_peak * np.max(np.abs(x))
    return np.clip(x, -lim, lim)


def spikes(x, rng, rate_per_s, fs=64_000):
    """EMI-like impulses, amplitude 10 x std, random sign."""
    y = np.array(x, dtype=np.float64, copy=True)
    n = y.shape[-1]
    k = max(1, int(rate_per_s * n / fs))
    idx = rng.integers(0, n, size=k)
    y[..., idx] += 10 * np.std(x) * rng.choice([-1, 1], size=k)
    return y


def stuck(x, rng, _sev=None):
    """Sensor frozen at its first value (non-zero constant)."""
    x = np.asarray(x)
    return np.broadcast_to(x[..., :1], x.shape).copy()


FAMILIES = {
    "noise": (gaussian_noise, [20, 10, 5, 0, -5]),       # SNR dB
    "dropout": (dropout, [None]),
    "intermittent": (intermittent, [0.05, 0.2, 0.5]),
    "gain": (gain_offset, [0.5, 2.0]),
    "clipping": (clipping, [0.5, 0.2, 0.05]),
    "spikes": (spikes, [10, 100, 1000]),
    "stuck": (stuck, [None]),
}
TRAIN_FAMILIES = ["noise", "dropout", "intermittent", "gain"]
HELD_OUT_FAMILIES = ["clipping", "spikes", "stuck"]
MODALITIES = ["vib", "cur"]


def apply(x, family: str, severity, rng):
    fn, _ = FAMILIES[family]
    return np.asarray(fn(np.asarray(x, dtype=np.float64), rng, severity), dtype=np.float32)


def eval_grid():
    """(modality, family, severity) for the test-time sweep; ('none',...) is clean."""
    grid = [("none", "clean", None)]
    for m in MODALITIES:
        for fam, (_, sevs) in FAMILIES.items():
            grid += [(m, fam, s) for s in sevs]
    grid += [("both", "noise", s) for s in (10, 0)]
    return grid


def random_train_corruption(rng):
    """Sample one augmentation: (modality, family, severity)."""
    fam = TRAIN_FAMILIES[rng.integers(len(TRAIN_FAMILIES))]
    sevs = FAMILIES[fam][1]
    return MODALITIES[rng.integers(2)], fam, sevs[rng.integers(len(sevs))]
