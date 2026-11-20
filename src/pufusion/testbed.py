"""Simulation-based virtual testbed (OB4).

Replays real held-out recordings window by window, injects seeded sensor faults for chosen
segments of the run, and passes every window through the SAME chain the dashboard uses:

  recording replay -> fault injection -> feature extraction -> sensor-quality check ->
  diagnosis (frozen demo models) -> HealthTracker state rules -> HealthStore (SQLite) log

A scenario is a list of segments (n windows, optional fault on a sensor) plus optional operator
acknowledgements. After a run, `check()` verifies safety invariants on the logged trace:
every state change has exactly one event, no diagnostic value is stored while diagnosis is
suspended, a dead sensor gets weight zero, an acknowledged INSPECT drops to WARNING (never
NORMAL), and diagnosis resumes when a sensor is restored.

Recordings are real (Paderborn CC BY-NC 4.0, MCC5-THU CC BY 4.0); sensor faults are synthetic.
A bearing recording has 8 windows and a gearbox recording 59; longer runs loop the recording.
No hardware is involved and nothing is trained here.
"""
from __future__ import annotations

import pickle
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import corruption as C
from . import gearbox as G
from .data import load_mat, windows
from .dataset import corrupt_pair
from .health import ACK_RULE, INSPECT, NORMAL, SENSOR_FAULT, WARNING, HealthTracker
from .monitor import SOURCE_BENCHMARK, BenchmarkDiagnoser, MonitorEngine

ROOT = Path(__file__).resolve().parents[2]
GB_SOURCE = "benchmark replay (MCC5-THU gearbox, held-out profile)"
T0 = 1_800_000_000.0            # fixed clock so traces are reproducible


@dataclass
class Segment:
    n: int
    fault: str | None = None      # corruption family, None = clean
    target: str | None = None     # bearing: vib | cur | both ; gearbox: motor | gearbox | both
    severity: object = None       # bearing only (gearbox uses sensor_faults.SCENARIOS)
    ack_before: bool = False      # operator acknowledges INSPECT before this segment starts


@dataclass
class Scenario:
    name: str
    subsystem: str                # "bearing" | "gearbox"
    recording: str
    segments: list
    purpose: str = ""
    expect: list = field(default_factory=list)   # [{"seg": i, "states": [...], "diagnosis": bool, "zero_weight": sensor}]


def gearbox_data_dir():
    """Folder holding the held-out gearbox recordings: full data, local demo copy, or the dashboard cache."""
    for d in (ROOT / "data" / "mcc5", ROOT / "data" / "mcc5_demo", Path(tempfile.gettempdir()) / "ivhm_mcc5_demo"):
        if d.is_dir() and any(d.glob("*.csv*")):
            return d
    return None


class Context:
    """Frozen models and recordings, loaded once."""

    def __init__(self, gearbox_dir=None):
        with open(ROOT / "models" / "demo_models.pkl", "rb") as f:
            self.bearing = pickle.load(f)
        self.bearing_recs = {b: ROOT / "data" / "raw" / b / f"N15_M07_F10_{b}_1.mat" for b in self.bearing["holdout"]}
        self.gearbox, self.gearbox_recs = None, {}
        gdir = Path(gearbox_dir) if gearbox_dir else gearbox_data_dir()
        man = ROOT / "models" / "gearbox_demo_1000rpm_10Nm.pkl"
        if gdir is not None and man.exists():
            with open(man, "rb") as f:
                self.gearbox = pickle.load(f)
            self.gearbox_recs = {r.id: r for r in G.discover(gdir) if r.id in self.gearbox["test"]}
        self._gb_windows = {}

    def gearbox_windows(self, rec_id):
        if rec_id not in self._gb_windows:
            self._gb_windows[rec_id] = list(G.windows(self.gearbox_recs[rec_id]))
        return self._gb_windows[rec_id]


def _plan(scn):
    """Per window: (segment index, fault, target, severity)."""
    return [(k, s.fault, s.target, s.severity) for k, s in enumerate(scn.segments) for _ in range(s.n)]


def _ack(tracker, store, asset, source, ts):
    res = tracker.acknowledge()
    if res is not None:
        store.log_event(asset, source, res["from_state"], res["to_state"], res["rule"], res["recommendations"], ts)
    return res is not None


