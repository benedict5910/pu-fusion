"""Virtual Testbed view (OB4): representative CAD drivetrain linked to recorded-signal replay.

What the user can do: choose the bearing or gearbox subsystem; see the representative drivetrain with that
subsystem's sensors; pick a real held-out recording; run, pause, step and reset the replay; inject noise,
clipping, stuck signals, dropout (and the other implemented sensor faults) on a chosen sensor at any window;
and watch the frozen models' predictions, sensor quality, fusion weights, health state, explanations and the
event history - all produced window by window by pufusion.testbed_session.ReplaySession, which uses the same
frozen models, fault injection, health rules and SQLite log as the verified testbed. Nothing is hard-coded.

Honesty labels on the page: recorded-signal replay with controlled sensor-fault injection (not a physics model);
the CAD assembly is representative (not either test bench); Paderborn and MCC5-THU are separate benches, so the
bearing and gearbox subsystems are replayed separately and never fused.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import streamlit as st

import cad3d
import ui
from pufusion import drivetrain_cad as D
from pufusion import testbed as T
from pufusion import testbed_session as S

SUBSYSTEMS = {"Bearing": "bearing", "Gearbox": "gearbox"}
SENSOR_CHOICES = {"bearing": ["none", "vib", "cur", "both"], "gearbox": ["none", "motor", "gearbox", "both"]}
SENSOR_NAMES = {"vib": "bearing accelerometer (S1)", "cur": "motor current sensors (S2)",
                "motor": "motor accelerometer (S3)", "gearbox": "gearbox accelerometer (S4)", "both": "both sensors"}
FAULT_HELP = {"noise": "additive Gaussian noise at the chosen SNR (dB)", "clipping": "signal clipped at a fraction of its peak",
              "stuck": "sensor frozen at its first value", "dropout": "sensor disconnected (reads zero)",
              "spikes": "EMI-like impulses", "intermittent": "burst packet loss", "gain": "calibration (gain + offset) error"}
DEFAULT_RUN = {"bearing": 24, "gearbox": 59}
VIEW_CHOICES = {"3D": "3D", "front": "2D front", "top": "2D top"}
VIEWER_HEIGHT = 640
NOTE_3D = ("Representative assembly built in FreeCAD (STEP -> GLB), not the Paderborn or MCC5-THU bench. Colours "
           "show the frozen models' replay output; the 3D view neither simulates physics nor generates the recordings.")
INACTIVE = "#475569"
_FULL = {"use_container_width": True}
NOTICE = ("Recorded-signal replay with controlled sensor-fault injection on a representative CAD drivetrain. "
          "Recordings are real and held out from training; sensor faults are synthetic; the CAD model is a "
          "representative assembly, not the Paderborn or MCC5-THU test bench, and the animation is not a physics "
          "simulation. Bearing (Paderborn) and gearbox (MCC5-THU) come from two different benches and are replayed "
          "separately.")


@st.cache_resource(show_spinner=False)
def _context(stamp):
    """Frozen models + held-out recordings (testbed.Context). `stamp` changes when gearbox data appear."""
    return T.Context()


def sensor_colours(subsystem, frame):
    """S1..S4 -> colour: the active subsystem's sensors by reliability status, the others greyed out."""
    out = {}
    for s in D.SENSORS:
        if s["subsystem"] != subsystem or frame is None:
            out[s["id"]] = INACTIVE if s["subsystem"] != subsystem else "#94a3b8"
        else:
            out[s["id"]] = ui.REL_COLOR.get(frame["status"][s["code"]], "#94a3b8")
    return out


def cad_state(subsystem, frame):
    """Colours for the CAD view, derived only from the frame (used by the view and checked by the tests)."""
    state = frame["state"] if frame else "NORMAL"
    fill = {c: ui.STATE_COLOR[state] for c in D.MONITORED[subsystem]} if frame else {}
    return {"part_fill": fill, "sensor_fill": sensor_colours(subsystem, frame), "highlight": D.MONITORED[subsystem]}


def cad_svg(subsystem, frame, view="front"):
    cs = cad_state(subsystem, frame)
    title = (f"REPRESENTATIVE DRIVETRAIN · {view.upper()} VIEW · monitored: "
             f"{'test bearing' if subsystem == 'bearing' else 'gearbox'}")
    return D.svg_view(view, cs["part_fill"], cs["sensor_fill"], cs["highlight"], title=title)


