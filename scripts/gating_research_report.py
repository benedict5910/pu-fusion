"""OB2 gating research report: v3 rules vs vib_only, late_average, gated_both, gated_v2.

Metric definitions are those of ob_final_report.py (imported): abstain counts as wrong;
run-level = per (fold, tag) metric averaged over the tags of a group, mean +- sd over the
15 bearing-disjoint runs; bearing-level = per held-out bearing accuracy averaged over runs.
Paired Wilcoxon, Holm-corrected within each (unit, new model) over 4 baselines x 3 groups.

  python scripts/gating_research_report.py results/gating_research/predictions_v3.npz \
      results/full_2026-11-15/ob_final/predictions.npz
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ob_final_report import group, holm, metrics  # noqa: E402

BASE = ["vib_only", "late_average", "gated_both", "gated_v2"]
NEW = ["v3_soft", "v3_strength", "v3_severity"]
GROUPS = ["clean", "seen", "withheld"]
KEYS = ("fold", "tag", "bearing", "y", "pred", "abstain")


def main():
    new, base = np.load(sys.argv[1]), np.load(sys.argv[2])
    out_dir = Path(sys.argv[1]).parent
    D = {}
    for z, names in ((base, BASE), (new, NEW)):
        mod = z["model"]
        for m in names:
            s = mod == m
            D[m] = {k: z[k][s] for k in KEYS}
            if "w_vib" in z.files:
                D[m]["w_vib"] = z["w_vib"][s]
    ref = D[BASE[0]]
    for m in BASE + NEW:                               # identical evaluation rows for every model
        for k in ("fold", "tag", "bearing", "y"):
            assert (D[m][k] == ref[k]).all(), (m, k)
    models = BASE + NEW
    folds = list(dict.fromkeys(ref["fold"].tolist()))
    tags = sorted(set(ref["tag"].tolist()))
    grp = {t: group(t) for t in tags}
    cell = {(fo, t): np.where((ref["fold"] == fo) & (ref["tag"] == t))[0] for fo in folds for t in tags}

    per_run, per_tag = defaultdict(list), defaultdict(dict)
    for m in models:
        d = D[m]
        for fo in folds:
            vals = defaultdict(lambda: defaultdict(list))
            for t in tags:
                i = cell[(fo, t)]
                for k, v in metrics(d["y"][i], d["pred"][i], d["abstain"][i]).items():
                    vals[grp[t]][k].append(v)
            for g in GROUPS:
                for k, v in vals[g].items():
                    per_run[(m, g, k)].append(float(np.nanmean(v)))
        for t in tags:                                  # pooled over runs, per scenario
            i = np.concatenate([cell[(fo, t)] for fo in folds])
            r = metrics(d["y"][i], d["pred"][i], d["abstain"][i])
            per_tag[m][t] = {"macro_f1": round(float(r["macro_f1"]), 4), "abstain": round(float(1 - r["coverage"]), 4),
                             "far": round(float(r["false_alarm_rate"]), 4),
                             **({"w_vib": round(float(d["w_vib"][i].mean()), 3)} if "w_vib" in d else {})}
    summary = {m: {g: {k: {"mean": round(float(np.mean(per_run[(m, g, k)])), 4),
                           "sd": round(float(np.std(per_run[(m, g, k)])), 4)}
                       for k in ("macro_f1", "coverage", "false_alarm_rate", "missed_fault_rate")}
                   for g in GROUPS} for m in models}

    gmask = {g: np.array([grp[t] == g for t in ref["tag"]]) for g in GROUPS}
    bearings = sorted(set(ref["bearing"].tolist()))
    bacc = {m: {g: {} for g in GROUPS} for m in models}
    for m in models:
        ok = (D[m]["pred"] == D[m]["y"]) & ~D[m]["abstain"]
        for g in GROUPS:
            for b in bearings:
                sb = gmask[g] & (ref["bearing"] == b)
                bacc[m][g][b] = round(float(np.mean([ok[sb & (ref["fold"] == fo)].mean()
                                                     for fo in np.unique(ref["fold"][sb])])), 4)
    tests = []
    for n in NEW:
        for unit in ("run", "bearing"):
            block = []
            for g in GROUPS:
                for b in BASE:
                    if unit == "run":
                        d = np.array(per_run[(n, g, "macro_f1")]) - np.array(per_run[(b, g, "macro_f1")])
                    else:
                        d = np.array([bacc[n][g][x] - bacc[b][g][x] for x in bearings])
                    p = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
                    block.append({"model": n, "unit": unit, "group": g, "vs": b, "n": len(d),
                                  "mean_diff": round(float(d.mean()), 4), "wins": int((d > 0).sum()), "p": float(p)})
            for x, a in zip(block, holm(np.array([x["p"] for x in block]))):
                x["p"], x["p_holm"] = round(x["p"], 4), round(float(a), 4)
            tests += block

    meta = json.loads(Path(sys.argv[1]).with_suffix(".json").read_text())["folds"]
    chosen = {m: [f["selected"][m]["param"] for f in meta] for m in ("soft", "strength", "severity")}
    res = {"runs": len(folds), "eval_windows_per_model": int(len(ref["y"])), "selected_params_per_fold": chosen,
           "run_level": summary, "tests": tests, "per_scenario_pooled": per_tag, "bearing_level_accuracy": bacc}
    (out_dir / "gating_research_results.json").write_text(json.dumps(res, indent=2, default=float))

    P = print
    P(f"runs={len(folds)}  eval windows per model={len(ref['y'])}  (abstain counts as wrong)")
    P("selected per fold: " + "; ".join(f"{k}={v}" for k, v in chosen.items()))
    P(f"\n{'model':13s} " + " ".join(f"{g + ' F1':>14s}" for g in GROUPS) + "   coverage s/w   FAR c/s/w          miss c/s/w")
    for m in models:
        s = summary[m]
        P(f"{m:13s} " + " ".join(f"{s[g]['macro_f1']['mean']:.3f}±{s[g]['macro_f1']['sd']:.3f}".rjust(14) for g in GROUPS)
          + f"   {s['seen']['coverage']['mean']:.3f}/{s['withheld']['coverage']['mean']:.3f}"
          + "   " + "/".join(f"{s[g]['false_alarm_rate']['mean']:.3f}" for g in GROUPS)
          + "   " + "/".join(f"{s[g]['missed_fault_rate']['mean']:.3f}" for g in GROUPS))
    P("\nPaired Wilcoxon (new - baseline macro-F1 / bearing accuracy), Holm within (model, unit):")
    for x in tests:
        flag = "*" if x["p_holm"] < 0.05 else " "
        P(f"  {x['model']:12s} {x['unit']:7s} {x['group']:9s} vs {x['vs']:13s} {x['mean_diff']:+.4f} "
          f"wins {x['wins']:2d}/{x['n']:2d}  p={x['p']:.4f} p_holm={x['p_holm']:.4f}{flag}")
    P("\nPer scenario, pooled macro-F1 (mean vibration weight of v3 models in brackets):")
    P(f"{'scenario':22s} " + " ".join(f"{m[:12]:>12s}" for m in models))
    for t in tags:
        P(f"{t:22s} " + " ".join(
            (f"{per_tag[m][t]['macro_f1']:.3f}" + (f"[{per_tag[m][t]['w_vib']:.2f}]" if m in NEW else "")).rjust(12)
            for m in models))
    P("\nmax abstention in any scenario: " + ", ".join(
        f"{m}={max(per_tag[m][t]['abstain'] for t in tags):.3f}" for m in models))
    P("\nBearing-level accuracy, clean | seen | withheld:")
    for g in GROUPS:
        P(f" [{g}] {'':8s}" + " ".join(f"{b:>5s}" for b in bearings))
        for m in models:
            P(f"  {m:13s}" + " ".join(f"{bacc[m][g][b]:5.2f}" for b in bearings))


if __name__ == "__main__":
    main()
