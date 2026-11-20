"""Hand-crafted, physics-informed features and label-free signal-quality indicators.

Design rules
- Every feature is computed from one window only (no dataset statistics), so
  nothing from the test set can leak into feature extraction.
- Spectral features are *relative* (normalised by the window's own power), so a
  pure gain error mostly shows up in the quality indicators, not the features.
- Quality indicators never use the label. They describe whether a channel looks
  like a working sensor (dead, stuck, clipped, noisy, spiky), not the fault.
"""
from __future__ import annotations

import numpy as np
from scipy import signal, stats

from .config import fault_frequencies

EPS = 1e-12


def _clean(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _db(a: float, b: float) -> float:
    return float(10 * np.log10((a + EPS) / (b + EPS)))


def _peak_energy(freqs, spec, f0, rel_tol=0.02, abs_tol=1.0):
    tol = max(abs_tol, rel_tol * f0)
    m = (freqs >= f0 - tol) & (freqs <= f0 + tol)
    return float(spec[m].max()) if m.any() else 0.0


def _log_bands(freqs, psd, f_lo, f_hi, n):
    edges = np.geomspace(f_lo, f_hi, n + 1)
    total = psd[(freqs >= f_lo) & (freqs < f_hi)].sum() + EPS
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        out.append(np.log10(psd[(freqs >= lo) & (freqs < hi)].sum() / total + 1e-9))
    return out


def _time_stats(x):
    rms = np.sqrt(np.mean(x ** 2)) + EPS
    return [
        float(stats.kurtosis(x)) if x.std() > EPS else 0.0,
        float(stats.skew(x)) if x.std() > EPS else 0.0,
        float(np.max(np.abs(x)) / rms),               # crest factor
        float(np.mean(np.abs(x)) / rms),              # shape-related
    ]


# ----------------------------------------------------------------- vibration
VIB_FEATURE_NAMES = (
    ["kurt", "skew", "crest", "mean_abs_over_rms"]
    + [f"env_{k}x{f}" for f in ("bpfo", "bpfi", "fr") for k in (1, 2, 3)]
    + [f"band{i}" for i in range(16)]
    + ["env_kurt", "hf_ratio"]
)


def vibration_features(x, fs: int, rpm: float, band=(2000, 20000), geom=None) -> np.ndarray:
    """``band``: resonance band for envelope analysis. Paderborn (64 kHz): 2-20 kHz.
    A low-cost rig (ADXL345, 3.2 kHz) must use a lower band, e.g. (300, 1500)."""
    x = _clean(x)
    x = x - x.mean()
    ff = fault_frequencies(rpm, geom)
    feats = _time_stats(x)

    # Envelope spectrum of the high-pass band (bearing impacts excite resonances)
    hi = min(band[1], 0.45 * fs)
    lo = min(band[0], 0.5 * hi)
    sos = signal.butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    xb = signal.sosfiltfilt(sos, x)
    env = np.abs(signal.hilbert(xb))
    env = env - env.mean()
    spec = np.abs(np.fft.rfft(env * np.hanning(len(env))))
    freqs = np.fft.rfftfreq(len(env), 1 / fs)
    ref = np.median(spec[(freqs > 5) & (freqs < 500)]) + EPS
    for name in ("bpfo", "bpfi", "fr"):
        for k in (1, 2, 3):
            feats.append(_db(_peak_energy(freqs, spec, k * ff[name]), ref))

    f, psd = signal.welch(x, fs=fs, nperseg=min(4096, len(x)))
    feats += _log_bands(f, psd, 10, fs / 2, 16)
    feats.append(float(stats.kurtosis(env)) if env.std() > EPS else 0.0)
    feats.append(_db(psd[f >= lo].sum(), psd.sum()))
    return np.asarray(feats, dtype=np.float32)


# ------------------------------------------------------------------- current
CUR_FEATURE_NAMES = (
    ["f1_hz", "imbalance_db"]
    + [f"h{k}_db" for k in range(2, 8)]
    + [f"sb_{s}{k}x{f}" for f in ("bpfo", "bpfi") for k in (1, 2) for s in ("m", "p")]
    + [f"band{i}" for i in range(12)]
    + ["resid_kurt", "resid_db"]
)


def _fundamental(freqs, spec, lo=10.0, hi=300.0):
    m = (freqs >= lo) & (freqs <= hi)
    i = np.argmax(spec[m])
    return float(freqs[m][i]), float(spec[m][i])


def current_features(c, fs: int, rpm: float) -> np.ndarray:
    """c: (2, n) phase currents. Features are averaged over the two phases."""
    c = _clean(c)
    ff = fault_frequencies(rpm)
    per_phase = []
    for x in c:
        x = x - x.mean()
        n = len(x)
        spec = np.abs(np.fft.rfft(x * np.hanning(n))) / n
        freqs = np.fft.rfftfreq(n, 1 / fs)
        f1, a1 = _fundamental(freqs, spec)
        row = [f1]
        row += [_db(_peak_energy(freqs, spec, k * f1, 0.01) ** 2, a1 ** 2) for k in range(2, 8)]
        for name in ("bpfo", "bpfi"):
            for k in (1, 2):
                for sgn in (-1, 1):
                    fsb = f1 + sgn * k * ff[name]
                    e = _peak_energy(freqs, spec, abs(fsb), 0.005, 0.5)
                    row.append(_db(e ** 2, a1 ** 2))
        f, psd = signal.welch(x, fs=fs, nperseg=8192)
        row += _log_bands(f, psd, 5, 8000, 12)
        # residual after removing the fundamental (notch)
        b, a = signal.iirnotch(max(f1, 1.0), Q=5, fs=fs)
        r = signal.filtfilt(b, a, x)
        row.append(float(stats.kurtosis(r)) if r.std() > EPS else 0.0)
        row.append(_db(np.mean(r ** 2), np.mean(x ** 2)))
        per_phase.append(row)
    per_phase = np.asarray(per_phase)
    mean = per_phase.mean(axis=0)
    rms = np.sqrt(np.mean(c ** 2, axis=1)) + EPS
    out = np.concatenate([[mean[0], _db(rms[0] ** 2, rms[1] ** 2)], mean[1:]])
    return out.astype(np.float32)


# ------------------------------------------------------------------- quality
QUALITY_NAMES = ["nan_frac", "flat_frac", "clip_frac", "log_rms", "flatness", "spike_db", "dominance"]


def quality_indicators(x, fs: int) -> np.ndarray:
    """Label-free health indicators of a sensor channel (or stacked channels)."""
    x = np.asarray(x, dtype=np.float64)
    x = x.reshape(-1, x.shape[-1]) if x.ndim > 1 else x[None]
    rows = []
    for ch in x:
        nan_frac = float(np.mean(~np.isfinite(ch)))
        ch = _clean(ch)
        d = np.abs(np.diff(ch))
        scale = np.std(ch) + EPS
        flat_frac = float(np.mean(d < 1e-6 * max(scale, 1e-3)))
        amax = np.max(np.abs(ch)) + EPS
        clip_frac = float(np.mean(np.abs(ch) >= 0.999 * amax)) if np.std(ch) > EPS else 1.0
        log_rms = float(np.log10(np.sqrt(np.mean(ch ** 2)) + 1e-9))
        f, psd = signal.welch(ch, fs=fs, nperseg=min(2048, len(ch)))
        psd = psd + EPS
        flatness = float(np.exp(np.mean(np.log(psd))) / np.mean(psd))
        med = np.median(ch)
        mad = np.median(np.abs(ch - med)) * 1.4826 + EPS
        spike_db = _db(np.max(np.abs(ch - med)), mad)
        dominance = float(psd.max() / psd.sum())
        rows.append([nan_frac, flat_frac, clip_frac, log_rms, flatness, spike_db, dominance])
    return np.asarray(rows).mean(axis=0).astype(np.float32)


# ---------------------------------------------------------- generic (rig)
GENERIC_NAMES = ["rms_log", "kurt", "skew", "crest", "mean_abs_over_rms", "dom_freq_hz"] + [f"band{i}" for i in range(8)]


def generic_features(x, fs: int) -> np.ndarray:
    """Model-free features for a signal without a known physical signature
    (e.g. DC-motor current on the rig). Not used on Paderborn."""
    x = _clean(x).ravel()
    xc = x - x.mean()
    f, psd = signal.welch(xc, fs=fs, nperseg=min(1024, len(xc)))
    feats = [float(np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))] + _time_stats(xc)
    feats.append(float(f[1:][np.argmax(psd[1:])]) if len(f) > 1 else 0.0)
    feats += _log_bands(f, psd, max(f[1], 1.0) if len(f) > 1 else 1.0, fs / 2, 8)
    return np.asarray(feats, dtype=np.float32)
