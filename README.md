# Sensor-fault-tolerant bearing health monitoring (IVHM prototype)

Final-year IVHM project. System scope, hardware, plan: **[IVHM_SPEC.md](IVHM_SPEC.md)**. Research protocol: **[SPEC.md](SPEC.md)**. Leakage guards: **[docs/LEAKAGE.md](docs/LEAKAGE.md)**.

**No experimental results exist yet.** The only numbers this repo has produced come from `pufusion/synthetic.py`, which is for testing code and is labelled SYNTHETIC everywhere it appears.

## Layout
```
src/pufusion/   config, data (loader), features, corruption, dataset, splits, models,
                metrics, experiment            <- benchmark research
                reliability, explain, health, store, rig, monitor   <- IVHM layer
scripts/        run_all.py (one command), download_pu.py, build_features.py,
                run_experiments.py, summarize.py, train_demo_model.py,
                rig_record.py, rig_train.py
firmware/       rig_esp32/rig_esp32.ino (ESP32 streamer; not yet flashed)
app/            dashboard.py (Streamlit: benchmark replay | rig simulated | rig live)
tests/          unit tests (stdlib unittest; pytest also works)
```

## Quick start
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v          # 31 tests

# Benchmark study, one command (download -> features -> P1/P2/P3/leaky -> summary -> demo model)
python scripts/run_all.py                         # starter subset, ~1.9 GB (Windows: scripts\windows\pu_download.bat, then --skip-download)
python scripts/run_all.py --subset all            # full dataset, ~5.1 GB, final results

# Rig (or --simulate without hardware)
python scripts/rig_record.py --calibrate-zero --port COM5     # motor off
python scripts/rig_record.py --port COM5 --session H1 --label healthy --minutes 5
python scripts/rig_train.py --fit H1 --cal H2 --test-healthy H3 --test-fault F1 F2

streamlit run app/dashboard.py
```
With the starter subset, P1 keeps only folds whose test set still contains all three classes.

## Data licence
Paderborn KAt-DataCenter data are CC BY-NC 4.0. Cite Lessmeier et al. (PHME 2016) and the KAt-DataCenter. Do not commit raw data.
