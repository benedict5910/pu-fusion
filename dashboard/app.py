"""IVHM bearing-health dashboard (OB3).

Replays *recorded* Paderborn windows from bearings held out of model training, through the
gated-fusion model and the health policy. Sensor faults can be injected (pre-computed
corruption variants of the same windows). History is logged to SQLite; CSV/HTML reports export.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations
import json
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from health.engine import PortableModel, HealthPolicy, CLASSES, ADVICE  # noqa: E402
from health.store import Store, html_report, csv_bytes  # noqa: E402
from pu.features import VIB_NAMES, CUR_NAMES, Q_NAMES, SEEN, WITHHELD  # noqa: E402

DEMO = ROOT / "demo"
QV = [f"qv_{q}" for q in Q_NAMES]
QC = [f"qc_{q}" for q in Q_NAMES]
STATE_STYLE = {"NORMAL": ("#1f7a3a", "NORMAL"), "WARNING": ("#b26a00", "WARNING"),
               "INSPECT": ("#b3261e", "INSPECT (latched)"),
               "SENSOR_FAULT": ("#5b4bb7", "SENSOR FAULT - diagnosis suspended")}

st.set_page_config(page_title="IVHM Bearing Health", layout="wide")


@st.cache_resource
def load():
    pm = PortableModel(str(DEMO / "model.json"))
    S = pd.read_csv(DEMO / "stream.csv.gz")
    return pm, S


@st.cache_resource
def store():
    return Store(str(DEMO / "health_history.sqlite"))


pm, S = load()
db = store()
ss = st.session_state
if "session" not in ss:
    ss.session = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    ss.policy = HealthPolicy()
    ss.i = 0
    ss.log = []

# ----------------------------------------------------------------------------- sidebar
st.sidebar.header("Replay source")
st.sidebar.caption(f"Data: {pm.meta['data_label']}. Model trained on "
                   f"{len(pm.meta['train_bearings'])} bearings; the bearings below were held out.")
labels = {b: f"{b} ({['healthy', 'outer race', 'inner race'][int(S[S.bearing == b].label.iloc[0])]})"
          for b in sorted(S.bearing.unique())}
bearing = st.sidebar.selectbox("Held-out bearing", list(labels), format_func=labels.get)
cond = st.sidebar.selectbox("Operating condition", sorted(S.condition.unique()))
st.sidebar.header("Sensor-fault injection")
inj_sensor = st.sidebar.selectbox("Sensor", ["none", "vib", "cur"],
                                  format_func={"none": "No injection", "vib": "Vibration",
                                               "cur": "Motor current"}.get)
inj_kind = st.sidebar.selectbox("Fault type", SEEN + WITHHELD,
                                format_func=lambda k: k + ("  (withheld from training)" if k in WITHHELD else ""),
                                disabled=inj_sensor == "none")
key = (bearing, cond)
if ss.get("key") != key:
    ss.key = key
    ss.i = 0
    ss.policy = HealthPolicy()
    ss.log = []
    db.action(ss.session, "select_stream", f"{bearing} {cond}")

clean = S[(S.bearing == bearing) & (S.condition == cond) & (S.variant == "clean")] \
    .sort_values(["run", "win"]).reset_index(drop=True)
n_total = len(clean)


def window_row(i):
    r = clean.iloc[i]
    if inj_sensor == "none":
        return r, "clean"
    m = S[(S.file == r.file) & (S.win == r.win) & (S.variant == inj_kind) & (S.corrupted == inj_sensor)]
    return (m.iloc[0], f"{inj_kind}@{inj_sensor}") if len(m) else (r, "clean")


def step():
    if ss.i >= n_total:
        return
    r, inj = window_row(ss.i)
    d = pd.DataFrame([r])
    o = pm.predict(d[VIB_NAMES].to_numpy(float), d[CUR_NAMES].to_numpy(float),
                   d[QV].to_numpy(float), d[QC].to_numpy(float))
    P = o["P"][0]
    rv = not (o["flag_v"][0] or o["dead_v"][0])
    rc = not (o["flag_c"][0] or o["dead_c"][0])
    e = float(1 - P[0])
    res = ss.policy.step(e, rv, rc)
    k = int(P.argmax())
    reasons = pm.explain(d[VIB_NAMES].iloc[0].to_numpy(float), d[CUR_NAMES].iloc[0].to_numpy(float),
                         k if k else int(np.argmax(P[1:]) + 1), o["w_v"][0], o["w_c"][0]) \
        if res["state"] != "SENSOR_FAULT" else []
    adv = ADVICE[k] if k and res["state"] in ("WARNING", "INSPECT") else "No maintenance action; continue monitoring."
    if not rv:
        adv += " " + ADVICE["vib"]
    if not rc:
        adv += " " + ADVICE["cur"]
    rec = dict(session=ss.session, source="paderborn-replay", stream=f"{bearing} {cond}", window=ss.i,
               state=res["state"], mode=res["mode"], evidence=e, predicted=CLASSES[k],
               p_healthy=float(P[0]), p_outer=float(P[1]), p_inner=float(P[2]),
               w_vib=float(o["w_v"][0]), w_cur=float(o["w_c"][0]), vib_reliable=int(rv),
               cur_reliable=int(rc), injected=inj, reasons=[list(x) for x in reasons], advice=adv)
    db.log(**rec)
    rec["Sv"], rec["Sc"] = o["Sv"][0], o["Sc"][0]
    ss.log.append(rec)
    ss.i += 1


# ----------------------------------------------------------------------------- header + controls
st.title("IVHM bearing health monitor")
st.caption("Component-level prototype. Replay of recorded Paderborn windows (0.5 s each) through the "
           "reliability-gated vibration-current model. Advisory only.")
c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 2])
if c1.button("Step 1 window"):
    step()
if c2.button("Run 10 windows"):
    for _ in range(10):
        step()
if c3.button("Acknowledge INSPECT"):
    ss.policy.acknowledge()
    db.action(ss.session, "acknowledge", f"window {ss.i}")
if c4.button("Reset stream"):
    ss.i, ss.policy, ss.log = 0, HealthPolicy(), []
    db.action(ss.session, "reset", f"{bearing} {cond}")
c5.progress(ss.i / max(n_total, 1), text=f"Window {ss.i} / {n_total}")

if not ss.log:
    st.info("Press **Step** or **Run 10 windows** to start the replay.")
    st.stop()

last = ss.log[-1]
color, text = STATE_STYLE[last["state"]]
st.markdown(f"<div style='padding:14px 18px;border-radius:8px;background:{color};color:white;"
            f"font-size:26px;font-weight:600'>{text}</div>", unsafe_allow_html=True)
st.write(f"**Mode:** {last['mode']}  ·  **Injected:** {last['injected']}  ·  "
         f"**Latched INSPECT pending acknowledgement:** {ss.policy.latched}")

a, b, c = st.columns(3)
a.metric("Fault evidence (1 - P healthy)", f"{last['evidence']:.2f}")
b.metric("Most likely condition", last["predicted"])
c.metric("Gate weight vibration / current", f"{last['w_vib']:.2f} / {last['w_cur']:.2f}")

L = pd.DataFrame(ss.log)
left, right = st.columns([3, 2])
with left:
    st.subheader("Evidence history")
    ch = L[["window", "evidence"]].set_index("window")
    ch["WARNING threshold"] = 0.5
    ch["INSPECT threshold"] = 0.8
    st.line_chart(ch, height=240)
    st.subheader("Class probabilities")
    st.bar_chart(pd.DataFrame({"probability": [last["p_healthy"], last["p_outer"], last["p_inner"]]},
                              index=["healthy", "outer race", "inner race"]), height=200)
with right:
    st.subheader("Sensor reliability (label-free)")
    for nm, ok, sc in (("Vibration", last["vib_reliable"], last["Sv"]),
                       ("Motor current", last["cur_reliable"], last["Sc"])):
        bad = [Q_NAMES[j] for j in np.where(sc > 0)[0]]
        st.write(("✅ " if ok else "⚠️ ") + f"**{nm}**: " +
                 ("reliable" if ok else "unreliable - " + ", ".join(bad)))
    st.subheader("Why (top feature contributions)")
    if last["reasons"]:
        st.dataframe(pd.DataFrame(last["reasons"], columns=["feature", "meaning", "contribution"]),
                     hide_index=True)
    else:
        st.write("Diagnosis suspended - no explanation.")
    st.subheader("Advice")
    st.write(last["advice"])

st.subheader("Logged history (SQLite)")
ev = db.events(ss.session)
st.dataframe(ev[["ts", "stream", "window", "state", "mode", "evidence", "predicted", "w_vib",
                 "w_cur", "injected"]].tail(200), hide_index=True)
prov = (f"Source: replay of recorded windows ({pm.meta['data_label']}); bearings "
        f"{', '.join(pm.meta['test_bearings'])} were not used to train the model.")
d1, d2 = st.columns(2)
d1.download_button("Download history CSV", csv_bytes(ev), f"health_history_{ss.session}.csv", "text/csv")
d2.download_button("Download HTML report",
                   html_report(ev, db.actions(ss.session), f"Bearing health report - session {ss.session}", prov),
                   f"health_report_{ss.session}.html", "text/html")