def _num(v):
    """JSON-safe float (None for missing / non-finite)."""
    if v is None:
        return None
    v = float(v)
    return v if np.isfinite(v) else None


def cad3d_args(subsystem, frame, sess=None, model_url=None, model_error=None):
    """Everything the 3D viewer displays, derived only from the replay frame (and the CAD sensor map).
    Colours come from cad_state(), the same function as the 2D drawings."""
    cs = cad_state(subsystem, frame)
    other = "gearbox" if subsystem == "bearing" else "bearing"
    sensors = {}
    for s in D.SENSORS:
        active = s["subsystem"] == subsystem
        d = {k: s[k] for k in ("id", "label", "subsystem", "code", "channels", "fs_hz", "where", "dataset")}
        d.update(active=active, status=None, score=None, reasons=[], weight=None)
        if active and frame is not None:
            rel = frame["reliability"][s["code"]]
            d.update(status=rel["status"], score=_num(rel["score"]), reasons=list(rel["reasons"]),
                     weight=_num(frame["weights"][s["code"]]))
        sensors[s["id"]] = d
    fr = None
    if frame is not None:
        fr = {"window": int(frame["window"]), "recording_window": int(frame["recording_window"]),
              "windows_per_recording": int(sess.windows_per_recording) if sess is not None else None,
              "recording": (None if sess is None else sess.recording if subsystem == "bearing"
                            else sess.recording.split("_torque")[0]),
              "ground_truth": frame["ground_truth"], "fault_label": frame["fault_label"],
              "state": frame["state"], "rule": frame["rule"], "diagnosis_available": bool(frame["diagnosis_available"]),
              "p_fault": _num(frame["p_fault"]), "fault_type": frame["fault_type"],
              "probs": {k: _num(v) for k, v in frame["probs"].items()} if frame.get("probs") else None}
    mon = D.MONITORED[subsystem]
    rec = "" if sess is None else (sess.recording if subsystem == "bearing" else sess.recording.split("_torque")[0])
    where = (f"{subsystem.capitalize()} replay · {rec}"
             + (f" · window {fr['window']}" if fr else " · ready"))
    return {"model_url": model_url, "model_error": model_error, "subsystem": subsystem, "other_subsystem": other,
            "monitored": mon, "other_monitored": D.MONITORED[other],
            "component_label": D.COMPONENT_LABELS.get(mon[0], mon[0]),
            "part_fill": cs["part_fill"], "sensor_fill": cs["sensor_fill"], "sensors": sensors, "frame": fr,
            "state_colors": dict(ui.STATE_COLOR), "rel_colors": dict(ui.REL_COLOR), "inactive": INACTIVE,
            "note": NOTE_3D, "subtitle": where, "height": VIEWER_HEIGHT}


def sensor_table_html(subsystem, frame):
    rows = []
    for s in D.SENSORS:
        if s["subsystem"] != subsystem:
            continue
        rel = frame["reliability"][s["code"]] if frame else None
        w = frame["weights"][s["code"]] if frame else None
        st_ = rel["status"] if rel else "-"
        col = ui.REL_COLOR.get(st_, "#94a3b8")
        score_txt = "" if rel is None else f"{rel['score']:.2f}"
        weight_txt = "n/a" if w is None else f"{w:.2f}"
        badge = ui.badge(st_.upper(), col) if rel else "-"
        reasons = ", ".join(rel["reasons"]) if rel and rel["reasons"] else ("within learned clean range" if rel else "")
        rows.append(
            f"<tr><td><b style='color:{col}'>{s['id']}</b></td><td>{ui.esc(s['label'])}<div class='ivhm-sub'>"
            f"{ui.esc(', '.join(s['channels']))}</div></td><td>{ui.esc(s['where'])}</td>"
            f"<td>{badge}<div class='ivhm-sub'>{ui.esc(reasons)}</div></td>"
            f"<td>{score_txt}</td><td>{weight_txt}</td></tr>")
    return ("<table class='ivhm-tbl' style='width:100%;font-size:.82rem'><tr><th>ID</th><th>Sensor / data channels</th>"
            "<th>CAD location</th><th>Quality</th><th>Score</th><th>Fusion weight</th></tr>" + "".join(rows) + "</table>")


