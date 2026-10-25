"""IVHM bearing health monitor (Streamlit).

    streamlit run app/dashboard.py          (Windows: scripts/windows/run_dashboard.bat)

Views
  Overview          project status, data-source legend, headline results, current state
  Live Diagnostics  monitoring engine on a selected source, with a guided professor demo
  Research Lab      frozen preliminary OB1/OB2 results, confusion matrices, limitations
  History & Reports SQLite history per asset, event audit trail, CSV/HTML export

Sources (always labelled)
  Benchmark replay  Paderborn recordings of bearings HELD OUT from training, replayed through the
                    Paderborn-trained reliability-gated fusion model (models/demo_models.pkl).
  Rig - simulated   the rig pipeline fed by SYNTHETIC signals (models/rig_models_simulated.pkl).
  Rig - live        the physical ESP32 rig (models/rig_models.pkl, trained on real rig sessions only).
                    The rig is at design stage; this mode reports "not connected" until it exists.
A model trained on one platform is never applied to the other. The dashboard computes no result of
its own: diagnoses come from the frozen models, research numbers from results/starter.
"""
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(APP))
import research as R  # noqa: E402
import ui  # noqa: E402
from pufusion import corruption as C  # noqa: E402
from pufusion.config import CLASS_NAMES  # noqa: E402
from pufusion.data import find_mat_files, load_mat, windows  # noqa: E402
from pufusion.dataset import corrupt_pair  # noqa: E402
from pufusion.health import HealthTracker  # noqa: E402
from pufusion.monitor import (SOURCE_BENCHMARK, SOURCE_RIG, SOURCE_SIM, BenchmarkDiagnoser,  # noqa: E402
                              MonitorEngine, RigDiagnoser)
from pufusion.rig import FrameParser, SerialRigSource, SimulatedRigSource, WindowAssembler  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

# Full-width widgets: `width="stretch"` on current Streamlit, `use_container_width` on older releases.
try:
    _ST_VER = tuple(int(x) for x in st.__version__.split(".")[:2])
except Exception:  # noqa: BLE001 - test stand-ins have no version
    _ST_VER = (0, 0)
FULL = {"width": "stretch"} if _ST_VER >= (1, 50) else {"use_container_width": True}

RESULTS = ROOT / "results" / "starter"
# Cloud deployment (Streamlit Community Cloud mounts the repo under /mount/src): every browser session gets
# its own temporary SQLite log and report folder, so viewers never see each other's runs, and no hardware
# can be attached. Locally (single operator) the shared data/health.db is kept.
CLOUD = os.environ.get("IVHM_CLOUD", "1" if str(ROOT).startswith("/mount/src") else "0") == "1"
if CLOUD and hasattr(time, "tzset"):                 # cloud servers run on UTC; show the team's local time
    os.environ["TZ"] = os.environ.get("IVHM_TZ", "Asia/Kolkata")
    time.tzset()
VIEWS = ["Overview", "Live Diagnostics", "Research Lab", "History & Reports"]
MODES = ["Benchmark replay", "Rig - simulated", "Rig - live"]
MODEL_FILES = {"Benchmark replay": ROOT / "models" / "demo_models.pkl",
               "Rig - simulated": ROOT / "models" / "rig_models_simulated.pkl",
               "Rig - live": ROOT / "models" / "rig_models.pkl"}

st.set_page_config(page_title="IVHM Bearing Health Monitor", page_icon="🛠️", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ cached resources
@st.cache_resource
def load_pickle(path):
    with open(path, "rb") as f:
        return pickle.load(f)


@st.cache_resource
def _shared_store():
    return HealthStore(os.environ.get("IVHM_DB", str(ROOT / "data" / "health.db")))


def get_store():
    """Local: one shared log. Cloud: one temporary log per browser session (isolated, not persistent)."""
    if not CLOUD:
        return _shared_store()
    if "_store" not in st.session_state:
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="ivhm_session_"))
        st.session_state["_store_dir"] = str(d)
        st.session_state["_store"] = HealthStore(d / "health.db")
    return st.session_state["_store"]


def export_dir() -> Path:
    if CLOUD:
        get_store()
        return Path(st.session_state["_store_dir"])
    return ROOT / "data"


@st.cache_data
def load_research():
    return {"summary": R.parse_summary(RESULTS / "SUMMARY.txt"), "headline": R.headline(RESULTS),
            "quality": R.quality_table(RESULTS / "quality.json"),
            "far": R.far_audit(RESULTS / "audit" / "far_audit.json")}


@st.cache_data
def recordings():
    return {f.stem: str(f) for f in find_mat_files(ROOT / "data" / "raw")}


@st.cache_resource
def load_recording(path):
    return load_mat(Path(path))


def html(s):
    st.markdown(s, unsafe_allow_html=True)


store = get_store()
ss = st.session_state
# Streamlit drops a widget's state when the widget is not rendered (e.g. another view is open);
# re-assigning keeps the operator's selections across views.
for _k in ("view", "mode", "asset", "nwin", "pace", "target", "fam", "sev", "sim_cond", "sim_fault", "port", "rec",
           "hist_asset"):
    if _k in ss:
        ss[_k] = ss[_k]
for k, v in dict(view="Overview", mode="Benchmark replay", asset="bearing-1", nwin=8, pace=0.4,
                 target="none", fam="noise", demo_on=False, demo_idx=None, last=None, port="COM5").items():
    ss.setdefault(k, v)


# ------------------------------------------------------------------ demo control
def demo_asset(step):
    return f"demo-{step['asset']}-{ss.demo_suffix}"


def start_demo():
    ss.demo_on, ss.demo_idx, ss.demo_suffix = True, None, time.strftime("%H%M")
    ss.view = "Live Diagnostics"


DEFAULT_ASSET = {"Benchmark replay": "bearing-1", "Rig - simulated": "sim-rig-1", "Rig - live": "rig-1"}


def stop_demo():
    ss.demo_on, ss.demo_idx = False, None
    if str(ss.get("asset", "")).startswith("demo-"):
        ss.asset = DEFAULT_ASSET[ss.mode]


def on_mode_change():
    """A new data source gets its own asset name, so benchmark, simulated and live logs never mix."""
    ss.asset = DEFAULT_ASSET[ss.mode]


