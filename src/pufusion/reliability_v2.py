"""Label-free sensor reliability, version 2 (OB2 correction).

Why a v2
--------
The original ``ReliabilityAssessor`` learns one [lo, hi] box per quality
indicator from clean training windows pooled over every bearing and every
operating condition, then widens it by 25 %. On Paderborn the clean vibration
indicators vary so much between operating conditions and bearings that broadband
noise, gain errors and spikes on the vibration channel mostly stay inside the box
(results/starter/quality.json: vibration noise 2-15 %, gain 2-16 %, spikes 2-11 %).

What v2 changes (still label-free: only CLEAN windows are used for fitting)
------------------------------------------------------------------------
* ``per_condition``: the normal range is learned separately for each operating
  condition (speed / load / radial-force set point), which the monitoring system
  knows at run time. Unseen conditions fall back to the pooled model.
* ``method="maha"``: a robust (MinCovDet) Mahalanobis distance over the four
  continuous indicators (log_rms, flatness, spike_db, dominance) instead of
  independent boxes, so a joint shift (e.g. noise: flatness up, dominance and
  spike level down) is caught even when no single indicator leaves its box. The
  threshold is the ``alpha`` quantile of the clean training distances.
* The hard rules of v1 are kept unchanged: NaN > 50 % or flat > 95 % = failed;
  clipping and missing/flat fractions above their clean range = degraded.

Configuration selection (``select_config``) uses TRAINING bearings only: inner
leave-one-training-bearing-out, scored on clean false flags and on detection of
the corruption families that are allowed in training (noise, dropout,
intermittent, gain). Test bearings and the withheld families (clipping, spikes,
stuck) are never used. The original class in ``reliability.py`` is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.covariance import MinCovDet

from .corruption import TRAIN_FAMILIES

CONT = [3, 4, 5, 6]          # log_rms, flatness, spike_db, dominance
HARD = [0, 1, 2]             # nan_frac, flat_frac, clip_frac (one-sided, "above" only)
OK, DEGRADED, FAILED = 0, 1, 2


@dataclass(frozen=True)
class V2Config:
    method: str = "maha"         # "box" | "maha"
    per_condition: bool = True
    q_lo: float = 0.5
    q_hi: float = 99.5
    margin: float = 0.25
    alpha: float = 99.5          # percentile of clean training distances (maha)
    baseline: bool = False       # compare each sensor with its own commissioning baseline

    @property
    def name(self):
        scope = ("base_" if self.baseline else "") + ("cond" if self.per_condition else "pooled")
        if self.method == "box":
            return f"box_{scope}_q{self.q_lo}-{self.q_hi}_m{self.margin}"
        return f"maha_{scope}_a{self.alpha}"


# a priori candidate sets (fixed before any held-out evaluation); v1-equivalent is the first
ABSOLUTE = [
    V2Config("box", False, 0.5, 99.5, 0.25),
    V2Config("box", True, 0.5, 99.5, 0.25),
    V2Config("box", True, 1.0, 99.0, 0.10),
    V2Config("maha", False, alpha=99.5),
    V2Config("maha", True, alpha=99.0),
    V2Config("maha", True, alpha=99.5),
]
# Commissioning-baseline variants: each sensor's indicators are expressed as the
# deviation from the median of its own first clean recording (repetition 1) under
# the same operating condition. Assumption, stated wherever results are reported:
# a monitoring system records a short known-good baseline when a sensor is
# installed. The baseline carries no fault label; the allowed deviation is learned
# from TRAINING bearings only.
BASELINE = [
    V2Config("box", False, 0.5, 99.5, 0.25, baseline=True),
    V2Config("box", False, 1.0, 99.0, 0.10, baseline=True),
    V2Config("maha", False, alpha=99.5, baseline=True),
    V2Config("maha", False, alpha=99.0, baseline=True),
]
CANDIDATES = ABSOLUTE + BASELINE


def repetition(stems) -> np.ndarray:
    """Repetition number from a Paderborn stem such as N15_M07_F10_KI18_3."""
    return np.array([int(str(s).rsplit("_", 1)[1]) for s in stems])


def build_baselines(table, key, rep_id=1) -> dict:
    """(bearing, condition) -> median of the continuous indicators over the
    CLEAN windows of commissioning recording ``rep_id``."""
    rep = repetition(table["stem"])
    out = {}
    for b in np.unique(table["bearing"]):
        for c in np.unique(table["condition"]):
            m = (table["bearing"] == b) & (table["condition"] == c) & (rep == rep_id)
            if m.any():
                out[(str(b), str(c))] = np.median(table[key][m][:, CONT], 0)
    return out


def apply_baseline(Q, bearings, conds, baselines) -> np.ndarray:
    """Replace the continuous indicators by their deviation from the baseline.
    Rows without a baseline get NaN deviations (treated as not assessable = flagged)."""
    Q = np.array(Q, float, copy=True)
    for i, (b, c) in enumerate(zip(bearings, conds)):
        ref = baselines.get((str(b), str(c)))
        Q[i, CONT] = Q[i, CONT] - ref if ref is not None else np.nan
    return Q


class _Model:
    """Normal-range model for one sensor within one scope (a condition or pooled)."""

    def __init__(self, cfg: V2Config, Q: np.ndarray, seed=0):
        self.cfg = cfg
        Q = Q[~np.isnan(Q).any(1)]
        lo, hi = np.percentile(Q, cfg.q_lo, 0), np.percentile(Q, cfg.q_hi, 0)
        pad = cfg.margin * (hi - lo) + 1e-3
        self.lo, self.hi = lo - pad, hi + pad
        if cfg.method == "maha":
            X = Q[:, CONT]
            self.mcd = MinCovDet(random_state=seed, support_fraction=0.9).fit(X)
            d = self.mcd.mahalanobis(X)
            self.thr = float(np.percentile(d, cfg.alpha))

    def status(self, Q: np.ndarray) -> np.ndarray:
        st = np.zeros(len(Q), dtype=int)
        hard_hi = (Q[:, HARD] > self.hi[HARD]).any(1)
        if self.cfg.method == "box":
            out = (Q[:, CONT] > self.hi[CONT]) | (Q[:, CONT] < self.lo[CONT])
            soft = out.any(1)
        else:
            X = np.nan_to_num(Q[:, CONT])
            soft = self.mcd.mahalanobis(X) > self.thr
        soft = soft | np.isnan(Q[:, CONT]).any(1)          # no baseline = cannot vouch for it
        st[hard_hi | soft] = DEGRADED
        st[(Q[:, 0] > 0.5) | (Q[:, 1] > 0.95)] = FAILED
        return st


class ConditionAwareAssessor:
    def __init__(self, cfg: V2Config = V2Config(), seed=0):
        self.cfg, self.seed = cfg, seed

    def fit(self, Q, cond):
        Q = np.asarray(Q, float)
        cond = np.asarray(cond)
        self.pooled = _Model(self.cfg, Q, self.seed)
        self.by_cond = {}
        if self.cfg.per_condition:
            for c in np.unique(cond):
                m = cond == c
                if m.sum() >= 50:
                    self.by_cond[str(c)] = _Model(self.cfg, Q[m], self.seed)
        return self

    def status(self, Q, cond) -> np.ndarray:
        Q = np.asarray(Q, float)
        cond = np.asarray(cond)
        out = self.pooled.status(Q)
        for c, model in self.by_cond.items():
            m = cond == c
            if m.any():
                out[m] = model.status(Q[m])
        return out

    def flagged(self, Q, cond) -> np.ndarray:
        return self.status(Q, cond) != OK


def _seen_tags(tags):
    return np.array([str(t).split(":")[1] in TRAIN_FAMILIES for t in tags])


def prepare(cfg, table, key, baselines=None) -> np.ndarray:
    """Indicator matrix the assessor sees: raw (absolute configs) or deviation from
    the sensor's own commissioning baseline (baseline configs)."""
    if not cfg.baseline:
        return table[key]
    return apply_baseline(table[key], table["bearing"], table["condition"], baselines)


