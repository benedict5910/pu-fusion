"""Health assessment and maintenance decision support.

Turns per-window fault evidence plus sensor reliability into an operational
state with a transparent rule and an evidence-based recommendation.

States
  NORMAL      no persistent fault evidence
  WARNING     fault evidence in >= warn_k of the last n windows
  INSPECT     strong evidence in >= inspect_k of the last n windows (latched
              until an operator acknowledges it, as in maintenance practice)
  SENSOR_FAULT no sensor is reliable enough to diagnose; diagnosis suspended

There is deliberately no remaining-useful-life estimate: the data contain
discrete damage states, not degradation trajectories.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

NORMAL, WARNING, INSPECT, SENSOR_FAULT = "NORMAL", "WARNING", "INSPECT", "SENSOR_FAULT"
SEVERITY = {NORMAL: 0, WARNING: 1, INSPECT: 2, SENSOR_FAULT: 1}

_FAULT_ADVICE = {
    "outer_race": "evidence matches outer-race damage: inspect the bearing outer ring and housing fit, check lubrication",
    "inner_race": "evidence matches inner-race damage: inspect the inner ring and shaft fit, check lubrication",
    None: "condition deviates from the healthy baseline: inspect bearing, coupling alignment and mounting",
}
_SENSOR_ADVICE = {
    "vib": "check the accelerometer mounting and cable",
    "cur": "check the current sensor wiring and supply",
}
_SENSOR_LABEL = {"vib": "Vibration", "cur": "Current"}


@dataclass
class HealthPolicy:
    warn_p: float = 0.5
    inspect_p: float = 0.8
    n: int = 6               # look-back windows
    warn_k: int = 2
    inspect_k: int = 4
    recover_n: int = 6       # consecutive quiet windows to clear WARNING
    min_reliability: float = 0.5


@dataclass
class Assessment:
    state: str
    rule: str
    recommendations: list[str] = field(default_factory=list)
    diagnosis_available: bool = True
    degraded_sensors: list[str] = field(default_factory=list)

    def as_dict(self):
        return dict(self.__dict__)


class HealthTracker:
    def __init__(self, policy: HealthPolicy | None = None):
        self.p = policy or HealthPolicy()
        self.hist = deque(maxlen=self.p.n)
        self.state = NORMAL
        self.quiet = 0

    def acknowledge(self):
        """Operator acknowledges an INSPECT state (e.g. after inspection)."""
        self.state, self.quiet = NORMAL, 0
        self.hist.clear()

    def update(self, p_fault: float | None, fault_type: str | None, reliability: dict) -> Assessment:
        p = self.p
        usable = [s for s, r in reliability.items() if r.status != "failed" and r.score >= p.min_reliability]
        degraded = [s for s, r in reliability.items() if r.status != "ok"]
        recs = []
        for s in degraded:
            r = reliability[s]
            recs.append(f"{_SENSOR_LABEL.get(s, s)} sensor {r.status} ({', '.join(r.reasons)}): {_SENSOR_ADVICE.get(s, 'check the sensor')}.")

        if not usable or p_fault is None:
            if self.state != INSPECT:            # never silently clear a latched INSPECT
                self.state = SENSOR_FAULT
            recs.insert(0, "No reliable sensor data: fault diagnosis suspended until a sensor is restored.")
            return Assessment(self.state, "no usable sensor", recs, False, degraded)

        self.hist.append(p_fault)
        n_warn = sum(x > p.warn_p for x in self.hist)
        n_insp = sum(x > p.inspect_p for x in self.hist)
        self.quiet = self.quiet + 1 if p_fault <= p.warn_p else 0

        if self.state == INSPECT:
            rule = "INSPECT latched until acknowledged"
        elif n_insp >= p.inspect_k:
            self.state, rule = INSPECT, f"fault evidence > {p.inspect_p} in {n_insp}/{len(self.hist)} recent windows"
        elif n_warn >= p.warn_k:
            self.state, rule = WARNING, f"fault evidence > {p.warn_p} in {n_warn}/{len(self.hist)} recent windows"
        elif self.state == WARNING and self.quiet < p.recover_n:
            rule = f"WARNING held: {self.quiet}/{p.recover_n} quiet windows"
        else:
            self.state, rule = NORMAL, "no persistent fault evidence"

        if self.state == INSPECT:
            recs.insert(0, f"Schedule an inspection - {_FAULT_ADVICE.get(fault_type, _FAULT_ADVICE[None])}.")
        elif self.state == WARNING:
            recs.insert(0, "Increase monitoring and watch the trend; no action yet unless the warning persists.")
        if len(usable) < len(reliability):
            recs.append(f"Diagnosis currently relies on: {', '.join(_SENSOR_LABEL.get(s, s) for s in usable)} only (reduced redundancy).")
        return Assessment(self.state, rule, recs, True, degraded)