def apply_step(i):
    s = ui.DEMO_STEPS[i]
    ss.demo_idx = i
    if s["action"] == "view":
        ss.view = s["view"]
        if s["view"] == "History & Reports":
            ss.hist_asset = demo_asset(ui.DEMO_STEPS[0])
        return
    ss.view, ss.mode, ss.asset = "Live Diagnostics", "Benchmark replay", demo_asset(s)
    ss.rec = s["rec"]
    if s["action"] == "run":
        ss.target, ss.fam, ss.nwin = s["target"], s["fam"], s["n"]
        ss.pending_run = True
    elif s["action"] == "ack":
        ss.pending_ack = True


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    html("<div style='font-size:1.15rem;font-weight:800;letter-spacing:.02em'>IVHM <span style='color:#22d3ee'>"
         "Bearing Health</span></div><div style='color:#94a3b8;font-size:.8rem;margin-bottom:.8rem'>"
         "Robust multisensor fusion &amp; fault diagnosis</div>")
    st.radio("View", VIEWS, key="view")
    st.divider()
    if not ss.demo_on:
        st.button("▶ Start professor demo", on_click=start_demo, **FULL, type="primary")
    else:
        st.button("■ End demo", on_click=stop_demo, **FULL)
    st.caption("Data sources are labelled on every view: BENCHMARK (real Paderborn recordings, held out), "
               "SIMULATED (synthetic), LIVE RIG (not connected), RESULTS (frozen).")
    if CLOUD:
        st.caption("Cloud demo: your runs, history and reports exist only in this browser session and are "
                   "cleared when it ends. Other viewers cannot see them.")
    st.caption("Benchmark recordings: Paderborn University KAt-DataCenter (Lessmeier et al., 2016), "
               "CC BY-NC 4.0, non-commercial academic use.")


def demo_bar():
    """Guided professor demo: one step at a time, always visible at the top of the current view."""
    steps, idx = ui.DEMO_STEPS, ss.demo_idx
    nxt = 0 if idx is None else idx + 1
    cur = steps[idx] if idx is not None else None
    if cur:
        body = (f"<div class='ttl'>Step {idx + 1} - {ui.esc(cur['title'])}</div>"
                f"<div class='say'>Say: {ui.esc(cur['say'])}</div>"
                f"<div class='exp'>Look for: {ui.esc(cur['expect'])}</div>")
    else:
        body = ("<div class='ttl'>Professor demo ready</div><div class='say'>Eight steps, each replaying a real "
                "held-out Paderborn recording (K004, KA22, KI18 - never used in training) or opening a view. "
                "Press the button below to run step 1.</div>")
    html(f"<div class='ivhm-demo'><div class='hd'><span style='color:#94a3b8;font-size:.75rem;letter-spacing:.1em;"
         f"font-weight:700'>PROFESSOR DEMO</span><span>{ui.demo_header(idx, len(steps))}</span></div>{body}</div>")
    b = st.columns([2.6, 1.1, 1])
    if nxt < len(steps):
        b[0].button(f"▶ Step {nxt + 1}: {steps[nxt]['title']}", key="demo_next", type="primary",
                    on_click=apply_step, args=(nxt,), **FULL)
    else:
        b[0].button("✓ Demo complete - end demo", key="demo_done", type="primary", on_click=stop_demo, **FULL)
    can_repeat = idx is not None and steps[idx]["action"] == "run"
    b[1].button(f"↺ Repeat {idx + 1}" if can_repeat else "↺ Repeat", key="demo_repeat", on_click=apply_step,
                args=(idx if can_repeat else 0,), disabled=not can_repeat, **FULL)
    b[2].button("■ End demo", key="demo_end", on_click=stop_demo, **FULL)
    with st.expander("Full demo script (all 8 steps)"):
        for i, s_ in enumerate(steps):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"<div class='ivhm-step{' on' if idx == i else ''}'><span class='n'>{i + 1}</span>"
                        f"<b>{ui.esc(s_['title'])}</b><div class='ivhm-sub'>{ui.esc(s_['say'])}</div>"
                        f"<div class='ivhm-sub' style='color:#22d3ee'>Look for: {ui.esc(s_['expect'])}</div></div>",
                        unsafe_allow_html=True)
            c2.button("Go", key=f"demo_btn_{i}", on_click=apply_step, args=(i,), **FULL)


def header(subtitle, kind=None, extra=""):
    right = ui.badge(ui.SOURCES[kind]["tag"], ui.SOURCES[kind]["color"]) if kind else ""
    html(ui.hero("IVHM <span>Bearing Health Monitor</span>", subtitle, right))
    if ss.demo_on:
        demo_bar()
    if kind:
        html(ui.source_banner(kind, extra))


