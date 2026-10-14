# Reliability-gated vibration–current fusion (Paderborn bearing data)

Final-year project code. Research question, protocol and plan: **[SPEC.md](SPEC.md)**. Leakage guards: **[docs/LEAKAGE.md](docs/LEAKAGE.md)**.

**No experimental results exist yet.** The only numbers this repo has produced come from `pufusion/synthetic.py`, which is for testing code and is labelled SYNTHETIC everywhere it appears.

## Layout
```
src/pufusion/   config (dataset metadata), data (loader), features, corruption,
                dataset (feature tables), splits, models, metrics, experiment
scripts/        download_pu.py, build_features.py, run_experiments.py,
                summarize.py, train_demo_model.py
app/            dashboard.py (Streamlit replay on held-out bearings)
tests/          unit tests (stdlib unittest; pytest also works)
```

## Quick start
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v                    # 18 tests

# 1. data (run on your own machine; ~1.9 GB starter, ~5.1 GB all)
python scripts/download_pu.py --subset starter

# 2. features (8 windows/file; ~80 ms per window per core)
python scripts/build_features.py --raw data/raw --out data/features.npz --jobs 4

# 3. experiments
python scripts/run_experiments.py --features data/features.npz --protocol p1 --models all --out results/p1.csv
python scripts/summarize.py results/p1.csv

# 4. demo
python scripts/train_demo_model.py --features data/features.npz --holdout K004 KA22 KI18
streamlit run app/dashboard.py -- --models models/demo_models.pkl --raw data/raw
```
With the starter subset, P1 keeps only folds whose test set still contains all three classes.

## Data licence
Paderborn KAt-DataCenter data are CC BY-NC 4.0. Cite Lessmeier et al. (PHME 2016) and the KAt-DataCenter. Do not commit raw data.
