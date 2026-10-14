"""Fit the rig's healthy-baseline detector and evaluate it by SESSION.

  python scripts/rig_train.py --fit H1 --cal H2 --test-healthy H3 --test-fault F1 F2

- fit: healthy session used to learn the baseline
- cal: a different healthy session that sets the alarm threshold (99.5th percentile)
- test-healthy / test-fault: sessions never used for fitting -> false alarms, detection, latency
Writes models/rig_models.pkl and results/rig_eval.json (with the data source recorded).
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.health import NORMAL, HealthTracker  # noqa: E402
from pufusion.monitor import RigDiagnoser  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402
from pufusion.rig import RigAnomalyDetector, load_rig_config, rig_features  # noqa: E402


def load_session(name, cfg):
    z = np.load(f"data/rig/{name}.npz")
    meta = json.loads(Path(f"data/rig/{name}.json").read_text())
    wins = [{"vib": z["vib"][i], "cur": z["cur"][i], "rpm": float(z["rpm"][i]),
             "temp_c": float(z["temp_c"][i]), "vbus": float(z["vbus"][i])} for i in range(len(z["vib"]))]
    return wins, meta


def table(wins, cfg):
    f = [rig_features(w, cfg) for w in wins]
    return {k: np.stack([x[k] for x in f]) for k in ("fv", "fc", "qv", "qc")}


def run_session(diag, wins, cfg):
    tr = HealthTracker()
    states, ev = [], []
    for w in wins:
        d = diag(w)
        states.append(tr.update(d["p_fault"], None, d["reliability"]).state)
        ev.append(d["p_fault"])
    first = next((i for i, s in enumerate(states) if s != NORMAL), None)
    return {"windows": len(wins), "window_alarm_rate": float(np.mean([e is not None and e > 0.5 for e in ev])),
            "ever_non_normal": first is not None,
            "first_non_normal_s": None if first is None else (first + 1) * cfg.window_s,
            "final_state": states[-1] if states else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--cal", required=True)
    ap.add_argument("--test-healthy", nargs="+", required=True)
    ap.add_argument("--test-fault", nargs="+", required=True)
    ap.add_argument("--config", default="configs/rig.json")
    a = ap.parse_args()
    names = [a.fit, a.cal, *a.test_healthy, *a.test_fault]
    if len(set(names)) != len(names):
        raise SystemExit("every session may be used only once (session-disjoint evaluation)")
    cfg = load_rig_config(a.config)
    (fw, fm), (cw, cm) = load_session(a.fit, cfg), load_session(a.cal, cfg)
    for m in (fm, cm):
        if m["label"] != "healthy":
            raise SystemExit(f"{m['session']} is not a healthy session")
    F, Cc = table(fw, cfg), table(cw, cfg)
    det = RigAnomalyDetector().fit(F, Cc)
    assess = {"vib": ReliabilityAssessor().fit(F["qv"]), "cur": ReliabilityAssessor().fit(F["qc"])}
    diag = RigDiagnoser(det, assess, cfg)
    report = {"data_source": sorted({fm["source"], cm["source"]}), "fit": a.fit, "cal": a.cal, "sessions": {}}
    for n in [*a.test_healthy, *a.test_fault]:
        w, m = load_session(n, cfg)
        report["sessions"][n] = {"label": m["label"], "source": m["source"], **run_session(diag, w, cfg)}
    Path("results").mkdir(exist_ok=True)
    Path("results/rig_eval.json").write_text(json.dumps(report, indent=2))
    Path("models").mkdir(exist_ok=True)
    with open("models/rig_models.pkl", "wb") as f:
        pickle.dump({"detector": det, "assessors": assess, "config": cfg, "trained_on": [a.fit, a.cal]}, f)
    print(json.dumps(report, indent=2))
    if any("SIMULATED" in s for s in report["data_source"]):
        print("\nSIMULATED sessions: this checks the pipeline only; it is not a rig result.")


if __name__ == "__main__":
    main()