# ======================================================================== OVERVIEW
def view_overview():
    header("AI-driven integrated vehicle health monitoring - robust multisensor fusion and fault diagnosis")
    h = load_research()["headline"]
    obj = [("OB1 Diagnosis", "Experimentally evaluated", "#3b82f6",
            f"P1 bearing-disjoint, {h['runs']} runs on the 12-bearing starter subset (preliminary)."),
           ("OB2 Sensor quality", "Experimentally evaluated", "#3b82f6",
            "Label-free reliability assessment; strong on dropout/stuck/clipping, weak on vibration noise."),
           ("OB3 Health layer", "Implemented - tested", "#10b981",
            "States, latching, acknowledgement, outage handling, logging and reports."),
           ("OB4 Physical rig", "Design stage", "#f59e0b",
            "Design B rev A approved; not yet built. No live rig data exists.")]
    html(ui.grid([ui.card(t, f"{ui.badge(s.upper(), colr)}<div class='ivhm-sub'>{ui.esc(sub)}</div>")
                  for t, s, colr, sub in obj], 200))
    html("<div class='ivhm-h'>Monitoring pipeline</div>")
    html(ui.pipeline_html())

    html("<div class='ivhm-h'>Headline results <span style='font-weight:400;color:#94a3b8;"
         "font-size:.85rem;text-transform:none;letter-spacing:0'>(frozen, preliminary - details in Research Lab)</span></div>")
    html(ui.grid([
        ui.card("Clean macro-F1 (P1)", ui.kpi(f"{h['gated_clean']:.3f}", "gated",
                f"vibration-only {h['vib_clean']:.3f}")),
        ui.card("Withheld sensor faults", ui.kpi(f"{h['gated_heldout']:.3f}", "gated",
                f"early {h['early_heldout']:.3f} &middot; average {h['avg_heldout']:.3f} &middot; "
                f"vib-only {h['vib_heldout']:.3f}")),
        ui.card("Healthy-window false alarms", ui.kpi(f"{h['gated_far']:.0%}", "",
                "concentrated in 2 of 4 healthy bearings")),
        ui.card("OB2 clean false flags", ui.kpi(f"{h['vib_false_flag']:.1%}", "vibration",
                f"current {h['cur_false_flag']:.1%}"))], 128))
    html(ui.alert("warn", "Honest reading of the results",
                  f"No fusion-vs-baseline difference is significant after Holm correction "
                  f"({h['n_significant_holm']} significant comparisons). Gated fusion beats early and "
                  "average fusion under withheld sensor faults but does not beat vibration-only, and healthy "
                  "bearings raise too many false alarms. These are preliminary results on a 12-bearing subset."))
    st.write("")
    l, r = st.columns(2, gap="medium")
    with l:
        html("<div class='ivhm-h'>Current monitoring status</div>")
        last = ss.last
        if last:
            html(ui.state_banner(last["state"], last["rule"],
                                 f"{last['asset']} · {last['recording']} · updated "
                                 f"{ui.fmt_ts(last['ts'])}"))
            html(ui.source_banner(last["kind"]))
        else:
            html(ui.card("No monitoring run in this session",
                         "<div class='ivhm-sub'>Open <b>Live Diagnostics</b> or start the professor demo from "
                         "the sidebar.</div>"))
    with r:
        html("<div class='ivhm-h'>Data-source labels</div>")
        html(ui.card("Every reading is tagged with its origin", "".join(
            f"<div style='margin:.4rem 0'>{ui.badge(s['tag'], s['color'])} "
            f"<span class='ivhm-sub'>{ui.esc(s['title'])}</span></div>" for s in ui.SOURCES.values())))


# ======================================================================== LIVE DIAGNOSTICS
def snapshot_render(boxes, snap):
    """Render one window's outputs (live during a run, or the last window after a rerun)."""
    a_state, kind = snap["state"], snap["kind"]
    boxes["state"].markdown(ui.state_banner(a_state, snap["rule"], snap["meta"]), unsafe_allow_html=True)
    rel = snap["rel"]
    boxes["vib"].markdown(ui.card("Vibration sensor", ui.sensor_card_html("Accelerometer", *rel["vib"])),
                          unsafe_allow_html=True)
    boxes["cur"].markdown(ui.card("Current sensor", ui.sensor_card_html("Motor current", *rel["cur"])),
                          unsafe_allow_html=True)
    if not snap["diag_ok"]:
        body = ui.alert("purple", "Diagnosis suspended",
                        "No usable sensor. No fault probabilities, sensor weights or explanation are shown "
                        "because none would be supported by data.")
    elif snap.get("probs"):
        colors = {"healthy": ui.STATE_COLOR["NORMAL"], "outer_race": ui.STATE_COLOR["WARNING"],
                  "inner_race": ui.STATE_COLOR["INSPECT"]}
        body = "".join(ui.bar(k.replace("_", " "), v, colors.get(k, ui.ACCENT)) for k, v in snap["probs"].items())
        if snap.get("weights"):
            w = snap["weights"]
            body += (f"<div class='ivhm-sub'>Fusion gate weights: vibration <b>{w['vib']:.2f}</b> &middot; current "
                     f"<b>{w['cur']:.2f}</b></div>")
    else:
        pf = snap.get("p_fault")
        body = ui.bar("combined anomaly evidence (alarm at 0.50)", pf, ui.STATE_COLOR["WARNING"])
        body += "".join(ui.bar(f"{k} evidence", v) for k, v in (snap.get("sensor_evidence") or {}).items())
    boxes["diag"].markdown(ui.card("Diagnostic evidence", body), unsafe_allow_html=True)
    boxes["comp"].markdown(ui.component_svg(a_state, rel["vib"][0], rel["cur"][0], ui.SOURCES[kind]["tag"]),
                           unsafe_allow_html=True)
    recs = snap["recs"] or ["none"]
    boxes["recs"].markdown(ui.card("Recommendations", ui.ulist(recs)), unsafe_allow_html=True)
    e = snap.get("expl")

    def chips(sensor, feats):            # a failed sensor's features are excluded by the gate: say so
        if rel[sensor][0] == "failed":
            return f"<span class=ivhm-chip>{sensor} <b>excluded - sensor failed</b></span>"
        return "".join(f"<span class=ivhm-chip>{sensor} <b>{ui.esc(x)}</b></span>" for x in feats)

    if e:
        boxes["expl"].markdown(ui.card("Why the model decided this", (
            f"<div class='ivhm-sub' style='color:#e2e8f0'>Predicted <b>{ui.esc(e['predicted'])}</b> with "
            f"confidence <b>{e['confidence']:.2f}</b>.</div>"
            f"<div style='margin-top:.4rem'>{chips('vib', e['vib'])}{chips('cur', e['cur'])}"
            f"{''.join(f'<span class=ivhm-chip>gate <b>{ui.esc(x)}</b></span>' for x in e['gate'])}</div>"
            f"<div class='ivhm-sub'>Faithfulness check - drop in predicted-class probability when the top features "
            f"are removed: vibration {e['drop_vib']:.2f}, current {e['drop_cur']:.2f}.</div>")),
            unsafe_allow_html=True)
    else:
        boxes["expl"].empty()
    sig = snap.get("sig")
    if sig is not None:
        if "sigh" in boxes:
            boxes["sigh"].markdown("<div class='ivhm-h' style='margin-top:.2rem'>Raw signal <span style='font-weight:"
                                   "400;color:#94a3b8;font-size:.8rem'>first 1,500 samples of the window, normalised "
                                   "units</span></div>", unsafe_allow_html=True)
        kw = {"x_label": "time within window (ms)", "y_label": "amplitude"} if _ST_VER >= (1, 40) else {}
        boxes["sig"].line_chart(sig, height=230, **kw)


