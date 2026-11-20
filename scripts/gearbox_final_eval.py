"""Gearbox OB1 / OB2 final evaluation on the data that is actually available.

Part A - OB1, all four leave-one-profile-out folds: read from the stored pilot evaluation
  (results/test_runs/mcc5_interim.json, written by scripts/evaluate_gearbox.py on the 12 pilot
  recordings). Nothing is re-scored; per-fold spread, per-class recall, false alarms and missed
  faults are derived from the stored confusion matrices.
Part B - re-evaluation FROM RAW SIGNALS of the one fold whose test recordings are available
  (profile 1000 rpm / 10 Nm, 3 recordings, 177 windows) with the frozen exported model, which
  was fitted on the 9 recordings of the other three profiles (scripts/export_gearbox_demo.py).
  B1 reproduces that fold of the stored evaluation; B2 (OB2) sweeps sensor-fault severity on
  each accelerometer and reports detection, fusion accuracy, coverage and abstention.

Nothing is fitted or tuned here.

  python scripts/gearbox_final_eval.py --data data/mcc5_demo --out results/final/gearbox
"""
import argparse
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pufusion import corruption as C  # noqa: E402
from pufusion import gearbox as G  # noqa: E402
from evaluate_gearbox import evaluate_record, summarize  # noqa: E402

METHODS = ["motor", "gearbox", "early", "late_average", "gated"]
ABSTAIN = "abstain"
H = G.CLASSES.index("healthy")


def cm_stats(cm):
    """cm rows = true (pitting, wear, healthy), cols = predicted (+ abstain)."""
    cm = np.asarray(cm, float)
    n = cm.sum()
    fault = [i for i in range(3) if i != H]
    return {
        "accuracy": float(np.trace(cm[:, :3]) / n),
        "recall": {c: float(cm[i, i] / max(cm[i].sum(), 1)) for i, c in enumerate(G.CLASSES)},
        "false_alarm_rate": float(cm[H, fault].sum() / max(cm[H].sum(), 1)),
        "missed_fault_rate": float(cm[fault, H].sum() / max(cm[fault].sum(), 1)),
        "abstain_rate": float(cm[:, 3].sum() / n),
    }


def part_a(pilot):
    d = json.loads(Path(pilot).read_text())
    out = {"source": str(pilot), "protocol": d["protocol"], "folds": list(d["folds"]),
           "recordings": sum(len(f["test"]) for f in d["folds"].values()), "scenarios": {}}
    for sc, by_m in d["pooled"].items():
        out["scenarios"][sc] = {}
        for m in METHODS:
            w, r = by_m[m]["window"], by_m[m]["recording"]
            folds = [f["metrics"][sc][m]["window"]["macro_f1"] for f in d["folds"].values()]
            out["scenarios"][sc][m] = {
                "windows": w["count"], "window_macro_f1": w["macro_f1"], "coverage": w["coverage"],
                "fold_min": min(folds), "fold_max": max(folds), "per_fold": dict(zip(d["folds"], folds)),
                "recording_macro_f1": r["macro_f1"], **cm_stats(w["confusion"])}
    status = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for f in d["folds"].values():
        for counts in f["sensor_status_counts"].values():
            for sc, by_s in counts.items():
                for s, c in by_s.items():
                    for k, v in c.items():
                        status[sc][s][k] += v
    out["flag_rate"] = {sc: {s: {"flagged": (c["degraded"] + c["failed"]) / sum(c.values()),
                                 "failed": c["failed"] / sum(c.values())} for s, c in by_s.items()}
                        for sc, by_s in status.items()}
    return out


def inject(sig, family, sev, rng):
    sig = np.asarray(sig, np.float64)
    if family == "spikes":
        return C.spikes(sig, rng, sev, fs=G.FS)
    return C.FAMILIES[family][0](sig, rng, sev)


def corrupt(window, family, sev, target, rng):
    out = window.copy()
    for s in G.SENSORS if target == "both" else (target,):
        axes = out[G.SENSORS.index(s)]
        for i, sig in enumerate(axes):
            axes[i] = inject(sig, family, sev, rng)
    return out


