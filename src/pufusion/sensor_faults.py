"""Controlled replay faults for one sampled sensor channel."""
from __future__ import annotations

import numpy as np

from . import corruption

SCENARIOS = {
    "dropout": None,
    "stuck": None,
    "intermittent": 0.2,
    "clipping": 0.2,
    "noise": 0,
    "gain": 2.0,
    "spikes": 100,
}


def inject(samples, family, rng, fs):
    """Apply a named scenario without modifying the recording."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or len(samples) < 2 or fs <= 0 or not np.isfinite(samples).all():
        raise ValueError("Expected a finite one-dimensional sampled signal")
    severity = SCENARIOS[family]
    if family == "spikes":
        # The original bearing implementation defaults to the Paderborn rate.
        return corruption.spikes(samples, rng, severity, fs=fs)
    transform, _ = corruption.FAMILIES[family]
    return transform(samples, rng, severity)
