"""Leakage-resistant splits. The unit of splitting is the physical bearing.

Protocol P1 (primary, "bearing-disjoint"):
  Test pool = 6 healthy + 5 real outer-race + 6 real inner-race bearings.
  Each repeat shuffles each class pool and cuts it into 3 folds, so every test
  fold holds ~2 healthy, ~2 real OR and 2 real IR bearings the model never saw.
  Artificially damaged bearings are only ever used for training.
Protocol P2 (secondary, "artificial -> real"):
  Train on artificial damage + half the healthy bearings; test on all real
  damage + the other healthy half (then swap the healthy halves).
Protocol P3 (diagnostic only): leave-one-operating-condition-out *within* P1
  folds, i.e. both bearing- and condition-disjoint.
"""
from __future__ import annotations

import numpy as np

from .config import BEARINGS, HEALTHY, INNER, OUTER


def _pool(cls, origin):
    return sorted(b for b, (c, o) in BEARINGS.items() if c == cls and o == origin)


def p1_folds(n_repeats=5, n_folds=3, seed=0):
    rng = np.random.default_rng(seed)
    pools = [_pool(HEALTHY, "healthy"), _pool(OUTER, "real"), _pool(INNER, "real")]
    artificial = sorted(b for b, (_, o) in BEARINGS.items() if o == "artificial")
    folds = []
    for r in range(n_repeats):
        parts = [np.array_split(rng.permutation(p), n_folds) for p in pools]
        for k in range(n_folds):
            test = sorted(str(b) for part in parts for b in part[k])
            train = sorted(set(BEARINGS) - set(test))
            assert set(artificial) <= set(train)
            folds.append({"name": f"P1_r{r}_f{k}", "train": train, "test": test})
    return folds


def p2_folds():
    healthy = _pool(HEALTHY, "healthy")
    art = sorted(b for b, (_, o) in BEARINGS.items() if o == "artificial")
    real = sorted(b for b, (_, o) in BEARINGS.items() if o == "real")
    halves = [healthy[:3], healthy[3:]]
    return [
        {"name": f"P2_h{i}", "train": sorted(art + halves[i]), "test": sorted(real + halves[1 - i])}
        for i in (0, 1)
    ]


def assert_disjoint(train_bearings, test_bearings):
    overlap = set(train_bearings) & set(test_bearings)
    if overlap:
        raise AssertionError(f"bearing leakage: {sorted(overlap)} in both train and test")


def inner_group_folds(bearings: np.ndarray, labels: np.ndarray, k=3, seed=0):
    """Grouped, class-aware folds over the *training* bearings (for OOF predictions)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(bearings)
    lab = {b: labels[bearings == b][0] for b in uniq}
    assign = {}
    for c in np.unique(labels):
        bs = rng.permutation([b for b in uniq if lab[b] == c])
        for i, b in enumerate(bs):
            assign[b] = i % k
    fold_of = np.array([assign[b] for b in bearings])
    return [(np.where(fold_of != i)[0], np.where(fold_of == i)[0]) for i in range(k)]
