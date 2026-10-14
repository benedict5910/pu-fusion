"""Label-free sensor reliability assessment.

Learns the normal range of each quality indicator from *healthy-sensor* data
(clean training windows on Paderborn, or a healthy calibration session on the
rig) and flags windows outside it. It never sees fault labels, so the same code
works on both platforms after refitting on that platform's own data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import QUALITY_NAMES

# indicator -> human-readable cause when it is ABOVE / BELOW its normal range
_CAUSES = {
    "nan_frac": ("missing samples (link loss)", None),
    "flat_frac": ("stuck or intermittent signal", None),
    "clip_frac": ("clipping / saturation", None),
    "log_rms": ("amplitude too high (gain error or loose mount)", "amplitude too low (gain error or detached sensor)"),
    "flatness": ("broadband noise", None),
    "spike_db": ("impulsive spikes (EMI or connector)", None),
    "dominance": (None, "signal structure lost (noise or distortion)"),
}


@dataclass
class SensorReliability:
    score: float                       # 1 = all indicators in normal range, 0 = failed
    status: str                        # "ok" | "degraded" | "failed"
    reasons: list[str] = field(default_factory=list)

    def as_dict(self):
        return {"score": round(self.score, 3), "status": self.status, "reasons": self.reasons}


class ReliabilityAssessor:
    def __init__(self, q_lo=0.5, q_hi=99.5, margin=0.25):
        self.q_lo, self.q_hi, self.margin = q_lo, q_hi, margin

    def fit(self, Q: np.ndarray):
        Q = np.asarray(Q, dtype=float)
        lo, hi = np.percentile(Q, self.q_lo, 0), np.percentile(Q, self.q_hi, 0)
        pad = self.margin * (hi - lo) + 1e-3
        self.lo, self.hi = lo - pad, hi + pad
        return self

    def assess(self, q) -> SensorReliability:
        q = np.asarray(q, dtype=float)
        i = {n: k for k, n in enumerate(QUALITY_NAMES)}
        if q[i["nan_frac"]] > 0.5 or q[i["flat_frac"]] > 0.95:
            cause = "no data (missing samples)" if q[i["nan_frac"]] > 0.5 else "dead or stuck sensor"
            return SensorReliability(0.0, "failed", [cause])
        reasons = []
        for name, k in i.items():
            above, below = _CAUSES[name]
            if q[k] > self.hi[k] and above:
                reasons.append(above)
            elif q[k] < self.lo[k] and below:
                reasons.append(below)
        score = 1.0 - len(reasons) / len(QUALITY_NAMES)
        return SensorReliability(score, "degraded" if reasons else "ok", reasons)

    def state(self):
        return {"lo": self.lo.tolist(), "hi": self.hi.tolist()}
