# Data-leakage risks and how this repo blocks them

| Risk | Why it inflates results | Guard in this repo | Where |
|---|---|---|---|
| Windows of one recording in train and test | Neighbouring windows are near-copies | Splits are by **bearing**, so every window of a recording stays on one side | `splits.py`, `experiment.run` → `assert_disjoint` |
| Same bearing in train and test (other repetition or condition) | Bearing-specific signatures (mounting, damage shape) are memorised; audits found this inflates PU accuracy by tens of points | P1/P2 never share a bearing; unit test checks every fold | `tests/test_pipeline.py::TestSplits` |
| Normalisation fitted on all data | Test statistics leak into training | Scaler lives inside each model's sklearn pipeline, fitted per training fold | `models.make_expert` |
| Gate or stacker trained on in-sample expert outputs | Experts look over-confident on their own training data, so the gate learns the wrong trust | Gate and stacker are fit on **out-of-fold** expert outputs from bearing-grouped inner folds | `models._LateBase._oof` |
| Feature extraction using dataset statistics | Same as normalisation | Features use one window only | `features.py` |
| Hyperparameters tuned on test bearings | Optimistic selection | Hyperparameters frozen in `SPEC.md` before full runs | `SPEC.md §4` |
| Corruptions used for training reused for testing | Robustness looks better than it is | Clipping, spikes, stuck values are never used for augmentation | `corruption.HELD_OUT_FAMILIES` |
| Artificial and real damage of the "same" kind mixed into test | Artificial faults are easier | Artificial bearings are training-only in P1 | `splits.p1_folds` |
| Dashboard replays training bearings | Demo shows memorisation | Demo model saves its held-out list; dashboard only lists those bearings | `train_demo_model.py`, `app/dashboard.py` |

Remaining, unavoidable: only 6 healthy bearings exist, so each test fold holds 2. Report per-bearing results and expect wide intervals.
