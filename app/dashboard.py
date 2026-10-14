"""IVHM dashboard (Streamlit).

  pip install streamlit
  streamlit run app/dashboard.py

Modes
  Benchmark replay  - Paderborn recordings of bearings held out from training,
                      Paderborn-trained reliability-gated fusion (validated protocol).
  Rig - live        - ESP32 rig over USB serial, rig-trained healthy-baseline detector.
  Rig - simulated   - the same rig pipeline fed by a SIMULATED rig (no hardware needed).
A model trained on one platform is never applied to the other.
"""
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion import corruption as C  # noqa: E402
from pufusion.config import CLASS_NAMES  # noqa: E402
from pufusion.data import find_mat_files, load_mat, windows  # noqa: E402
from pufusion.dataset import corrupt_pair  # noqa: E402
from pufusion.health import HealthTracker  # noqa: E402
from pufusion.monitor import (SOURCE_BENCHMARK, SOURCE_RIG, SOURCE_SIM, BenchmarkDiagnoser,  # noqa: E402
                              MonitorEngine, RigDiagnoser)
from pufusion.rig import FrameParser, SerialRigSource, SimulatedRigSource, WindowAssembler  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

STATE_COLOR = {"NORMAL": "#1b7f3b", "WARNING": "#b7791f", "INSPECT": "#c53030", "SENSOR_FAULT": "#6b46c1"}
REL_COLOR = {"ok": "#1b7f3b", "degraded": "#b7791f", "failed": "#c53030"}

st.set_page_config(page_title="IVHM bearing monitor", layout="wide")


@st.cache_resource
def load_pickle(path):
    return pickle.load(open(path, "rb"))


@st.cache_resource
def get_store():
    return HealthStore(ROOT / "data" / "health.db")


def component_svg(state, rel):
    """Schematic of the monitored component, coloured by state; not a digital twin."""
    sc = STATE_COLOR.get(state, "#888")
    rv, rc = REL_COLOR[rel["vib"].status], REL_COLOR[rel["cur"].status]
    return f"""<svg viewBox="0 0 420 150" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="12">
<rect x="10" y="45" width="110" height="60" rx="6" fill="#ddd" stroke="#555"/><text x="40" y="80">Motor</text>
<rect x="120" y="70" width="270" height="10" fill="#999"/>
<rect x="250" y="40" width="60" height="70" rx="6" fill="{sc}" opacity=".85" stroke="#333"/>
<text x="255" y="125">Bearing</text><text x="255" y="140" font-weight="bold" fill="{sc}">{state}</text>
<circle cx="280" cy="32" r="8" fill="{rv}"/><text x="292" y="28">vibration sensor</text>
<circle cx="65" cy="120" r="8" fill="{rc}"/><text x="77" y="124">current sensor</text></svg>"""


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Source")
    mode = st.radio("Mode", ["Benchmark replay", "Rig - simulated", "Rig - live"])
    asset = st.text_input("Asset name", "bearing-1")
    n_windows = st.slider("Windows to run", 4, 120, 24)
    pace = st.slider("Seconds per window", 0.0, 1.0, 0.3)
    st.header("Inject sensor fault")
    if mode == "Benchmark replay":
        target = st.radio("Sensor", ["none", "vib", "cur", "both"], horizontal=True)
        fam = st.selectbox("Fault type", list(C.FAMILIES))
        sevs = C.FAMILIES[fam][1]
        sev = st.select_slider("Severity", options=sevs, value=sevs[0]) if len(sevs) > 1 else sevs[0]
    elif mode == "Rig - simulated":
        sim_cond = st.selectbox("Simulated bearing condition", ["healthy", "outer_race", "unbalance"])
        sim_fault = st.selectbox("Simulated sensor fault", ["none", "vib_dropout", "vib_clip", "cur_noise", "frame_loss"])
    else:
        port = st.text_input("Serial port", "COM5")
    run = st.button("Run", type="primary")

store = get_store()
key = f"{mode}|{asset}"
if st.session_state.get("tracker_key") != key:
    st.session_state.tracker, st.session_state.tracker_key = HealthTracker(), key
tracker = st.session_state.tracker

# ------------------------------------------------------------- engine setup
if mode == "Benchmark replay":
    mp = ROOT / "models" / "demo_models.pkl"
    if not mp.exists():
        st.error("models/demo_models.pkl not found - run `python scripts/run_all.py` first."); st.stop()
    bundle = load_pickle(str(mp))
    files = [f for f in find_mat_files(ROOT / "data" / "raw") if f.stem.split("_")[3] in bundle["holdout"]]
    if not files:
        st.error(f"No raw files for held-out bearings {bundle['holdout']}"); st.stop()
    f = st.sidebar.selectbox("Recording (unseen bearing)", files, format_func=lambda p: p.stem)
    engine = MonitorEngine(BenchmarkDiagnoser(bundle["models"]["gated_both"], bundle["assessors"]),
                           SOURCE_BENCHMARK, asset, store, tracker)
    rec = load_mat(f)
    truth = CLASS_NAMES[rec.label]

    def stream():
        for i, v, c in list(windows(rec))[:n_windows]:
            if target != "none":
                v, c = corrupt_pair(v, c, target, fam, sev, np.random.default_rng(i))
            yield {"vib": v, "cur": c, "fs": rec.fs, "condition": rec.condition}