def make_snapshot(out, win, kind, asset, recording, i, n):
    a, d = out["assessment"], out["diagnosis"]
    rel = {s: (r.status, float(r.score), list(r.reasons)) for s, r in d["reliability"].items()}
    vib = np.asarray(win["vib"], float)
    cur = np.asarray(win["cur"], float)
    cur = cur[0] if cur.ndim > 1 else cur
    fs = float(win.get("fs", win.get("fs_vib", 1.0)))
    m = min(1500, len(vib), len(cur))
    sig = pd.DataFrame({"vibration": vib[:m], "current": cur[:m]}, index=pd.Index(np.arange(m) / fs * 1e3, name="ms"))
    e = d.get("explanation") if a.diagnosis_available else None
    snap = dict(state=a.state, rule=a.rule, kind=kind, asset=asset, recording=recording, ts=out["ts"],
                meta=f"window {i + 1}/{n} · {recording} · asset {asset} · {ui.fmt_ts(out['ts'], False)}",
                rel=rel, diag_ok=a.diagnosis_available, recs=list(a.recommendations), sig=sig,
                p_fault=d.get("p_fault") if a.diagnosis_available else None,
                sensor_evidence=d.get("sensor_evidence") if a.diagnosis_available else None)
    if a.diagnosis_available and "probs" in d:
        snap["probs"], snap["weights"] = dict(d["probs"]), d.get("weights")
    if e:
        snap["expl"] = dict(predicted=e["predicted"], confidence=e["confidence"],
                            vib=[x["feature"] for x in e["vibration_evidence"][:3]],
                            cur=[x["feature"] for x in e["current_evidence"][:3]],
                            gate=[x["feature"] for x in e.get("gate_drivers", [])],
                            drop_vib=e["faithfulness_drop"]["vibration"], drop_cur=e["faithfulness_drop"]["current"])
    return snap


