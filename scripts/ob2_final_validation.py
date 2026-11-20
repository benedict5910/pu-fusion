"""OB2 final validation of the FROZEN v3_strength fusion (fusion_v3, rule "strength").

Nothing is tuned here. beta per fold is read from results/gating_research/predictions_v3.json
(chosen earlier on training bearings only); the selection is re-run only to confirm it
reproduces. For every P1 fold the script:

  1. refits the experts / gate / v2 detector on training bearings (deterministic) and checks
     that v3_strength and the comparison models reproduce the stored predictions exactly
     (regression check; vib_only, late_average, gated_both, gated_v2 are derived from the
     same fitted experts, so no other model is retrained);
  2. builds DUAL-SENSOR-FAILURE windows from held-out bearing recordings (repetitions >= 2).
     Vibration and current features are computed independently per sensor, so a window with
     both sensors dead is the vibration half of the stored vib:<failure> row plus the current
     half of the stored cur:<failure> row of the same recording window (exact; verified
     against raw signals with --raw-dir);
  3. passes every decision through the health tracker (health.HealthTracker) and records
     SENSOR_FAULT / diagnosis availability / whether a fault class was issued.

With --raw-dir (extracted .mat files of the held-out bearings of --raw-fold) the same chain is
run from RAW signals through monitor.MonitorEngine: corruption -> feature extraction ->
detector -> fusion -> health state, plus a clean -> outage -> restored sequence per bearing.

  python scripts/ob2_final_validation.py --features data/features_full.npz \
      --selection results/full_2026-11-15/ob2_v2/quality_v2.json \
      --frozen results/gating_research/predictions_v3.json \
      --v3-pred results/gating_research/predictions_v3.npz \
      --base-pred results/full_2026-11-15/ob_final/predictions.npz \
      --raw-dir /path/to/raw --out results/gating_research/final_validation
"""
import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion import corruption as C  # noqa: E402
from pufusion.config import CLASS_NAMES, HEALTHY, OPERATING_CONDITIONS  # noqa: E402
from pufusion.data import load_mat, windows  # noqa: E402
from pufusion.dataset import concat, extract, load_tables, subset  # noqa: E402
from pufusion.fusion_v3 import GatedV3, combine, select_params  # noqa: E402
from pufusion.health import SENSOR_FAULT, HealthTracker  # noqa: E402
from pufusion.models import ReliabilityGated  # noqa: E402
from pufusion.monitor import MonitorEngine  # noqa: E402
from pufusion.reliability import SensorReliability  # noqa: E402
from pufusion.reliability_v2 import CANDIDATES, build_baselines, repetition  # noqa: E402
from pufusion.splits import assert_disjoint, p1_folds  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import restrict  # noqa: E402

MODELS = ["vib_only", "late_average", "gated_both", "gated_v2", "v3_strength"]
DUAL = [("dropout", "dropout"), ("stuck", "stuck"), ("dropout", "stuck"), ("stuck", "dropout")]


def reliability(e, failed):
    if failed:
        return SensorReliability(0.0, "failed", ["dead or missing signal"])
    return SensorReliability(1.0, "ok") if e == 0 else SensorReliability(0.75, "degraded", ["outside normal range"])


def all_models(model, beta, t):
    """Predictions of every compared model from ONE set of fitted experts."""
    pk = model.pack(t)
    out = {"vib_only": (pk["pv"], np.zeros(len(pk["pv"]), bool)),
           "late_average": (0.5 * (pk["pv"] + pk["pc"]), np.zeros(len(pk["pv"]), bool)),
           "gated_both": (ReliabilityGated.predict_proba(model, t), model._dead(t["qv"]) & model._dead(t["qc"])),
           "gated_v2": model.predict_with_abstain(t)}
    p, ab, _ = combine("strength", beta, pk)
    out["v3_strength"] = (p, ab)
    return out, pk


def health_flags(p, ab, pk):
    """One fresh HealthTracker per window: (SENSOR_FAULT, diagnosis available)."""
    sf, avail = np.zeros(len(p), bool), np.zeros(len(p), bool)
    for i in range(len(p)):
        rel = {"vib": reliability(pk["ev"][i], pk["fv"][i]), "cur": reliability(pk["ec"][i], pk["fc"][i])}
        cls = int(p[i].argmax())
        a = HealthTracker().update(None if ab[i] else float(1 - p[i, HEALTHY]),
                                   None if ab[i] or cls == HEALTHY else CLASS_NAMES[cls], rel)
        sf[i], avail[i] = a.state == SENSOR_FAULT, a.diagnosis_available
    return sf, avail


