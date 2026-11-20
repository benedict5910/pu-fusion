"""OB2 gating research: three alternatives to the hard exclusion rule of ``GatedV2``.

Motivation (results/full_2026-11-15): excluding every sensor the v2 detector flags
throws away mildly corrupted vibration that is still more informative than clean
current. All three rules below keep the v2 detector, the same experts and the same
learned gate; they differ only in how detector output changes the fusion weights.

Shared, fixed rules (not tuned):
  * a FAILED sensor (dead: NaN > 50 % or flat > 95 %) always gets weight 0;
  * the model abstains only when BOTH sensors are FAILED.

  soft      w_s ∝ g_s · exp(-e_s / tau)          g = learned gate weight, e = severity
  strength  w_s ∝ skill_s[state_s] ** beta       skill = out-of-fold balanced accuracy
                                                 above chance of expert s in detector
                                                 state ok / degraded (training bearings)
  severity  sensor excluded only if e_s > theta; otherwise the learned gate decides

``severity`` e is a continuous, label-free score from the fitted detector: 0 inside
the normal range, otherwise the largest exceedance in units of the range width
(box) or distance / threshold - 1 (Mahalanobis).

tau / beta / theta are chosen per outer fold by inner bearing-disjoint validation on
TRAINING bearings, using clean windows and seen corruption families only
(``select_params``). Existing modules are unchanged.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import f1_score, recall_score

from .corruption import TRAIN_FAMILIES
from .dataset import concat, subset
from .fusion_v2 import GatedV2
from .reliability_v2 import CONT, HARD, prepare, repetition
from .splits import inner_group_folds

GRIDS = {
    "soft": [0.1, 0.3, 1.0, 3.0, 10.0, 30.0],            # tau
    "strength": [0.5, 1.0, 2.0, 4.0, 8.0],               # beta
    "severity": [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, np.inf],   # theta (0 = exclude every flag)
}
METHODS = list(GRIDS)
BIG = 1e6


def _model_severity(model, Q):
    width = model.hi - model.lo
    over = (Q - model.hi) / width
    under = (model.lo - Q) / width
    e = np.maximum(over[:, HARD].max(1), 0.0)
    if model.cfg.method == "box":
        e = np.maximum(e, np.maximum(over[:, CONT], under[:, CONT]).max(1))
    else:
        d = model.mcd.mahalanobis(np.nan_to_num(Q[:, CONT]))
        e = np.maximum(e, d / model.thr - 1.0)
    e = np.where(np.isnan(Q[:, CONT]).any(1), BIG, e)      # no baseline: cannot vouch for it
    return np.nan_to_num(np.maximum(e, 0.0), nan=BIG, posinf=BIG)


def severity(assessor, Q, cond):
    """(e, failed): continuous exceedance (0 = inside normal range) and the dead-sensor rule."""
    Q = np.asarray(Q, float)
    cond = np.asarray(cond)
    e = _model_severity(assessor.pooled, Q)
    for c, model in assessor.by_cond.items():
        m = cond == c
        if m.any():
            e[m] = _model_severity(model, Q[m])
    failed = (Q[:, 0] > 0.5) | (Q[:, 1] > 0.95)
    return e, failed


class GatedV3(GatedV2):
    """Same experts, gate and detector as GatedV2; exposes what the three rules need."""

    def __init__(self, cfg, baselines, kind="logreg", seed=0):
        super().__init__(cfg, baselines, kind, seed)
        self.name = "gated_v3_base"

    def _oof(self, t):
        self._oof_cache = super()._oof(t)
        return self._oof_cache

    def _sev(self, t):
        ev, fv = severity(self.av, prepare(self.cfg, t, "qv", self.baselines["qv"]), t["condition"])
        ec, fc = severity(self.ac, prepare(self.cfg, t, "qc", self.baselines["qc"]), t["condition"])
        return ev, fv, ec, fc

    def fit(self, t):
        super().fit(t)
        # expert skill per detector state, from out-of-fold (bearing-grouped) predictions on training rows
        pv, pc = self._oof_cache
        ev, fv, ec, fc = self._sev(t)
        self.skill = np.zeros((2, 2))
        for i, (p, e, f) in enumerate(((pv, ev, fv), (pc, ec, fc))):
            overall = recall_score(t["y"][~f], p[~f].argmax(1), average="macro")
            for st, m in enumerate(((e == 0) & ~f, (e > 0) & ~f)):
                acc = recall_score(t["y"][m], p[m].argmax(1), average="macro") if m.sum() >= 50 else overall
                self.skill[i, st] = max(acc - 1 / 3, 0.01)
        del self._oof_cache
        return self

    def pack(self, t):
        pv, pc = self._probs(t)
        g = ReliabilityGatedWeights(self, t, pv, pc)
        ev, fv, ec, fc = self._sev(t)
        return {"pv": pv, "pc": pc, "g": g, "ev": ev, "ec": ec, "fv": fv, "fc": fc,
                "skill": self.skill, "prior": self.prior}


def ReliabilityGatedWeights(model, t, pv, pc):
    """Learned gate weights WITHOUT any hard mask (masks are applied by the rules)."""
    old = model.hard_mask
    model.hard_mask = False
    try:
        return model.weights(t, pv, pc)
    finally:
        model.hard_mask = old


def combine(method, param, k):
    """Apply one rule. Returns (probabilities, abstain mask, weights)."""
    ev, ec, fv, fc = k["ev"], k["ec"], k["fv"], k["fc"]
    if method == "soft":
        w = k["g"] * np.exp(-np.stack([ev, ec], 1) / param)
    elif method == "strength":
        sv = k["skill"][0][(ev > 0).astype(int)]
        sc = k["skill"][1][(ec > 0).astype(int)]
        w = np.stack([sv, sc], 1) ** param
    elif method == "severity":
        w = k["g"].copy()
        xv, xc = ev > param, ec > param
        w[xv & ~xc] = [0.0, 1.0]
        w[xc & ~xv] = [1.0, 0.0]
    else:
        raise ValueError(method)
    w = np.array(w, float, copy=True)
    w[fv, 0] = 0.0
    w[fc, 1] = 0.0
    s = w.sum(1, keepdims=True)
    tiny = s[:, 0] < 1e-300                       # both weights underflowed but not both failed
    w[tiny] = k["g"][tiny] * np.stack([~fv[tiny], ~fc[tiny]], 1)
    abstain = fv & fc
    w[abstain] = 0.5
    w = w / w.sum(1, keepdims=True)
    p = w[:, :1] * k["pv"] + w[:, 1:] * k["pc"]
    p[abstain] = k["prior"]
    return p, abstain, w


def _score(y, tags, p, abstain):
    """Inner objective: mean of clean macro-F1 and mean per-tag macro-F1 over seen tags; abstain = wrong."""
    pr = np.where(abstain, -1, p.argmax(1))
    f = lambda m: f1_score(y[m], pr[m], labels=[0, 1, 2], average="macro", zero_division=0)
    clean = tags == "clean"
    seen = [f(tags == t) for t in np.unique(tags[~clean])]
    return 0.5 * f(clean) + 0.5 * float(np.mean(seen))


def select_params(tables, train_bearings, cfg, baselines, kind="logreg", seed=0, k=3):
    """Inner bearing-disjoint validation on TRAINING bearings only.

    Validation rows: repetitions >= 2 of the inner-held-out training bearings, clean
    plus corrupted windows of the SEEN families only. Returns the chosen parameter
    and the full inner score table for each method.
    """
    tb = np.array(sorted(train_bearings))
    lab = np.array([tables["clean"]["y"][tables["clean"]["bearing"] == b][0] for b in tb])
    fam_seen = np.array([str(t).split(":")[1] in TRAIN_FAMILIES for t in tables["corr"]["tag"]])
    scores = {m: np.zeros(len(GRIDS[m])) for m in METHODS}
    n = 0
    for tr, va in inner_group_folds(tb, lab, k=k, seed=seed):
        trb, vab = tb[tr], tb[va]
        train = concat(subset(tables["clean"], np.isin(tables["clean"]["bearing"], trb)),
                       subset(tables["aug"], np.isin(tables["aug"]["bearing"], trb)))
        vc = subset(tables["clean"], np.isin(tables["clean"]["bearing"], vab))
        vc = subset(vc, repetition(vc["stem"]) != 1)
        vr = subset(tables["corr"], np.isin(tables["corr"]["bearing"], vab) & fam_seen)
        vr = subset(vr, repetition(vr["stem"]) != 1)
        val = concat(vc, vr)
        pk = GatedV3(cfg, baselines, kind, seed).fit(train).pack(val)
        for m in METHODS:
            for i, prm in enumerate(GRIDS[m]):
                p, ab, _ = combine(m, prm, pk)
                scores[m][i] += _score(val["y"], val["tag"], p, ab)
        n += 1
    out = {}
    for m in METHODS:
        s = scores[m] / n
        out[m] = {"param": float(GRIDS[m][int(np.argmax(s))]),
                  "inner": {str(g): round(float(x), 4) for g, x in zip(GRIDS[m], s)}}
    return out