def view_live():
    kind = ui.MODE_SOURCE[ss.mode]
    rec_map = recordings()
    main = st.container()

    with st.sidebar:
        st.subheader("Source")
        st.radio("Mode", MODES, key="mode", on_change=on_mode_change)
        st.text_input("Asset name", key="asset")
        st.slider("Windows to run", 4, 120, key="nwin", help="A Paderborn recording is 4 s = 8 windows of 0.5 s; rig modes can run longer.")
        st.slider("Seconds per window", 0.0, 1.0, key="pace")
        if ss.mode == "Benchmark replay":
            st.subheader("Inject sensor fault")
            st.radio("Sensor", ["none", "vib", "cur", "both"], horizontal=True, key="target")
            st.selectbox("Fault type", list(C.FAMILIES), key="fam")
            sevs = C.FAMILIES[ss.fam][1]
            if len(sevs) > 1:
                if ss.get("sev") not in sevs:
                    ss.sev = sevs[0]
                st.select_slider("Severity", options=sevs, key="sev")
        elif ss.mode == "Rig - simulated":
            st.selectbox("Simulated bearing condition", ["healthy", "outer_race", "unbalance"], key="sim_cond")
            st.selectbox("Simulated sensor fault", ["none", "vib_dropout", "vib_clip", "cur_noise", "frame_loss"],
                         key="sim_fault")
        else:
            st.text_input("Serial port", key="port")

    with main:
        header("Live diagnostics", kind)
        # ---------------------------------------------------------------- source / model
        engine, stream, truth, rec_name, err = None, None, None, "-", None
        mp = MODEL_FILES[ss.mode]
        if ss.mode == "Benchmark replay":
            if not mp.exists():
                err = "models/demo_models.pkl not found - run scripts/windows/run_dashboard.bat once."
            else:
                bundle = load_pickle(str(mp))
                stems = sorted(s for s in rec_map if s.split("_")[3] in bundle["holdout"])
                if not stems:
                    err = f"No recordings of the held-out bearings {bundle['holdout']} in data/raw."
        if err:
            html(ui.alert("danger", "Cannot start", ui.esc(err)))
            return
        if ss.mode == "Benchmark replay":
            if ss.get("rec") not in stems:
                ss.rec = stems[0]
            cols = st.columns([1.5, 1, 1])
            cols[0].selectbox("Recording (held-out bearing)", stems, key="rec")
            rec_name = ss.rec
            rec = load_recording(rec_map[rec_name])
            truth = CLASS_NAMES[rec.label]
            cols[1].markdown(ui.card("Ground truth", f"<b>{ui.esc(truth.replace('_', ' '))}</b>"
                                     f"<div class='ivhm-sub'>bearing {ui.esc(rec_name.split('_')[3])}</div>"),
                             unsafe_allow_html=True)
            sev_v = (ss.sev if len(C.FAMILIES[ss.fam][1]) > 1 else C.FAMILIES[ss.fam][1][0])
            inj = "none" if ss.target == "none" else f"{ss.fam} on {ss.target}" + (
                f" (severity {sev_v})" if sev_v is not None else "")
            cols[2].markdown(ui.card("Injected fault", f"<b>{ui.esc(inj)}</b><div class='ivhm-sub'>"
                                     "synthetic corruption of a real recording</div>"), unsafe_allow_html=True)

        tkey = (ss.mode, ss.asset, rec_name)
        if ss.get("tracker_key") != tkey:        # new asset / recording = new bearing: never carry state over
            ss.tracker, ss.tracker_key = HealthTracker(), tkey
        tracker = ss.tracker

        if ss.mode == "Benchmark replay":
            engine = MonitorEngine(BenchmarkDiagnoser(bundle["models"]["gated_both"], bundle["assessors"]),
                                   SOURCE_BENCHMARK, ss.asset, store, tracker)
            wins = list(windows(rec))
            target, fam, n = ss.target, ss.fam, min(ss.nwin, len(wins))
            st.caption(f"This recording provides {len(wins)} windows; a run replays {n} of them "
                       f"(requested {ss.nwin}).")

            def stream():
                for i, v, c in wins[:n]:
                    if target != "none":
                        v, c = corrupt_pair(v, c, target, fam, sev_v, np.random.default_rng(i))
                    yield {"vib": v, "cur": c, "fs": rec.fs, "condition": rec.condition}
        else:
            rig_err = None
            if ss.mode == "Rig - live" and CLOUD:
                rig_err = ("This is the cloud demo: no USB/serial hardware can be attached here, and the physical "
                           "rig has not been built yet (Design B rev A). No live rig data exists.")
            elif not mp.exists():
                rig_err = (f"{mp.relative_to(ROOT)} not found. " + (
                    "run_dashboard.bat creates it from simulated sessions." if ss.mode == "Rig - simulated"
                    else "The physical rig has not been built yet (Design B rev A); no rig model exists."))
            else:
                bundle = load_pickle(str(mp))
                src_kinds = " ".join(bundle.get("data_source", ["unknown"]))
                if ss.mode == "Rig - live" and "SIMULATED" in src_kinds:
                    rig_err = "Refusing to apply a model trained on SIMULATED sessions to live rig data."
                if ss.mode == "Rig - simulated" and "SIMULATED" not in src_kinds:
                    rig_err = "The simulated mode expects a model trained on SIMULATED sessions."
            if rig_err:
                html(ui.alert("warn" if ss.mode == "Rig - live" else "danger",
                              "Rig not connected" if ss.mode == "Rig - live" else "Simulated rig model missing",
                              ui.esc(rig_err)))
                return
            cfg = bundle["config"]
            engine = MonitorEngine(RigDiagnoser(bundle["detector"], bundle["assessors"], cfg),
                                   SOURCE_SIM if ss.mode == "Rig - simulated" else SOURCE_RIG, ss.asset, store,
                                   tracker)
            truth = ss.get("sim_cond", "healthy") if ss.mode == "Rig - simulated" else None
            rec_name = f"SIMULATED {truth}" if ss.mode == "Rig - simulated" else f"serial {ss.port}"
            st.caption(f"Rig model trained on sessions {', '.join(bundle.get('trained_on', []))} "
                       f"(data source: {src_kinds}).")
            mode, n, port = ss.mode, ss.nwin, ss.port
            sim_cond, sim_fault = ss.get("sim_cond", "healthy"), ss.get("sim_fault", "none")

            def stream():
                if mode == "Rig - simulated":
                    src = SimulatedRigSource(cfg, sim_cond, seed=int(time.time()))
                    src.sensor_fault = None if sim_fault == "none" else sim_fault
                else:
                    src = SerialRigSource(port)
                parser, asm, sent, t0 = FrameParser(), WindowAssembler(cfg), 0, time.time()
                while sent < n:
                    got = False
                    for fr in parser.feed(src.read()):
                        for w in asm.push(fr):
                            sent, got = sent + 1, True
                            yield w
                    if not got and time.time() - t0 > 5 and sent == 0:
                        raise TimeoutError("no frames received within 5 s")


        # ---------------------------------------------------------------- controls
        b1, b2, _ = st.columns([1.15, 1.45, 1.2])
        run_clicked = b1.button("▶ Run monitoring", type="primary", **FULL)
        ack_clicked = b2.button("Acknowledge INSPECT alert", **FULL)
        run = run_clicked or ss.pop("pending_run", False)
        ack = ack_clicked or ss.pop("pending_ack", False)
        msg_box = st.empty()
        if ack:
            res = tracker.acknowledge()
            if res is None:
                msg_box.markdown(ui.alert("info", "Nothing to acknowledge",
                                          f"Current state is {tracker.state}, not INSPECT."), unsafe_allow_html=True)
            else:
                store.log_event(ss.asset, engine.source, res["from_state"], res["to_state"], res["rule"],
                                res["recommendations"], time.time())
                msg_box.markdown(ui.alert("warn", "INSPECT acknowledged and logged",
                                          "This does <b>not</b> confirm the bearing is healthy: the state is now "
                                          "WARNING and returns to NORMAL only after consecutive windows show no "
                                          "fault evidence; persistent evidence re-raises INSPECT."),
                                 unsafe_allow_html=True)
                if ss.last and ss.last["asset"] == ss.asset:
                    ss.last.update(state=tracker.state, rule=res["rule"],
                                   recs=res["recommendations"], meta=ss.last["meta"] + " · acknowledged")

        # ---------------------------------------------------------------- layout
        boxes = {"state": st.empty()}
        boxes["comp"] = st.empty()
        r1 = st.columns(2, gap="medium")
        boxes["vib"], boxes["cur"] = r1[0].empty(), r1[1].empty()
        r2 = st.columns([1, 1.35], gap="medium")
        boxes["diag"] = r2[0].empty()
        boxes["sigh"], boxes["sig"] = r2[1].empty(), r2[1].empty()
        r3 = st.columns([1, 1], gap="medium")
        boxes["recs"], boxes["expl"] = r3[0].empty(), r3[1].empty()

        if run:
            try:
                for i, win in enumerate(stream()):
                    out = engine.step(win)
                    ss.last = make_snapshot(out, win, kind, ss.asset, rec_name, i, n)
                    snapshot_render(boxes, ss.last)
                    time.sleep(ss.pace)
            except Exception as ex:  # serial port missing, no frames, etc.: report, never fabricate
                html(ui.alert("danger", "Source error", ui.esc(f"{type(ex).__name__}: {ex}")))
        elif ss.last and ss.last["asset"] == ss.asset and ss.last["kind"] == kind:
            snap = dict(ss.last)
            snap["state"] = tracker.state if ss.get("tracker_key") == tkey else snap["state"]
            snapshot_render(boxes, snap)
        else:
            boxes["state"].markdown(ui.alert("info", "Ready", "Press <b>Run monitoring</b> to replay the selected "
                                             "source through the monitoring engine."), unsafe_allow_html=True)


