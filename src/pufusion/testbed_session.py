"""Interactive, window-by-window replay for the CAD-linked virtual testbed (OB4).

`ReplaySession` drives exactly the same chain as `testbed.run_scenario` - the same frozen models, the same
fault-injection functions and seeds, the same HealthTracker rules and the same HealthStore logging - but one
window per `step()` call, so a user interface can run, pause, single-step and reset a replay and change the
injected sensor fault between windows. Nothing is trained, tuned or hard-coded here: every prediction, quality
score, fusion weight and health state comes from the frozen models and the existing code.

Equivalence with the batch testbed is checked in tests/test_testbed_session.py: for a fault plan expressed as
segments, the session reproduces run_scenario's trace (states, availability, labels, sensor status exactly;
probabilities to 1e-9 - the gearbox model is evaluated one row at a time instead of in one batch).

Recordings are real held-out recordings (Paderborn K004/KA22/KI18; MCC5-THU 1000 rpm / 10 Nm); sensor faults are
synthetic. This is recorded-signal replay with controlled sensor-fault injection, not a physics simulation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import corruption as C
from . import gearbox as G
from . import testbed as T
from .data import load_mat, windows
from .dataset import corrupt_pair
from .health import HealthTracker
from .monitor import SOURCE_BENCHMARK, BenchmarkDiagnoser, MonitorEngine

BEARING_SENSORS = ("vib", "cur")
TARGETS = {"bearing": ("vib", "cur", "both"), "gearbox": ("motor", "gearbox", "both")}
# Fault families offered in the interactive view (all already implemented in corruption.py / sensor_faults.py).
UI_FAULTS = ("noise", "clipping", "stuck", "dropout", "spikes", "intermittent", "gain")
SIGNAL_SAMPLES = 1500            # samples of each channel kept per frame for the waveform plot


@dataclass
class Fault:
    family: str | None = None     # None = clean
    target: str | None = None     # bearing: vib | cur | both ; gearbox: motor | gearbox | both
    severity: object = None       # bearing only; gearbox uses sensor_faults.SCENARIOS

    def active(self):
        return bool(self.family) and bool(self.target)

    def label(self):
        if not self.active():
            return "clean"
        sev = "" if self.severity is None else f" ({self.severity})"
        return f"{self.family}{sev} on {self.target}"


def default_severity(family):
    """Bearing severity used when none is chosen: the one the testbed scenarios use (0 dB noise, etc.)."""
    sevs = C.FAMILIES[family][1]
    if len(sevs) == 1:
        return sevs[0]
    return {"noise": 0, "clipping": 0.2, "spikes": 100, "intermittent": 0.2, "gain": 2.0}.get(family, sevs[0])


class ReplaySession:
    """One replay of one held-out recording, advanced one window at a time.

    ctx: testbed.Context (frozen models + recordings); store: HealthStore that receives every window and event.
    ts_fn(i) gives the timestamp of window i (default: the testbed's fixed clock T0 + i, for reproducibility).
    """

    def __init__(self, ctx: T.Context, subsystem: str, recording: str, store, asset: str, ts_fn=None):
        if subsystem not in TARGETS:
            raise ValueError(subsystem)
        self.ctx, self.subsystem, self.recording, self.store, self.asset = ctx, subsystem, recording, store, asset
        self.ts_fn = ts_fn or (lambda i: T.T0 + i)
        if subsystem == "bearing":
            if recording not in ctx.bearing_recs:
                raise KeyError(f"{recording} is not a held-out bearing recording")
            self._rec = load_mat(ctx.bearing_recs[recording])
            self._wins = list(windows(self._rec))
            self.source = SOURCE_BENCHMARK
            self.label = {0: "healthy", 1: "outer_race", 2: "inner_race"}.get(self._rec.label, str(self._rec.label))
        else:
            if ctx.gearbox is None or recording not in ctx.gearbox_recs:
                raise FileNotFoundError("held-out MCC5-THU recording not available")
            self._wins = ctx.gearbox_windows(recording)
            self.source = T.GB_SOURCE
            self.label = ctx.gearbox_recs[recording].label
        self.reset()

    # ------------------------------------------------------------------ control
    @property
    def windows_per_recording(self):
        return len(self._wins)

    def reset(self):
        """Fresh tracker, fresh fault generator, window counter at 0. The store keeps what was logged; use a new
        asset name for a run that must not continue an earlier history."""
        self.i = 0
        self.frames = []
        self.events = []
        self.acks = []
        self.fault = Fault()
        if self.subsystem == "bearing":
            self.tracker = HealthTracker()
            self._eng = MonitorEngine(BenchmarkDiagnoser(self.ctx.bearing["models"]["gated_both"],
                                                         self.ctx.bearing["assessors"]),
                                      self.source, self.asset, self.store, self.tracker)
        else:
            self.tracker = HealthTracker(fault_advice=G.GEARBOX_ADVICE)
            # one generator per recording, consumed only by corrupted windows - as in run_scenario / gearbox.extract
            self._rng = np.random.default_rng(self.ctx.gearbox["seeds"][self.recording])

    def set_fault(self, family=None, target=None, severity=None):
        """Fault applied from the NEXT window on (None / 'none' = clean)."""
        if family in (None, "none") or target in (None, "none"):
            self.fault = Fault()
            return self.fault
        if target not in TARGETS[self.subsystem]:
            raise ValueError(f"target {target!r} not valid for {self.subsystem}")
        if family not in C.FAMILIES:
            raise ValueError(f"unknown fault family {family!r}")
        if self.subsystem == "bearing" and severity is None:
            severity = default_severity(family)
        if self.subsystem == "gearbox":
            severity = None                   # gearbox faults use the fixed severities of sensor_faults.SCENARIOS
        self.fault = Fault(family, target, severity)
        return self.fault

    def acknowledge(self):
        """Operator acknowledges a latched INSPECT before the next window (logged like the testbed does)."""
        done = T._ack(self.tracker, self.store, self.asset, self.source, self.ts_fn(self.i) - 0.5)
        self.acks.append((self.i, done))
        if done:
            self.events.append({"window": self.i, "from_state": "INSPECT", "to_state": "WARNING",
                                "rule": "acknowledged by operator"})
        return done

    @property
    def state(self):
        return self.tracker.state

    # ------------------------------------------------------------------ one window
    def step(self):
        i, f = self.i, self.fault
        ts = self.ts_fn(i)
        before = self.tracker.state
        if self.subsystem == "bearing":
            frame = self._step_bearing(i, f, ts)
        else:
            frame = self._step_gearbox(i, f, ts)
        frame.update(window=i + 1, ts=ts, fault=f.family if f.active() else None,
                     target=f.target if f.active() else None, fault_label=f.label(),
                     recording_window=i % len(self._wins) + 1, ground_truth=self.label)
        if frame["state"] != before:
            if self.subsystem == "gearbox":       # the bearing MonitorEngine logs its own events
                self.store.log_event(self.asset, self.source, before, frame["state"], frame["rule"],
                                     frame["recommendations"], ts)
            ev = {"window": i + 1, "from_state": before, "to_state": frame["state"], "rule": frame["rule"]}
            self.events.append(ev)
            frame["event"] = ev
        self.frames.append(frame)
        self.i += 1
        return frame

    def run(self, n):
        return [self.step() for _ in range(n)]

    def _step_bearing(self, i, f, ts):
        _, v, c = self._wins[i % len(self._wins)]
        if f.active():
            v, c = corrupt_pair(v, c, f.target, f.family, f.severity, np.random.default_rng(i))
        r = self._eng.step({"vib": v, "cur": c, "fs": self._rec.fs, "condition": self._rec.condition}, ts=ts)
        a, d = r["assessment"], r["diagnosis"]
        rel = d["reliability"]
        ok = a.diagnosis_available
        e = d.get("explanation") if ok else None
        cur = np.asarray(c, float)
        return {
            "state": r["state"], "rule": a.rule, "diagnosis_available": ok,
            "p_fault": r["p_fault"], "fault_type": r["fault_type"],
            "probs": dict(d["probs"]) if ok else None, "confidence": d.get("confidence") if ok else None,
            "status": {s: rel[s].status for s in BEARING_SENSORS},
            "reliability": {s: {"status": rel[s].status, "score": float(rel[s].score), "reasons": list(rel[s].reasons)}
                            for s in BEARING_SENSORS},
            "weights": {"vib": r["w_vib"], "cur": r["w_cur"]},
            "recommendations": list(a.recommendations),
            "explanation": None if not e else {
                "predicted": e["predicted"], "confidence": e["confidence"],
                "vib": [x["feature"] for x in e["vibration_evidence"][:3]],
                "cur": [x["feature"] for x in e["current_evidence"][:3]],
                "gate": [x["feature"] for x in e.get("gate_drivers", [])],
                "drop_vib": e["faithfulness_drop"]["vibration"], "drop_cur": e["faithfulness_drop"]["current"]},
            "signals": {"fs": float(self._rec.fs), "unit": "as recorded",
                        "channels": {"vibration_1": np.asarray(v, float)[:SIGNAL_SAMPLES],
                                     "phase_current_1": (cur[0] if cur.ndim > 1 else cur)[:SIGNAL_SAMPLES],
                                     "phase_current_2": (cur[1] if cur.ndim > 1 else cur)[:SIGNAL_SAMPLES]}},
        }

    def _step_gearbox(self, i, f, ts):
        w = self._wins[i % len(self._wins)]
        if f.active():
            w = G.corrupt(w, f.family, f.target, self._rng)
        x, q = G.features(w)
        row = next(G.replay(self.ctx.gearbox["model"], x[None], q[None], include_details=True, tracker=self.tracker))
        row["ts"] = ts
        self.store.log_window(G.store_record(row, self.asset, self.source, self.recording))
        ok = row["diagnosis_available"]
        return {
            "state": row["state"], "rule": row["rule"], "diagnosis_available": ok,
            "p_fault": row["fault_score"] if ok else None, "fault_type": row["prediction"] if ok else None,
            "probs": row["probs"], "confidence": row["confidence"],
            "status": {s: row["reliability"][s]["status"] for s in G.SENSORS},
            "reliability": {s: {"status": row["reliability"][s]["status"], "score": float(row["reliability"][s]["score"]),
                                "reasons": list(row["reliability"][s]["reasons"])} for s in G.SENSORS},
            "weights": {s: (row[f"{s}_weight"] if ok else None) for s in G.SENSORS},
            "recommendations": list(row["recommendation_list"]),
            "explanation": None,
            "signals": {"fs": float(G.FS), "unit": "g",
                        "channels": {f"{s}_vibration_{a}": np.asarray(w[k, j], float)[:SIGNAL_SAMPLES]
                                     for k, s in enumerate(G.SENSORS) for j, a in enumerate(G.AXES)}},
        }


def trace_row(frame):
    """The subset of a frame that testbed.run_scenario records in its trace (for equivalence checks)."""
    row = {k: frame[k] for k in ("window", "fault", "target", "state", "diagnosis_available", "p_fault",
                                 "fault_type", "rule", "status", "weights")}
    if "segment" in frame:
        row["segment"] = frame["segment"]
    return row


def run_plan(session, scenario):
    """Drive a session with a testbed Scenario's segments (fault per segment, acknowledgements before segments)."""
    for k, seg in enumerate(scenario.segments):
        if seg.ack_before:
            session.acknowledge()
        session.set_fault(seg.fault, seg.target, seg.severity)
        if seg.fault and session.subsystem == "bearing":
            session.fault.severity = seg.severity        # exactly the scenario's severity (may be None)
        for frame in session.run(seg.n):
            frame["segment"] = k
    return session
