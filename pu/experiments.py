"""Protocols P1/P2/P3 + random-split leakage demonstration + OB2 quality evaluation.

Usage: python -m pu.experiments <features_dir> <results_dir> [--protocols P1,P2,P3,LEAK]
Writes per-run metric rows (CSV), confusion matrices (JSON) and a run manifest.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.metrics import f1_score, confusion_matrix
from sklearn.model_selection import StratifiedKFold

from .data import HEALTHY, OR_REAL, IR_REAL, OR_ARTIFICIAL, IR_ARTIFICIAL, CONDITIONS
from .features import SEEN, WITHHELD, FAMILY
from .models import FusionSuite, MODELS, ABLATIONS, QV, QC

ALL_MODELS = MODELS + ABLATIONS


# ----------------------------------------------------------------------------- data
def load_features(fdir: str | Path) -> pd.DataFrame:
    files = sorted(Path(fdir).glob("*.pkl"))
    df = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True)
    df["variant"] = df["variant"].astype("category")
    df["corrupted"] = df["corrupted"].astype("category")
    return df


def training_rows(df_tr: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Clean rows + one seeded random *seen* corruption per window per sensor.
    Identical for every model (equal augmentation)."""
    clean = df_tr[df_tr.variant == "clean"]
    keys = clean[["file", "win"]].drop_duplicates().reset_index(drop=True)
    rng = np.random.default_rng(seed)
    parts = [clean]
    for s in ("vib", "cur"):
        k = keys.copy()
        k["variant"] = rng.choice(SEEN, len(k))
        k["corrupted"] = s
        sub = df_tr[df_tr.corrupted == s]
        parts.append(sub.merge(k, on=["file", "win", "variant", "corrupted"]))
    return pd.concat(parts, ignore_index=True)


# ----------------------------------------------------------------------------- metrics
def ece(P, y, bins=15):
    conf, pred = P.max(1), P.argmax(1)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (conf > a) & (conf <= b)
        if m.any():
            e += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return e


def metrics(P, y):
    pred = P.argmax(1)
    Pc = np.clip(P, 1e-12, 1)
    onehot = np.eye(P.shape[1])[y]
    healthy, faulty = y == 0, y != 0
    return {"macro_f1": f1_score(y, pred, average="macro", labels=[0, 1, 2], zero_division=0),
            "accuracy": float((pred == y).mean()),
            "nll": float(-np.log(Pc[np.arange(len(y)), y]).mean()),
            "brier": float(((P - onehot) ** 2).sum(1).mean()),
            "ece": float(ece(P, y)),
            "false_alarm": float((pred[healthy] != 0).mean()) if healthy.any() else np.nan,
            "miss": float((pred[faulty] == 0).mean()) if faulty.any() else np.nan}


def evaluate(suite, df_te, run_info, cm_store):
    rows = []
    qrows = []
    for (variant, sensor), d in df_te.groupby(["variant", "corrupted"], observed=True):
        y = d["label"].to_numpy()
        out, ex = suite.predict_all(d)
        for m in ALL_MODELS:
            r = dict(run_info, variant=variant, corrupted=sensor, model=m,
                     family=FAMILY.get(variant, "clean"),
                     split=("clean" if variant == "clean" else
                            "seen" if variant in SEEN else "withheld"), n=len(y))
            r.update(metrics(out[m], y))
            rows.append(r)
            if variant == "clean" or m in ("gated", "early", "vib_only", "cur_only", "average",
                                           "stacked"):
                key = f"{run_info['protocol']}|{m}|{variant}|{sensor}"
                cm = confusion_matrix(y, out[m].argmax(1), labels=[0, 1, 2])
                cm_store[key] = (np.array(cm_store[key]) + cm).tolist() if key in cm_store \
                    else cm.tolist()
        qrows.append(dict(run_info, variant=variant, corrupted=sensor,
                          family=FAMILY.get(variant, "clean"), n=len(y),
                          flag_vib=float(ex["flag_v"].mean()), flag_cur=float(ex["flag_c"].mean()),
                          dead_vib=float(ex["dead_v"].mean()), dead_cur=float(ex["dead_c"].mean()),
                          mean_w_vib=float(ex["w_v"].mean()),
                          both_dead=float(ex["both_dead"].mean())))
    return rows, qrows


# ----------------------------------------------------------------------------- splits
def p1_splits(repeats=5, folds=3):
    for r in range(repeats):
        rng = np.random.default_rng(1000 + r)
        assign = {}
        for group in (HEALTHY, OR_REAL, IR_REAL):
            perm = list(rng.permutation(group))
            for i, b in enumerate(perm):
                assign[b] = i % folds
        for f in range(folds):
            test = [b for b, k in assign.items() if k == f]
            train = [b for b, k in assign.items() if k != f]
            yield r, f, train, test