# ======================================================================== RESEARCH LAB
def view_research():
    import altair as alt
    header("Research lab - frozen preliminary results (OB1 diagnosis, OB2 sensor quality)", "results")
    data = load_research()
    S, h = data["summary"], data["headline"]
    t1, t2, t3, t4 = st.tabs(["OB1 · Diagnosis", "OB1 · Confusion matrices", "OB2 · Sensor quality",
                              "Limitations & audit"])
    order = ["vib_only", "cur_only", "early_fusion", "late_average", "late_stacked", "gated_both"]

    def f1_chart(proto):
        rows = []
        for m in order:
            v = S[proto]["models"].get(m)
            if not v:
                continue
            for k in ("clean", "seen", "heldout"):
                if v[k][0] is not None:
                    rows.append({"model": R.MODEL_LABEL[m], "scenario": R.SCENARIO_LABEL[k], "mean": v[k][0],
                                 "lo": max(0, v[k][0] - v[k][1]), "hi": min(1, v[k][0] + v[k][1])})
        df = pd.DataFrame(rows)
        sort = [R.MODEL_LABEL[m] for m in order]
        base = alt.Chart(df).encode(y=alt.Y("model:N", sort=sort, title=None, axis=alt.Axis(labelLimit=220)),
                                    yOffset=alt.YOffset("scenario:N", sort=list(R.SCENARIO_LABEL.values())))
        bars = base.mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("mean:Q", scale=alt.Scale(domain=[0, 1]), title="macro-F1 (mean ± sd across runs)"),
            color=alt.Color("scenario:N", sort=list(R.SCENARIO_LABEL.values()),
                            scale=alt.Scale(range=["#22d3ee", "#3b82f6", "#a855f7"]), title=None,
                            legend=alt.Legend(orient="top")),
            tooltip=["model", "scenario", alt.Tooltip("mean:Q", format=".3f")])
        err = base.mark_rule(color="#e2e8f0", opacity=.6).encode(x="lo:Q", x2="hi:Q")
        return (bars + err).properties(height=360)

    with t1:
        c1, c2 = st.columns([3, 2], gap="large")
        with c1:
            html(f"<div class='ivhm-h'>P1 - bearing-disjoint, {S['p1']['runs']} runs <span style='font-weight:400;color:#94a3b8;font-size:.85rem'>(test bearings never in training)</span></div>")
            st.altair_chart(f1_chart("p1"), **FULL)
        with c2:
            html("<div class='ivhm-h'>What this shows</div>")
            html(ui.alert("warn", "Fusion improvement is not significant",
                          f"Under withheld sensor faults the gated model scores {h['gated_heldout']:.3f} vs early "
                          f"fusion {h['early_heldout']:.3f} and average fusion {h['avg_heldout']:.3f}, but not above "
                          f"vibration-only ({h['vib_heldout']:.3f}). After Holm correction none of the paired "
                          "Wilcoxon tests is significant. With 11 overlapping runs on 12 bearings the test has low "
                          "power, and the p-values overstate independence."))
            html(ui.alert("info", "Leakage check",
                          "A random (leaky) split scores 0.95-0.98 macro-F1; the bearing-disjoint split 0.53-0.57. "
                          "Only the bearing-disjoint numbers are used as evidence."))
        html(f"<div class='ivhm-h'>Paired tests - gated fusion vs each baseline <span style='font-weight:400;color:#94a3b8;font-size:.85rem'>(P1, per-run mean macro-F1)</span></div>")
        tests = pd.DataFrame([{**t, "baseline": R.MODEL_LABEL.get(t["baseline"], t["baseline"]),
                               "scenario": R.SCENARIO_LABEL[t["scenario"]],
                               "significant (Holm < 0.05)": "yes" if t["p_holm"] < 0.05 else "no"}
                              for t in S["p1"]["tests"]])
        st.dataframe(tests, hide_index=True, **FULL,
                     column_config={"delta": st.column_config.NumberColumn("Δ macro-F1", format="%+.3f"),
                                    "p": st.column_config.NumberColumn("p", format="%.4f"),
                                    "p_holm": st.column_config.NumberColumn("p (Holm)", format="%.4f")})
        html(f"<div class='ivhm-h'>P3 - condition hold-out, {S['p3']['runs']} runs</div>")
        st.altair_chart(f1_chart("p3"), **FULL)
        tbl = pd.DataFrame([{"model": R.MODEL_LABEL[m], "clean": v["clean"][0], "withheld faults": v["heldout"][0],
                             "worst case": v["worst"][0], "ECE": v["ece"], "healthy FAR": v["far"],
                             "miss rate": v["miss"]} for m, v in S["p1"]["models"].items()])
        html(f"<div class='ivhm-h'>P1 summary table <span style='font-weight:400;color:#94a3b8;font-size:.85rem'>(as in results/starter/SUMMARY.txt)</span></div>")
        st.dataframe(tbl, hide_index=True, **FULL, column_config={
            c_: st.column_config.NumberColumn(c_, format="%.3f") for c_ in tbl.columns if c_ != "model"})

    with t2:
        st.markdown("Row-normalised confusion matrices **summed over the P1 runs** (counts in brackets), computed "
                    "from results/starter/p1.csv exactly as the reported figures.")
        for tag, title in (("none:clean:None", "Clean signals"), ("vib:dropout:None", "Vibration sensor dropout")):
            html(f"<div class='ivhm-h'>{title}</div>")
            cols = st.columns(3, gap="medium")
            models = ["vib_only", "early_fusion", "gated_both"] if tag.startswith("none") else \
                ["early_fusion", "late_average", "gated_both"]
            for col, m in zip(cols, models):
                df = pd.DataFrame(R.cm_long(R.summed_cm(RESULTS / "p1.csv", m, tag)))
                df["label"] = df.apply(lambda r: f"{r.share:.2f} ({r['count']})", axis=1)
                base = alt.Chart(df).encode(
                    x=alt.X("predicted:N", sort=R.CLASSES, title="predicted", axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("true:N", sort=R.CLASSES, title="true"))
                hm = base.mark_rect(stroke="#0b1220", strokeWidth=2).encode(
                    color=alt.Color("share:Q", scale=alt.Scale(domain=[0, 1], range=["#111b2e", "#1d4ed8"]),
                                    legend=None),
                    tooltip=["true", "predicted", alt.Tooltip("share:Q", format=".2f"), "count"])
                txt = base.mark_text(fontSize=12, color="#f1f5f9").encode(text="label:N")
                col.markdown(f"<div style='text-align:center;color:#94a3b8'>{R.MODEL_LABEL[m]}</div>",
                             unsafe_allow_html=True)
                col.altair_chart((hm + txt).properties(height=230), **FULL)
        cmg = R.summed_cm(RESULTS / "p1.csv", "gated_both", "vib:dropout:None")
        rec = [cmg[i][i] / max(sum(cmg[i]), 1) for i in range(3)]
        html(ui.alert("warn", "Reading the matrices",
                      "On clean signals every model confuses the two fault types and calls about 30 % of healthy "
                      "windows 'outer race' - the source of the false alarms. With the accelerometer lost, gated "
                      f"fusion's per-class recall is healthy {rec[0]:.2f}, outer race {rec[1]:.2f}, inner race "
                      f"{rec[2]:.2f}: close to chance, because current alone carries little fault information (OB1)."))
        with st.expander("Figures exactly as reported (results/starter/figures)"):
            for f in ("p1_macro_f1.png", "p1_confusion_clean.png", "p1_confusion_vib_dropout.png",
                      "p1_fault_family_heatmap.png", "leakage_check.png", "p3_macro_f1.png"):
                p = RESULTS / "figures" / f
                if p.exists():
                    st.image(str(p), caption=f)

    with t3:
        q = pd.DataFrame(data["quality"])
        clean = q[q.family == "clean"]
        c = st.columns(2, gap="medium")
        for col, s, name in zip(c, ("vib", "cur"), ("Vibration", "Current")):
            ff = float(clean[clean.sensor == s].false_flag.iloc[0])
            col.markdown(ui.card(f"{name} - false flags on clean data", ui.kpi(f"{ff:.1%}", "",
                         "share of clean windows flagged unreliable (15 folds, held-out bearings)")),
                         unsafe_allow_html=True)
        d = q[q.family != "clean"].copy()
        unit = {"noise": " dB SNR", "spikes": " /s", "gain": "x", "clipping": " x peak", "intermittent": " lost"}
        d["sev_num"] = pd.to_numeric(d.severity, errors="coerce")
        d["fault"] = [f if pd.isna(v) else f"{f} {v:g}{unit.get(f, '')}" for f, v in zip(d.family, d.sev_num)]
        d = d.sort_values(["family", "sev_num"])
        fault_order = list(dict.fromkeys(d.fault))
        d["sensor"] = d.sensor.map({"vib": "vibration", "cur": "current"})
        hm = alt.Chart(d).mark_rect(stroke="#0b1220", strokeWidth=1).encode(
            x=alt.X("sensor:N", title=None, sort=["vibration", "current"], axis=alt.Axis(labelAngle=0, orient="top")),
            y=alt.Y("fault:N", title="injected fault (family, severity)", sort=fault_order,
                    axis=alt.Axis(labelLimit=220)),
            color=alt.Color("detect:Q", scale=alt.Scale(domain=[0, 1], range=["#111b2e", "#0e7490"]), title="detected"),
            tooltip=["fault", "sensor", alt.Tooltip("detect:Q", format=".2f")])
        tx = alt.Chart(d).mark_text(fontSize=11, color="#f1f5f9").encode(
            x=alt.X("sensor:N", sort=["vibration", "current"]), y=alt.Y("fault:N", sort=fault_order),
            text=alt.Text("detect:Q", format=".2f"))
        l, r = st.columns([2, 3], gap="large")
        l.altair_chart((hm + tx).properties(height=520), **FULL)
        with r:
            html(ui.alert("ok", "Strong", "Dropout, stuck, clipping and intermittent faults are detected on both sensors "
                                          "(96-100 %), and current-sensor noise and spikes are caught."))
            html(ui.alert("danger", "Weak - identified implementation issue",
                          "Vibration noise (2-15 %), spikes (2-11 %) and gain (2-16 %) are largely missed. The learned "
                          "spectral-flatness upper bound for vibration (1.20) lies above the attainable maximum (~1) "
                          "because of the 25 % range padding in ReliabilityAssessor, so that indicator can never fire. "
                          "Not fixed before the review; any fix must be selected on training bearings only."))
            html(ui.alert("info", "Cross-flags", "When one sensor is corrupted the other is flagged at its clean "
                                                 "rate (1.3-1.5 %), i.e. the assessor does not blame the healthy "
                                                 "sensor."))

    with t4:
        far = data["far"]
        rows = [{"bearing": b, "model": R.MODEL_LABEL[m], "FAR": v}
                for m, d0 in far["far_by_heldout_healthy_bearing"].items() for b, v in d0.items()]
        df = pd.DataFrame(rows)
        ch = alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("bearing:N", title="held-out healthy bearing", axis=alt.Axis(labelAngle=0)), xOffset="model:N",
            y=alt.Y("FAR:Q", scale=alt.Scale(domain=[0, 1]), title="healthy windows flagged as faulty"),
            color=alt.Color("model:N", scale=alt.Scale(range=["#22d3ee", "#3b82f6", "#a855f7", "#f59e0b"]),
                            legend=alt.Legend(orient="top", title=None, labelLimit=260, columns=2)),
            tooltip=["bearing", "model", alt.Tooltip("FAR:Q", format=".3f")])
        l, r = st.columns([3, 2], gap="large")
        l.markdown("<div class='ivhm-h'>Why the healthy-window false-alarm rate is ~0.45 (gated 0.47)</div>",
                   unsafe_allow_html=True)
        l.altair_chart(ch.properties(height=330), **FULL)
        with r:
            html(ui.alert("warn", "Concentrated in two bearings",
                          "K002 (0.75) and K004 (0.82-0.87) are misclassified by every model; K001 and K003 are "
                          "near zero. The pooled ~0.45 is the window-weighted mean over folds that hold out K002 or "
                          "K004."))
            html(ui.alert("info", "Cause: healthy-bearing diversity",
                          "Each fold trained on only 2-3 healthy bearings. Folds that trained on both K002 and K004 "
                          "had near-zero FAR. Healthy bearings differ from each other about as much as from damaged "
                          "ones. Not an evaluation error: per-bearing values recombine to the reported fold FARs."))
            html(ui.alert("info", "Health rules propagate it",
                          "Replayed through WARNING/INSPECT, 35-39 % of healthy recordings end in INSPECT for every "
                          "model. The rules turn persistent misclassification into alarms, as designed."))
        html("<div class='ivhm-h'>Other limitations stated openly</div>")
        html(ui.ulist([
            "Starter subset: 12 of 32 Paderborn bearings; 11 of 15 P1 folds ran (4 lacked a class in the subset).",
            "Runs reuse the same 12 bearings, so the effective sample size is ~12 bearings, not 11 runs.",
            "Current-only diagnosis is weak (macro-F1 0.32), so current cannot replace a failed accelerometer well.",
            "No threshold or parameter was tuned on held-out bearings; the dashboard re-computes nothing.",
            "The physical rig (OB4) is at design stage; no rig results exist.",
        ]))