def run_scenario(scn: Scenario, ctx: Context, store, asset=None):
    """Run one scenario; returns the per-window trace (also logged to `store`)."""
    asset = asset or f"vt-{scn.name}"
    plan = _plan(scn)
    starts = {sum(s.n for s in scn.segments[:k]): s for k, s in enumerate(scn.segments)}
    trace, acks = [], []
    if scn.subsystem == "bearing":
        rec = load_mat(ctx.bearing_recs[scn.recording])
        wins = list(windows(rec))
        tracker = HealthTracker()
        eng = MonitorEngine(BenchmarkDiagnoser(ctx.bearing["models"]["gated_both"], ctx.bearing["assessors"]),
                            SOURCE_BENCHMARK, asset, store, tracker)
        for i, (seg, fam, target, sev) in enumerate(plan):
            ts = T0 + i
            if i in starts and starts[i].ack_before:
                acks.append((i, _ack(tracker, store, asset, eng.source, ts - 0.5)))
            _, v, c = wins[i % len(wins)]
            if fam:
                if sev is None and len(C.FAMILIES[fam][1]) > 1:
                    raise ValueError(f"{scn.name}: severity required for {fam}")
                v, c = corrupt_pair(v, c, target, fam, sev, np.random.default_rng(i))
            r = eng.step({"vib": v, "cur": c, "fs": rec.fs, "condition": rec.condition}, ts=ts)
            rel = r["diagnosis"]["reliability"]
            trace.append({"window": i + 1, "segment": seg, "fault": fam, "target": target, "state": r["state"],
                          "diagnosis_available": r["assessment"].diagnosis_available, "p_fault": r["p_fault"],
                          "fault_type": r["fault_type"], "rule": r["assessment"].rule,
                          "status": {"vib": rel["vib"].status, "cur": rel["cur"].status},
                          "weights": {"vib": r["w_vib"], "cur": r["w_cur"]}})
    elif scn.subsystem == "gearbox":
        if ctx.gearbox is None or scn.recording not in ctx.gearbox_recs:
            raise FileNotFoundError("held-out MCC5-THU recordings not available")
        wins = ctx.gearbox_windows(scn.recording)
        rng = np.random.default_rng(ctx.gearbox["seeds"][scn.recording])
        feats = [G.features(G.corrupt(wins[i % len(wins)], fam, target, rng) if fam else wins[i % len(wins)])
                 for i, (_, fam, target, _) in enumerate(plan)]
        x, q = np.stack([f[0] for f in feats]), np.stack([f[1] for f in feats])
        tracker = HealthTracker(fault_advice=G.GEARBOX_ADVICE)
        rows = G.replay(ctx.gearbox["model"], x, q, include_details=True, tracker=tracker)
        before = tracker.state
        for i, (seg, fam, target, _) in enumerate(plan):
            ts = T0 + i
            if i in starts and starts[i].ack_before:
                acks.append((i, _ack(tracker, store, asset, GB_SOURCE, ts - 0.5)))
                before = tracker.state
            row = next(rows)
            row["ts"] = ts
            store.log_window(G.store_record(row, asset, GB_SOURCE, scn.recording))
            if row["state"] != before:
                store.log_event(asset, GB_SOURCE, before, row["state"], row["rule"], row["recommendation_list"], ts)
            before = row["state"]
            ok = row["diagnosis_available"]
            trace.append({"window": i + 1, "segment": seg, "fault": fam, "target": target, "state": row["state"],
                          "diagnosis_available": ok, "p_fault": row["fault_score"] if ok else None,
                          "fault_type": row["prediction"] if ok else None, "rule": row["rule"],
                          "status": {s: row["reliability"][s]["status"] for s in G.SENSORS},
                          "weights": {s: (row[f"{s}_weight"] if ok else None) for s in G.SENSORS}})
    else:
        raise ValueError(scn.subsystem)
    return {"asset": asset, "trace": trace, "acks": acks}


