"""Baselines and the proposed reliability-gated late fusion.

All models share one interface: ``fit(table)`` and ``predict_proba(table)``,
where ``table`` is a dict with fv, fc (features), qv, qc (quality indicators),
y and bearing. All models use the *same* expert classifier family and receive
the *same* training rows, so differences come from the fusion rule only.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .splits import inner_group_folds

N_CLASSES = 3
EPS = 1e-9


def _clip(z):
    return np.clip(z, -8, 8)


def make_expert(kind="logreg", seed=0):
    if kind == "logreg":
        clf = LogisticRegression(C=0.1, max_iter=3000, class_weight="balanced")
    elif kind == "hgb":
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             class_weight="balanced", random_state=seed)
    else:
        raise ValueError(kind)
    return make_pipeline(StandardScaler(), FunctionTransformer(_clip), clf)


def _full_proba(model, X):
    """predict_proba padded to all 3 classes (a fold may miss a class)."""
    p = np.zeros((len(X), N_CLASSES))
    p[:, model.classes_] = model.predict_proba(X)
    return p


def _entropy(p):
    return -(p * np.log(p + EPS)).sum(1, keepdims=True)


class SingleSensor:
    def __init__(self, modality, kind="logreg", seed=0):
        self.key = {"vib": "fv", "cur": "fc"}[modality]
        self.m = make_expert(kind, seed)
        self.name = f"{modality}_only"

    def fit(self, t):
        self.m.fit(t[self.key], t["y"])
        return self

    def predict_proba(self, t):
        return _full_proba(self.m, t[self.key])


class EarlyFusion:
    """Concatenate both feature vectors into one classifier."""
    name = "early_fusion"

    def __init__(self, kind="logreg", seed=0):
        self.m = make_expert(kind, seed)

    def fit(self, t):
        self.m.fit(np.hstack([t["fv"], t["fc"]]), t["y"])
        return self

    def predict_proba(self, t):
        return _full_proba(self.m, np.hstack([t["fv"], t["fc"]]))


class _LateBase:
    def __init__(self, kind="logreg", seed=0):
        self.kind, self.seed = kind, seed

    def _experts(self, t):
        ev = make_expert(self.kind, self.seed).fit(t["fv"], t["y"])
        ec = make_expert(self.kind, self.seed).fit(t["fc"], t["y"])
        return ev, ec

    def _oof(self, t):
        """Out-of-fold expert probabilities, grouped by bearing (no self-prediction)."""
        pv = np.zeros((len(t["y"]), N_CLASSES))
        pc = np.zeros_like(pv)
        for tr, va in inner_group_folds(t["bearing"], t["y"], k=3, seed=self.seed):
            sub = {k: v[tr] for k, v in t.items()}
            ev, ec = self._experts(sub)
            pv[va] = _full_proba(ev, t["fv"][va])
            pc[va] = _full_proba(ec, t["fc"][va])
        return pv, pc

    def _probs(self, t):
        return _full_proba(self.ev, t["fv"]), _full_proba(self.ec, t["fc"])


class LateAverage(_LateBase):
    name = "late_average"

    def fit(self, t):
        self.ev, self.ec = self._experts(t)
        return self

    def predict_proba(self, t):
        pv, pc = self._probs(t)
        return 0.5 * (pv + pc)


class LateStacked(_LateBase):
    """Static learned combination: logistic regression on expert log-probs."""
    name = "late_stacked"

    def fit(self, t):
        pv, pc = self._oof(t)
        self.meta = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
        self.meta.fit(np.hstack([np.log(pv + EPS), np.log(pc + EPS)]), t["y"])
        self.ev, self.ec = self._experts(t)
        return self

    def predict_proba(self, t):
        pv, pc = self._probs(t)
        return _full_proba(self.meta, np.hstack([np.log(pv + EPS), np.log(pc + EPS)]))


class ReliabilityGated(_LateBase):
    """Proposed: per-window expert weights from label-free quality indicators.

    p(y|x) = w_vib(z) * p_vib(y|x) + w_cur(z) * p_cur(y|x),  w = softmax(z A + b)
    z = [quality(vib), quality(cur), entropy and max-prob of each expert].
    A, b are fitted by penalised maximum likelihood on out-of-fold expert
    outputs. With ``hard_mask`` a channel that is plainly dead (NaN / flat) gets
    weight zero regardless of the gate.
    ``use`` selects gate inputs for the ablation: "quality", "confidence", "both".
    """

    def __init__(self, kind="logreg", seed=0, use="both", hard_mask=True, l2=1e-2):
        super().__init__(kind, seed)
        self.use, self.hard_mask, self.l2 = use, hard_mask, l2
        self.name = f"gated_{use}" + ("" if hard_mask else "_nomask")

    def _z(self, t, pv, pc):
        parts = []
        if self.use in ("quality", "both"):
            parts += [t["qv"], t["qc"]]
        if self.use in ("confidence", "both"):
            parts += [_entropy(pv), _entropy(pc), pv.max(1, keepdims=True), pc.max(1, keepdims=True)]
        return np.hstack(parts)

    @staticmethod
    def _dead(q):
        return (q[:, 0] > 0.5) | (q[:, 1] > 0.95)

    def fit(self, t):
        pv, pc = self._oof(t)
        z = self._z(t, pv, pc)
        self.mu, self.sd = z.mean(0), z.std(0) + 1e-6
        z = np.clip((z - self.mu) / self.sd, -8, 8)
        P = np.stack([pv, pc], 1)                      # (n, 2, K)
        Py = P[np.arange(len(t["y"])), :, t["y"]]      # (n, 2)
        d = z.shape[1]

        def loss(theta):
            A, b = theta[:2 * d].reshape(d, 2), theta[2 * d:]
            s = z @ A + b
            s -= s.max(1, keepdims=True)
            w = np.exp(s); w /= w.sum(1, keepdims=True)
            py = (w * Py).sum(1) + EPS
            L = -np.log(py).mean() + self.l2 * (A ** 2).sum()
            g_s = -(w * (Py - py[:, None])) / py[:, None] / len(py)
            gA = z.T @ g_s + 2 * self.l2 * A
            return L, np.concatenate([gA.ravel(), g_s.sum(0)])

        res = minimize(loss, np.zeros(2 * d + 2), jac=True, method="L-BFGS-B")
        self.A, self.b = res.x[:2 * d].reshape(d, 2), res.x[2 * d:]
        self.prior = np.bincount(t["y"], minlength=N_CLASSES) / len(t["y"])
        self.ev, self.ec = self._experts(t)
        return self

    def weights(self, t, pv=None, pc=None):
        if pv is None:
            pv, pc = self._probs(t)
        z = np.clip((self._z(t, pv, pc) - self.mu) / self.sd, -8, 8)
        s = z @ self.A + self.b
        s -= s.max(1, keepdims=True)
        w = np.exp(s); w /= w.sum(1, keepdims=True)
        if self.hard_mask:
            dv, dc = self._dead(t["qv"]), self._dead(t["qc"])
            w[dv & ~dc] = [0.0, 1.0]
            w[dc & ~dv] = [1.0, 0.0]
        return w

    def predict_proba(self, t):
        pv, pc = self._probs(t)
        w = self.weights(t, pv, pc)
        p = w[:, :1] * pv + w[:, 1:] * pc
        if self.hard_mask:
            both = self._dead(t["qv"]) & self._dead(t["qc"])
            p[both] = self.prior
        return p


def model_zoo(kind="logreg", seed=0):
    return [
        SingleSensor("vib", kind, seed),
        SingleSensor("cur", kind, seed),
        EarlyFusion(kind, seed),
        LateAverage(kind, seed),
        LateStacked(kind, seed),
        ReliabilityGated(kind, seed, use="both"),
    ]


def ablation_zoo(kind="logreg", seed=0):
    return [
        ReliabilityGated(kind, seed, use="quality"),
        ReliabilityGated(kind, seed, use="confidence"),
        ReliabilityGated(kind, seed, use="both", hard_mask=False),
    ]
