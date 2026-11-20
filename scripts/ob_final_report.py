"""Turn results/ob_final/predictions.npz into OB1/OB2 tables, confusion matrices and tests.

Definitions (fixed before looking at results)
  - groups: clean | seen (noise, dropout, intermittent, gain) | withheld (clipping, spikes, stuck)
  - abstained window: the model gives no diagnosis (gated_v2: both sensors flagged by the
    v2 detector; gated_both: both sensors dead by the original hard rule)
  - macro_f1: over ALL windows, an abstained window counts as wrong for its true class
  - macro_f1_covered: over non-abstained windows only;  coverage = 1 - abstain rate
  - false_alarm_rate: healthy windows diagnosed as damaged / healthy windows
  - missed_fault_rate: damaged windows diagnosed as healthy / damaged windows
  - undiagnosed_fault_rate: damaged windows abstained / damaged windows
  - run-level: metric per (fold, tag), averaged over the tags of a group, then mean +- sd
    over the bearing-disjoint runs; paired Wilcoxon over runs, Holm-corrected
  - bearing-level: per held-out bearing, the fraction of its windows correctly diagnosed
    (abstain = wrong), averaged over runs; paired Wilcoxon over bearings (independent units)

  python scripts/ob_final_report.py results/ob_final/predictions.npz
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon
from sklearn.metrics import f1_score, precision_recall_fscore_support

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.corruption import HELD_OUT_FAMILIES  # noqa: E402

CLASSES = ["healthy", "outer_race", "inner_race"]
PROPOSED = "gated_v2"


def group(tag):
    if tag == "clean" or str(tag).startswith("none"):
        return "clean"
    return "withheld" if str(tag).split(":")[1] in HELD_OUT_FAMILIES else "seen"


def metrics(y, pred, ab):
    pr = np.where(ab, -1, pred)
    h, f = y == 0, y != 0
    cov = ~ab
    return {
        "macro_f1": f1_score(y, pr, labels=[0, 1, 2], average="macro", zero_division=0),
        "macro_f1_covered": (f1_score(y[cov], pr[cov], labels=[0, 1, 2], average="macro", zero_division=0)
                             if cov.any() else np.nan),
        "coverage": cov.mean(),
        "false_alarm_rate": ((pr != 0) & (pr != -1) & h).sum() / max(h.sum(), 1),
        "missed_fault_rate": ((pr == 0) & f).sum() / max(f.sum(), 1),
        "undiagnosed_fault_rate": ((pr == -1) & f).sum() / max(f.sum(), 1),
    }


def holm(pvals):
    order = np.argsort(pvals)
    adj = np.empty(len(pvals))
    run = 0.0
    for i, k in enumerate(order):
        run = max(run, (len(pvals) - i) * pvals[k])
        adj[k] = min(1.0, run)
    return adj


def main():
    path = Path(sys.argv[1])
    out_dir = path.parent
    z = np.load(path)
    D = {k: z[k] for k in z.files}
    D["group"] = np.array([group(x) for x in D["tag"]])
    models = list(dict.fromkeys(D["model"].tolist()))
    folds = list(dict.fromkeys(D["fold"].tolist()))
    groups = ["clean", "seen", "withheld"]
    res = {"source": str(path), "runs": len(folds), "models": models, "definitions": __doc__}

    # ---- run-level summary
    per_run = defaultdict(list)          # (model, group, metric) -> per-run values
    for m in models:
        for fo in folds:
            for g in groups:
                sel = (D["model"] == m) & (D["fold"] == fo) & (D["group"] == g)
                vals = defaultdict(list)
                for tag in np.unique(D["tag"][sel]):
                    s = sel & (D["tag"] == tag)
                    for k, v in metrics(D["y"][s], D["pred"][s], D["abstain"][s]).items():
                        vals[k].append(v)
                for k, v in vals.items():
                    per_run[(m, g, k)].append(float(np.nanmean(v)))
    summary = {}
    for (m, g, k), v in per_run.items():
        summary.setdefault(m, {}).setdefault(g, {})[k] = {"mean": round(float(np.mean(v)), 4),
                                                          "sd": round(float(np.std(v)), 4)}
    res["run_level"] = summary

    # ---- paired tests over runs and over bearings (proposed vs every other model)
    tests = []
    for g in groups:
        for m in models:
            if m == PROPOSED:
                continue
            d = np.array(per_run[(PROPOSED, g, "macro_f1")]) - np.array(per_run[(m, g, "macro_f1")])
            p = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
            tests.append({"unit": "run", "group": g, "vs": m, "mean_diff": round(float(d.mean()), 4), "p": p})
    bacc = defaultdict(lambda: defaultdict(list))
    for m in models:
        for b in np.unique(D["bearing"]):
            for g in groups:
                for fo in folds:
                    s = (D["model"] == m) & (D["bearing"] == b) & (D["group"] == g) & (D["fold"] == fo)
                    if s.any():
                        ok = (D["pred"][s] == D["y"][s]) & ~D["abstain"][s]
                        bacc[(m, g)][b].append(ok.mean())
    bearing_level = {}
    for (m, g), d in bacc.items():
        bearing_level.setdefault(m, {})[g] = {b: round(float(np.mean(v)), 4) for b, v in sorted(d.items())}
    res["bearing_level_accuracy"] = bearing_level
    for g in groups:
        bs = sorted(bearing_level[PROPOSED][g])
        for m in models:
            if m == PROPOSED:
                continue
            d = np.array([bearing_level[PROPOSED][g][b] - bearing_level[m][g][b] for b in bs])
            p = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
            tests.append({"unit": "bearing", "group": g, "vs": m, "mean_diff": round(float(d.mean()), 4),
                          "n": len(bs), "p": p})
    for unit in ("run", "bearing"):
        idx = [i for i, x in enumerate(tests) if x["unit"] == unit]
        adj = holm(np.array([tests[i]["p"] for i in idx]))
        for i, a in zip(idx, adj):
            tests[i]["p"] = round(float(tests[i]["p"]), 4)
            tests[i]["p_holm"] = round(float(a), 4)
    res["tests"] = tests

    # ---- per-class metrics and pooled confusion matrices (rows true, cols pred + abstain)
    pc, cms = {}, {}
    for m in models:
        for g in groups:
            s = (D["model"] == m) & (D["group"] == g)
            y, pr = D["y"][s], np.where(D["abstain"][s], -1, D["pred"][s])
            P, R, F, N = precision_recall_fscore_support(y, pr, labels=[0, 1, 2], zero_division=0)
            pc.setdefault(m, {})[g] = {c: {"precision": round(float(P[i]), 4), "recall": round(float(R[i]), 4),
                                           "f1": round(float(F[i]), 4), "support": int(N[i])}
                                       for i, c in enumerate(CLASSES)}
            cm = np.zeros((3, 4), int)
            for yt, yp in zip(y, pr):
                cm[yt, 3 if yp == -1 else yp] += 1
            cms.setdefault(m, {})[g] = cm.tolist()
    res["per_class"] = pc
    res["confusion_pooled"] = {"rows": CLASSES, "cols": CLASSES + ["abstain"], "matrices": cms}

    # ---- per corruption family on the vibration channel (where OB2 was weak)
    fam = defaultdict(dict)
    for m in models:
        for f in ("noise", "gain", "spikes", "clipping", "stuck", "dropout", "intermittent"):
            s = (D["model"] == m) & np.array([str(x).startswith(f"vib:{f}:") for x in D["tag"]])
            if s.any():
                fam[m][f] = round(float(metrics(D["y"][s], D["pred"][s], D["abstain"][s])["macro_f1"]), 4)
    res["vib_family_macro_f1_pooled"] = fam

    (out_dir / "ob_final_results.json").write_text(json.dumps(res, indent=2, default=float))
    _figures(cms, out_dir)
    _print(res, models)


def _figures(cms, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for g in ("clean", "withheld"):
        ms = [m for m in ("vib_only", "early_fusion", "late_average", "gated_both", "gated_v2") if m in cms]
        fig, axes = plt.subplots(1, len(ms), figsize=(3.3 * len(ms), 3.2))
        for ax, m in zip(axes, ms):
            cm = np.array(cms[m][g], float)
            norm = cm / cm.sum(1, keepdims=True)
            ax.imshow(norm, vmin=0, vmax=1, cmap="Blues")
            for i in range(3):
                for j in range(4):
                    ax.text(j, i, f"{norm[i, j]:.2f}\n({int(cm[i, j])})", ha="center", va="center", fontsize=7,
                            color="white" if norm[i, j] > 0.6 else "black")
            ax.set_xticks(range(4), ["H", "OR", "IR", "abst."], fontsize=8)
            ax.set_yticks(range(3), ["H", "OR", "IR"], fontsize=8)
            ax.set_title(m, fontsize=9)
        fig.suptitle(f"P1 pooled confusion ({g}), row-normalised; starter subset, held-out bearings, reps >= 2",
                     fontsize=9)
        fig.tight_layout()
        fig.savefig(out_dir / f"confusion_{g}.png", dpi=150)
        plt.close(fig)


def _print(res, models):
    print(f"runs={res['runs']}  (mean +- sd over bearing-disjoint runs; abstain counts as wrong)")
    for g in ("clean", "seen", "withheld"):
        print(f"\n[{g}] {'model':14s} {'macroF1':>13s} {'covered F1':>11s} {'coverage':>9s} {'FAR':>7s} {'miss':>7s} {'undiag':>7s}")
        for m in models:
            d = res["run_level"][m][g]
            f = lambda k: d[k]["mean"]
            print(f"      {m:14s} {f('macro_f1'):.3f}±{d['macro_f1']['sd']:.3f} {f('macro_f1_covered'):11.3f} "
                  f"{f('coverage'):9.3f} {f('false_alarm_rate'):7.3f} {f('missed_fault_rate'):7.3f} "
                  f"{f('undiagnosed_fault_rate'):7.3f}")
    print("\nTests (gated_v2 vs model): unit group vs mean_diff p p_holm")
    for x in res["tests"]:
        print(f"  {x['unit']:7s} {x['group']:9s} {x['vs']:14s} {x['mean_diff']:+.4f} {x['p']:.4f} {x['p_holm']:.4f}")
    print("\nvibration-corruption families, pooled macro-F1:")
    for m, d in res["vib_family_macro_f1_pooled"].items():
        print(f"  {m:14s} " + " ".join(f"{k}={v:.3f}" for k, v in d.items()))


if __name__ == "__main__":
    main()