def run(features_dir, results_dir, protocols=("P1", "P2", "P3", "LEAK")):
    res = Path(results_dir)
    res.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    df = load_features(features_dir)
    manifest = {"n_rows": len(df), "n_files": int(df.file.nunique()),
                "bearings": sorted(df.bearing.unique().tolist()),
                "conditions": sorted(df.condition.unique().tolist()),
                "windows_clean": int((df.variant == "clean").sum()),
                "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows, qrows, cms = [], [], {}

    def do(protocol, rep, fold, train_b, test_b, train_cond=None, test_cond=None, seed=0):
        tr = df[df.bearing.isin(train_b)]
        te = df[df.bearing.isin(test_b)]
        if train_cond is not None:
            tr, te = tr[tr.condition.isin(train_cond)], te[te.condition.isin(test_cond)]
        if tr.empty or te.empty or te.label.nunique() < 3:
            return
        trows = training_rows(tr, seed)
        suite = FusionSuite(seed=seed).fit(trows, tr[tr.variant == "clean"])
        info = {"protocol": protocol, "repeat": rep, "fold": fold,
                "test_bearings": ",".join(test_b),
                "test_condition": ",".join(test_cond) if test_cond else "all"}
        a, b = evaluate(suite, te, info, cms)
        rows.extend(a)
        qrows.extend(b)
        print(protocol, rep, fold, info["test_condition"], f"{time.time()-t0:.0f}s", flush=True)

    if "P1" in protocols:
        for r, f, tr_b, te_b in p1_splits():
            do("P1", r, f, tr_b, te_b, seed=r * 10 + f)
    if "P2" in protocols:
        for i, (h_tr, h_te) in enumerate([(HEALTHY[:3], HEALTHY[3:]), (HEALTHY[3:], HEALTHY[:3])]):
            do("P2", i, 0, h_tr + OR_ARTIFICIAL + IR_ARTIFICIAL, h_te + OR_REAL + IR_REAL, seed=i)
    if "P3" in protocols:
        for r, f, tr_b, te_b in p1_splits(repeats=1):
            for c in CONDITIONS:
                do("P3", r, f, tr_b, te_b, [k for k in CONDITIONS if k != c], [c], seed=f)
    if "LEAK" in protocols:
        # leakage demonstration: random window split that mixes bearings (clean data only)
        sub = df[df.bearing.isin(HEALTHY + OR_REAL + IR_REAL)]
        keys = sub[sub.variant == "clean"][["file", "win", "label"]].reset_index(drop=True)
        skf = StratifiedKFold(3, shuffle=True, random_state=0)
        for f, (a, b) in enumerate(skf.split(keys, keys.label)):
            ka, kb = keys.iloc[a][["file", "win"]], keys.iloc[b][["file", "win"]]
            tr = sub.merge(ka, on=["file", "win"])
            te = sub.merge(kb, on=["file", "win"])
            trows = training_rows(tr, f)
            suite = FusionSuite(seed=f).fit(trows, tr[tr.variant == "clean"])
            a_, _ = evaluate(suite, te[te.variant == "clean"],
                             {"protocol": "LEAK_random_split", "repeat": 0, "fold": f,
                              "test_bearings": "mixed", "test_condition": "all"}, cms)
            rows.extend(a_)
        print("LEAK done", flush=True)

    R = pd.DataFrame(rows)
    Q = pd.DataFrame(qrows)
    R.to_csv(res / "metrics_all.csv", index=False)
    Q.to_csv(res / "quality_all.csv", index=False)
    (res / "confusion_matrices.json").write_text(json.dumps(cms))
    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["seconds"] = round(time.time() - t0)
    (res / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return R, Q


# ----------------------------------------------------------------------------- statistics
def holm(pvals):
    p = np.asarray(pvals)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(p) - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj


def paired_tests(R: pd.DataFrame, protocol="P1", ref="gated"):
    d = R[R.protocol == protocol]
    agg = (d.groupby(["repeat", "fold", "split", "model"], observed=True)["macro_f1"].mean()
           .unstack("model"))
    out = []
    for split in ("clean", "seen", "withheld"):
        s = agg.xs(split, level="split")
        for m in MODELS:
            if m == ref:
                continue
            diff = s[ref] - s[m]
            try:
                p = wilcoxon(s[ref], s[m]).pvalue if (diff != 0).any() else 1.0
            except ValueError:
                p = 1.0
            out.append({"split": split, "baseline": m, "n_pairs": len(diff),
                        "mean_ref": s[ref].mean(), "mean_baseline": s[m].mean(),
                        "mean_diff": diff.mean(), "wins": int((diff > 0).sum()), "p_raw": p})
    T = pd.DataFrame(out)
    T["p_holm"] = holm(T.p_raw.to_numpy())
    return T


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("features_dir")
    ap.add_argument("results_dir")
    ap.add_argument("--protocols", default="P1,P2,P3,LEAK")
    a = ap.parse_args()
    R, _ = run(a.features_dir, a.results_dir, tuple(a.protocols.split(",")))
    for p in sorted(R.protocol.unique()):
        if p == "P1":
            paired_tests(R, p).to_csv(Path(a.results_dir) / f"stats_{p}.csv", index=False)
