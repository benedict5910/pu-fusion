"""Explanations for the logistic-regression experts and the reliability gate.

For a linear model, the exact contribution of feature j to the log-odds of
class c (relative to the average class) is (w_cj - mean_k w_kj) * z_j, where z
is the standardised feature. For linear models with standardised inputs this
equals linear SHAP under a feature-independence assumption, so SHAP is not
needed. Tree experts (HGB) are not explained here.

Two different things are reported and must not be confused:
- *confidence*: the fused class probability (how sure the model is);
- *explanation faithfulness*: a deletion test - how much that probability
  drops when the top-k cited features are reset to their training mean. A
  confident prediction can still have an unfaithful (uninformative) explanation.
"""
from __future__ import annotations

import numpy as np

from .config import CLASS_NAMES
from .features import CUR_FEATURE_NAMES, QUALITY_NAMES, VIB_FEATURE_NAMES

GATE_NAMES = ([f"vib_{n}" for n in QUALITY_NAMES] + [f"cur_{n}" for n in QUALITY_NAMES]
              + ["vib_entropy", "cur_entropy", "vib_maxprob", "cur_maxprob"])


def _parts(pipe):
    scaler, clip, clf = (s for _, s in pipe.steps)
    return scaler, clip, clf


def linear_contributions(pipe, x, cls: int) -> np.ndarray:
    scaler, clip, clf = _parts(pipe)
    if not hasattr(clf, "coef_"):
        raise TypeError("explanations are implemented for linear experts only")
    z = clip.transform(scaler.transform(np.atleast_2d(x)))[0]
    W = np.zeros((3, clf.coef_.shape[1]))
    W[clf.classes_] = clf.coef_
    return (W[cls] - W.mean(0)) * z


def top_k(values, names, k=5):
    idx = np.argsort(-np.abs(values))[:k]
    return [{"feature": names[i], "contribution": round(float(values[i]), 3)} for i in idx]


def deletion_check(pipe, x, cls: int, k=5) -> float:
    """Drop in P(cls) when the top-k contributing features are set to the training mean."""
    scaler, clip, clf = _parts(pipe)
    x = np.atleast_2d(np.asarray(x, dtype=float)).copy()
    contrib = linear_contributions(pipe, x[0], cls)
    p0 = _p(pipe, x, cls)
    for j in np.argsort(-np.abs(contrib))[:k]:
        x[0, j] = scaler.mean_[j]
    return float(p0 - _p(pipe, x, cls))


def _p(pipe, x, cls):
    p = np.zeros(3)
    clf = pipe.steps[-1][1]
    p[clf.classes_] = pipe.predict_proba(x)[0]
    return p[cls]


def explain_gated(model, t: dict, k=5) -> dict:
    """Explanation for ONE window of a fitted ReliabilityGated model."""
    p = model.predict_proba(t)[0]
    cls = int(np.argmax(p))
    pv, pc = model._probs(t)
    w = model.weights(t, pv, pc)[0]
    cv = linear_contributions(model.ev, t["fv"][0], cls)
    cc = linear_contributions(model.ec, t["fc"][0], cls)
    out = {
        "predicted": CLASS_NAMES[cls],
        "confidence": round(float(p[cls]), 3),
        "sensor_weights": {"vibration": round(float(w[0]), 3), "current": round(float(w[1]), 3)},
        "vibration_evidence": top_k(cv, VIB_FEATURE_NAMES, k),
        "current_evidence": top_k(cc, CUR_FEATURE_NAMES, k),
        "faithfulness_drop": {"vibration": round(deletion_check(model.ev, t["fv"][0], cls, k), 3),
                              "current": round(deletion_check(model.ec, t["fc"][0], cls, k), 3)},
    }
    if model.use == "both":
        z = np.clip((model._z(t, pv, pc) - model.mu) / model.sd, -8, 8)[0]
        drive = (model.A[:, 0] - model.A[:, 1]) * z      # >0 pushes trust toward vibration
        out["gate_drivers"] = top_k(drive, GATE_NAMES, 3)
    return out
