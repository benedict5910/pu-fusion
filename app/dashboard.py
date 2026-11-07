"""Presentation entry point. Run with python -m streamlit run app/dashboard.py."""
import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from presentation_replay import (
    BEARING_NAMES, DEFAULT_GEARBOX, GEARBOX_NAMES, bearing_options, bearing_replay,
    gearbox_options, gearbox_replay, system_state,
)
from research import parse_summary
from pufusion.sensor_faults import SCENARIOS

VIEWS = ("Overview", "System Dashboard", "Simulation", "Results")
COMPONENTS = ("Bearing", "Gearbox")
STATE_LABELS = {"NORMAL": "Normal", "WARNING": "Warning", "INSPECT": "Inspect",
                "SENSOR_FAULT": "Sensor fault"}


def label(state):
    return STATE_LABELS.get(state, state)


def run_component(component, family=None, target=None, record=None):
    """Replay into an independent tracker and publish a complete snapshot on success."""
    try:
        if component == "Bearing":
            choices = bearing_options(ROOT)
            record = record or next((p for p in choices if p.stem == "N15_M07_F10_KI18_1"),
                                    choices[0] if choices else None)
            if record is None:
                st.info("Add a held-out Paderborn recording to assess the bearing.")
                return None
            snapshot = bearing_replay(ROOT, record, family, target)
        else:
            choices = gearbox_options(ROOT)
            record = record or next((r for r in choices if r.id == DEFAULT_GEARBOX), next(iter(choices), None))
            if record is None:
                st.info("Add the MCC5-THU pilot recordings under data/mcc5 to assess the gearbox.")
                return None
            snapshot = gearbox_replay(record, choices, family, target)
    except (OSError, ValueError, KeyError) as error:
        st.error(f"{component} replay could not run. {error}")
        return None
    st.session_state.snapshots[component] = snapshot
    return snapshot


def overview():
    st.title("Integrated Vehicle Health Monitoring")
    st.subheader("Bearing and gearbox diagnostics")
    st.write("See how each component is assessed, which sensors the diagnosis relies on, "
             "and when the system asks for an inspection or suspends diagnosis.")
    st.info("Presentation mode uses held-out laboratory recordings. Sensor faults are simulated "
            "only when you run a simulation.")
    st.markdown("**System Dashboard** · Replay both components and inspect the latest assessments.\n\n"
                "**Simulation** · Inject a sensor fault and compare the original and altered signal.\n\n"
                "**Results** · See the verified evaluation for each component.")


def show_component(component, snapshot):
    st.subheader(f"{component} assessment")
    if snapshot is None:
        st.info(f"Run a replay to assess the {component.lower()}.")
        return
    st.caption(f"{snapshot['source']} · {snapshot['scenario']} · {snapshot['recording']}")
    columns = st.columns(3)
    condition = snapshot["condition"]
    confidence = snapshot["confidence"]
    columns[0].metric("Predicted condition", condition.replace("_", " ").capitalize() if condition else "Unavailable")
    columns[1].metric("Model confidence", f"{confidence:.0%}" if confidence is not None else "Unavailable")
    columns[2].metric("Health state", label(snapshot["state"]))
    st.caption("Confidence is the model score for the selected class on the final window.")
    st.markdown("**Sensor reliability**")
    sensors = snapshot["sensors"]
    st.dataframe([
        {"Sensor": sensor, "Status": reading["status"].title(), "Reliability": f"{reading['score']:.0%}",
         "Fusion weight": f"{reading['weight']:.0%}" if reading["weight"] is not None else "—",
         "Observations": ", ".join(reading["reasons"]) or "Within reference range"}
        for sensor, reading in sensors.items()
    ], hide_index=True)
    st.markdown("**Why this assessment?**")
    st.write(snapshot["rule"].capitalize())
    if condition is not None:
        weights = [f"{sensor} {reading['weight']:.0%}" for sensor, reading in sensors.items()
                   if reading["weight"] is not None]
        if weights:
            st.caption("Final-window fusion weights · " + " · ".join(weights))
    for sensor, features in snapshot.get("evidence", {}).items():
        st.caption(f"{sensor} features with the largest model contributions · {', '.join(features)}")
    for recommendation in snapshot["recommendations"]:
        st.write(recommendation)
    if snapshot["signal"] is not None:
        signal = snapshot["signal"]
        st.markdown("**Clean vs corrupted signal**")
        st.caption(f"{signal['name']} ({signal['unit']}) · first 60 ms of the same replay window")
        st.line_chart(pd.DataFrame({"Time (ms)": signal["ms"], "Clean": signal["clean"],
                                    "Corrupted": signal["corrupted"]}), x="Time (ms)")
    st.caption(f"{snapshot['window_count']} replayed windows. The assessment above is for the final window.")


