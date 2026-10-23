"""Read the frozen experiment outputs for the dashboard's Research Lab.

Pure Python (no Streamlit): every number shown in the Research Lab comes from these
files, unchanged:
  results/starter/SUMMARY.txt       mean +/- sd macro-F1, ECE, FAR per model; Wilcoxon + Holm
  results/starter/p1.csv, p3.csv    per-run rows incl. confusion-matrix counts
  results/starter/quality.json      OB2 detection / false-flag rates
  results/starter/audit/far_audit.json  false-alarm audit (per held-out healthy bearing)
Nothing here re-trains, re-scores or re-thresholds anything.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

CLASSES = ["healthy", "outer_race", "inner_race"]
MODEL_LABEL = {
    "vib_only": "Vibration only", "cur_only": "Current only", "early_fusion": "Early fusion",
    "late_average": "Late fusion (average)", "late_stacked": "Late fusion (stacked)",
    "gated_both": "Reliability-gated (proposed)", "gated_quality": "Gate: quality only",
    "gated_confidence": "Gate: confidence only", "gated_both_nomask": "Gated, no hard mask",
}
SCENARIO_LABEL = {"clean": "Clean signals", "seen": "Seen sensor faults", "heldout": "Withheld sensor faults"}

_ROW = re.compile(r"^(\w+)\s+([\d.]+)±([\d.]+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)")
_PM = re.compile(r"([\d.]+)±([\d.]+)")
_TEST = re.compile(r"^\s*(clean|seen|heldout)\s+vs\s+(\w+)\s+Δ=([+-][\d.]+)\s+p=([\d.]+)\s+p_holm=([\d.]+)")


def _pm(tok):
    m = _PM.fullmatch(tok)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def parse_summary(path) -> dict:
    """SUMMARY.txt -> {protocol: {"runs": int, "models": {model: {...}}, "tests": [...]}}."""
    out, cur = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("##### "):
            cur = out.setdefault(line[6:].strip(), {"runs": None, "models": {}, "tests": []})
            continue
        if cur is None:
            continue
        if line.startswith("runs="):
            cur["runs"] = int(line.split()[0].split("=")[1])
            continue
        m = _ROW.match(line)
        if m:
            toks = line.split()
            clean, seen, held, worst = (_pm(t) for t in toks[1:5])
            cur["models"][toks[0]] = {"clean": clean, "seen": seen, "heldout": held, "worst": worst,
                                      "ece": float(toks[5]), "far": float(toks[6]), "miss": float(toks[7])}
            continue
        if line.split() and line.split()[0] in MODEL_LABEL and "-" in line.split()[2:]:
            toks = line.split()                                  # leaky table: no corrupted scenarios
            clean = _pm(toks[1])
            cur["models"][toks[0]] = {"clean": clean, "seen": (None, None), "heldout": (None, None),
                                      "worst": _pm(toks[4]), "ece": float(toks[5]), "far": float(toks[6]),
                                      "miss": float(toks[7])}
            continue
        t = _TEST.match(line)
        if t:
            cur["tests"].append({"scenario": t.group(1), "baseline": t.group(2), "delta": float(t.group(3)),
                                 "p": float(t.group(4)), "p_holm": float(t.group(5))})
    return out


def summed_cm(csv_path, model: str, tag: str = "none:clean:None"):
    """Confusion matrix summed over runs, exactly as scripts/make_figures.py:summed_cm."""
    cm = [0.0] * 9
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["model"] == model and r["corruption"] == tag and r.get("cm"):
                for i, v in enumerate(r["cm"].split()):
                    cm[i] += float(v)
    return [cm[0:3], cm[3:6], cm[6:9]]


def cm_long(cm) -> list[dict]:
    """Row-normalised long format for a heatmap (true class x predicted class)."""
    rows = []
    for i, t in enumerate(CLASSES):
        n = sum(cm[i]) or 1.0
        for j, p in enumerate(CLASSES):
            rows.append({"true": t, "predicted": p, "share": cm[i][j] / n, "count": int(cm[i][j])})
    return rows


def quality_table(path) -> list[dict]:
    """quality.json -> rows {sensor, family, severity, detect, cross_flag} (+ clean false-flag rows)."""
    q = json.loads(Path(path).read_text(encoding="utf-8"))["metrics"]
    rows = []
    for key, m in q.items():
        if key == "clean":
            for s in ("vib", "cur"):
                rows.append({"sensor": s, "family": "clean", "severity": "-", "detect": None,
                             "false_flag": m[f"{s}_false_flag"]["mean"]})
            continue
        fam, sev = (key.split(":") + [""])[:2]
        if fam == "both":
            continue
        for s in ("vib", "cur"):
            if f"{s}_detect" in m:
                rows.append({"sensor": s, "family": fam, "severity": sev, "detect": m[f"{s}_detect"]["mean"],
                             "cross_flag": m.get(f"{s}_cross_flag", {}).get("mean")})
    return rows


def far_audit(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def headline(results_dir) -> dict:
    """The few numbers quoted on the Overview, read from the frozen summary."""
    s = parse_summary(Path(results_dir) / "SUMMARY.txt")["p1"]
    m = s["models"]
    q = json.loads((Path(results_dir) / "quality.json").read_text(encoding="utf-8"))["metrics"]
    sig = [t for t in s["tests"] if t["p_holm"] < 0.05]
    return {
        "runs": s["runs"],
        "gated_clean": m["gated_both"]["clean"][0], "vib_clean": m["vib_only"]["clean"][0],
        "gated_heldout": m["gated_both"]["heldout"][0], "vib_heldout": m["vib_only"]["heldout"][0],
        "early_heldout": m["early_fusion"]["heldout"][0], "avg_heldout": m["late_average"]["heldout"][0],
        "gated_far": m["gated_both"]["far"],
        "vib_false_flag": q["clean"]["vib_false_flag"]["mean"], "cur_false_flag": q["clean"]["cur_false_flag"]["mean"],
        "n_significant_holm": len(sig),
    }