# ======================================================================== HISTORY & REPORTS
def history_chart(hist):
    """Fault evidence, sensor reliability and health state per logged window (Altair)."""
    import altair as alt
    rows = []
    for k, h0 in enumerate(hist, 1):
        t = ui.fmt_ts(h0["ts"])
        for name, v in (("fault evidence", h0["p_fault"]), ("vibration reliability", h0["rel_vib"]),
                        ("current reliability", h0["rel_cur"])):
            rows.append({"window": k, "time": t, "series": name, "value": None if v is None else float(v),
                         "state": h0["state"]})
    df = pd.DataFrame(rows)
    sc = alt.Scale(domain=list(ui.STATE_COLOR), range=list(ui.STATE_COLOR.values()))
    ser = alt.Scale(domain=["fault evidence", "vibration reliability", "current reliability"],
                    range=[ui.ACCENT, "#64748b", "#94a3b8"])
    xs = alt.Scale(domain=[1, len(hist) + 1], nice=False)
    ys = alt.Scale(domain=[-0.17, 1.05])
    base = alt.Chart(df).encode(x=alt.X("window:Q", title="logged window #", scale=xs, axis=alt.Axis(tickMinStep=1)))
    lines = base.mark_line(strokeWidth=2).encode(
        y=alt.Y("value:Q", title="evidence / reliability (0-1)", scale=ys, axis=alt.Axis(values=[0, .25, .5, .75, 1])),
        color=alt.Color("series:N", scale=ser, legend=alt.Legend(orient="top", title=None)),
        strokeDash=alt.condition("datum.series == 'fault evidence'", alt.value([1, 0]), alt.value([4, 3])),
        tooltip=["window", "time", "series", alt.Tooltip("value:Q", format=".2f"), "state"])
    thr = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color="#f59e0b", strokeDash=[2, 2]).encode(
        y=alt.Y("y:Q", scale=ys))
    strip = alt.Chart(df[df.series == "fault evidence"]).mark_rect().encode(
        x=alt.X("window:Q", scale=xs), x2="w2:Q", y=alt.Y("lo:Q", scale=ys), y2="hi:Q",
        color=alt.Color("state:N", scale=sc, legend=alt.Legend(orient="bottom", title="health state band")),
        tooltip=["window", "time", "state"]).transform_calculate(w2="datum.window + 1", lo="-0.15", hi="-0.04")
    return (alt.layer(strip, lines, thr).resolve_scale(color="independent")
            .properties(height=340).configure_view(strokeWidth=0))