def timeline_chart(frames, subsystem):
    """Fault evidence, fusion weights and health-state band per replayed window (Altair)."""
    import altair as alt
    names = {"bearing": ("vib", "cur"), "gearbox": ("gearbox", "motor")}[subsystem]
    rows = []
    for f in frames:
        rows.append({"window": f["window"], "series": "fault evidence", "value": f["p_fault"], "state": f["state"],
                     "fault": f["fault_label"]})
        for s in names:
            rows.append({"window": f["window"], "series": f"weight {s}", "value": f["weights"][s], "state": f["state"],
                         "fault": f["fault_label"]})
    df = pd.DataFrame(rows)
    sc = alt.Scale(domain=list(ui.STATE_COLOR), range=list(ui.STATE_COLOR.values()))
    xs = alt.Scale(domain=[1, max(len(frames), 2) + 1], nice=False)
    ys = alt.Scale(domain=[-0.17, 1.05])
    lines = alt.Chart(df).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("window:Q", title="replayed window", scale=xs, axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("value:Q", title="evidence / weight (0-1)", scale=ys),
        color=alt.Color("series:N", legend=alt.Legend(orient="top", title=None)),
        tooltip=["window", "series", alt.Tooltip("value:Q", format=".2f"), "state", "fault"])
    strip = alt.Chart(df[df.series == "fault evidence"]).mark_rect().encode(
        x=alt.X("window:Q", scale=xs), x2="w2:Q", y=alt.Y("lo:Q", scale=ys), y2="hi:Q",
        color=alt.Color("state:N", scale=sc, legend=alt.Legend(orient="bottom", title="health state")),
        tooltip=["window", "state", "fault"]).transform_calculate(w2="datum.window + 1", lo="-0.15", hi="-0.04")
    thr = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color="#f59e0b", strokeDash=[2, 2]).encode(y=alt.Y("y:Q", scale=ys))
    return alt.layer(strip, lines, thr).resolve_scale(color="independent").properties(height=260).configure_view(strokeWidth=0)


def waveforms(frame):
    """One DataFrame per sensor (channels of that sensor), time axis in ms."""
    sig = frame["signals"]
    fs = sig["fs"]
    out = {}
    for s in D.SENSORS:
        chans = {c: sig["channels"][c] for c in s["channels"] if c in sig["channels"]}
        if not chans:
            continue
        n = min(len(v) for v in chans.values())
        out[s["id"]] = pd.DataFrame({c: np.asarray(v[:n]) for c, v in chans.items()},
                                    index=pd.Index(np.arange(n) / fs * 1e3, name="ms"))
    return out


