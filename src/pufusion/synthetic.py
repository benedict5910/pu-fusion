"""SYNTHETIC signals for unit tests and pipeline smoke runs ONLY.

Nothing produced from this module is an experimental result. It exists so the
code can be tested without the Paderborn data. Signals mimic the structure of
the real problem (impacts at BPFO/BPFI exciting a resonance; current with a
fundamental, harmonics and weak fault sidebands; per-bearing variation) but
not its difficulty.
"""
from __future__ import annotations

import zlib

import numpy as np

from .config import BEARINGS, INNER, OUTER, OPERATING_CONDITIONS, fault_frequencies
from .data import Recording


def synth_recording(bearing, condition, repetition, seconds=1.0, fs=64_000):
    label, origin = BEARINGS[bearing]
    rpm = OPERATING_CONDITIONS[condition][0]
    ff = fault_frequencies(rpm)
    brng = np.random.default_rng(zlib.crc32(bearing.encode()))       # bearing identity
    rng = np.random.default_rng(zlib.crc32(f"{bearing}{condition}{repetition}".encode()))
    n = int(seconds * fs)
    t = np.arange(n) / fs
    res_f = brng.uniform(4000, 9000)
    sev = brng.uniform(0.6, 1.4)

    vib = 0.3 * np.sin(2 * np.pi * ff["fr"] * t) + 0.1 * np.sin(4 * np.pi * ff["fr"] * t)
    vib += rng.normal(0, 0.2, n)
    if label in (OUTER, INNER):
        f_imp = ff["bpfo"] if label == OUTER else ff["bpfi"]
        kernel_t = np.arange(int(0.003 * fs)) / fs
        kernel = np.exp(-kernel_t * 1500) * np.sin(2 * np.pi * res_f * kernel_t)
        imp = np.zeros(n)
        idx = (np.arange(0, seconds, 1 / f_imp) * fs).astype(int)
        amp = sev * (1 + (0.5 * np.sin(2 * np.pi * ff["fr"] * idx / fs) if label == INNER else 0))
        imp[idx[idx < n]] = amp[: (idx < n).sum()] if np.ndim(amp) else amp
        vib += np.convolve(imp, kernel)[:n]

    f1 = 4 * ff["fr"]
    cur = []
    for ph in (0, 2 * np.pi / 3):
        x = 2.0 * np.sin(2 * np.pi * f1 * t + ph) + 0.1 * np.sin(2 * np.pi * 5 * f1 * t + ph)
        if label in (OUTER, INNER):
            fb = ff["bpfo"] if label == OUTER else ff["bpfi"]
            for s in (-1, 1):
                x += 0.02 * sev * np.sin(2 * np.pi * (f1 + s * fb) * t + ph)
        cur.append(x + rng.normal(0, 0.05, n))
    stem = f"{condition}_{bearing}_{repetition}"
    return Recording(stem=stem, condition=condition, bearing=bearing, repetition=repetition,
                     label=label, origin=origin, vib=vib.astype(np.float32),
                     cur=np.asarray(cur, dtype=np.float32), fs=fs)
