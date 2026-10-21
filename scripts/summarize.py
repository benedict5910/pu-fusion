"""Summarise a results CSV: clean / seen-corruption / held-out-corruption macro-F1,
worst case, calibration, alarm metrics, and paired Wilcoxon tests vs the proposed model.

  python scripts/summarize.py results/p1.csv --proposed gated_both
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.corruption import HELD_OUT_FAMILIES  # noqa: E402


def group(tag):
    if tag.startswith("none"):
        return "clean"
    fam = tag.split(":")[1]
    return "heldout" if fam in HELD_OUT_FAMILIES else "seen"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--proposed", default="gated_both")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.csv)))
    src = {r.get("data_source", "?") for r in rows}
    if any("SYNTHETIC" in s for s in src):
        print("=" * 72 + "\nSYNTHETIC DATA - pipeline check only, NOT an experimental result\n" + "=" * 72)

    # per (model, fold-run, group) mean macro-F1 across corruption tags
    acc = defaultdict(list)
    worst = defaultdict(lambda: 1.0)
    extra = defaultdict(list)
    for r in rows:
        run_id = (r["fold"], r["held_condition"])
        g = group(r["corruption"])
        f1 = float(r["macro_f1"])
        acc[(r["model"], run_id, g)].append(f1)
        worst[(r["model"], run_id)] = min(worst[(r["model"], run_id)], f1)
        if g == "clean":
            for k in ("ece", "false_alarm_rate", "miss_rate", "latency_s", "false_alarms_per_hour"):
                if r.get(k) not in (None, "", "nan"):
                    extra[(r["model"], k)].append(float(r[k]))
    models = sorted({k[0] for k in acc})
    runs = sorted({k[1] for k in acc})
    per = {(m, g): np.array([np.mean(acc[(m, rid, g)]) for rid in runs if (m, rid, g) in acc])
           for m in models for g in ("clean", "seen", "heldout")}
    wc = {m: np.array([worst[(m, rid)] for rid in runs]) for m in models}

    print(f"runs={len(runs)}  (mean ± sd of macro-F1 across bearing-disjoint runs)")
    hdr = f"{'model':22s} {'clean':>13s} {'seen-corr':>13s} {'heldout-corr':>13s} {'worst':>13s} {'ECE':>6s} {'FAR':>6s} {'miss':>6s} {'lat_s':>6s}"
    print(hdr); print("-" * len(hdr))
    fmt = lambda v: f"{v.mean():.3f}±{v.std():.3f}" if len(v) else "      -      "
    mean = lambda k: f"{np.nanmean(extra[k]):.3f}" if extra[k] else "  -  "
    for m in models:
        print(f"{m:22s} {fmt(per[(m,'clean')]):>13s} {fmt(per[(m,'seen')]):>13s} "
              f"{fmt(per[(m,'heldout')]):>13s} {fmt(wc[m]):>13s} {mean((m,'ece')):>6s} "
              f"{mean((m,'false_alarm_rate')):>6s} {mean((m,'miss_rate')):>6s} {mean((m,'latency_s')):>6s}")

    if a.proposed in models and len(runs) >= 6:
        print(f"\nPaired Wilcoxon, {a.proposed} vs baseline (per-run mean macro-F1; Holm-correct across baselines)")
        tests = []
        for g in ("clean", "seen", "heldout"):
            for m in models:
                if m == a.proposed or not len(per[(m, g)]):
                    continue
                d = per[(a.proposed, g)] - per[(m, g)]
                p = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
                tests.append((g, m, d.mean(), p))
        # Holm step-down correction across all comparisons printed here
        order = np.argsort([t[3] for t in tests])
        adj, run = np.empty(len(tests)), 0.0
        for rank, i in enumerate(order):
            run = max(run, (len(tests) - rank) * tests[i][3])
            adj[i] = min(1.0, run)
        for (g, m, dm, p), ph in zip(tests, adj):
            print(f"  {g:8s} vs {m:20s} Δ={dm:+.3f}  p={p:.4f}  p_holm={ph:.4f}")
    elif a.proposed in models:
        print("\n(too few runs for a paired test; use >= 6, ideally 15 = 5 repeats x 3 folds)")


if __name__ == "__main__":
    main()