def render(env):
    """env: dict with the dashboard's store, header(), html(), FULL, ss and gearbox_source()."""
    global _FULL
    store, html, FULL, ss = env["store"], env["html"], env["FULL"], env["ss"]
    _FULL = FULL
    for k, v in dict(tb_sub="Bearing", tb_target="none", tb_fam="noise", tb_pace=0.3, tb_view="3D",
                     tb_playing=False).items():
        ss.setdefault(k, v)
    with st.sidebar:
        st.subheader("Virtual testbed")
        st.radio("Subsystem", list(SUBSYSTEMS), key="tb_sub", horizontal=True)
        if ss.tb_view not in VIEW_CHOICES:
            ss.tb_view = "3D"
        st.radio("CAD view", list(VIEW_CHOICES), key="tb_view", horizontal=True, format_func=VIEW_CHOICES.get,
                 help="3D: interactive CAD-derived model (rotate, zoom, pan, click to inspect). 2D: line drawings.")
    subsystem = SUBSYSTEMS[ss.tb_sub]
    env["header"]("Virtual testbed - CAD-linked replay", "benchmark" if subsystem == "bearing" else "gearbox")
    html("<div class='ivhm-sub' style='border-left:3px solid #38bdf8;padding:.35rem .7rem;margin:.2rem 0 .6rem;"
         "background:rgba(56,189,248,.06);border-radius:4px'><b style='color:#bae6fd'>What this is:</b> "
         + ui.esc(NOTICE) + "</div>")

    if subsystem == "gearbox":
        recs, _, dl_err = env["gearbox_source"]()        # fetches the verified demo recordings if needed
        if dl_err or not recs:
            html(ui.alert("warn", "Gearbox recordings unavailable",
                          ui.esc(dl_err or "No MCC5-THU recordings found; nothing is substituted.")))
    ctx = _context(T.gearbox_data_dir() is not None)
    recs = sorted(ctx.bearing_recs) if subsystem == "bearing" else sorted(ctx.gearbox_recs)
    if subsystem == "gearbox" and not recs:
        html(ui.alert("warn", "Gearbox replay unavailable", "The held-out MCC5-THU recordings are not present."))
        return
    # each subsystem remembers its own recording and replay session, so switching bearing <-> gearbox and back
    # resumes where that replay was (paused) instead of starting it again
    last_rec = ss.setdefault("tb_last_rec", {})
    if ss.get("tb_rec") not in recs:
        ss.tb_rec = last_rec.get(subsystem) if last_rec.get(subsystem) in recs else recs[0]

    with st.sidebar:
        fmt = (lambda r: ui.bearing_scenario_label(f"N15_M07_F10_{r}_1")) if subsystem == "bearing" else ui.gearbox_scenario_label
        st.selectbox("Held-out recording", recs, key="tb_rec", format_func=fmt)
        ss.setdefault(f"tb_stop_{subsystem}", DEFAULT_RUN[subsystem])
        st.slider("Stop after window", 4, 120, key=f"tb_stop_{subsystem}")
        st.slider("Seconds per window", 0.0, 1.0, key="tb_pace")
        st.subheader("Inject sensor fault")
        if ss.tb_target not in SENSOR_CHOICES[subsystem]:
            ss.tb_target = "none"
        st.radio("Sensor", SENSOR_CHOICES[subsystem], key="tb_target", horizontal=True,
                 help="; ".join(f"{k}: {v}" for k, v in SENSOR_NAMES.items()))
        st.selectbox("Fault type", list(S.UI_FAULTS), key="tb_fam", help="; ".join(f"{k}: {v}" for k, v in FAULT_HELP.items()))
        sev = None
        if subsystem == "bearing":
            sevs = S.C.FAMILIES[ss.tb_fam][1]
            if len(sevs) > 1:
                if ss.get("tb_sev") not in sevs:
                    ss.tb_sev = S.default_severity(ss.tb_fam)
                st.select_slider("Severity", options=sevs, key="tb_sev")
                sev = ss.tb_sev
        else:
            st.caption("Gearbox faults use the fixed severities of the validated gearbox evaluation "
                       "(noise 0 dB, clipping 0.2 of peak, spikes 100/s, gain x2).")
        st.caption("A fault change applies from the next replayed window.")

    last_rec[subsystem] = ss.tb_rec
    key = (subsystem, ss.tb_rec)
    sessions = ss.setdefault("tb_sessions", {})
    if ss.get("tb_key") != key:                       # another subsystem or recording: pause, keep the old replay
        ss.tb_playing = False
    sess = sessions.get(key)
    if sess is None:
        sess = sessions[key] = _new_session(ctx, subsystem, ss.tb_rec, store)
    ss.tb_session, ss.tb_key = sess, key
    stop = ss.get(f"tb_stop_{subsystem}", DEFAULT_RUN[subsystem])

    # ---------------------------------------------------------------- controls
    c = st.columns([1, 1, 1, 1, 1.6])
    c[0].button("▶ Run", key="tb_run", type="primary", on_click=_set, args=(ss, "tb_playing", True), **FULL)
    c[1].button("⏸ Pause", key="tb_pause", on_click=_set, args=(ss, "tb_playing", False), **FULL)
    step = c[2].button("⏭ Step", key="tb_step", **FULL)
    reset = c[3].button("⟲ Reset", key="tb_reset", **FULL)
    ack = c[4].button("Acknowledge INSPECT", key="tb_ack", **FULL)
    msg = st.empty()
    if reset:
        sess = sessions[key] = _new_session(ctx, subsystem, ss.tb_rec, store)
        ss.tb_session, ss.tb_playing = sess, False
    done = False
    if ack:
        done = sess.acknowledge()
        msg.markdown(ui.alert("warn" if done else "info", "INSPECT acknowledged and logged" if done else "Nothing to acknowledge",
                              "State is now WARNING; the component condition is NOT verified."
                              if done else f"Current state is {sess.state}, not INSPECT."), unsafe_allow_html=True)

    boxes = _layout()
    target = ss.tb_target
    sess.set_fault(None if target == "none" else ss.tb_fam, None if target == "none" else target, sev)

    if step and sess.i < 10_000:
        ss.tb_playing = False
        _render(boxes, sess, sess.step(), subsystem, ss)
    elif ss.tb_playing:
        if sess.i >= stop:
            ss.tb_playing = False
            msg.markdown(ui.alert("info", "Run complete", f"Stopped after window {sess.i}. Reset to start again, "
                                  "or raise 'Stop after window' and press Run to continue."), unsafe_allow_html=True)
            if sess.frames:
                _render(boxes, sess, sess.frames[-1], subsystem, ss)
        else:
            # One window per script run, then st.rerun(). A long in-script loop could not be interrupted
            # reliably: on the PC a Pause click during a gearbox run was only handled after the stop window.
            # Ending each run here lets every Pause/Step/Reset/Acknowledge click be processed between windows.
            _render(boxes, sess, sess.step(), subsystem, ss)
            time.sleep(ss.tb_pace)
            if sess.i < stop:
                st.rerun()
            ss.tb_playing = False
            msg.markdown(ui.alert("info", "Run complete", f"Stopped after window {sess.i}. Reset to start again, "
                                  "or raise 'Stop after window' and press Run to continue."), unsafe_allow_html=True)
    else:
        frame = sess.frames[-1] if sess.frames else None
        if done and frame is not None:      # show the acknowledged state now, not the state recorded for that window
            frame = dict(frame, state=sess.state, rule="INSPECT acknowledged by the operator (condition not verified)")
        _render(boxes, sess, frame, subsystem, ss)


