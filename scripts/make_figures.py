"""Presentation figures from results CSVs (+ quality.json). Every figure is stamped with
the data source; SYNTHETIC inputs are stamped as pipeline checks, not results.

  python scripts/make_figures.py results/starter
Writes results/<subset>/figures/*.png
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.corruption import HELD_OUT_FAMILIES  # noqa: E402

BLUE, GRAY, LIGHT = "#2a78d6", "#a9a8a3", "#cfcec9"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
SEQ = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5",
                                                "#1c5cab", "#0d366b"])
MAIN = ["vib_only", "cur_only", "early_fusion", "late_average", "late_stacked", "gated_both"]
NICE = {"vib_only": "Vibration only", "cur_only": "Current only", "early_fusion": "Early fusion",
        "late_average": "Average fusion", "late_stacked": "Stacked fusion",
        "gated_both": "Gated (proposed)", "gated_quality": "Gate: quality only",
        "gated_confidence": "Gate: confidence only", "gated_both_nomask": "Gate: no mask"}
CLASSES = ["Healthy", "Outer race", "Inner race"]
PROPOSED = "gated_both"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": "white", "axes.facecolor": "white"})


def group(tag):
    if tag.startswith("none"):
        return "clean"
    return "heldout" if tag.split(":")[1] in HELD_OUT_FAMILIES else "seen"


def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        r["macro_f1"] = float(r["macro_f1"])
        r["run"] = (r["fold"], r["held_condition"])
        r["group"] = group(r["corruption"])
    return rows


def stamp_text(rows):
    src = {r.get("data_source", "?") for r in rows}
    if any("SYNTHETIC" in s for s in src):
        return "SYNTHETIC DATA - pipeline check only, NOT a result"
    return "Real Paderborn data (CC BY-NC 4.0) - bearing-disjoint evaluation"


def _stamp(fig, text):
    fig.text(0.995, 0.005, text, ha="right", va="bottom", fontsize=7, color=INK2)


def per_run(rows, models):
    acc = defaultdict(list)
    for r in rows:
        if r["model"] in models:
            acc[(r["model"], r["run"], r["group"])].append(r["macro_f1"])
    out = defaultdict(list)
    for (m, run, g), v in acc.items():
        out[(m, g)].append(np.mean(v))
    return out


def fig_groups(rows, title, out, stamp):
    models = [m for m in MAIN if any(r["model"] == m for r in rows)]
    pr = per_run(rows, models)
    groups = [g for g in ("clean", "seen", "heldout") if any((m, g) in pr for m in models)]
    names = {"clean": "Clean sensors", "seen": "Seen sensor faults", "heldout": "Withheld sensor faults"}
    fig, axes = plt.subplots(1, len(groups), figsize=(4.3 * len(groups), 3.9), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, g in zip(axes, groups):
        y = np.arange(len(models))
        mean = [np.mean(pr[(m, g)]) if pr[(m, g)] else np.nan for m in models]
        sd = [np.std(pr[(m, g)]) if pr[(m, g)] else 0 for m in models]
        ax.barh(y, mean, xerr=sd, height=0.62, color=[BLUE if m == PROPOSED else GRAY for m in models],
                error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 2})
        for yi, v, m in zip(y, mean, models):
            inside = v > 0.8
            ax.text(v - 0.03 if inside else v + 0.04, yi - 0.12, f"{v:.3f}", va="center",
                    ha="right" if inside else "left", fontsize=8.5,
                    color="white" if inside and m == PROPOSED else INK)
        ax.set_yticks(y, [NICE[m] for m in models])
        ax.invert_yaxis()
        ax.set_xlim(0, 1.08)
        ax.set_title(names[g], loc="left", fontsize=11, color=INK)
        ax.xaxis.grid(True, color=GRID)
        ax.set_axisbelow(True)
        ax.set_xlabel("Macro-F1 (unseen bearings)")
    n = len({r["run"] for r in rows})
    fig.suptitle(f"{title}: Macro-F1 (mean ± sd over {n} bearing-disjoint runs)", x=0.01, ha="left",
                 fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _stamp(fig, stamp)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def fig_family(rows, title, out, stamp):
    models = [m for m in MAIN if any(r["model"] == m for r in rows)]
    acc = defaultdict(list)
    for r in rows:
        if r["group"] != "clean" and r["model"] in models:
            mod, fam, _ = r["corruption"].split(":")
            acc[(f"{fam} on {mod}", r["model"])].append(r["macro_f1"])
    keys = sorted({k[0] for k in acc}, key=lambda s: (s.split(" on ")[1], s.split(" on ")[0] in HELD_OUT_FAMILIES, s))
    if not keys:
        return
    M = np.array([[np.mean(acc[(k, m)]) if acc[(k, m)] else np.nan for m in models] for k in keys])
    fig, ax = plt.subplots(figsize=(8.8, 0.42 * len(keys) + 1.6))
    im = ax.imshow(M, cmap=SEQ, vmin=0, vmax=1, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if M[i, j] > 0.6 else INK)
    ax.set_xticks(range(len(models)), [NICE[m] for m in models], rotation=20, ha="right")
    ax.set_yticks(range(len(keys)), [k + ("  (withheld)" if k.split(" on ")[0] in HELD_OUT_FAMILIES else "")
                                     for k in keys])
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.colorbar(im, ax=ax, fraction=0.03).set_label("Macro-F1")
    ax.set_title(f"{title}: Macro-F1 per sensor-fault family (mean over severities and runs)",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _stamp(fig, stamp)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def summed_cm(rows, model, tag):
    cm = np.zeros(9)
    for r in rows:
        if r["model"] == model and r["corruption"] == tag and r.get("cm"):
            cm += np.array(r["cm"].split(), float)
    return cm.reshape(3, 3)


def fig_cm(rows, models, tag, title, out, stamp):
    cms = [summed_cm(rows, m, tag) for m in models]
    if not any(c.sum() for c in cms):
        return
    fig, axes = plt.subplots(1, len(models), figsize=(3.7 * len(models), 3.7))
    for ax, m, cm in zip(np.atleast_1d(axes), models, cms):
        rn = cm / cm.sum(1, keepdims=True).clip(1)
        ax.imshow(rn, cmap=SEQ, vmin=0, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{rn[i, j]:.2f}\n({int(cm[i, j])})", ha="center", va="center", fontsize=8,
                        color="white" if rn[i, j] > 0.6 else INK)
        ax.set_xticks(range(3), CLASSES, rotation=20)
        ax.set_yticks(range(3), CLASSES)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(NICE[m], fontsize=10, color=INK)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _stamp(fig, stamp)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def fig_leak(p1, leaky, out, stamp):
    models = [m for m in ("vib_only", "early_fusion", PROPOSED) if any(r["model"] == m for r in leaky)]
    if not models:
        return
    val = lambda rows, m: np.mean([r["macro_f1"] for r in rows if r["model"] == m and r["group"] == "clean"])
    fig, ax = plt.subplots(figsize=(7, 3.5))
    labels = ["Random recording split\n(same bearings in train & test)", "Bearing-disjoint split\n(unseen bearings)"]
    x = np.arange(2)
    shade = {"vib_only": LIGHT, "early_fusion": GRAY, PROPOSED: BLUE}
    for i, m in enumerate(models):
        v = [val(leaky, m), val(p1, m)]
        ax.bar(x + (i - 1) * 0.26, v, 0.23, color=shade[m], label=NICE[m])
        for xi, vi in zip(x + (i - 1) * 0.26, v):
            ax.text(xi, vi + 0.015, f"{vi:.2f}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Macro-F1 (clean)")
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.14), fontsize=8.5)
    ax.set_title("Leakage check: random splits overstate accuracy", loc="left", fontsize=11, color=INK, pad=26)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _stamp(fig, stamp)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def fig_quality(q, out, stamp):
    met = q["metrics"]
    rows = []
    for cond, d in met.items():
        if cond == "clean" or cond.startswith("both:"):
            continue
        for s in ("vib", "cur"):
            if f"{s}_detect" in d:
                other = "cur" if s == "vib" else "vib"
                rows.append((f"{cond} on {s}", d[f"{s}_detect"]["mean"], d.get(f"{other}_cross_flag", {}).get("mean", np.nan),
                             cond.split(":")[0] in HELD_OUT_FAMILIES))
    if not rows:
        return
    rows.sort(key=lambda r: (r[0].split(" on ")[1], r[3], r[0]))
    fig, ax = plt.subplots(figsize=(8, 0.25 * len(rows) + 1.3))
    y = np.arange(len(rows))
    ax.barh(y, [r[1] for r in rows], color=BLUE, height=0.62, label="Flagged on degraded sensor")
    ax.scatter([r[2] for r in rows], y, color=INK, s=14, zorder=3, label="Wrong flag on healthy sensor")
    ax.set_yticks(y, [r[0] + (" (withheld)" if r[3] else "") for r in rows], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.05)
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_xlabel(f"Fraction of held-out windows (mean over {q.get('folds')} folds)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    c = met.get("clean", {})
    ff = lambda k: c.get(k, {}).get("mean", float("nan"))
    ax.set_title(f"OB2 label-free sensor-quality detector (clean false-flag: vib {ff('vib_false_flag'):.3f}, "
                 f"cur {ff('cur_false_flag'):.3f})", loc="left", fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _stamp(fig, stamp)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    a = ap.parse_args()
    res = Path(a.results_dir)
    fd = res / "figures"
    fd.mkdir(exist_ok=True)
    data = {n: load(res / f"{n}.csv") for n in ("p1", "p2", "p3", "leaky") if (res / f"{n}.csv").exists()}
    for n, rows in data.items():
        if n == "leaky":
            continue
        st = stamp_text(rows)
        fig_groups(rows, n.upper(), fd / f"{n}_macro_f1.png", st)
        fig_family(rows, n.upper(), fd / f"{n}_fault_family_heatmap.png", st)
        fig_cm(rows, ["vib_only", "early_fusion", PROPOSED], "none:clean:None",
               f"{n.upper()} confusion matrices, clean sensors (row-normalised; counts summed over runs)",
               fd / f"{n}_confusion_clean.png", st)
        fig_cm(rows, ["early_fusion", "late_average", PROPOSED], "vib:dropout:None",
               f"{n.upper()} confusion matrices, vibration sensor dropped out",
               fd / f"{n}_confusion_vib_dropout.png", st)
    if "p1" in data and "leaky" in data:
        fig_leak(data["p1"], data["leaky"], fd / "leakage_check.png", stamp_text(data["leaky"]))
    if (res / "quality.json").exists():
        q = json.loads((res / "quality.json").read_text())
        st = "SYNTHETIC DATA - pipeline check only, NOT a result" if "SYNTHETIC" in str(q.get("source")) \
            else "Real Paderborn data (CC BY-NC 4.0) - held-out bearings"
        fig_quality(q, fd / "ob2_quality_detector.png", st)
    print("figures:", sorted(p.name for p in fd.glob("*.png")))


if __name__ == "__main__":
    main()
