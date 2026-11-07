"""Presentation replay adapters for the existing component pipelines."""
import pickle

import numpy as np
import streamlit as st

from pufusion import gearbox
from pufusion.data import load_mat, windows
from pufusion.dataset import corrupt_pair
from pufusion.monitor import BenchmarkDiagnoser, MonitorEngine, SOURCE_BENCHMARK
from pufusion.sensor_faults import SCENARIOS

BEARING_NAMES = {"vib": "Vibration", "cur": "Motor current"}
GEARBOX_NAMES = {"motor": "Motor vibration", "gearbox": "Gearbox vibration"}
DEFAULT_GEARBOX = "gear_pitting_M_torque_circulation_1000rpm_10Nm.csv"


@st.cache_resource
def bearing_bundle(path):
    with path.open("rb") as file:
        return pickle.load(file)


def bearing_options(root):
    bundle = bearing_bundle(root / "models" / "demo_models.pkl")
    return sorted(path for path in (root / "data" / "raw").glob("*/*.mat")
                  if path.parent.name in bundle["holdout"])


def gearbox_options(root):
    records = gearbox.discover(root / "data" / "mcc5")
    choices = {}
    for condition in sorted({record.condition for record in records}):
        try:
            train, test = gearbox.condition_split(records, condition)
        except ValueError:
            continue
        for record in test:
            choices[record] = tuple(train)
    return choices


@st.cache_resource(max_entries=4, show_spinner=False)
def train_gearbox(records, fingerprints):
    return gearbox.fit_records(records, {record.id: gearbox.extract(record) for record in records})


def preview(clean, changed, fs, name, unit):
    # Keep a short segment at full sampling resolution so clipping and spikes stay visible.
    end = min(len(clean), int(0.06 * fs))
    return {"name": name, "unit": unit, "ms": np.arange(end) * 1000 / fs,
            "clean": clean[:end].copy(), "corrupted": changed[:end].copy()}


def bearing_replay(root, path, family=None, target=None):
    bundle = bearing_bundle(root / "models" / "demo_models.pkl")
    record = load_mat(path)
    if record.bearing not in bundle["holdout"]:
        raise ValueError("Choose a held-out bearing recording.")
    engine = MonitorEngine(BenchmarkDiagnoser(bundle["models"]["gated_both"], bundle["assessors"]),
                           SOURCE_BENCHMARK)
    signal = None
    window_count = 0
    for index, vib, cur in windows(record):
        clean = (vib, cur)
        if family:
            vib, cur = corrupt_pair(vib, cur, target, family, SCENARIOS[family], np.random.default_rng(index))
        output = engine.step({"vib": vib, "cur": cur, "fs": record.fs, "condition": record.condition})
        window_count += 1
        if family and index == 0:
            if target == "cur":
                signal = preview(clean[1][0], cur[0], record.fs, "Motor current, phase 1", "A")
            else:
                signal = preview(clean[0], vib, record.fs, "Vibration", "g")
    if not window_count:
        raise ValueError("The bearing recording contains no complete windows.")
    assessment, diagnosis = output["assessment"], output["diagnosis"]
    probs = diagnosis["probs"] if assessment.diagnosis_available else {}
    evidence = {}
    explanation = output["explanation"] or {}
    for sensor, name in (("vibration", BEARING_NAMES["vib"]), ("current", BEARING_NAMES["cur"])):
        features = explanation.get(f"{sensor}_evidence", [])
        if explanation.get("sensor_weights", {}).get(sensor, 0) > 0 and features:
            evidence[name] = [item["feature"].replace("_", " ") for item in features[:2]]
    return {
        "evidence": evidence,
        "source": "Paderborn held-out replay", "recording": record.stem,
        "state": assessment.state, "condition": max(probs, key=probs.get) if probs else None,
        "confidence": output["confidence"], "rule": assessment.rule, "window_count": window_count,
        "sensors": {BEARING_NAMES[s]: {**reading.as_dict(), "weight": diagnosis.get("weights", {}).get(s)}
                    for s, reading in diagnosis["reliability"].items()},
        "recommendations": assessment.recommendations, "signal": signal,
        "scenario": scenario(family, target, BEARING_NAMES),
    }


def gearbox_replay(record, choices, family=None, target=None):
    train = choices[record]
    stats = (entry.path.stat() for entry in train)
    model = train_gearbox(train, tuple((s.st_size, s.st_mtime_ns) for s in stats))
    seed = 42 + gearbox.discover(record.path.parent).index(record)
    x, q = gearbox.extract(record, family, target, seed=seed)
    trace = list(gearbox.replay(model, x, q, include_details=True))
    final = trace[-1]
    signal = None
    if family:
        recording_windows = gearbox.windows(record)
        try:
            clean = next(recording_windows)
        finally:
            recording_windows.close()
        changed = gearbox.corrupt(clean, family, target, np.random.default_rng(seed))
        sensor = "gearbox" if target == "both" else target
        index = gearbox.SENSORS.index(sensor)
        signal = preview(clean[index, 2], changed[index, 2], gearbox.FS, f"{GEARBOX_NAMES[sensor]}, Z axis", "g")
    return {
        "source": "MCC5-THU held-out profile replay", "recording": record.id,
        "state": final["state"], "condition": final["prediction"], "confidence": final["confidence"],
        "rule": final["rule"], "window_count": len(trace),
        "sensors": {GEARBOX_NAMES[s]: {**reading, "weight": final[f"{s}_weight"]}
                    for s, reading in final["reliability"].items()},
        "recommendations": [final["recommendations"]] if final["recommendations"] else [],
        "signal": signal, "scenario": scenario(family, target, GEARBOX_NAMES),
    }


def scenario(family, target, names):
    return f"{family.title()} · {names.get(target, 'Both sensors')}" if family else "Clean replay"


def system_state(snapshots):
    states = {snap["state"] for snap in snapshots.values()}
    for state in ("INSPECT", "SENSOR_FAULT", "WARNING"):
        if state in states:
            return state
    return "NORMAL" if len(snapshots) == 2 and states == {"NORMAL"} else "Awaiting replay"
