"""OB2 final tables and figures for the frozen v3_strength validation.

Scenario classes (fixed here, before computing anything):
  clean          uncorrupted windows
  mild           noise 20 / 10 dB, gain x0.5 / x2, intermittent 5 %, spikes 10 /s, clipping 0.5
                 (either sensor, plus both:noise:10)
  vib_dropout / cur_dropout / vib_stuck / cur_stuck      single dead sensor
  dual_failure   both sensors dead (4 dropout / stuck combinations; ob2_final_validation.py)
Metrics per (fold, tag), averaged over the tags of a class, mean +- sd over the 15 runs.
accuracy and macro-F1 count an abstained window as wrong.

  python scripts/ob2_final_report.py results/gating_research/final_validation
"""
import json
import warnings
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ob_final_report import metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["vib_only", "late_average", "gated_both", "gated_v2", "v3_strength"]
COLORS = dict(zip(MODELS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))   # validated (dataviz skill)
MILD = {"noise:20", "noise:10", "gain:0.5", "gain:2.0", "intermittent:0.05", "spikes:10", "clipping:0.5"}
CLASSES = ["clean", "mild", "vib_dropout", "cur_dropout", "vib_stuck", "cur_stuck", "dual_failure"]
LABEL = {"clean": "Clean", "mild": "Mild corruption", "vib_dropout": "Vibration dropout", "cur_dropout": "Current dropout",
         "vib_stuck": "Vibration stuck", "cur_stuck": "Current stuck", "dual_failure": "Both sensors dead"}
INK, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def scen(tag):
    tag = str(tag)
    if tag == "clean":
        return "clean"
    if tag.startswith("dual:"):
        return "dual_failure"
    mod, rest = tag.split(":", 1)
    if rest in ("dropout:None", "stuck:None") and mod in ("vib", "cur"):
        return f"{mod}_{rest.split(':')[0]}"
    return "mild" if rest in MILD else None