else:
    mp = ROOT / "models" / "rig_models.pkl"
    if not mp.exists():
        st.error("models/rig_models.pkl not found - record sessions and run `python scripts/rig_train.py`."); st.stop()
    bundle = load_pickle(str(mp))
    cfg = bundle["config"]
    engine = MonitorEngine(RigDiagnoser(bundle["detector"], bundle["assessors"], cfg),
                           SOURCE_SIM if mode == "Rig - simulated" else SOURCE_RIG, asset, store, tracker)
    truth = sim_cond if mode == "Rig - simulated" else None

    def stream():
        if mode == "Rig - simulated":
            src = SimulatedRigSource(cfg, sim_cond, seed=int(time.time()))
            src.sensor_fault = None if sim_fault == "none" else sim_fault
        else:
            src = SerialRigSource(port)
        parser, asm, sent = FrameParser(), WindowAssembler(cfg), 0
        while sent < n_windows:
            for fr in parser.feed(src.read()):
                for w in asm.push(fr):
                    sent += 1
                    yield w

# ------------------------------------------------------------------ layout
st.title("Bearing health monitor - IVHM prototype")
banner = {"Benchmark replay": "Validated benchmark mode: Paderborn bearing never seen in training.",
          "Rig - simulated": "SIMULATED rig - demonstration of the pipeline, not measured data.",
          "Rig - live": "Live rig - healthy-baseline detector trained on this rig only."}[mode]
st.info(banner + (f" Ground truth: **{truth}**." if truth else ""))
tab_live, tab_hist = st.tabs(["Live", "History & reports"])

with tab_live:
    state_box = st.empty()
    c1, c2, c3 = st.columns([3, 2, 2])
    sig_box, rel_box, diag_box = c1.empty(), c2.empty(), c3.empty()
    c4, c5 = st.columns([2, 3])
    comp_box, rec_box = c4.empty(), c5.empty()
    expl_box = st.empty()
    if st.button("Acknowledge INSPECT (after inspection)"):
        tracker.acknowledge()
        st.success("Acknowledged - state reset to NORMAL.")

    if run:
        for win in stream():
            out = engine.step(win)
            a, d = out["assessment"], out["diagnosis"]
            col = STATE_COLOR.get(a.state, "#888")
            state_box.markdown(f"<div style='padding:.6rem 1rem;border-radius:6px;background:{col};color:white'>"
                               f"<b>{a.state}</b> - {a.rule}</div>", unsafe_allow_html=True)
            cur = np.asarray(win["cur"])
            sig_box.line_chart({"vibration": np.asarray(win["vib"])[:1500],
                                "current": (cur[0] if cur.ndim > 1 else cur)[:1500]})
            rel_box.markdown("**Sensor reliability**\n\n" + "\n\n".join(
                f"- {s}: **{r.status}** ({r.score:.2f}) {', '.join(r.reasons)}" for s, r in d["reliability"].items()))
            if "probs" in d:
                txt = "**AI diagnosis**\n\n" + "\n".join(f"- {k}: {v:.2f}" for k, v in d["probs"].items())
                if d.get("weights"):
                    txt += f"\n\nSensor weights: vib {d['weights']['vib']:.2f} / cur {d['weights']['cur']:.2f}"
            else:
                pf = d["p_fault"]
                txt = ("**Anomaly evidence** (0.5 = alarm threshold)\n\n"
                       f"- combined: {'n/a' if pf is None else f'{pf:.2f}'}\n" +
                       "\n".join(f"- {s}: {v:.2f}" for s, v in d["sensor_evidence"].items()))
            diag_box.markdown(txt)
            comp_box.markdown(component_svg(a.state, d["reliability"]), unsafe_allow_html=True)
            rec_box.markdown("**Recommendations**\n\n" + ("\n".join(f"- {r}" for r in a.recommendations) or "- none"))
            e = d.get("explanation")
            if e:
                expl_box.markdown(
                    f"**Why** - predicted *{e['predicted']}* (confidence {e['confidence']:.2f}). "
                    f"Top vibration evidence: {', '.join(x['feature'] for x in e['vibration_evidence'][:3])}. "
                    f"Top current evidence: {', '.join(x['feature'] for x in e['current_evidence'][:3])}. "
                    f"Gate drivers: {', '.join(x['feature'] for x in e.get('gate_drivers', []))}. "
                    f"Explanation faithfulness (prob. drop when top features removed): "
                    f"vib {e['faithfulness_drop']['vibration']:.2f}, cur {e['faithfulness_drop']['current']:.2f}.")
            time.sleep(pace)

with tab_hist:
    hist = store.history(asset, limit=2000)
    if hist:
        st.line_chart({"fault evidence": [h["p_fault"] if h["p_fault"] is not None else np.nan for h in hist],
                       "vib reliability": [h["rel_vib"] for h in hist],
                       "cur reliability": [h["rel_cur"] for h in hist]})
        st.dataframe([{k: e[k] for k in ("ts", "source", "from_state", "to_state", "rule")} for e in store.events(asset)])
        rp = ROOT / "data" / f"report_{asset}.html"
        cp = ROOT / "data" / f"history_{asset}.csv"
        store.export_html(rp, asset); store.export_csv(cp, asset)
        st.download_button("Download HTML report", rp.read_bytes(), rp.name, "text/html")
        st.download_button("Download CSV history", cp.read_bytes(), cp.name, "text/csv")
    else:
        st.write("No history yet for this asset.")
