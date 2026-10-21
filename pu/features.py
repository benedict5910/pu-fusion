"""Windowing, physics-based features, sensor corruptions and label-free quality indicators.

All functions are deterministic given a numpy Generator.
"""
from __future__ import annotations
import numpy as np
from scipy import signal as sps
from scipy.stats import kurtosis, skew

FS = 64000.0
WIN_S = 0.5
EPS = 1e-12

# 6203 deep-groove ball bearing: 8 balls, ball diameter 6.75 mm, pitch diameter 28.55 mm
N_BALLS, D_BALL, D_PITCH = 8, 6.75, 28.55
BPFO_RATIO = N_BALLS / 2 * (1 - D_BALL / D_PITCH)   # ~3.05 x shaft frequency
BPFI_RATIO = N_BALLS / 2 * (1 + D_BALL / D_PITCH)   # ~4.95 x shaft frequency


def windows(x: np.ndarray, fs: float = FS, win_s: float = WIN_S) -> list[slice]:
    n = x.shape[-1]
    w = int(round(fs * win_s))
    return [slice(i, i + w) for i in range(0, n - w + 1, w)]


# ----------------------------------------------------------------------------- corruptions
SEEN = ["noise20", "noise10", "noise0", "dropout", "intermit10", "intermit30",
        "gain_low", "gain_high"]
WITHHELD = ["clip60", "clip30", "spike_lo", "spike_hi", "stuck20", "stuck50"]
FAMILY = {"noise20": "noise", "noise10": "noise", "noise0": "noise", "dropout": "dropout",
          "intermit10": "intermittent", "intermit30": "intermittent",
          "gain_low": "gain_offset", "gain_high": "gain_offset",
          "clip60": "clipping", "clip30": "clipping", "spike_lo": "spikes",
          "spike_hi": "spikes", "stuck20": "stuck", "stuck50": "stuck"}


def corrupt(x: np.ndarray, kind: str, rng: np.random.Generator) -> np.ndarray:
    """Apply one corruption to a sensor window. x: [n] or [ch, n]. Returns float copy."""
    y = np.array(x, dtype=np.float64, copy=True)
    two_d = y.ndim == 2
    Y = y if two_d else y[None, :]
    n = Y.shape[1]
    if kind.startswith("noise"):
        snr = float(kind[5:])
        for c in range(Y.shape[0]):
            r = np.sqrt(np.mean(Y[c] ** 2)) + EPS
            Y[c] += rng.normal(0, r / 10 ** (snr / 20), n)
    elif kind == "dropout":
        Y[:] = np.nan
    elif kind.startswith("intermit"):
        frac = float(kind[8:]) / 100
        seg = int(n * frac / 4)
        for _ in range(4):
            s = rng.integers(0, n - seg)
            Y[:, s:s + seg] = np.nan
    elif kind in ("gain_low", "gain_high"):
        g = 0.5 if kind == "gain_low" else 2.0
        sign = -1 if kind == "gain_low" else 1
        for c in range(Y.shape[0]):
            Y[c] = Y[c] * g + sign * 0.5 * np.std(Y[c])
    elif kind.startswith("clip"):
        lvl = float(kind[4:]) / 100
        for c in range(Y.shape[0]):
            m = lvl * np.max(np.abs(Y[c]))
            Y[c] = np.clip(Y[c], -m, m)
    elif kind.startswith("spike"):
        k = 8 if kind == "spike_lo" else 64
        for c in range(Y.shape[0]):
            idx = rng.choice(n, k, replace=False)
            Y[c, idx] += rng.choice([-1, 1], k) * 10 * np.std(Y[c])
    elif kind.startswith("stuck"):
        frac = float(kind[5:]) / 100
        L = int(n * frac)
        s = rng.integers(0, n - L)
        Y[:, s:s + L] = Y[:, s:s + 1]
    else:
        raise ValueError(kind)
    return Y if two_d else Y[0]


# ----------------------------------------------------------------------------- quality indicators
Q_NAMES = ["nan_frac", "flat_frac", "clip_frac", "log_rms", "spec_flatness", "spike_frac",
           "dominance"]


def _quality_1d(x: np.ndarray) -> np.ndarray:
    n = len(x)
    nanm = ~np.isfinite(x)
    nan_frac = nanm.mean()
    v = x[~nanm]
    if len(v) < 64:
        return np.array([nan_frac, 1.0, 0.0, np.log10(EPS), 0.0, 0.0, 0.0])
    d = np.diff(v)
    flat_frac = np.mean(d == 0)
    amax = np.max(np.abs(v)) + EPS
    clip_frac = np.mean(np.abs(v) >= 0.995 * amax)
    log_rms = np.log10(np.sqrt(np.mean(v ** 2)) + EPS)
    p = np.abs(np.fft.rfft((v - v.mean()) * np.hanning(len(v)))) ** 2 + EPS
    flat = np.exp(np.mean(np.log(p))) / np.mean(p)
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med)) + EPS
    spike_frac = np.mean(np.abs(v - med) > 8 * mad)
    dom = p.max() / p.sum()
    return np.array([nan_frac, flat_frac, clip_frac, log_rms, flat, spike_frac, dom])


def quality(x: np.ndarray) -> np.ndarray:
    """7 label-free indicators. For multi-channel input (currents), fractions take the
    worst channel and continuous indicators the mean."""
    if x.ndim == 1:
        return _quality_1d(x)
    q = np.vstack([_quality_1d(c) for c in x])
    out = q.mean(0)
    for i in (0, 1, 2, 5):
        out[i] = q[:, i].max()
    return out