def main():
    warnings.filterwarnings("ignore", "Mean of empty slice")   # covered-F1 is undefined at zero coverage
    out = Path(sys.argv[1])
    base = np.load(ROOT / "results/full_2026-11-15/ob_final/predictions.npz")
    v3 = np.load(ROOT / "results/gating_research/predictions_v3.npz")
    dual = np.load(out / "dual_failure_predictions.npz")
    val = json.loads((out / "validation.json").read_text())
    gr = json.loads((ROOT / "results/gating_research/gating_research_results.json").read_text())
    D = {}
    for m in MODELS:
        z = v3 if m == "v3_strength" else base
        s, sd = z["model"] == m, dual["model"] == m
        D[m] = {k: np.concatenate([z[k][s], dual[k][sd]]) for k in ("fold", "tag", "y", "pred", "abstain")}
    ref = D[MODELS[0]]
    folds = list(dict.fromkeys(ref["fold"].tolist()))
    tags = [t for t in sorted(set(ref["tag"].tolist())) if scen(t)]
    cell = {(fo, t): np.where((ref["fold"] == fo) & (ref["tag"] == t))[0] for fo in folds for t in tags}
    table = {}
    for m in MODELS:
        d = D[m]
        assert (d["tag"] == ref["tag"]).all() and (d["y"] == ref["y"]).all()
        runs = defaultdict(lambda: defaultdict(list))
        for fo in folds:
            vals = defaultdict(lambda: defaultdict(list))
            for t in tags:
                i = cell[(fo, t)]
                r = metrics(d["y"][i], d["pred"][i], d["abstain"][i])
                r["accuracy"] = float(((d["pred"][i] == d["y"][i]) & ~d["abstain"][i]).mean())
                r["fault_class_issued"] = float(((d["pred"][i] != 0) & ~d["abstain"][i]).mean())
                for k, v in r.items():
                    vals[scen(t)][k].append(v)
            for c in CLASSES:
                for k, v in vals[c].items():
                    runs[c][k].append(float(np.nanmean(v)))
        table[m] = {c: {k: {"mean": round(float(np.mean(v)), 4), "sd": round(float(np.std(v)), 4)}
                        for k, v in runs[c].items()} for c in CLASSES}
    n_win = {c: int(sum(len(cell[(fo, t)]) for fo in folds for t in tags if scen(t) == c)) for c in CLASSES}
    res = {"runs": len(folds), "windows_per_model": n_win, "scenario_table": table,
           "mild_definition": sorted(MILD), "note": "accuracy / macro-F1 count abstention as wrong"}
    (out / "final_tables.json").write_text(json.dumps(res, indent=2))

    # ---------------- markdown tables
    L = ["# OB2 final validation tables (frozen v3_strength; exploratory, see README)", "",
         f"15 P1 runs, held-out bearings, repetitions >= 2. Windows per model: " +
         ", ".join(f"{LABEL[c]} {n_win[c]:,}" for c in CLASSES) + ".", ""]
    for metric, title in (("accuracy", "Accuracy"), ("macro_f1", "Macro-F1"), ("false_alarm_rate", "False-alarm rate (healthy windows diagnosed as damaged)"),
                          ("coverage", "Coverage (1 - abstention)")):
        L += [f"## {title}", "", "| Model | " + " | ".join(LABEL[c] for c in CLASSES) + " |", "|---|" + "---|" * len(CLASSES)]
        for m in MODELS:
            L.append(f"| {m} | " + " | ".join(f"{table[m][c][metric]['mean']:.3f}" for c in CLASSES) + " |")
        L.append("")
    L += ["## Group summary (from results/gating_research/gating_research_results.json, unchanged)", "",
          "| Model | Clean F1 | Seen F1 | Withheld F1 |", "|---|---|---|---|"]
    for m in MODELS:
        s = gr["run_level"][m]
        L.append(f"| {m} | " + " | ".join(f"{s[g]['macro_f1']['mean']:.3f} ± {s[g]['macro_f1']['sd']:.3f}" for g in ("clean", "seen", "withheld")) + " |")
    (out / "final_tables.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))

    # ---------------- figures
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK, "figure.facecolor": SURF,
                         "axes.facecolor": SURF, "savefig.facecolor": SURF})

    def bars(ax, groups, value, err=None, ymax=1.0, fmt="{:.2f}"):
        w = 0.8 / len(MODELS)
        for j, m in enumerate(MODELS):
            x = np.arange(len(groups)) + (j - (len(MODELS) - 1) / 2) * w
            y = [value(m, g) for g in groups]
            ax.bar(x, y, w * 0.86, color=COLORS[m], label=m, zorder=3,
                   yerr=[err(m, g) for g in groups] if err else None, error_kw={"ecolor": MUTED, "elinewidth": 0.8, "capsize": 1.5})
            for xi, yi in zip(x, y):
                ax.text(xi, yi + 0.012 * ymax + (max(err(m, g) for g in groups) if err else 0), fmt.format(yi), ha="center", va="bottom",
                        fontsize=6, color=MUTED, rotation=90)
        ax.set_ylim(0, ymax)
        ax.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0)

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    G = ["clean", "seen", "withheld"]
    bars(ax, G, lambda m, g: gr["run_level"][m][g]["macro_f1"]["mean"], lambda m, g: gr["run_level"][m][g]["macro_f1"]["sd"], ymax=0.9)
    ax.set_xticks(range(3), ["Clean", "Seen corruptions", "Withheld corruptions"])
    ax.set_ylabel("Macro-F1 (abstain = wrong)")
    ax.set_title("Bearing diagnosis on held-out bearings: mean ± sd over 15 bearing-disjoint runs", fontsize=9.5, loc="left")
    ax.legend(ncol=5, frameon=False, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    fig.tight_layout(); fig.savefig(out / "fig_macro_f1_groups.png", dpi=170); plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.2), sharex=True)
    bars(axes[0], CLASSES, lambda m, c: table[m][c]["macro_f1"]["mean"], ymax=0.85)
    axes[0].set_ylabel("Macro-F1 (abstain = wrong)")
    axes[0].set_title("Sensor-failure behaviour by scenario (15 runs, held-out bearings)", fontsize=9.5, loc="left")
    bars(axes[1], CLASSES, lambda m, c: table[m][c]["coverage"]["mean"], ymax=1.25)
    axes[1].set_ylabel("Coverage (share of windows diagnosed)")
    axes[1].set_yticks([0, 0.5, 1.0])
    axes[1].set_xticks(range(len(CLASSES)), [LABEL[c].replace(" ", "\n", 1) for c in CLASSES])
    axes[1].legend(ncol=5, frameon=False, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    fig.tight_layout(); fig.savefig(out / "fig_scenarios.png", dpi=170); plt.close(fig)

    # dual failure: what each model outputs when both sensors are dead (single series per panel -> one hue)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    y = np.arange(len(MODELS))[::-1]
    v = [table[m]["dual_failure"]["fault_class_issued"]["mean"] for m in MODELS]
    h = [1 - table[m]["dual_failure"]["coverage"]["mean"] for m in MODELS]
    ax.barh(y, v, 0.55, color="#2a78d6", zorder=3)
    for yi, vi, hi, m in zip(y, v, h, MODELS):
        ax.text(vi + 0.012, yi, f"{vi:.0%} fault class issued" + ("  ·  diagnosis withheld on 100 % of windows" if hi == 1 else
                                                                 "  ·  never withholds"), va="center", fontsize=7.5, color=INK)
    ax.set_yticks(y, MODELS); ax.set_xlim(0, 1.0); ax.set_xticks([0, 0.25, 0.5])
    ax.set_xticklabels(["0 %", "25 %", "50 %"])
    ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
    for s in ("top", "right", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.set_title(f"Both sensors dead ({n_win['dual_failure']:,} windows): share of windows given a damage diagnosis",
                 fontsize=9, loc="left")
    fig.tight_layout(); fig.savefig(out / "fig_dual_failure.png", dpi=170); plt.close(fig)


if __name__ == "__main__":
    main()
