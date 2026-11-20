"""Merge eval_quality_v2.py shards (run in parallel over folds) into one result file.

  python scripts/merge_quality_v2.py results/ob2_v2/shard_a.json results/ob2_v2/shard_b.json \
      --out results/ob2_v2/quality_v2.json
Aggregation uses nanmean/nanstd: folds without a healthy (or damaged) test bearing have
no value for the healthy/damaged split of the clean false-flag rate.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shards", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    shards = [json.loads(Path(p).read_text()) for p in a.shards]
    raw, selection = {}, []
    for s in shards:
        selection += s["selection"]
        for k, v in s["raw"].items():
            raw.setdefault(k, []).extend(v)
    order = {f"P1_r{r}_f{k}": 3 * r + k for r in range(5) for k in range(3)}
    selection.sort(key=lambda x: order.get(x["fold"], 99))
    metrics = {}
    for key, v in sorted(raw.items()):
        ver, cond, s, kind = key.split("|")
        v = np.array(v, float)
        metrics.setdefault(ver, {}).setdefault(cond, {})[f"{s}_{kind}"] = {
            "mean": round(float(np.nanmean(v)), 4), "sd": round(float(np.nanstd(v)), 4),
            "n_folds": int(np.isfinite(v).sum())}
    res = {k: shards[0][k] for k in ("features", "protocol", "withheld_families")}
    res.update({"folds": len(selection), "selected_counts": dict(Counter(x["selected"] for x in selection)),
                "selection": selection, "metrics": metrics, "raw": raw})
    Path(a.out).write_text(json.dumps(res, indent=2))
    m1, m2 = metrics["v1"], metrics["v2"]
    print(f"folds={len(selection)}  selected={res['selected_counts']}")
    print(f"{'condition':26s} {'v1 vib':>8s} {'v2 vib':>8s} {'v1 cur':>8s} {'v2 cur':>8s}")
    for cond in m2:
        key = "false_flag" if cond.startswith("clean") else "detect"
        g = lambda d, s: f"{d[cond][f'{s}_{key}']['mean']:.3f}" if f"{s}_{key}" in d.get(cond, {}) else "-"
        print(f"{cond:26s} {g(m1, 'vib'):>8s} {g(m2, 'vib'):>8s} {g(m1, 'cur'):>8s} {g(m2, 'cur'):>8s}")


if __name__ == "__main__":
    main()
