"""Streamlit replay dashboard.

  pip install streamlit
  streamlit run app/dashboard.py -- --models models/demo_models.pkl --raw data/raw

Replays recorded Paderborn windows of bearings held out from training, lets you
inject sensor faults live, and shows per-sensor quality, fusion weights,
class probabilities and the k-of-n alarm. This is a replay demo, not live
hardware: the on-screen numbers are not field accuracy.
"""
import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion import corruption as C  # noqa: E402
from pufusion.config import CLASS_NAMES, OPERATING_CONDITIONS  # noqa: E402
from pufusion.data import find_mat_files, load_mat, windows  # noqa: E402
from pufusion.dataset import corrupt_pair, extract  # noqa: E402
from pufusion.features import QUALITY_NAMES  # noqa: E402
from pufusion.metrics import alarm_stream  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--models", default="models/demo_models.pkl")
ap.add_argument("--raw", default="data/raw")
args, _ = ap.parse_known_args()

st.set_page_config(page_title="Bearing health replay", layout="wide")
bundle = pickle.load(open(args.models, "rb"))
models, holdout = bundle["models"], bundle["holdout"]

files = [f for f in find_mat_files(args.raw) if f.stem.split("_")[3] in holdout]
if not files:
    st.error(f"No raw files for held-out bearings {holdout} under {args.raw}")
    st.stop()

with st.sidebar:
    st.header("Replay")
    f = st.selectbox("Recording (unseen bearing)", files, format_func=lambda p: p.stem)
    model_name = st.selectbox("Model", list(models), index=len(models) - 1)
    st.header("Inject sensor fault")
    target = st.radio("Sensor", ["none", "vib", "cur", "both"], horizontal=True)
    fam = st.selectbox("Fault type", list(C.FAMILIES))
    sevs = C.FAMILIES[fam][1]
    sev = st.select_slider("Severity", options=sevs, value=sevs[0]) if len(sevs) > 1 else sevs[0]
    speed = st.slider("Seconds per window", 0.1, 2.0, 0.5)

rec = load_mat(f)
rpm = OPERATING_CONDITIONS[rec.condition][0]
model = models[model_name]
st.title("Vibration + current bearing monitor (replay)")
st.caption(f"{rec.stem} · true class: **{CLASS_NAMES[rec.label]}** · bearing never seen in training")

c1, c2 = st.columns([3, 2])
sig_box, prob_box = c1.empty(), c2.empty()
q_box, alarm_box = st.empty(), st.empty()
history = []
for i, v, c in windows(rec):
    if target != "none":
        v, c = corrupt_pair(v, c, target, fam, sev, np.random.default_rng(i))
    feats = extract(v, c, rec.fs, rpm)
    t = {k: np.asarray(x)[None] for k, x in feats.items()}
    p = model.predict_proba(t)[0]
    history.append(1 - p[0])
    sig_box.line_chart({"vibration": v[:4000], "current A": c[0, :4000]})
    info = {"class probabilities": dict(zip(CLASS_NAMES, np.round(p, 3)))}
    if hasattr(model, "weights"):
        w = model.weights(t)[0]
        info["fusion weights"] = {"vibration": round(float(w[0]), 3), "current": round(float(w[1]), 3)}
    prob_box.json(info)
    q_box.dataframe({"indicator": QUALITY_NAMES, "vibration": feats["qv"], "current": feats["qc"]})
    on = alarm_stream(history)[-1]
    alarm_box.markdown(f"### {'🔴 FAULT ALARM' if on else '🟢 normal'} — window {i + 1}")
    time.sleep(speed)