# ----------------------------------------------------------------------------- features
_BP = sps.butter(4, [2000, 20000], btype="bandpass", fs=FS, output="sos")


def _peak_near(freqs, spec, f0, tol=0.03):
    m = (freqs >= f0 * (1 - tol)) & (freqs <= f0 * (1 + tol))
    return spec[m].max() if m.any() else EPS


VIB_NAMES = (["v_rms", "v_std", "v_kurt", "v_skew", "v_crest", "v_p2p", "v_shape", "v_impulse"]
             + [f"v_env_bpfo{k}" for k in (1, 2, 3)] + [f"v_env_bpfi{k}" for k in (1, 2, 3)]
             + ["v_env_fr"] + [f"v_band{i}" for i in range(8)])


def vib_features(x: np.ndarray, rpm: float, fs: float = FS) -> np.ndarray:
    x = np.nan_to_num(x, nan=0.0)
    x = x - x.mean()
    rms = np.sqrt(np.mean(x ** 2)) + EPS
    a = np.abs(x)
    f = [np.log10(rms), np.log10(np.std(x) + EPS), np.log10(kurtosis(x, fisher=False) + EPS)
         if rms > 1e-9 else 0.0, skew(x) if rms > 1e-9 else 0.0, a.max() / rms,
         np.log10(np.ptp(x) + EPS), rms / (a.mean() + EPS), a.max() / (a.mean() + EPS)]
    fr = rpm / 60.0
    env = np.abs(sps.hilbert(sps.sosfiltfilt(_BP, x)))
    env -= env.mean()
    es = np.abs(np.fft.rfft(env * np.hanning(len(env))))
    ef = np.fft.rfftfreq(len(env), 1 / fs)
    base = np.median(es[(ef > 5) & (ef < 1000)]) + EPS
    for r in [BPFO_RATIO * k for k in (1, 2, 3)] + [BPFI_RATIO * k for k in (1, 2, 3)] + [1.0]:
        f.append(np.log10(_peak_near(ef, es, r * fr) / base + EPS))
    p = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    pf = np.fft.rfftfreq(len(x), 1 / fs)
    tot = p.sum() + EPS
    edges = np.linspace(0, fs / 2, 9)
    for i in range(8):
        f.append(np.log10(p[(pf >= edges[i]) & (pf < edges[i + 1])].sum() / tot + EPS))
    return np.nan_to_num(np.array(f, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)


CUR_NAMES = (["c_rms", "c_res_ratio", "c_h3", "c_h5", "c_h7", "c_sb_bpfo1", "c_sb_bpfo2",
              "c_sb_bpfi1", "c_sb_bpfi2", "c_res_kurt", "c_res_crest"]
             + [f"c_band{i}" for i in range(8)])
_CUR_EDGES = [0, 100, 300, 600, 1000, 2000, 5000, 10000, 32000]


def _cur_1d(x, rpm, fs):
    x = np.nan_to_num(x, nan=0.0)
    x = x - x.mean()
    n = len(x)
    X = np.fft.rfft(x * np.hanning(n))
    p = np.abs(X)
    fq = np.fft.rfftfreq(n, 1 / fs)
    band = (fq > 20) & (fq < 250)
    fe = fq[band][np.argmax(p[band])] if p[band].max() > EPS else 100.0
    fund = _peak_near(fq, p, fe, 0.02)
    out = [np.log10(np.sqrt(np.mean(x ** 2)) + EPS)]
    # residual: remove fundamental and odd harmonics (+-4 Hz) from the raw spectrum
    Xr = np.fft.rfft(x)
    mask = np.zeros_like(fq, dtype=bool)
    for h in range(1, 16):
        mask |= np.abs(fq - h * fe) <= 4
    Xr[mask] = 0
    res = np.fft.irfft(Xr, n)
    tot = np.sum(x ** 2) + EPS
    out.append(np.log10(np.sum(res ** 2) / tot + EPS))
    for h in (3, 5, 7):
        out.append(np.log10(_peak_near(fq, p, h * fe, 0.02) / (fund + EPS) + EPS))
    fr = rpm / 60.0
    base = np.median(p[(fq > 5) & (fq < 1000)]) + EPS
    for r in (BPFO_RATIO, BPFI_RATIO):
        for k in (1, 2):
            fc = k * r * fr
            a = 0.5 * (_peak_near(fq, p, abs(fe - fc)) + _peak_near(fq, p, fe + fc))
            out.append(np.log10(a / base + EPS))
    rr = np.sqrt(np.mean(res ** 2)) + EPS
    out.append(np.log10(kurtosis(res, fisher=False) + EPS) if rr > 1e-9 else 0.0)
    out.append(np.max(np.abs(res)) / rr)
    pw = np.abs(X) ** 2
    t = pw.sum() + EPS
    for i in range(8):
        out.append(np.log10(pw[(fq >= _CUR_EDGES[i]) & (fq < _CUR_EDGES[i + 1])].sum() / t + EPS))
    return np.nan_to_num(np.array(out, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)


def cur_features(x: np.ndarray, rpm: float, fs: float = FS) -> np.ndarray:
    """x: [2, n] two phase currents; features averaged over phases."""
    return np.mean([_cur_1d(c, rpm, fs) for c in x], axis=0)