def system_dashboard():
    st.title("System Dashboard")
    st.caption("Latest replay per component. Each assessment comes from its own laboratory recording.")
    if st.button("Run clean system replay", type="primary"):
        with st.spinner("Replaying bearing and gearbox recordings…"):
            for component in COMPONENTS:
                st.session_state.snapshots.pop(component, None)
                run_component(component)
    snapshots = st.session_state.snapshots
    columns = st.columns(3)
    columns[0].metric("Overall system state", label(system_state(snapshots)))
    for column, component in zip(columns[1:], COMPONENTS):
        snap = snapshots.get(component)
        column.metric(f"{component} state", label(snap["state"]) if snap else "Awaiting replay")
        if snap:
            column.caption(snap["scenario"])

    st.subheader("Active warnings")
    warnings = []
    for component, snap in snapshots.items():
        if snap["state"] != "NORMAL":
            warnings.append(f"{component} · {label(snap['state'])} · {snap['rule']}")
        for sensor, reading in snap["sensors"].items():
            if reading["status"] != "ok":
                warnings.append(f"{component} · {sensor} {reading['status']}")
    if warnings:
        for warning in warnings:
            st.warning(warning)
    else:
        st.caption("No active warnings in assessed components." if snapshots else "Awaiting replay.")
    st.subheader("Sensor status")
    rows = []
    for component, names in zip(COMPONENTS, (BEARING_NAMES, GEARBOX_NAMES)):
        sensors = snapshots.get(component, {}).get("sensors", {})
        rows.extend({"Component": component, "Sensor": sensor,
                     "Status": sensors.get(sensor, {}).get("status", "Awaiting replay").capitalize()}
                    for sensor in names.values())
    st.dataframe(rows, hide_index=True)
    component = st.radio("Selected component", COMPONENTS, horizontal=True, key="system_component")
    show_component(component, snapshots.get(component))


def simulation():
    st.title("Simulation")
    st.caption("Inject a reproducible sensor fault into a held-out laboratory recording.")
    component = st.radio("Component", COMPONENTS, horizontal=True, key="simulation_component")
    names = BEARING_NAMES if component == "Bearing" else GEARBOX_NAMES
    try:
        if component == "Bearing":
            options = bearing_options(ROOT)
            default = next((i for i, p in enumerate(options) if p.stem == "N15_M07_F10_KI18_1"), 0)
            format_record = lambda p: p.stem
        else:
            options = list(gearbox_options(ROOT))
            default = next((i for i, r in enumerate(options) if r.id == DEFAULT_GEARBOX), 0)
            format_record = lambda r: r.id
    except (OSError, ValueError) as error:
        st.error(f"Recordings are unavailable. {error}")
        return
    if not options:
        st.info(f"Add the local {component.lower()} recordings to enable simulation.")
        return
    record = st.selectbox("Recording", options, index=default, format_func=format_record, key=f"record_{component}")
    family = st.selectbox("Sensor fault", [None, *SCENARIOS],
                          format_func=lambda value: value.capitalize() if value else "Clean replay")
    target = st.selectbox("Affected sensor", [*names, "both"],
                          format_func=lambda value: names.get(value, "Both sensors")) if family else None
    request = (component, record, family, target)
    if st.button("Run simulation", type="primary"):
        st.session_state.pop("simulation_result", None)
        with st.spinner("Running replay…"):
            snapshot = run_component(component, family, target, record)
        if snapshot:
            st.session_state.simulation_result = (request, snapshot)
    result = st.session_state.get("simulation_result")
    if result and result[0] == request:
        show_component(component, result[1])


def results():
    st.title("Verified Results")
    st.subheader("Bearing · Paderborn")
    path = ROOT / "results" / "starter" / "SUMMARY.txt"
    if path.exists():
        summary = parse_summary(path)["p1"]
        st.caption(f"{summary['runs']} bearing-disjoint runs · mean macro-F1")
        st.dataframe([
            {"Model": name, "Clean": f"{summary['models'][key]['clean'][0]:.3f}",
             "Held-out sensor faults": f"{summary['models'][key]['heldout'][0]:.3f}"}
            for key, name in (("vib_only", "Vibration only"), ("early_fusion", "Early fusion"),
                              ("gated_both", "Gated fusion"))
        ], hide_index=True)
    else:
        st.info("Verified bearing results are unavailable in this checkout.")

    st.subheader("Gearbox · MCC5-THU pilot")
    path = ROOT / "results" / "test_runs" / "mcc5_interim.json"
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
        pooled = report["pooled"]
        recordings = sum(len(fold["test"]) for fold in report["folds"].values())
        st.caption(f"{recordings} recordings · {len(report['folds'])} held-out profiles · pooled window macro-F1")
        st.dataframe([
            {"Replay": name, "Gearbox only": f"{pooled[key]['gearbox']['window']['macro_f1']:.3f}",
             "Early fusion": f"{pooled[key]['early']['window']['macro_f1']:.3f}",
             "Gated fusion": f"{pooled[key]['gated']['window']['macro_f1']:.3f}",
             "Gated diagnosis coverage": f"{pooled[key]['gated']['window']['coverage']:.0%}"}
            for key, name in (("clean", "Clean"), ("dropout@motor", "Motor sensor dropout"),
                              ("dropout@gearbox", "Gearbox sensor dropout"), ("dropout@both", "Dual dropout"))
        ], hide_index=True)
        st.caption("Single-sensor dropout retained diagnosis through the surviving sensor. "
                   "Dual dropout suspended diagnosis. The clean gearbox-only baseline scored highest among the models shown.")
    else:
        st.info("Verified gearbox results are unavailable in this checkout.")


st.set_page_config(page_title="IVHM | System Dashboard", page_icon="🛠️", layout="wide")
if "snapshots" not in st.session_state:
    st.session_state.snapshots = {}
st.sidebar.title("IVHM")
view = st.sidebar.radio("Navigation", VIEWS, index=1, label_visibility="collapsed")
{"Overview": overview, "System Dashboard": system_dashboard, "Simulation": simulation, "Results": results}[view]()