def _set(ss, k, v):
    ss[k] = v


def _new_session(ctx, subsystem, rec, store):
    asset = f"vt-{subsystem}-{rec.split('_')[0] if subsystem == 'bearing' else rec.split('_torque')[0]}-{time.strftime('%H%M%S')}"
    return S.ReplaySession(ctx, subsystem, rec, store, asset, ts_fn=lambda i: time.time())


def _layout():
    b = {"state": st.empty()}
    b["cad"] = st.container()            # the 3D viewer (or 2D drawing) is rendered here exactly once per script run
    t = st.tabs(["Diagnosis & sensors", "Waveforms", "Timeline & events", "Explanation & actions"])
    r = t[0].columns([1, 1.5], gap="medium")
    b["diag"], b["sensors"] = r[0].empty(), r[1].empty()
    b["wave"] = t[1].empty()               # empty(): each window replaces, never appends
    b["timeline_h"], b["timeline"], b["events"] = t[2].empty(), t[2].empty(), t[2].empty()
    r2 = t[3].columns([1, 1], gap="medium")
    b["recs"], b["expl"] = r2[0].empty(), r2[1].empty()
    return b


def _render(b, sess, frame, subsystem, ss):
    if frame is None:
        b["state"].markdown(ui.alert("info", "Ready", f"Recording {ui.esc(sess.recording)} (ground truth: "
                                     f"{ui.esc(sess.label.replace('_', ' '))}). Press <b>Run</b> or <b>Step</b>."),
                            unsafe_allow_html=True)
    else:
        meta = (f"window {frame['window']} (recording window {frame['recording_window']}/{sess.windows_per_recording}) · "
                f"{sess.recording} · ground truth {frame['ground_truth'].replace('_', ' ')} · injected: {frame['fault_label']}"
                f" · asset {sess.asset}")
        b["state"].markdown(ui.state_banner(frame["state"], frame["rule"], meta), unsafe_allow_html=True)
    view = ss.get("tb_view", "3D")
    url, err = cad3d.model_url() if view == "3D" else (None, None)
    with b["cad"]:
        if view == "3D" and url:
            st.markdown(f"<div class='ivhm-sub' style='letter-spacing:.06em;margin:.3rem 0'>REPRESENTATIVE DRIVETRAIN · "
                        f"INTERACTIVE 3D FROM THE FREECAD STEP EXPORT · monitored: "
                        f"{'test bearing' if subsystem == 'bearing' else 'gearbox'}</div>", unsafe_allow_html=True)
            cad3d.viewer(cad3d_args(subsystem, frame, sess, model_url=url))
        else:
            if view == "3D":
                st.markdown(ui.alert("info", "3D model not available", ui.esc(err or "")), unsafe_allow_html=True)
                view = "front"
            st.markdown(f"<div style='margin:.4rem 0'>{cad_svg(subsystem, frame, view)}</div>", unsafe_allow_html=True)
    b["sensors"].markdown(ui.card("Sensors on the CAD model (S1-S4, see sensor map)",
                                  sensor_table_html(subsystem, frame)), unsafe_allow_html=True)
    if frame is None:
        return
    if not frame["diagnosis_available"]:
        body = ui.alert("purple", "Diagnosis suspended", "No usable sensor: no probabilities or weights are shown.")
    else:
        colours = {"healthy": ui.STATE_COLOR["NORMAL"], "outer_race": ui.STATE_COLOR["WARNING"],
                   "inner_race": ui.STATE_COLOR["INSPECT"], "gear_wear": ui.STATE_COLOR["WARNING"],
                   "gear_pitting": ui.STATE_COLOR["INSPECT"]}
        body = "".join(ui.bar(k.replace("_", " "), v, colours.get(k, ui.ACCENT)) for k, v in (frame["probs"] or {}).items())
        body += ui.bar("fault evidence (1 - P(healthy))", frame["p_fault"], ui.STATE_COLOR["WARNING"])
        w = frame["weights"]
        body += "<div class='ivhm-sub'>Fusion weights: " + " · ".join(f"{k} <b>{v:.2f}</b>" for k, v in w.items()) + "</div>"
    b["diag"].markdown(ui.card("Frozen-model output (this window)", body), unsafe_allow_html=True)
    with b["wave"].container():
        for sid, df in waveforms(frame).items():
            st.caption(f"{sid} waveform - first {len(df)} samples of the window ({frame['signals']['unit']})")
            st.line_chart(df, height=150)
    b["timeline_h"].markdown("<div class='ivhm-h'>Health-state transitions in this run</div>", unsafe_allow_html=True)
    b["timeline"].altair_chart(timeline_chart(sess.frames, subsystem), **_FULL)
    b["recs"].markdown(ui.card("Recommendations", ui.ulist(frame["recommendations"] or ["none"])), unsafe_allow_html=True)
    e = frame.get("explanation")
    if e:
        b["expl"].markdown(ui.card("Why the model decided this", (
            f"<div class='ivhm-sub' style='color:#e2e8f0'>Predicted <b>{ui.esc(e['predicted'])}</b>, confidence "
            f"<b>{e['confidence']:.2f}</b>.</div><div class='ivhm-sub'>vibration: {ui.esc(', '.join(e['vib']))}<br>"
            f"current: {ui.esc(', '.join(e['cur']))}<br>gate: {ui.esc(', '.join(e['gate']))}</div>"
            f"<div class='ivhm-sub'>Faithfulness drop: vibration {e['drop_vib']:.2f}, current {e['drop_cur']:.2f}.</div>")),
            unsafe_allow_html=True)
    elif subsystem == "gearbox":
        b["expl"].markdown(ui.card("Why the model decided this", "<div class='ivhm-sub'>Per-window explanations are "
                                   "implemented for the bearing model only; the gearbox shows class probabilities, "
                                   "sensor quality reasons and fusion weights.</div>"), unsafe_allow_html=True)
    ev = [{"ts": f["ts"], "from_state": e_["from_state"], "to_state": e_["to_state"], "rule": e_["rule"],
           "asset": sess.asset} for f in sess.frames for e_ in [f.get("event")] if e_]
    b["events"].markdown(ui.card(f"Event history ({len(ev)} state changes in this run; full log: History & Reports, "
                                 f"asset {ui.esc(sess.asset)})", ui.event_table(sess.store.events(sess.asset))),
                         unsafe_allow_html=True)
