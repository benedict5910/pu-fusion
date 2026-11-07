"""MCC5-THU v2 pilot using motor and gearbox vibration as separate sensors."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import generic_features, quality_indicators
from .health import HealthTracker
from .reliability import ReliabilityAssessor, SensorReliability
from .sensor_faults import inject

FS = 12_800
SENSORS = ("motor", "gearbox")
AXES = ("x", "y", "z")
CLASSES = ("gear_pitting", "gear_wear", "healthy")
PILOT_NAME = re.compile(
    r"(health|gear_pitting_M|gear_wear_M)_"
    r"(speed_circulation_\d+Nm-\d+rpm|torque_circulation_\d+rpm_\d+Nm)\.csv(?:\.gz)?"
)
GEARBOX_ADVICE = {
    None: "inspect the gearbox, mounting and lubrication",
    "gear_pitting": "inspect the gearbox tooth surfaces for pitting and check lubrication",
    "gear_wear": "inspect the gearbox tooth surfaces for wear and check lubrication",
}


@dataclass(frozen=True)
class Recording:
    path: Path
    label: str
    condition: str

    @property
    def id(self):
        return self.path.name.removesuffix(".gz")


def discover(root):
    recordings = []
    seen = set()
    for path in sorted(Path(root).glob("*.csv*")):
        match = PILOT_NAME.fullmatch(path.name)
        if not match:
            continue
        label, condition = match.groups()
        label = "healthy" if label == "health" else label.removesuffix("_M")
        record = Recording(path, label, condition)
        if record.id in seen:
            raise ValueError(f"Duplicate recording: {record.id}")
        seen.add(record.id)
        recordings.append(record)
    return recordings


def condition_split(recordings, condition):
    train = [r for r in recordings if r.condition != condition]
    test = [r for r in recordings if r.condition == condition]
    if any({r.label for r in split} != set(CLASSES) for split in (train, test)):
        raise ValueError(f"Each side of the {condition} split must contain every pilot class")
    return train, test


def windows(record):
    """Read the published vibration columns as complete one-second windows."""
    cols = [f"{sensor}_vibration_{axis}" for sensor in SENSORS for axis in AXES]
    with pd.read_csv(record.path, usecols=cols, dtype=np.float32, chunksize=FS) as chunks:
        for frame in chunks:
            values = frame[cols].to_numpy().T
            if not np.isfinite(values).all():
                raise ValueError(f"Non-finite sample in {record.id}")
            if len(frame) == FS:
                yield values.reshape(len(SENSORS), len(AXES), FS)


def features(window):
    return (
        np.array([np.concatenate([generic_features(axis, FS) for axis in sensor]) for sensor in window]),
        np.array([[quality_indicators(axis, FS) for axis in sensor] for sensor in window]),
    )


def corrupt(window, family, target, rng):
    result = window.copy()
    for sensor in SENSORS if target == "both" else (target,):
        axes = result[SENSORS.index(sensor)]
        for index, signal in enumerate(axes):
            axes[index] = inject(signal, family, rng, FS)
    return result


def _classifier():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1500))


class GearboxModel:
    def fit(self, x, q, y):
        self.experts = [_classifier().fit(x[:, i], y) for i in range(len(SENSORS))]
        self.early = _classifier().fit(x.reshape(len(x), -1), y)
        self.assessors = [
            [ReliabilityAssessor().fit(q[:, i, j]) for j in range(len(AXES))]
            for i in range(len(SENSORS))
        ]
        self.classes = self.early.classes_
        return self

    def reliability(self, quality):
        result = {}
        for sensor, assessors, axes in zip(SENSORS, self.assessors, quality):
            readings = [assessor.assess(axis) for assessor, axis in zip(assessors, axes)]
            worst = min(readings, key=lambda reading: reading.score)
            reasons = [f"{axis}: {reason}" for axis, reading in zip(AXES, readings) for reason in reading.reasons]
            result[sensor] = SensorReliability(worst.score, worst.status, reasons)
        return result

    def predict(self, x, q, min_reliability=0.5):
        expert = np.stack([model.predict_proba(x[:, i]) for i, model in enumerate(self.experts)], axis=1)
        reliability = [self.reliability(window) for window in q]
        weights = np.array([
            [r.score if r.status != "failed" and r.score >= min_reliability else 0.0 for r in row.values()]
            for row in reliability
        ])
        totals = weights.sum(axis=1, keepdims=True)
        np.divide(weights, totals, out=weights, where=totals > 0)
        gated = (expert * weights[..., None]).sum(axis=1)
        gated[totals[:, 0] == 0] = np.nan
        return {
            "motor": expert[:, 0], "gearbox": expert[:, 1],
            "early": self.early.predict_proba(x.reshape(len(x), -1)),
            "late_average": expert.mean(axis=1), "gated": gated,
        }, reliability, weights


def replay(model, x, q, *, include_details=False):
    tracker = HealthTracker(fault_advice=GEARBOX_ADVICE)
    probabilities, reliability, weights = model.predict(x, q, tracker.p.min_reliability)
    healthy = list(model.classes).index("healthy")
    for index, (probs, rel, weight) in enumerate(zip(probabilities["gated"], reliability, weights), 1):
        available = np.isfinite(probs).all()
        label = model.classes[np.argmax(probs)] if available else None
        evidence = float(1 - probs[healthy]) if available else None
        assessment = tracker.update(evidence, label, rel)
        row = {
            "window": index, "state": assessment.state,
            "prediction": label, "fault_score": evidence,
            **{f"{s}_status": rel[s].status for s in SENSORS},
            **{f"{s}_weight": float(w) for s, w in zip(SENSORS, weight)},
            "rule": assessment.rule, "recommendations": " ".join(assessment.recommendations),
        }
        if include_details:
            row["confidence"] = float(probs.max()) if available else None
            row["reliability"] = {sensor: reading.as_dict() for sensor, reading in rel.items()}
        yield row


def extract(record, family=None, target=None, seed=42):
    rng = np.random.default_rng(seed)
    rows = [
        features(corrupt(w, family, target, rng) if family else w)
        for w in windows(record)
    ]
    if not rows:
        raise ValueError(f"No complete one-second window in {record.id}")
    x, q = zip(*rows)
    return np.stack(x), np.stack(q)


def fit_records(recordings, clean):
    return GearboxModel().fit(
        np.concatenate([clean[r.id][0] for r in recordings]),
        np.concatenate([clean[r.id][1] for r in recordings]),
        np.concatenate([np.repeat(r.label, len(clean[r.id][0])) for r in recordings]),
    )