def grid():
    g = [(f, s, t) for t in G.SENSORS for f, (_, sevs) in C.FAMILIES.items() for s in sevs]
    return g + [("dropout", None, "both"), ("stuck", None, "both"), ("noise", 0, "both"), ("noise", 10, "both")]


def part_b(data, bundle_path, pilot):
    bundle = pickle.load(open(bundle_path, "rb"))
    model = bundle["model"]
    recs = [r for r in G.discover(data) if r.id in bundle["test"]]
    if len(recs) != 3:
        raise SystemExit(f"need the 3 held-out recordings of {bundle['condition']} in {data}")
    wins = {r.id: list(G.windows(r)) for r in recs}
    clean = {r.id: tuple(np.stack(z) for z in zip(*[G.features(w) for w in wins[r.id]])) for r in recs}
    # ---- B1: reproduce the stored fold
    fold = defaultdict(list)
    for r in recs:
        _, rows, _, _ = evaluate_record((model, r, clean[r.id], bundle["seeds"][r.id]))
        for k, v in rows.items():
            fold[k].extend(v)
    new = summarize(fold)
    old = json.loads(Path(pilot).read_text())["folds"][bundle["condition"]]["metrics"]
    cells, mism, dmax = 0, 0, 0.0
    for sc in old:
        for m in old[sc]:
            for lvl in old[sc][m]:
                cells += 1
                dmax = max(dmax, abs(old[sc][m][lvl]["macro_f1"] - new[sc][m][lvl]["macro_f1"]))
                mism += old[sc][m][lvl]["confusion"] != new[sc][m][lvl]["confusion"]
    repro = {"cells_compared": cells, "confusion_mismatches": int(mism), "max_abs_macro_f1_diff": dmax}

    # ---- B2: severity sweep
    truth = np.concatenate([[r.label] * len(wins[r.id]) for r in recs])
    res = {}
    for fam, sev, target in [(None, None, None)] + grid():
        xs, qs = [], []
        for r in recs:
            if fam is None:
                x, q = clean[r.id]
            else:
                rng = np.random.default_rng(bundle["seeds"][r.id])
                x, q = (np.stack(z) for z in zip(*[G.features(corrupt(w, fam, sev, target, rng)) for w in wins[r.id]]))
            xs.append(x); qs.append(q)
        x, q = np.concatenate(xs), np.concatenate(qs)
        outcomes, rel, weights = model.predict(x, q)
        key = "clean" if fam is None else f"{fam}:{sev}@{target}"
        row = {"windows": len(x),
               "flagged": {s: float(np.mean([r_[s].status != "ok" for r_ in rel])) for s in G.SENSORS},
               "failed": {s: float(np.mean([r_[s].status == "failed" for r_ in rel])) for s in G.SENSORS},
               "mean_weight": dict(zip(G.SENSORS, map(float, weights.mean(0)))), "methods": {}}
        for m in METHODS:
            p = outcomes[m]
            valid = np.isfinite(p).all(1)
            pred = np.full(len(p), ABSTAIN, dtype="U16")
            pred[valid] = model.classes[p[valid].argmax(1)]
            healthy, fault = truth == "healthy", truth != "healthy"
            row["methods"][m] = {
                "macro_f1": float(f1_score(truth, pred, labels=G.CLASSES, average="macro", zero_division=0)),
                "accuracy": float((pred == truth).mean()), "coverage": float(valid.mean()),
                "false_alarm_rate": float(((pred != "healthy") & (pred != ABSTAIN) & healthy).sum() / healthy.sum()),
                "missed_fault_rate": float(((pred == "healthy") & fault).sum() / fault.sum()),
                "fault_class_issued": float(((pred != "healthy") & (pred != ABSTAIN)).mean())}
        res[key] = row
        print(f"{key:28s} flagged m/g {row['flagged']['motor']:.2f}/{row['flagged']['gearbox']:.2f}  "
              + " ".join(f"{m}={row['methods'][m]['macro_f1']:.3f}" for m in METHODS)
              + f"  cov={row['methods']['gated']['coverage']:.2f}", flush=True)
    return {"condition": bundle["condition"], "train_recordings": bundle["train"], "test_recordings": bundle["test"],
            "reproduction_of_stored_fold": repro, "severity_sweep": res}