def fit_assessor(cfg, clean, key, fit_mask, baselines=None, seed=0):
    """Fit on clean windows selected by ``fit_mask``. For baseline configs the
    commissioning recording itself is excluded from the deviation distribution."""
    m = fit_mask.copy()
    if cfg.baseline:
        m &= repetition(clean["stem"]) != 1
    Q = prepare(cfg, {k: v[m] for k, v in clean.items()}, key, baselines)
    return ConditionAwareAssessor(cfg, seed).fit(Q, clean["condition"][m])


def score_config(cfg, clean, corr, train_bearings, seed=0):
    """Inner leave-one-training-bearing-out evaluation of one configuration.

    Validation uses only repetitions >= 2 of the left-out TRAINING bearing (so
    absolute and baseline configurations are scored on identical windows).
    Returns mean clean false-flag rate and mean detection over seen-family
    corruptions on the corrupted sensor.
    """
    ff, det = [], []
    bl = {"qv": build_baselines(clean, "qv"), "qc": build_baselines(clean, "qc")}
    rep_clean, rep_corr = repetition(clean["stem"]), repetition(corr["stem"])
    mods = np.array([str(t).split(":")[0] for t in corr["tag"]])
    seen = _seen_tags(corr["tag"])
    for b in train_bearings:
        fit_mask = np.isin(clean["bearing"], [x for x in train_bearings if x != b])
        val_clean = (clean["bearing"] == b) & (rep_clean != 1)
        if not fit_mask.any() or not val_clean.any():
            continue
        for s, k in (("vib", "qv"), ("cur", "qc")):
            A = fit_assessor(cfg, clean, k, fit_mask, bl[k], seed)
            vc = {kk: v[val_clean] for kk, v in clean.items()}
            ff.append(A.flagged(prepare(cfg, vc, k, bl[k]), vc["condition"]).mean())
            hit = (corr["bearing"] == b) & (rep_corr != 1) & seen & np.isin(mods, [s, "both"])
            if hit.any():
                vr = {kk: v[hit] for kk, v in corr.items()}
                det.append(A.flagged(prepare(cfg, vr, k, bl[k]), vr["condition"]).mean())
    return float(np.mean(ff)), float(np.mean(det))


def select_config(clean, corr, train_bearings, candidates=CANDIDATES, max_false_flag=0.05, seed=0):
    """Pick the candidate with the highest inner detection whose inner clean
    false-flag rate is <= max_false_flag (else the lowest false-flag rate)."""
    scored = [(c, *score_config(c, clean, corr, train_bearings, seed=seed)) for c in candidates]
    ok = [s for s in scored if s[1] <= max_false_flag]
    best = max(ok, key=lambda s: (s[2], -s[1])) if ok else min(scored, key=lambda s: s[1])
    return best[0], [{"config": c.name, "inner_false_flag": round(f, 4), "inner_detect_seen": round(d, 4)}
                     for c, f, d in scored]
