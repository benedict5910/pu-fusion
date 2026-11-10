"""Evaluate a real MCC5-THU pilot with whole-profile holdout and paired replay faults."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.gearbox import CLASSES, SENSORS, condition_split, discover, extract, fit_records, replay
from pufusion.sensor_faults import SCENARIOS

ABSTAIN = "abstain"


def scores(rows):
    truth, pred = zip(*rows)
    accepted = [i for i, label in enumerate(pred) if label != ABSTAIN]
    return {
        "count": len(rows),
        "coverage": len(accepted) / len(rows),
        "macro_f1": f1_score(truth, pred, labels=CLASSES, average="macro", zero_division=0),
        "confusion": confusion_matrix(truth, pred, labels=[*CLASSES, ABSTAIN])[:len(CLASSES)].tolist(),
    }


def evaluate_record(task):
    model, record, clean, seed = task
    rows = defaultdict(list)
    traces = {}
    quality = {}
    scenarios = [("clean", None), *[(f, s) for f in SCENARIOS for s in SENSORS], ("dropout", "both")]
    for family, target in scenarios:
        x, q = clean if target is None else extract(record, family, target, seed=seed)
        outcomes, rel, _ = model.predict(x, q)
        scenario = family if target is None else f"{family}@{target}"
        quality[scenario] = {
            sensor: {status: sum(row[sensor].status == status for row in rel)
                     for status in ("ok", "degraded", "failed")}
            for sensor in SENSORS
        }
        for method, probs in outcomes.items():
            valid = np.isfinite(probs).all(axis=1)
            labels = np.full(len(probs), ABSTAIN, dtype="U16")
            labels[valid] = model.classes[probs[valid].argmax(axis=1)]
            key = (scenario, method)
            rows[key].extend((record.label, label) for label in labels)
            # A majority of windows must have a diagnosis before assigning a recording label.
            label = model.classes[probs[valid].mean(axis=0).argmax()] if valid.sum() > len(valid) / 2 else ABSTAIN
            rows[key + ("recording",)].append((record.label, label))
        if scenario in ("clean", "dropout@motor", "dropout@both"):
            trace = list(replay(model, x, q))
            traces[scenario] = {
                "states": {state: sum(r["state"] == state for r in trace) for state in sorted({r["state"] for r in trace})},
                "first_state_windows": {state: next(r["window"] for r in trace if r["state"] == state)
                                        for state in sorted({r["state"] for r in trace})},
                "first_window": trace[0], "last_window": trace[-1],
            }
    return record.id, dict(rows), traces, quality


def summarize(rows):
    result = {}
    for key, values in sorted(rows.items()):
        scenario, method, *level = key
        result.setdefault(scenario, {}).setdefault(method, {})[level[0] if level else "window"] = scores(values)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    recordings = discover(args.data)
    conditions = sorted({r.condition for r in recordings})
    if len(conditions) < 2:
        parser.error("At least two complete operating profiles are required")
    folds = [(condition, *condition_split(recordings, condition)) for condition in conditions]
    report = {
        "source": "MCC5-THU v2, DOI 10.17632/p92gj2732w.2",
        "protocol": "leave one whole operating profile out, clean-only training, one-second nonoverlapping windows",
        "classes": CLASSES, "confusion_columns": [*CLASSES, ABSTAIN], "folds": {},
    }
    pooled = defaultdict(list)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        clean = dict(zip((r.id for r in recordings), pool.map(extract, recordings)))
        for condition, train, test in folds:
            print(f"{condition}: {len(train)} train / {len(test)} test recordings", flush=True)
            model = fit_records(train, clean)
            jobs = [(model, r, clean[r.id], 42 + recordings.index(r)) for r in test]
            fold = defaultdict(list)
            traces, quality = {}, {}
            for record_id, rows, trace, counts in pool.map(evaluate_record, jobs):
                quality[record_id] = counts
                traces[record_id] = trace
                for key, values in rows.items():
                    fold[key].extend(values)
                    pooled[key].extend(values)
            report["folds"][condition] = {
                "train": [r.id for r in train], "test": [r.id for r in test],
                "metrics": summarize(fold), "replay": traces, "sensor_status_counts": quality,
            }
    report["pooled"] = summarize(pooled)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
