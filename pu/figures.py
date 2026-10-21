"""Figures + summary tables from results produced by pu.experiments.

Usage: python -m pu.figures <results_dir> [--label "REAL PADERBORN"|"SYNTHETIC TEST"]
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from .experiments import paired_tests
from .models import MODELS, ABLATIONS

BLUE = "#2a78d6"
GRAY = "#a9a8a3"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
SEQ = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5",
                                                "#1c5cab", "#0d366b"])
NICE = {"vib_only": "Vibration only", "cur_only": "Current only", "early": "Early fusion",
        "average": "Average fusion", "stacked": "Stacked fusion", "gated": "Gated (proposed)",
        "gated_quality_only": "Gate: quality only", "gated_conf_only": "Gate: confidence only",
        "gated_no_mask": "Gate: no mask"}
CLASSES = ["Healthy", "Outer race", "Inner race"]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": "white", "axes.facecolor": "white"})


def _stamp(fig, label):
    fig.text(0.995, 0.005, label, ha="right", va="bottom", fontsize=7, color=INK2)


def fig_split_bars(R, protocol, out, label):
    d = R[(R.protocol == protocol) & R.model.isin(MODELS)]
    per = d.groupby(["repeat", "fold", "split", "model"])["macro_f1"].mean().reset_index()
    g = per.groupby(["split", "model"])["macro_f1"].agg(["mean", "std"]).reset_index()
    splits = [s for s in ("clean", "seen", "withheld") if s in g.split.unique()]
    fig, axes = plt.subplots(1, len(splits), figsize=(4.2 * len(splits), 3.8), sharey=True)
    axes = np.atleast_1d(axes)
    titles = {"clean": "Clean sensors", "seen": "Seen sensor faults",
              "withheld": "Withheld sensor faults"}
    for ax, s in zip(axes, splits):
        gg = g[g.split == s].set_index("model").reindex(MODELS)
        y = np.arange(len(MODELS))
        cols = [BLUE if m == "gated" else GRAY for m in MODELS]
        ax.barh(y, gg["mean"], xerr=gg["std"].fillna(0), color=cols, height=0.62,
                error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 2})
        for yi, v, m in zip(y, gg["mean"], MODELS):
            if v > 0.8:
                ax.text(v - 0.03, yi - 0.12, f"{v:.3f}", va="center", ha="right", fontsize=8.5,
                        color="white" if m == "gated" else INK)
            else:
                ax.text(v + 0.04, yi - 0.12, f"{v:.3f}", va="center", fontsize=8.5, color=INK)
        ax.set_yticks(y, [NICE[m] for m in MODELS])
        ax.invert_yaxis()
        ax.set_xlim(0, 1.08)
        ax.set_title(titles[s], fontsize=11, color=INK, loc="left")
        ax.xaxis.grid(True, color=GRID)
        ax.set_axisbelow(True)
        ax.set_xlabel("Macro-F1 (unseen bearings)")
    nfold = per.groupby(["repeat", "fold"]).ngroups
    fig.suptitle(f"{protocol}: Macro-F1 by model (mean ± sd over {nfold} train/test splits)",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout()
    _stamp(fig, label)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def fig_family_heatmap(R, protocol, out, label):
    d = R[(R.protocol == protocol) & (R.split != "clean") & R.model.isin(MODELS)]
    t = d.groupby(["corrupted", "family", "model"])["macro_f1"].mean().unstack("model")[MODELS]
    t.index = [f"{fam} on {'vibration' if s == 'vib' else 'current'}" for s, fam in t.index]
    fig, ax = plt.subplots(figsize=(8.6, 0.42 * len(t) + 1.4))
    im = ax.imshow(t.to_numpy(), cmap=SEQ, vmin=0, vmax=1, aspect="auto")
    for i in range(t.shape[0]):
        for j in range(t.shape[1]):
            v = t.iat[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if v > 0.6 else INK)
    ax.set_xticks(range(len(MODELS)), [NICE[m] for m in MODELS], rotation=20, ha="right")
    ax.set_yticks(range(len(t)), t.index)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03)
    cb.set_label("Macro-F1")
    ax.set_title(f"{protocol}: Macro-F1 per sensor-fault family (withheld: clipping, spikes, stuck)",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    _stamp(fig, label)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return t


def fig_confusion(cms, keys, titles, out, label, suptitle):
    fig, axes = plt.subplots(1, len(keys), figsize=(3.6 * len(keys), 3.6))
    axes = np.atleast_1d(axes)
    for ax, k, ti in zip(axes, keys, titles):
        cm = np.array(cms[k], dtype=float)
        rn = cm / cm.sum(1, keepdims=True).clip(1)
        ax.imshow(rn, cmap=SEQ, vmin=0, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{rn[i, j]:.2f}\n({int(cm[i, j])})", ha="center", va="center",
                        fontsize=8, color="white" if rn[i, j] > 0.6 else INK)
        ax.set_xticks(range(3), CLASSES, rotation=20)
        ax.set_yticks(range(3), CLASSES)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(ti, fontsize=10, color=INK)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.suptitle(suptitle, x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    _stamp(fig, label)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def fig_leakage(R, out, label):
    rows = []
    for p, name in [("LEAK_random_split", "Random window split\n(same bearings in train & test)"),
                    ("P1", "Bearing-disjoint split\n(unseen bearings)")]:
        d = R[(R.protocol == p) & (R.split == "clean") & R.model.isin(["vib_only", "early", "gated"])]
        if not d.empty:
            for m, v in d.groupby("model")["macro_f1"].mean().items():
                rows.append((name, m, v))
    if not rows:
        return
    t = pd.DataFrame(rows, columns=["split", "model", "f1"])
    fig, ax = plt.subplots(figsize=(7, 3.4))
    models = ["vib_only", "early", "gated"]
    x = np.arange(t.split.nunique())
    w = 0.26
    shades = {"vib_only": "#c9c8c3", "early": GRAY, "gated": BLUE}
    for i, m in enumerate(models):
        vals = t[t.model == m].set_index("split").reindex(t.split.unique())["f1"]
        b = ax.bar(x + (i - 1) * w, vals, w - 0.03, color=shades[m], label=NICE[m])
        for xi, v in zip(x + (i - 1) * w, vals):
            ax.text(xi, v + 0.015, f"{v:.2f}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x, t.split.unique())
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Macro-F1 (clean)")
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.13), fontsize=8.5)
    ax.set_title("Leakage check: random splits overstate accuracy", loc="left", fontsize=11,
                 color=INK, pad=24)
    fig.tight_layout()
    _stamp(fig, label)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def quality_table(Q, protocol="P1"):
    d = Q[Q.protocol == protocol]
    rows = []
    for (variant, sensor, fam), g in d.groupby(["variant", "corrupted", "family"]):
        if sensor == "none":
            rows.append({"variant": "clean", "sensor": "-", "family": "clean",
                         "detect_on_corrupted": np.nan,
                         "false_flag_vib": g.flag_vib.mean(), "false_flag_cur": g.flag_cur.mean()})
        else:
            det = g.flag_vib.mean() if sensor == "vib" else g.flag_cur.mean()
            wrong = g.flag_cur.mean() if sensor == "vib" else g.flag_vib.mean()
            rows.append({"variant": variant, "sensor": sensor, "family": fam,
                         "detect_on_corrupted": det, "wrong_flag_other_sensor": wrong,
                         "mean_gate_weight_vib": g.mean_w_vib.mean()})
    return pd.DataFrame(rows)


def fig_quality(T, out, label):
    t = T[T.variant != "clean"].copy()
    t["name"] = t.variant + " (" + t.sensor.map({"vib": "vib", "cur": "cur"}) + ")"
    t = t.sort_values(["sensor", "family", "variant"])
    fig, ax = plt.subplots(figsize=(8, 0.26 * len(t) + 1.2))
    y = np.arange(len(t))
    ax.barh(y, t.detect_on_corrupted, color=BLUE, height=0.6, label="Flagged on degraded sensor")
    ax.scatter(t.wrong_flag_other_sensor, y, color=INK, s=14, zorder=3,
               label="Wrong flag on healthy sensor")
    ax.set_yticks(y, t.name, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.05)
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_xlabel("Fraction of held-out windows")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    c = T[T.variant == "clean"]
    if len(c):
        ax.set_title(f"OB2 label-free quality assessor (clean false-flag: vib "
                     f"{c.false_flag_vib.iat[0]:.3f}, cur {c.false_flag_cur.iat[0]:.3f})",
                     loc="left", fontsize=10.5, color=INK)
    fig.tight_layout()
    _stamp(fig, label)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def main(results_dir, label):
    res = Path(results_dir)
    fdir = res / "figures"
    fdir.mkdir(exist_ok=True)
    R = pd.read_csv(res / "metrics_all.csv")
    Q = pd.read_csv(res / "quality_all.csv")
    cms = json.loads((res / "confusion_matrices.json").read_text())
    md = [f"# Results summary ({label})\n"]
    man = json.loads((res / "manifest.json").read_text())
    md.append(f"Data: {man['n_files']} files, {len(man['bearings'])} bearings, "
              f"{man['windows_clean']} clean 0.5 s windows; run {man['started']} - {man['finished']}.\n")
    for p in ("P1", "P2", "P3"):
        if p not in set(R.protocol):
            continue
        fig_split_bars(R, p, fdir / f"{p}_macro_f1_by_split.png", label)
        fig_family_heatmap(R, p, fdir / f"{p}_family_heatmap.png", label)
        d = R[R.protocol == p]
        tab = (d.groupby(["split", "model"])[["macro_f1", "ece", "nll", "brier", "false_alarm",
                                               "miss"]].mean().round(3))
        md.append(f"## {p}\n\n" + tab.to_markdown() + "\n")
    if "P1" in set(R.protocol):
        st = paired_tests(R, "P1")
        st.to_csv(res / "stats_P1.csv", index=False)
        md.append("## P1 paired Wilcoxon (gated vs baseline, Holm-corrected)\n\n"
                  + st.round(4).to_markdown(index=False) + "\n")
        fig_confusion(cms, ["P1|vib_only|clean|none", "P1|early|clean|none", "P1|gated|clean|none"],
                      ["Vibration only", "Early fusion", "Gated (proposed)"],
                      fdir / "P1_confusion_clean.png", label,
                      "P1 confusion matrices, clean sensors (row-normalised; counts summed over splits)")
        k = [f"P1|{m}|dropout|vib" for m in ("early", "average", "gated")]
        if all(x in cms for x in k):
            fig_confusion(cms, k, ["Early fusion", "Average fusion", "Gated (proposed)"],
                          fdir / "P1_confusion_vib_dropout.png", label,
                          "P1 confusion matrices, vibration sensor dropped out")
        T = quality_table(Q, "P1")
        T.round(4).to_csv(res / "ob2_quality_P1.csv", index=False)
        fig_quality(T, fdir / "OB2_quality_detection.png", label)
        md.append("## OB2 quality assessor (P1 held-out bearings)\n\n" + T.round(3).to_markdown(index=False) + "\n")
        ab = (R[(R.protocol == "P1") & R.model.isin(["gated"] + ABLATIONS)]
              .groupby(["split", "model"])["macro_f1"].mean().unstack().round(3))
        md.append("## Gate ablations (P1)\n\n" + ab.to_markdown() + "\n")
    fig_leakage(R, fdir / "leakage_random_vs_bearing_split.png", label)
    if "LEAK_random_split" in set(R.protocol):
        lk = R[(R.protocol == "LEAK_random_split")].groupby("model")["macro_f1"].mean().round(3)
        md.append("## Leakage demonstration (random window split, clean)\n\n" + lk.to_markdown() + "\n")
    (res / "RESULTS_SUMMARY.md").write_text("\n".join(md))
    print("\n".join(md)[:3000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--label", default="SYNTHETIC TEST DATA - NOT A RESULT")
    a = ap.parse_args()
    main(a.results_dir, a.label)