def dual_table(cr, fam_v, fam_c):
    """Both sensors failed: vibration half of vib:<fam_v>, current half of cur:<fam_c>, same windows."""
    v = subset(cr, cr["tag"] == f"vib:{fam_v}:None")
    c = subset(cr, cr["tag"] == f"cur:{fam_c}:None")
    v, c = subset(v, np.argsort(v["stem"], kind="stable")), subset(c, np.argsort(c["stem"], kind="stable"))
    assert (v["stem"] == c["stem"]).all() and (v["win"] == c["win"]).all() and len(np.unique(v["stem"])) == len(v["stem"])
    d = dict(v)
    d["fc"], d["qc"] = c["fc"], c["qc"]
    d["tag"] = np.array([f"dual:vib_{fam_v}+cur_{fam_c}"] * len(v["y"]))
    return d


class V3Diagnoser:
    """Raw window -> features -> v2 detector -> frozen v3_strength -> diagnosis dict for MonitorEngine."""

    def __init__(self, model, beta):
        self.model, self.beta = model, beta

    def __call__(self, win):
        rpm = OPERATING_CONDITIONS[win["condition"]][0]
        feats = extract(win["vib"], win["cur"], win["fs"], rpm)
        t = {k: np.asarray(v)[None] for k, v in feats.items()}
        t["bearing"], t["condition"] = np.array([win["bearing"]]), np.array([win["condition"]])
        pk = self.model.pack(t)
        p, ab, w = combine("strength", self.beta, pk)
        cls = int(p[0].argmax())
        rel = {"vib": reliability(pk["ev"][0], pk["fv"][0]), "cur": reliability(pk["ec"][0], pk["fc"][0])}
        return {"reliability": rel, "p_fault": None if ab[0] else float(1 - p[0, HEALTHY]),
                "fault_type": None if ab[0] or cls == HEALTHY else CLASS_NAMES[cls],
                "confidence": None if ab[0] else float(p[0, cls]), "weights": {"vib": float(w[0, 0]), "cur": float(w[0, 1])},
                "readings": {}, "features": feats, "abstain": bool(ab[0])}


def _corrupt(x, fam):
    return x if fam is None else C.apply(x, fam, None, np.random.default_rng(0))


def raw_check(model, beta, raw_dir, test_bearings, tables):
    """End to end from raw held-out recordings (repetitions >= 2, first window)."""
    scen = [("clean", None, None), ("vib_dropout", "dropout", None), ("cur_dropout", None, "dropout"),
            ("vib_stuck", "stuck", None), ("cur_stuck", None, "stuck")] + \
           [(f"dual:vib_{a}+cur_{b}", a, b) for a, b in DUAL]
    files = sorted(f for f in Path(raw_dir).rglob("*.mat")
                   if f.stem.split("_")[3] in test_bearings and int(f.stem.rsplit("_", 1)[1]) >= 2)
    diag = V3Diagnoser(model, beta)
    acc = {s[0]: defaultdict(int) for s in scen}
    key = {(s, t): i for tab in ("clean", "corr") for i, (s, t) in
           enumerate(zip(tables[tab]["stem"], tables[tab]["tag"])) if tables[tab]["win"][i] == 0 for _ in [0]}
    idx = {tab: {(s, t): i for i, (s, t, w) in enumerate(zip(tables[tab]["stem"], tables[tab]["tag"], tables[tab]["win"]))
                 if w == 0} for tab in ("clean", "corr")}
    del key
    feat_diff, n_feat = 0.0, 0
    seq = []
    for f in files:
        rec = load_mat(f)
        wins = list(windows(rec, 0.5))
        _, v, c = wins[0]
        for name, fv_, fc_ in scen:
            eng = MonitorEngine(diag, "final validation (raw, held-out bearing)")
            win = {"vib": _corrupt(v, fv_), "cur": _corrupt(c, fc_), "fs": rec.fs,
                   "condition": rec.condition, "bearing": rec.bearing}
            r = eng.step(win, ts=1.0)
            a = acc[name]
            a["n"] += 1
            a["sensor_fault"] += r["state"] == SENSOR_FAULT
            a["diagnosis_available"] += r["assessment"].diagnosis_available
            a["logged_p_fault_is_none"] += r["p_fault"] is None
            a["fault_class_issued"] += r["fault_type"] is not None
            a["healthy"] += rec.label == HEALTHY
            a["false_alarm"] += (rec.label == HEALTHY) and (r["fault_type"] is not None)
            a["correct"] += (not r["diagnosis"]["abstain"]) and (
                (r["diagnosis"]["fault_type"] or "healthy") == CLASS_NAMES[rec.label])
            # raw-derived features vs stored table rows (clean and single failures; duals vs composition)
            ft = r["diagnosis"]["features"]
            if name == "clean":
                ref = {k: tables["clean"][k][idx["clean"][(rec.stem, "clean")]] for k in ("fv", "fc", "qv", "qc")}
            elif name.startswith("dual"):
                iv = idx["corr"][(rec.stem, f"vib:{fv_}:None")]
                ic = idx["corr"][(rec.stem, f"cur:{fc_}:None")]
                ref = {"fv": tables["corr"]["fv"][iv], "qv": tables["corr"]["qv"][iv],
                       "fc": tables["corr"]["fc"][ic], "qc": tables["corr"]["qc"][ic]}
            else:
                i = idx["corr"][(rec.stem, f"{name[:3]}:{name[4:]}:None")]
                ref = {k: tables["corr"][k][i] for k in ("fv", "fc", "qv", "qc")}
            for k in ref:
                feat_diff = max(feat_diff, float(np.nanmax(np.abs(np.asarray(ft[k], float) - ref[k]))))
                n_feat += 1
        # sequence on repetition 2 of each bearing/condition: 4 clean, 4 both-dropout, 4 clean windows
        if rec.repetition == 2:
            eng = MonitorEngine(diag, "final validation sequence")
            states = []
            for j, (_, vv, cc) in enumerate(wins[:8] + wins[:4]):
                dead = 4 <= j < 8
                r = eng.step({"vib": _corrupt(vv, "dropout" if dead else None), "cur": _corrupt(cc, "dropout" if dead else None),
                              "fs": rec.fs, "condition": rec.condition, "bearing": rec.bearing}, ts=float(j + 1))
                states.append((r["state"], r["assessment"].diagnosis_available, r["p_fault"] is None))
            before = states[3][0]
            seq.append({"stem": rec.stem, "label": CLASS_NAMES[rec.label], "state_before": before,
                        "outage_states": sorted({s[0] for s in states[4:8]}),
                        "outage_diagnosis_available": any(s[1] for s in states[4:8]),
                        "outage_p_fault_all_none": all(s[2] for s in states[4:8]),
                        "state_first_restored_window": states[8][0], "restored_diagnosis_available": states[8][1]})
    return {"recordings": len(files), "scenarios": {k: dict(v) for k, v in acc.items()},
            "max_abs_feature_diff_raw_vs_table": feat_diff, "feature_vectors_compared": n_feat, "sequences": seq}