def check(scn: Scenario, run, store):
    """Safety invariants on the trace and on what was actually logged. Returns [(name, passed, detail)]."""
    tr, asset, out = run["trace"], run["asset"], []
    hist, events = store.history(asset, limit=10 ** 6), store.events(asset)

    def add(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    add("every window logged", len(hist) == len(tr), f"{len(hist)} logged / {len(tr)} run")
    # expected event sequence: state changes in the trace, plus acknowledgements
    exp, prev = [], NORMAL
    ack_at = {i for i, done in run["acks"] if done}
    for k, w in enumerate(tr):
        if k in ack_at:
            exp.append((INSPECT, WARNING)); prev = WARNING
        if w["state"] != prev:
            exp.append((prev, w["state"]))
        prev = w["state"]
    got = [(e["from_state"], e["to_state"]) for e in events]
    add("one logged event per state change", got == exp, f"{len(got)} events logged, {len(exp)} expected")
    susp = [k for k, w in enumerate(tr) if not w["diagnosis_available"]]
    add("no diagnostic values stored while suspended",
        all(hist[k]["p_fault"] is None and hist[k]["fault_type"] is None and hist[k]["w_vib"] is None
            and hist[k]["w_cur"] is None for k in susp), f"{len(susp)} suspended windows")
    dead_all = [w for w in tr if all(s == "failed" for s in w["status"].values())]
    add("all sensors failed -> diagnosis suspended, state SENSOR_FAULT or latched INSPECT",
        all((not w["diagnosis_available"]) and w["state"] in (SENSOR_FAULT, INSPECT) for w in dead_all),
        f"{len(dead_all)} windows")
    add("SENSOR_FAULT only when no sensor is usable",
        all(not w["diagnosis_available"] for w in tr if w["state"] == SENSOR_FAULT))
    one = [w for w in tr if sum(s == "failed" for s in w["status"].values()) == 1]
    add("single failed sensor -> weight 0, diagnosis continues",
        all(w["diagnosis_available"] and all((w["weights"][s] or 0.0) == 0.0 for s, st in w["status"].items()
                                             if st == "failed") for w in one), f"{len(one)} windows")
    add("INSPECT never drops straight to NORMAL",
        not any(a["state"] == INSPECT and b["state"] == NORMAL for a, b in zip(tr, tr[1:])))
    for i, done in run["acks"]:
        if done:
            add(f"acknowledgement before window {i + 1} logged, state not NORMAL",
                any(e["rule"] == ACK_RULE for e in events) and tr[i]["state"] != NORMAL, f"state {tr[i]['state']}")
        else:
            add(f"acknowledgement before window {i + 1}: nothing to acknowledge", True)
    for k in range(1, len(tr)):                               # restoration after a full outage
        if not tr[k - 1]["diagnosis_available"] and tr[k]["fault"] is None and tr[k - 1]["fault"] is not None:
            add(f"diagnosis resumes at window {k + 1} after outage",
                tr[k]["diagnosis_available"] and tr[k]["state"] != SENSOR_FAULT, f"state {tr[k]['state']}")
    for e in scn.expect:                                      # scenario-specific expectations
        seg = [w for w in tr if w["segment"] == e["seg"]]
        if "states" in e:
            add(f"segment {e['seg']}: states within {e['states']}", all(w["state"] in e["states"] for w in seg),
                str(sorted({w['state'] for w in seg})))
        if "reaches" in e:
            add(f"segment {e['seg']}: reaches {e['reaches']}", any(w["state"] == e["reaches"] for w in seg))
        if "diagnosis" in e:
            add(f"segment {e['seg']}: diagnosis available = {e['diagnosis']}",
                all(w["diagnosis_available"] == e["diagnosis"] for w in seg))
        if "zero_weight" in e:
            add(f"segment {e['seg']}: {e['zero_weight']} weight 0",
                all((w["weights"][e["zero_weight"]] or 0.0) == 0.0 for w in seg))
        if "flagged" in e:
            add(f"segment {e['seg']}: {e['flagged']} sensor flagged",
                all(w["status"][e["flagged"]] != "ok" for w in seg))
    return out


def summarize(scn, run, checks):
    tr = run["trace"]
    first = lambda s: next((w["window"] for w in tr if w["state"] == s), None)  # noqa: E731
    segs = []
    for k, s in enumerate(scn.segments):
        ws = [w for w in tr if w["segment"] == k]
        states = {}
        for w in ws:
            states[w["state"]] = states.get(w["state"], 0) + 1
        segs.append({"windows": s.n, "fault": f"{s.fault} on {s.target}" if s.fault else "clean",
                     "ack_before": s.ack_before, "states": states, "end_state": ws[-1]["state"],
                     "diagnosis_coverage": sum(w["diagnosis_available"] for w in ws) / len(ws)})
    return {"name": scn.name, "subsystem": scn.subsystem, "recording": scn.recording, "purpose": scn.purpose,
            "asset": run["asset"], "windows": len(tr), "segments": segs,
            "first_WARNING": first(WARNING), "first_INSPECT": first(INSPECT), "first_SENSOR_FAULT": first(SENSOR_FAULT),
            "final_state": tr[-1]["state"],
            "checks": [{"check": n, "passed": p, "detail": d} for n, p, d in checks],
            "passed": all(p for _, p, _ in checks)}


PIT = "gear_pitting_M_torque_circulation_1000rpm_10Nm.csv"
WEAR = "gear_wear_M_torque_circulation_1000rpm_10Nm.csv"
HEALTHY = "health_torque_circulation_1000rpm_10Nm.csv"


def default_scenarios():
    S, X = Segment, Scenario
    return [
        X("bearing-fault-ack", "bearing", "KI18", [S(12), S(12, ack_before=True)],
          "Inner-race damage: evidence latches INSPECT; operator acknowledges; persistent evidence re-latches",
          [{"seg": 0, "reaches": "INSPECT"}, {"seg": 1, "reaches": "INSPECT"}, {"seg": 1, "states": ["WARNING", "INSPECT"]}]),
        X("bearing-vib-dropout", "bearing", "KI18", [S(8), S(8, "dropout", "vib"), S(8)],
          "Accelerometer dies mid-run: fall back to current, keep diagnosing, recover",
          [{"seg": 1, "diagnosis": True, "zero_weight": "vib", "flagged": "vib"}, {"seg": 2, "diagnosis": True}]),
        X("bearing-cur-stuck", "bearing", "KA22", [S(8), S(8, "stuck", "cur"), S(8)],
          "Current sensor frozen: fall back to vibration",
          [{"seg": 1, "diagnosis": True, "zero_weight": "cur", "flagged": "cur"}]),
        X("bearing-dual-failure-healthy", "bearing", "K004", [S(1), S(8, "dropout", "both"), S(8)],
          "Healthy bearing, both sensors die before any alarm: SENSOR_FAULT, no diagnosis, then recovery",
          [{"seg": 1, "states": ["SENSOR_FAULT"], "diagnosis": False}, {"seg": 2, "diagnosis": True}]),
        X("bearing-dual-failure-latched", "bearing", "KI18", [S(8), S(8, "stuck", "both"), S(8)],
          "Both sensors die while INSPECT is latched: alert kept, diagnosis suspended, then recovery",
          [{"seg": 0, "reaches": "INSPECT"}, {"seg": 1, "states": ["INSPECT"], "diagnosis": False},
           {"seg": 2, "diagnosis": True}]),
        X("bearing-vib-noise", "bearing", "KA22", [S(8), S(8, "noise", "vib", 0), S(8)],
          "Strong noise (0 dB) on the accelerometer: sensor degraded but alive, diagnosis continues",
          [{"seg": 1, "diagnosis": True}]),
        X("bearing-healthy-clean", "bearing", "K004", [S(24)],
          "Healthy held-out bearing, clean sensors (documents the known false-alarm behaviour)"),
        X("gearbox-pitting-clean", "gearbox", PIT, [S(59)], "Gear pitting, clean sensors: WARNING then INSPECT",
          [{"seg": 0, "reaches": "INSPECT", "diagnosis": True}]),
        X("gearbox-motor-dropout", "gearbox", PIT, [S(15), S(15, "dropout", "motor"), S(15)],
          "Motor accelerometer dies mid-run: gearbox sensor carries the diagnosis, then recovery",
          [{"seg": 1, "diagnosis": True, "zero_weight": "motor", "flagged": "motor"}, {"seg": 2, "diagnosis": True}]),
        X("gearbox-gearbox-stuck", "gearbox", PIT, [S(15), S(15, "stuck", "gearbox"), S(15)],
          "Gearbox accelerometer frozen: motor sensor carries the diagnosis",
          [{"seg": 1, "diagnosis": True, "zero_weight": "gearbox", "flagged": "gearbox"}]),
        X("gearbox-dual-failure-healthy", "gearbox", HEALTHY, [S(5), S(20, "dropout", "both"), S(20)],
          "Healthy gearbox, both accelerometers die: SENSOR_FAULT, no diagnosis, then recovery",
          [{"seg": 1, "diagnosis": False}, {"seg": 2, "diagnosis": True}]),
        X("gearbox-dual-failure-latched", "gearbox", PIT, [S(15), S(15, "dropout", "both"), S(15, ack_before=True)],
          "Both die while INSPECT is latched; operator acknowledges after restoration",
          [{"seg": 0, "reaches": "INSPECT"}, {"seg": 1, "states": ["INSPECT"], "diagnosis": False},
           {"seg": 2, "diagnosis": True}]),
        X("gearbox-wear-noise", "gearbox", WEAR, [S(15), S(15, "noise", "gearbox"), S(15)],
          "Gear wear with 0 dB noise on the gearbox accelerometer: degraded sensor down-weighted",
          [{"seg": 1, "diagnosis": True, "flagged": "gearbox"}]),
        X("gearbox-healthy-spikes", "gearbox", HEALTHY, [S(15), S(15, "spikes", "motor"), S(15)],
          "Healthy gearbox with EMI-like spikes on the motor accelerometer",
          [{"seg": 1, "diagnosis": True, "flagged": "motor"}]),
        X("gearbox-healthy-clean", "gearbox", HEALTHY, [S(59)],
          "Healthy held-out gearbox recording, clean sensors (documents false-alarm behaviour)"),
    ]