def view_history():
    header("History & reports - SQLite audit trail", None)
    assets = [r[0] for r in store.db.execute(
        "SELECT asset FROM windows GROUP BY asset ORDER BY MAX(ts) DESC").fetchall()]
    if not assets:
        html(ui.alert("info", "No history yet", "Run monitoring in Live Diagnostics to create history."))
        return
    if ss.get("hist_asset") not in assets:
        ss.hist_asset = ss.asset if ss.asset in assets else assets[0]
    top = st.columns([1.5, 1, 1, 1.5])
    top[0].selectbox("Asset", assets, key="hist_asset")
    asset = ss.hist_asset
    hist = store.history(asset, limit=5000)
    ev = store.events(asset)
    srcs = sorted({h0["source"] for h0 in hist})
    counts = pd.Series([h0["state"] for h0 in hist]).value_counts()
    t0, t1 = hist[0]["ts"], hist[-1]["ts"]
    top[1].markdown(ui.card("Windows logged", ui.kpi(f"{len(hist)}")), unsafe_allow_html=True)
    top[2].markdown(ui.card("State changes", ui.kpi(f"{len(ev)}")), unsafe_allow_html=True)
    top[3].markdown(ui.card("Time span", f"<div style='color:#e2e8f0;font-weight:600'>{ui.fmt_ts(t0, False)} &#8594; "
                            f"{ui.fmt_ts(t1, False)}</div><div class='ivhm-sub'>"
                            f"{time.strftime('%d %b %Y', time.localtime(t0))}</div>"), unsafe_allow_html=True)
    kind = "simulated" if any("SIMULATED" in s for s in srcs) else "live" if any("rig live" == s for s in srcs) \
        else "benchmark"
    html(ui.source_banner(kind, "Logged source(s): " + "; ".join(srcs)))
    html("<div class='ivhm-h'>Trend <span style='font-weight:400;color:#94a3b8;font-size:.82rem'>per logged "
         "window; fault evidence is left blank while diagnosis is suspended (no usable sensor)</span></div>")
    st.altair_chart(history_chart(hist), **FULL)
    html("<div class='ivhm-h'>State-change audit trail</div>")
    html(ui.event_table(ev) + (f"<div class='ivhm-sub'>Showing the latest 60 of {len(ev)} events; the CSV/HTML "
                               "exports contain everything.</div>" if len(ev) > 60 else ""))
    c = st.columns([1.3, 1], gap="large")
    with c[0]:
        html("<div class='ivhm-h'>Windows per state</div>")
        html("".join(ui.bar(s.replace("_", " "), counts.get(s, 0) / max(len(hist), 1), ui.STATE_COLOR[s],
                            fmt="{:.0%}") for s in ui.STATE_COLOR))
    with c[1]:
        rp = export_dir() / f"report_{asset}.html"
        cp = export_dir() / f"history_{asset}.csv"
        store.export_html(rp, asset)
        store.export_csv(cp, asset)
        html("<div class='ivhm-h'>Exports</div><div class='ivhm-sub' style='margin-bottom:.5rem'>Generated from "
             f"SQLite for {ui.esc(asset)}: every window with state, evidence, reliability and advice.</div>")
        st.download_button("⬇ HTML report", rp.read_bytes(), rp.name, "text/html", **FULL)
        st.download_button("⬇ CSV history", cp.read_bytes(), cp.name, "text/csv", **FULL)


{"Overview": view_overview, "Live Diagnostics": view_live, "Research Lab": view_research,
 "History & Reports": view_history}[ss.view]()