def tables(a, b):
    L = ["# Gearbox final evaluation tables", "",
         f"## A. Stored pilot, {len(a['folds'])} leave-one-profile-out folds, {a['recordings']} recordings (window macro-F1; fold min-max)", "",
         "| Scenario | " + " | ".join(METHODS) + " | gated coverage |", "|---|" + "---|" * (len(METHODS) + 1)]
    for sc, by_m in a["scenarios"].items():
        L.append(f"| {sc} | " + " | ".join(f"{by_m[m]['window_macro_f1']:.3f} ({by_m[m]['fold_min']:.2f}-{by_m[m]['fold_max']:.2f})"
                                          for m in METHODS) + f" | {by_m['gated']['coverage']:.2f} |")
    c = a["scenarios"]["clean"]
    L += ["", "Clean, pooled windows:", "", "| Method | Accuracy | Recall pitting / wear / healthy | False alarms | Missed faults | Recording macro-F1 |",
          "|---|---|---|---|---|---|"]
    for m in METHODS:
        r = c[m]["recall"]
        L.append(f"| {m} | {c[m]['accuracy']:.3f} | {r['gear_pitting']:.2f} / {r['gear_wear']:.2f} / {r['healthy']:.2f} | "
                 f"{c[m]['false_alarm_rate']:.3f} | {c[m]['missed_fault_rate']:.3f} | {c[m]['recording_macro_f1']:.3f} |")
    L += ["", "Detector flag rate on the corrupted sensor (stored pilot, all folds):", "", "| Scenario | motor flagged | gearbox flagged |", "|---|---|---|"]
    for sc, fr in a["flag_rate"].items():
        L.append(f"| {sc} | {fr['motor']['flagged']:.2f} | {fr['gearbox']['flagged']:.2f} |")
    rp = b["reproduction_of_stored_fold"]
    L += ["", f"## B. Held-out profile {b['condition']} from raw signals (frozen model, 3 recordings)", "",
          f"Reproduction of the stored fold: {rp['cells_compared']} metric cells, {rp['confusion_mismatches']} confusion-matrix "
          f"mismatches, max |macro-F1 difference| {rp['max_abs_macro_f1_diff']:.2g}.", "",
          "| Scenario | flagged motor / gearbox | " + " | ".join(METHODS) + " | gated coverage | gated false alarms |",
          "|---|---|" + "---|" * (len(METHODS) + 2)]
    for sc, r in b["severity_sweep"].items():
        L.append(f"| {sc} | {r['flagged']['motor']:.2f} / {r['flagged']['gearbox']:.2f} | "
                 + " | ".join(f"{r['methods'][m]['macro_f1']:.3f}" for m in METHODS)
                 + f" | {r['methods']['gated']['coverage']:.2f} | {r['methods']['gated']['false_alarm_rate']:.2f} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", default=str(ROOT / "results/test_runs/mcc5_interim.json"))
    ap.add_argument("--data", default=str(ROOT / "data/mcc5_demo"))
    ap.add_argument("--bundle", default=str(ROOT / "models/gearbox_demo_1000rpm_10Nm.pkl"))
    ap.add_argument("--out", default=str(ROOT / "results/final/gearbox"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    A = part_a(a.pilot)
    B = part_b(a.data, a.bundle, a.pilot)
    (out / "ob1_pilot_summary.json").write_text(json.dumps(A, indent=2))
    (out / "ob2_heldout_profile.json").write_text(json.dumps(B, indent=2))
    (out / "tables.md").write_text(tables(A, B))
    print("wrote", out)


if __name__ == "__main__":
    main()