def main():
    ap = argparse.ArgumentParser()
    for k in ("features", "selection", "frozen", "v3-pred", "base-pred", "out"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--raw-dir", default="")
    ap.add_argument("--raw-fold", default="P1_r0_f0")
    ap.add_argument("--folds", default="")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    t = load_tables(a.features)
    sel = {s["fold"]: s["selected"] for s in json.loads(Path(a.selection).read_text())["selection"]}
    frozen = {f["fold"]: f for f in json.loads(Path(a.frozen).read_text())["folds"]}
    by_name = {c.name: c for c in CANDIDATES}
    stored = {}
    for path, names in ((a.base_pred, MODELS[:4]), (a.v3_pred, ["v3_strength"])):
        z = np.load(path)
        for m in names:
            s = z["model"] == m
            stored[m] = {k: z[k][s] for k in ("fold", "tag", "bearing", "y", "pred", "abstain", "p")}
    folds = restrict(p1_folds(5), set(np.unique(t["clean"]["bearing"])))
    if a.folds:
        folds = [f for f in folds if f["name"] in set(a.folds.split(","))]
    rec = {k: [] for k in ("fold", "model", "tag", "bearing", "y", "pred", "abstain", "sensor_fault", "diag_avail")}
    std_health = defaultdict(lambda: [0, 0, 0])      # tag -> [n, sensor_fault, diagnosis available] for v3_strength
    reg = {m: {"rows": 0, "pred_mismatch": 0, "abstain_mismatch": 0, "max_abs_p_diff": 0.0} for m in MODELS}
    checks = {"selection_reproduced": [], "train_test_disjoint": [], "selection_tables_contain_test_bearing": [],
              "dual_rows_from_test_bearings_rep_ge_2": []}
    raw = None
    for fold in folds:
        assert_disjoint(fold["train"], fold["test"])
        cfg, fz = by_name[sel[fold["name"]]], frozen[fold["name"]]
        assert fz["train"] == fold["train"] and fz["test"] == fold["test"]
        beta = fz["selected"]["strength"]["param"]
        in_tr = lambda tab: np.isin(tab["bearing"], fold["train"])
        trc = subset(t["clean"], in_tr(t["clean"]))
        train_tabs = {"clean": trc, "aug": subset(t["aug"], in_tr(t["aug"])), "corr": subset(t["corr"], in_tr(t["corr"]))}
        bl_tr = {k: build_baselines(trc, k) for k in ("qv", "qc")}
        # frozen selection must reproduce from training bearings alone
        again = select_params(train_tabs, fold["train"], cfg, bl_tr)["strength"]
        checks["selection_reproduced"].append(again["param"] == beta and again["inner"] == fz["selected"]["strength"]["inner"])
        checks["train_test_disjoint"].append(not set(fold["train"]) & set(fold["test"]))
        checks["selection_tables_contain_test_bearing"].append(
            any(np.isin(tab["bearing"], fold["test"]).any() for tab in train_tabs.values()))
        te_all = subset(t["clean"], np.isin(t["clean"]["bearing"], fold["test"]))
        bl = {k: {**bl_tr[k], **build_baselines(te_all, k)} for k in ("qv", "qc")}
        model = GatedV3(cfg, bl).fit(concat(trc, train_tabs["aug"]))
        te = subset(te_all, repetition(te_all["stem"]) != 1)
        cr = subset(t["corr"], np.isin(t["corr"]["bearing"], fold["test"]))
        cr = subset(cr, repetition(cr["stem"]) != 1)
        evalset = concat(te, cr)
        # ---- regression: every model reproduces its stored predictions on the standard evaluation rows
        preds, pk = all_models(model, beta, evalset)
        for m in MODELS:
            st = {k: v[stored[m]["fold"] == fold["name"]] for k, v in stored[m].items()}
            assert (st["tag"] == evalset["tag"]).all() and (st["y"] == evalset["y"]).all()
            p, ab = preds[m]
            r = reg[m]
            r["rows"] += len(p)
            r["pred_mismatch"] += int((p.argmax(1) != st["pred"]).sum())
            r["abstain_mismatch"] += int((ab != st["abstain"]).sum())
            r["max_abs_p_diff"] = max(r["max_abs_p_diff"], float(np.abs(p.astype(np.float32) - st["p"]).max()))
        sf, av = health_flags(*preds["v3_strength"], pk)
        for tag in np.unique(evalset["tag"]):
            m_ = evalset["tag"] == tag
            h = std_health[str(tag)]
            h[0] += int(m_.sum()); h[1] += int(sf[m_].sum()); h[2] += int(av[m_].sum())
        # ---- dual sensor failure on held-out bearings
        for fam_v, fam_c in DUAL:
            d = dual_table(cr, fam_v, fam_c)
            checks["dual_rows_from_test_bearings_rep_ge_2"].append(
                bool(np.isin(d["bearing"], fold["test"]).all() and (repetition(d["stem"]) >= 2).all()))
            dp, dpk = all_models(model, beta, d)
            for m in MODELS:
                p, ab = dp[m]
                if m == "v3_strength":
                    sf, av = health_flags(p, ab, dpk)
                else:
                    sf, av = np.zeros(len(p), bool), ~ab
                n = len(p)
                rec["fold"] += [fold["name"]] * n; rec["model"] += [m] * n
                rec["tag"] += list(d["tag"]); rec["bearing"] += list(d["bearing"])
                rec["y"].append(d["y"]); rec["pred"].append(p.argmax(1)); rec["abstain"].append(ab)
                rec["sensor_fault"].append(sf); rec["diag_avail"].append(av)
        if a.raw_dir and fold["name"] == a.raw_fold:
            raw = raw_check(model, beta, a.raw_dir, set(fold["test"]), t)
            raw["fold"], raw["beta"] = fold["name"], beta
            print(f"  raw end-to-end: {raw['recordings']} recordings, max |feature diff| = "
                  f"{raw['max_abs_feature_diff_raw_vs_table']:.3g}", flush=True)
        print(f"{fold['name']}: beta={beta} ok  ({time.time() - t0:.0f}s)", flush=True)

    arr = {k: (np.concatenate(v) if k in ("y", "pred", "abstain", "sensor_fault", "diag_avail") else np.array(v))
           for k, v in rec.items()}
    np.savez_compressed(out / "dual_failure_predictions.npz", **arr)
    res = {"frozen": {"method": "v3_strength (fusion_v3.combine 'strength')",
                      "fusion_v3_sha256": hashlib.sha256((ROOT / "src/pufusion/fusion_v3.py").read_bytes()).hexdigest(),
                      "beta_per_fold": {f["name"]: frozen[f["name"]]["selected"]["strength"]["param"] for f in folds},
                      "source": a.frozen},
           "folds": len(folds), "regression_vs_stored_predictions": reg,
           "checks": {k: {"n": len(v), "true": int(sum(v))} for k, v in checks.items()},
           "v3_health_on_standard_rows": {k: {"n": v[0], "sensor_fault": v[1], "diagnosis_available": v[2]}
                                          for k, v in sorted(std_health.items())},
           "raw_end_to_end": raw}
    (out / "validation.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({"regression": reg, "checks": res["checks"]}, indent=1))


if __name__ == "__main__":
    main()
