"""OB2 fusion variant: the learned gate of ``ReliabilityGated`` plus an explicit
sensor-exclusion rule driven by the corrected label-free detector (reliability_v2).

Rule (fixed before evaluation, same as the gearbox pipeline): a sensor that the
detector flags (degraded or failed) gets weight 0 and the other expert's output
is used alone; if both sensors are flagged the model ABSTAINS (no diagnosis).
The detector configuration is chosen per fold on training bearings only
(reliability_v2.select_config) and fitted on clean training windows only.
The original ``models.py`` classes are unchanged.
"""
from __future__ import annotations

import numpy as np

from .models import ReliabilityGated
from .reliability_v2 import fit_assessor, prepare


class GatedV2(ReliabilityGated):
    def __init__(self, cfg, baselines, kind="logreg", seed=0):
        super().__init__(kind, seed, use="both", hard_mask=True)
        self.cfg, self.baselines = cfg, baselines
        self.name = "gated_v2"

    def fit(self, t):
        super().fit(t)
        clean = {k: v[t["tag"] == "clean"] for k, v in t.items()}   # never the augmented rows
        fit_all = np.ones(len(clean["y"]), bool)
        self.av = fit_assessor(self.cfg, clean, "qv", fit_all, self.baselines["qv"], self.seed)
        self.ac = fit_assessor(self.cfg, clean, "qc", fit_all, self.baselines["qc"], self.seed)
        return self

    def flags(self, t):
        fv = self.av.flagged(prepare(self.cfg, t, "qv", self.baselines["qv"]), t["condition"])
        fc = self.ac.flagged(prepare(self.cfg, t, "qc", self.baselines["qc"]), t["condition"])
        return fv, fc

    def predict_with_abstain(self, t):
        pv, pc = self._probs(t)
        w = self.weights(t, pv, pc)
        fv, fc = self.flags(t)
        w[fv & ~fc] = [0.0, 1.0]
        w[fc & ~fv] = [1.0, 0.0]
        p = w[:, :1] * pv + w[:, 1:] * pc
        abstain = fv & fc
        p[abstain] = self.prior
        return p, abstain

    def predict_proba(self, t):
        return self.predict_with_abstain(t)[0]
