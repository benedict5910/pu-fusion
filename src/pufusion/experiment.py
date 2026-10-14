"""Runs a protocol: for each fold, fit every model on training bearings only and
evaluate on held-out bearings (clean, every corruption, and alarm replay)."""
from __future__ import annotations

import copy
import time

import numpy as np

from .config import HEALTHY
from .dataset import concat, subset
from .metrics import classification, replay_latency
from .splits import assert_disjoint


def _rows_for(table, bearings, condition=None):
    m = np.isin(table["bearing"], bearings)
    if condition is not None:
        m &= table["condition"] == condition
    return subset(table, m)


def _replay(model, test):
    """Average healthy->fault replay over all (healthy, faulty) test bearing pairs."""
    out = []
    for cond in np.unique(test["condition"]):
        tc = subset(test, test["condition"] == cond)
        order = np.lexsort((tc["win"], tc["stem"]))
        tc = subset(tc, order)
        p_fault = 1 - model.predict_proba(tc)[:, HEALTHY]
        healthy = [b for b in np.unique(tc["bearing"]) if (tc["y"][tc["bearing"] == b] == HEALTHY).all()]
        faulty = [b for b in np.unique(tc["bearing"]) if b not in healthy]
        for h in healthy:
            for f in faulty:
                out.append(replay_latency(p_fault[tc["bearing"] == h], p_fault[tc["bearing"] == f]))
    if not out:
        return {}
    return {k: float(np.nanmean([o[k] for o in out])) for k in out[0]}


def run(tables, folds, models, use_aug=True, condition_holdout=False, log=print):
    rows = []
    for fold in folds:
        assert_disjoint(fold["train"], fold["test"])
        conds = np.unique(tables["clean"]["condition"]) if condition_holdout else [None]
        for held in conds:
            train = _rows_for(tables["clean"], fold["train"])
            if use_aug and "aug" in tables:
                train = concat(train, _rows_for(tables["aug"], fold["train"]))
            if held is not None:
                train = subset(train, train["condition"] != held)
            test = _rows_for(tables["clean"], fold["test"], held)
            corr = _rows_for(tables["corr"], fold["test"], held) if "corr" in tables else None
            for proto in models:
                model = copy.deepcopy(proto)
                t0 = time.time()
                model.fit(train)
                base = {"fold": fold["name"], "held_condition": held or "-", "model": model.name,
                        "aug": use_aug, "fit_s": round(time.time() - t0, 2)}
                clean_row = {**base, "corruption": "none:clean:None",
                             **classification(test["y"], model.predict_proba(test)),
                             **_replay(model, test)}
                rows.append(clean_row)
                if corr is not None and len(corr["y"]):
                    p = model.predict_proba(corr)
                    for tag in np.unique(corr["tag"]):
                        m = corr["tag"] == tag
                        rows.append({**base, "corruption": str(tag),
                                     **classification(corr["y"][m], p[m])})
                log(f"{fold['name']} held={held or '-'} {model.name}: "
                    f"clean macro-F1={clean_row['macro_f1']:.3f}")
    return rows
