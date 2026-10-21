"""OB3 validation on held-out Paderborn streams (bearings never used to train the demo model).

Usage: python -m health.validate <demo_dir> <out_dir>
Outputs: ob3_policy_streams.csv, ob3_summary.json, ob3_faithfulness.json,
         sample_report.html, sample_history.csv, health_demo.sqlite
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

from .engine import PortableModel, HealthPolicy, CLASSES, ADVICE
from .store import Store, html_report, csv_bytes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pu.features import VIB_NAMES, CUR_NAMES, Q_NAMES  # noqa: E402

QV = [f"qv_{q}" for q in Q_NAMES]
QC = [f"qc_{q}" for q in Q_NAMES]
INJECT_AT = 16
SCEN = [("none", "clean"), ("vib", "dropout"), ("vib", "stuck50"), ("vib", "spike_hi"),
        ("vib", "noise0"), ("cur", "dropout"), ("cur", "clip30")]


def stream_rows(S, bearing, cond, sensor, variant):
    base = S[(S.bearing == bearing) & (S.condition == cond)]
    clean = base[base.variant == "clean"].sort_values(["run", "win"]).reset_index(drop=True)
    if sensor == "none":
        return clean, ["clean"] * len(clean)
    bad = base[(base.variant == variant) & (base.corrupted == sensor)].set_index(["run", "win"])
    rows, inj = [], []
    for i, r in clean.iterrows():
        if i >= INJECT_AT and (r.run, r.win) in bad.index:
            rows.append(bad.loc[(r.run, r.win)])
            inj.append(f"{variant}@{sensor}")
        else:
            rows.append(r)
            inj.append("clean")
    return pd.DataFrame(rows).reset_index(drop=True), inj


def run_stream(pm, d, inj, store=None, session="", stream=""):
    r = pm.predict(d[VIB_NAMES].to_numpy(), d[CUR_NAMES].to_numpy(), d[QV].to_numpy(),
                   d[QC].to_numpy())
    pol = HealthPolicy()
    states = []
    for i in range(len(d)):
        e = 1 - r["P"][i, 0]
        rv = not (r["flag_v"][i] or r["dead_v"][i])
        rc = not (r["flag_c"][i] or r["dead_c"][i])
        o = pol.step(e, rv, rc)
        k = int(r["P"][i].argmax())
        states.append(o["state"])
        if store is not None:
            reasons = pm.explain(d[VIB_NAMES].iloc[i], d[CUR_NAMES].iloc[i], k if k else 1,
                                 r["w_v"][i], r["w_c"][i]) if o["state"] != "SENSOR_FAULT" else []
            adv = ADVICE.get(k, "No action; continue monitoring.") if k else "No action; continue monitoring."
            if not rv:
                adv += " " + ADVICE["vib"]
            if not rc:
                adv += " " + ADVICE["cur"]
            store.log(session=session, source="paderborn-replay", stream=stream, window=i,
                      state=o["state"], mode=o["mode"], evidence=float(e), predicted=CLASSES[k],
                      p_healthy=float(r["P"][i, 0]), p_outer=float(r["P"][i, 1]),
                      p_inner=float(r["P"][i, 2]), w_vib=float(r["w_v"][i]), w_cur=float(r["w_c"][i]),
                      vib_reliable=int(rv), cur_reliable=int(rc), injected=inj[i],
                      reasons=[list(x) for x in reasons], advice=adv)
    return np.array(states), r


def first(states, s):
    idx = np.where(states == s)[0]
    return int(idx[0]) if len(idx) else None


def main(demo_dir, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pm = PortableModel(str(Path(demo_dir) / "model.json"))
    S = pd.read_csv(Path(demo_dir) / "stream.csv.gz")
    rows = []
    for (b, c), g in S[S.variant == "clean"].groupby(["bearing", "condition"]):
        label = int(g.label.iloc[0])
        for sensor, variant in SCEN:
            d, inj = stream_rows(S, b, c, sensor, variant)
            st, r = run_stream(pm, d, inj)
            post = st[INJECT_AT:] if sensor != "none" else st
            pred = r["P"].argmax(1)
            # benchmark replay latency: 2-of-3 windows predicted faulty (not the operational policy)
            fl = (pred != 0).astype(int)
            lat = next((i for i in range(2, len(fl)) if fl[i - 2:i + 1].sum() >= 2), None)
            rows.append({"bearing": b, "condition": c, "true": CLASSES[label], "sensor": sensor,
                         "variant": variant, "n_windows": len(st),
                         "frac_NORMAL": float((st == "NORMAL").mean()),
                         "frac_WARNING": float((st == "WARNING").mean()),
                         "frac_INSPECT": float((st == "INSPECT").mean()),
                         "frac_SENSOR_FAULT_after_injection": float((post == "SENSOR_FAULT").mean()),
                         "first_WARNING": first(st, "WARNING"), "first_INSPECT": first(st, "INSPECT"),
                         "inspect_latched": bool((st == "INSPECT").any()),
                         "final_state": st[-1], "window_acc": float((pred == label).mean()),
                         "replay_latency_2of3": lat})
    T = pd.DataFrame(rows)
    T.to_csv(out / "ob3_policy_streams.csv", index=False)
    summ = {}
    for (true, sensor, variant), g in T.groupby(["true", "sensor", "variant"]):
        summ[f"{true}|{variant}@{sensor}"] = {
            "streams": len(g), "inspect_latched_rate": round(g.inspect_latched.mean(), 3),
            "mean_frac_INSPECT": round(g.frac_INSPECT.mean(), 3),
            "median_first_INSPECT": None if g.first_INSPECT.isna().all() else float(g.first_INSPECT.median()),
            "mean_frac_SENSOR_FAULT_after_injection": round(g.frac_SENSOR_FAULT_after_injection.mean(), 3),
            "mean_window_acc": round(g.window_acc.mean(), 3)}
    (out / "ob3_summary.json").write_text(json.dumps(summ, indent=1))

    # deletion faithfulness check on clean windows predicted faulty
    C = S[S.variant == "clean"]
    r = pm.predict(C[VIB_NAMES].to_numpy(), C[CUR_NAMES].to_numpy(), C[QV].to_numpy(), C[QC].to_numpy())
    rng = np.random.default_rng(0)
    idx = np.where(r["P"].argmax(1) != 0)[0]
    idx = rng.choice(idx, min(500, len(idx)), replace=False) if len(idx) else idx
    drops_top, drops_rand = [], []
    for i in idx:
        k = int(r["P"][i].argmax())
        for lin, X in ((pm.vib, C[VIB_NAMES].to_numpy()), (pm.cur, C[CUR_NAMES].to_numpy())):
            z = lin.z(X[i:i + 1])[0]
            contrib = (lin.coef[k] - lin.coef[0]) * z
            base = lin.proba(X[i:i + 1])[0, k]

            def p_after(js):
                z2 = z.copy()
                z2[js] = 0.0  # feature replaced by its training mean
                s = z2 @ lin.coef.T + lin.intercept
                s = np.exp(s - s.max())
                return (s / s.sum())[k]
            top = np.argsort(-contrib)[:3]
            rnd = rng.choice(len(z), 3, replace=False)
            drops_top.append(base - p_after(top))
            drops_rand.append(base - p_after(rnd))
    faith = {"n_windows": int(len(idx)), "mean_prob_drop_top3_deleted": float(np.mean(drops_top)) if drops_top else None,
             "mean_prob_drop_random3_deleted": float(np.mean(drops_rand)) if drops_rand else None,
             "frac_top3_drop_exceeds_random": float(np.mean(np.array(drops_top) > np.array(drops_rand))) if drops_top else None}
    (out / "ob3_faithfulness.json").write_text(json.dumps(faith, indent=1))

    # end-to-end logging + report: one faulty stream with a vibration dropout injected
    db = out / "health_demo.sqlite"
    if db.exists():
        db.unlink()
    store = Store(str(db))
    faulty = [b for b in pm.meta["test_bearings"] if not b.startswith("K0")]
    b = faulty[0]
    d, inj = stream_rows(S, b, "N15_M07_F10", "vib", "dropout")
    st, _ = run_stream(pm, d, inj, store, session="validation", stream=f"{b} N15_M07_F10")
    store.action("validation", "acknowledge", "operator acknowledged INSPECT (validation run)")
    ev, acts = store.events("validation"), store.actions("validation")
    (out / "sample_history.csv").write_bytes(csv_bytes(ev))
    (out / "sample_report.html").write_text(html_report(
        ev, acts, f"Bearing health report - {b} (held-out)",
        f"Source: replay of recorded Paderborn windows ({pm.meta['data_label']}); bearing {b} was not used "
        f"to train the model. Vibration dropout injected from window {INJECT_AT}."))
    print(json.dumps(summ, indent=1)[:2500])
    print(faith)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
