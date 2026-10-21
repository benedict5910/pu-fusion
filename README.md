# IVHM: robust vibration-current bearing fault diagnosis

B.Tech project (MSRUAS, CSE AI&ML). Component-level IVHM prototype:
(A) Paderborn benchmark, (B) ESP32 motor rig, (C) shared health layer + dashboard.

## Layout
```
pu/          benchmark: data loader, features, corruptions, quality, 6 models, protocols, figures, export
health/      OB3 health policy, explanations, SQLite store, reports, headless validation
dashboard/   Streamlit app (replays held-out Paderborn windows)
rig/         OB4 firmware (ESP32), serial protocol, logger, timing test, detector, synthetic stream simulator
tests/       synthetic .mat fixtures (code tests only)
```

## Run on Windows (from this folder)
```
pip install numpy scipy scikit-learn pandas matplotlib tabulate streamlit pyserial
python -m pu.extract  %USERPROFILE%\Downloads\paderborn\extracted  work\features --workers 4
python -m pu.experiments work\features results
python -m pu.figures results --label "REAL PADERBORN DATA"
python -m pu.export_demo work\features demo
python -m health.validate demo results\ob3
streamlit run dashboard\app.py
```

Data: Paderborn University KAt Bearing DataCenter (Lessmeier et al., 2016), CC BY-NC 4.0.
See `EVIDENCE_LOG.md` for what is validated and what isn't.
