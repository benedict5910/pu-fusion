"""Quality assessor, logistic experts, conventional fusion baselines and the per-window
quality-informed gate (plus ablations). All learners are standardised logistic regression.
"""
from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupKFold

from .features import VIB_NAMES, CUR_NAMES, Q_NAMES

QV = [f"qv_{q}" for q in Q_NAMES]
QC = [f"qc_{q}" for q in Q_NAMES]
ONE_SIDED = {"nan_frac", "flat_frac", "clip_frac", "spike_frac"}
K = 3


def _lr(C=1.0):
    return make_pipeline(StandardScaler(),
                         LogisticRegression(C=C, max_iter=3000, class_weight="balanced"))


# ----------------------------------------------------------------------------- quality assessor
class QualityAssessor:
    """Label-free: per-indicator bounds learned from clean training windows only."""

    def fit(self, Q: np.ndarray, names=Q_NAMES, q=0.001, widen=0.25):
        self.names = list(names)
        lo, hi = np.quantile(Q, q, axis=0), np.quantile(Q, 1 - q, axis=0)
        span = np.maximum(hi - lo, 1e-6)
        self.lo, self.hi, self.scale = lo - widen * span, hi + widen * span, span
        for i, n in enumerate(self.names):
            if n in ONE_SIDED:
                self.lo[i] = -np.inf
                if n == "nan_frac":  # any missing sample is abnormal for a healthy sensor stream
                    self.hi[i] = max(self.hi[i], 0.0)
        return self

    def scores(self, Q: np.ndarray) -> np.ndarray:
        """Per-indicator exceedance (0 inside bounds), in units of the clean span."""
        z = np.maximum(Q - self.hi, 0) + np.maximum(self.lo - Q, 0)
        return np.where(np.isfinite(z), z / self.scale, 0.0)

    def flag(self, Q: np.ndarray) -> np.ndarray:
        return (self.scores(Q) > 0).any(axis=1)

    def dead(self, Q: np.ndarray) -> np.ndarray:
        i_nan, i_flat = self.names.index("nan_frac"), self.names.index("flat_frac")
        return (Q[:, i_nan] > 0.5) | (Q[:, i_flat] > 0.5)

    def to_dict(self):
        return {"names": self.names, "lo": self.lo.tolist(), "hi": self.hi.tolist(),
                "scale": self.scale.tolist()}


def _conf_feats(P):
    P = np.clip(P, 1e-9, 1)
    s = np.sort(P, axis=1)
    ent = -(P * np.log(P)).sum(1) / np.log(P.shape[1])
    return np.column_stack([s[:, -1], s[:, -1] - s[:, -2], ent])


# ----------------------------------------------------------------------------- fusion suite
MODELS = ["vib_only", "cur_only", "early", "average", "stacked", "gated"]
ABLATIONS = ["gated_quality_only", "gated_conf_only", "gated_no_mask"]


class FusionSuite:
    """Fits all six models (+ gate ablations) on identical training rows."""

    def __init__(self, inner_folds=3, seed=0):
        self.inner_folds, self.seed = inner_folds, seed

    def fit(self, df_train, df_clean_train):
        y = df_train["label"].to_numpy()
        g = df_train["bearing"].to_numpy()
        Xv, Xc = df_train[VIB_NAMES].to_numpy(), df_train[CUR_NAMES].to_numpy()
        # label-free quality assessors: clean training windows only
        self.qa_v = QualityAssessor().fit(df_clean_train[QV].to_numpy())
        self.qa_c = QualityAssessor().fit(df_clean_train[QC].to_numpy())
        self.vib = _lr().fit(Xv, y)
        self.cur = _lr().fit(Xc, y)
        self.early = _lr().fit(np.hstack([Xv, Xc]), y)
        # bearing-grouped out-of-fold expert probabilities for stacking and gate training
        Pv, Pc = np.zeros((len(y), K)), np.zeros((len(y), K))
        nf = min(self.inner_folds, len(np.unique(g)))
        for tr, te in GroupKFold(nf).split(Xv, y, g):
            Pv[te] = _lr().fit(Xv[tr], y[tr]).predict_proba(Xv[te])
            Pc[te] = _lr().fit(Xc[tr], y[tr]).predict_proba(Xc[te])
        self.stack = _lr().fit(np.log(np.clip(np.hstack([Pv, Pc]), 1e-9, 1)), y)
        Sv = self.qa_v.scores(df_train[QV].to_numpy())
        Sc = self.qa_c.scores(df_train[QC].to_numpy())
        cv, cc = (Pv.argmax(1) == y).astype(int), (Pc.argmax(1) == y).astype(int)
        self.gates = {}
        for name, use_q, use_c in [("gated", 1, 1), ("gated_quality_only", 1, 0),
                                   ("gated_conf_only", 0, 1)]:
            fv = self._gate_x(Sv, Pv, use_q, use_c)
            fc = self._gate_x(Sc, Pc, use_q, use_c)
            self.gates[name] = (self._fit_bin(fv, cv), self._fit_bin(fc, cc))
        return self

    @staticmethod
    def _fit_bin(X, t):
        if len(np.unique(t)) < 2:
            return float(t.mean())
        return _lr().fit(X, t)

    @staticmethod
    def _gate_x(S, P, use_q, use_c):
        parts = []
        if use_q:
            parts.append(np.log1p(np.minimum(S, 100)))
        if use_c:
            parts.append(_conf_feats(P))
        return np.hstack(parts)

    @staticmethod
    def _p1(model, X):
        return np.full(len(X), model) if isinstance(model, float) else model.predict_proba(X)[:, 1]

    def predict_all(self, df):
        Xv, Xc = df[VIB_NAMES].to_numpy(), df[CUR_NAMES].to_numpy()
        Qv, Qc = df[QV].to_numpy(), df[QC].to_numpy()
        Pv, Pc = self.vib.predict_proba(Xv), self.cur.predict_proba(Xc)
        out = {"vib_only": Pv, "cur_only": Pc,
               "early": self.early.predict_proba(np.hstack([Xv, Xc])),
               "average": 0.5 * (Pv + Pc),
               "stacked": self.stack.predict_proba(np.log(np.clip(np.hstack([Pv, Pc]), 1e-9, 1)))}
        Sv, Sc = self.qa_v.scores(Qv), self.qa_c.scores(Qc)
        dv, dc = self.qa_v.dead(Qv), self.qa_c.dead(Qc)
        extras = {"flag_v": self.qa_v.flag(Qv), "flag_c": self.qa_c.flag(Qc), "dead_v": dv,
                  "dead_c": dc}
        for name, use_q, use_c in [("gated", 1, 1), ("gated_quality_only", 1, 0),
                                   ("gated_conf_only", 0, 1), ("gated_no_mask", 1, 1)]:
            gname = "gated" if name == "gated_no_mask" else name
            gv, gc = self.gates[gname]
            wv = self._p1(gv, self._gate_x(Sv, Pv, use_q, use_c))
            wc = self._p1(gc, self._gate_x(Sc, Pc, use_q, use_c))
            if name != "gated_no_mask":
                wv, wc = np.where(dv, 0, wv), np.where(dc, 0, wc)
            both = (wv + wc) < 1e-9
            wv, wc = np.where(both, 0.5, wv), np.where(both, 0.5, wc)
            out[name] = (wv[:, None] * Pv + wc[:, None] * Pc) / (wv + wc)[:, None]
            if name == "gated":
                extras.update({"w_v": wv / (wv + wc), "w_c": wc / (wv + wc), "both_dead": both})
        return out, extras
