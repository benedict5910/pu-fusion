"""IVHM monitoring engine: one call per window runs
reliability assessment -> diagnosis -> health decision -> logging.

Two diagnosers with an identical interface keep the two platforms apart:
- BenchmarkDiagnoser: Paderborn-trained reliability-gated fusion, used ONLY on
  Paderborn recordings (validated, bearing-disjoint).
- RigDiagnoser: healthy-baseline anomaly detection trained on the rig itself.
"""
from __future__ import annotations

import time

import numpy as np

from .config import CLASS_NAMES, HEALTHY, OPERATING_CONDITIONS
from .dataset import extract
from .explain import explain_gated
from .health import HealthTracker
from .rig import RigAnomalyDetector, RigConfig, rig_features

SOURCE_BENCHMARK = "benchmark replay (Paderborn, held-out bearing)"
SOURCE_RIG = "rig live"
SOURCE_SIM = "SIMULATED rig"


def _temp_or_none(t):
    """DS18B20 reports -127 C when not fitted or disconnected: show 'no reading', not a temperature."""
    return None if t is None or not np.isfinite(t) or t <= -100 else float(t)


class BenchmarkDiagnoser:
    def __init__(self, model, assessors):
        self.model, self.assessors = model, assessors

    def __call__(self, win: dict) -> dict:
        rpm = OPERATING_CONDITIONS[win["condition"]][0]
        feats = extract(win["vib"], win["cur"], win["fs"], rpm)
        t = {k: np.asarray(v)[None] for k, v in feats.items()}
        rel = {"vib": self.assessors["vib"].assess(feats["qv"]), "cur": self.assessors["cur"].assess(feats["qc"])}
        p = self.model.predict_proba(t)[0]
        cls = int(np.argmax(p))
        out = {"reliability": rel, "p_fault": float(1 - p[HEALTHY]),
               "fault_type": CLASS_NAMES[cls] if cls != HEALTHY else None,
               "confidence": float(p[cls]), "probs": dict(zip(CLASS_NAMES, map(float, p))),
               "readings": {"vib_rms_g": float(np.sqrt(np.nanmean(np.square(win["vib"])))),
                            "cur_rms_a": float(np.sqrt(np.nanmean(np.square(win["cur"])))), "rpm": rpm}}
        if hasattr(self.model, "weights"):
            w = self.model.weights(t)[0]
            out["weights"] = {"vib": float(w[0]), "cur": float(w[1])}
            try:
                out["explanation"] = explain_gated(self.model, t)
            except TypeError:
                out["explanation"] = None
        return out


class RigDiagnoser:
    def __init__(self, detector: RigAnomalyDetector, assessors, cfg: RigConfig | None = None):
        self.det, self.assessors, self.cfg = detector, assessors, cfg or RigConfig()

    def __call__(self, win: dict) -> dict:
        feats = rig_features(win, self.cfg)
        rel = {"vib": self.assessors["vib"].assess(feats["qv"]), "cur": self.assessors["cur"].assess(feats["qc"])}
        ev = self.det.evidence(feats)
        return {"reliability": rel, "p_fault": RigAnomalyDetector.combine(ev, rel), "fault_type": None,
                "confidence": None, "sensor_evidence": {s: float(np.ravel(v)[0]) for s, v in ev.items()},
                "readings": {"vib_rms_g": float(np.sqrt(np.nanmean(np.square(win["vib"])))),
                             "cur_mean_a": float(np.nanmean(win["cur"])), "rpm": win.get("rpm"),
                             "temp_c": _temp_or_none(win.get("temp_c")), "vbus": win.get("vbus")}}


class MonitorEngine:
    def __init__(self, diagnoser, source: str, asset: str = "bearing-1", store=None, tracker=None):
        self.diag, self.source, self.asset = diagnoser, source, asset
        self.store, self.tracker = store, tracker or HealthTracker()

    def step(self, win: dict, ts: float | None = None) -> dict:
        ts = ts or time.time()
        d = self.diag(win)
        before = self.tracker.state
        a = self.tracker.update(d["p_fault"], d["fault_type"], d["reliability"])
        rec = {"ts": ts, "asset": self.asset, "source": self.source, "state": a.state,
               "p_fault": d["p_fault"], "fault_type": d["fault_type"], "confidence": d.get("confidence"),
               "rel_vib": d["reliability"]["vib"].score, "rel_cur": d["reliability"]["cur"].score,
               "w_vib": d.get("weights", {}).get("vib"), "w_cur": d.get("weights", {}).get("cur"),
               "readings": d["readings"], "explanation": d.get("explanation"),
               "recommendations": a.recommendations}
        if self.store:
            self.store.log_window(rec)
            if a.state != before:
                self.store.log_event(self.asset, self.source, before, a.state, a.rule, a.recommendations, ts)
        return {**rec, "assessment": a, "diagnosis": d}
