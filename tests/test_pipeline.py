"""Unit tests. Run:  python -m unittest discover -s tests -v   (pytest also works)."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import scipy.io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pufusion import corruption as C  # noqa: E402
from pufusion.config import BEARINGS, N_BALLS, fault_frequencies, parse_filename  # noqa: E402
from pufusion.data import load_mat  # noqa: E402
from pufusion.dataset import TableBuilder, process_recording  # noqa: E402
from pufusion.experiment import run  # noqa: E402
from pufusion.features import current_features, quality_indicators, vibration_features  # noqa: E402
from pufusion.models import ReliabilityGated, model_zoo  # noqa: E402
from pufusion.splits import assert_disjoint, p1_folds, p2_folds  # noqa: E402
from pufusion.synthetic import synth_recording  # noqa: E402

FS = 64_000


def _small_tables(bearings, reps=1, n_aug=1, win=0.25):
    b = {k: TableBuilder() for k in ("clean", "aug", "corr")}
    grid = [("vib", "dropout", None), ("cur", "noise", 0), ("vib", "clipping", 0.2)]
    for bear in bearings:
        for cond in ("N15_M07_F10", "N09_M07_F10"):
            for r in range(1, reps + 1):
                rec = synth_recording(bear, cond, r, seconds=0.5)
                process_recording(rec, b, win_s=win, n_aug=n_aug, eval_windows=1, grid=grid)
    return {k: v.arrays() for k, v in b.items()}


class TestConfig(unittest.TestCase):
    def test_fault_frequencies(self):
        ff = fault_frequencies(1500)
        self.assertAlmostEqual(ff["fr"], 25.0)
        self.assertAlmostEqual(ff["bpfo"] + ff["bpfi"], N_BALLS * ff["fr"], places=6)
        self.assertLess(ff["bpfo"], ff["bpfi"])

    def test_parse(self):
        self.assertEqual(parse_filename("N15_M07_F10_KA01_3"),
                         {"condition": "N15_M07_F10", "bearing": "KA01", "repetition": 3})
        with self.assertRaises(ValueError):
            parse_filename("N99_M07_F10_KA01_3")

    def test_bearing_counts(self):
        origins = [o for _, o in BEARINGS.values()]
        self.assertEqual(origins.count("healthy"), 6)
        self.assertEqual(origins.count("artificial"), 12)
        self.assertEqual(origins.count("real"), 11)   # 14 real minus 3 combined (KB*)


class TestSplits(unittest.TestCase):
    def test_p1_disjoint_and_complete(self):
        folds = p1_folds(n_repeats=3)
        for f in folds:
            assert_disjoint(f["train"], f["test"])
            self.assertFalse(any(BEARINGS[b][1] == "artificial" for b in f["test"]))
            self.assertEqual({BEARINGS[b][0] for b in f["test"]}, {0, 1, 2})
        # each test-pool bearing is tested exactly once per repeat
        for r in range(3):
            tested = [b for f in folds if f["name"].startswith(f"P1_r{r}_") for b in f["test"]]
            self.assertEqual(len(tested), len(set(tested)))
            self.assertEqual(len(tested), 17)

    def test_p2(self):
        for f in p2_folds():
            assert_disjoint(f["train"], f["test"])

    def test_run_refuses_leaky_fold(self):
        t = _small_tables(["K001", "KA04", "KI04"])
        bad = [{"name": "bad", "train": ["K001", "KA04", "KI04"], "test": ["K001", "KA04", "KI04"]}]
        with self.assertRaises(AssertionError):
            run(t, bad, model_zoo()[:1], log=lambda *_: None)


class TestCorruption(unittest.TestCase):
    def setUp(self):
        self.x = np.sin(np.linspace(0, 200, 32000)).astype(np.float32)

    def test_families_partitioned(self):
        self.assertFalse(set(C.TRAIN_FAMILIES) & set(C.HELD_OUT_FAMILIES))

    def test_deterministic(self):
        a = C.apply(self.x, "noise", 0, np.random.default_rng(1))
        b = C.apply(self.x, "noise", 0, np.random.default_rng(1))
        np.testing.assert_array_equal(a, b)

    def test_snr(self):
        y = C.apply(self.x, "noise", 10, np.random.default_rng(0))
        snr = 10 * np.log10(np.mean(self.x ** 2) / np.mean((y - self.x) ** 2))
        self.assertAlmostEqual(snr, 10, delta=0.3)

    def test_dropout_and_stuck(self):
        self.assertTrue(np.all(C.apply(self.x, "dropout", None, np.random.default_rng(0)) == 0))
        two = np.stack([self.x, self.x + 1])
        s = C.apply(two, "stuck", None, np.random.default_rng(0))
        self.assertTrue(np.all(s[1] == two[1, 0]))


class TestFeatures(unittest.TestCase):
    def setUp(self):
        rec = synth_recording("KA04", "N15_M07_F10", 1, seconds=0.5)
        self.v, self.c = rec.vib, rec.cur

    def test_finite_under_all_corruptions(self):
        rng = np.random.default_rng(0)
        for fam, (_, sevs) in C.FAMILIES.items():
            for s in sevs:
                v = C.apply(self.v, fam, s, rng)
                c = C.apply(self.c, fam, s, rng)
                for arr in (vibration_features(v, FS, 1500), current_features(c, FS, 1500),
                            quality_indicators(v, FS), quality_indicators(c, FS)):
                    self.assertTrue(np.all(np.isfinite(arr)), f"{fam}:{s}")

    def test_nan_samples(self):
        v = self.v.copy(); v[:100] = np.nan
        self.assertTrue(np.all(np.isfinite(vibration_features(v, FS, 1500))))
        self.assertGreater(quality_indicators(v, FS)[0], 0)

    def test_gain_invariance_of_spectral_bands(self):
        a = vibration_features(self.v, FS, 1500)
        b = vibration_features(3.0 * self.v, FS, 1500)
        np.testing.assert_allclose(a, b, atol=1e-3)

    def test_quality_flags_dead_channel(self):
        q_ok = quality_indicators(self.v, FS)
        q_dead = quality_indicators(np.zeros_like(self.v), FS)
        self.assertLess(q_ok[1], 0.1)
        self.assertGreater(q_dead[1], 0.95)


class TestLoader(unittest.TestCase):
    def test_load_paderborn_like_mat(self):
        n = 64000
        names = ["force", "phase_current_1", "phase_current_2", "speed",
                 "temp_2_bearing_module", "torque", "vibration_1"]
        dtype = [("Name", "O"), ("Type", "O"), ("Data", "O"), ("Raster", "O")]
        Y = np.zeros((1, len(names)), dtype=dtype)
        for i, nm in enumerate(names):
            Y[0, i] = (nm, "x", np.arange(n, dtype=float).reshape(1, -1) * (i + 1), "HostService")
        root = np.zeros((1, 1), dtype=[("Info", "O"), ("X", "O"), ("Y", "O"), ("Description", "O")])
        root[0, 0] = ("i", "x", Y, "d")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "N15_M07_F10_KA04_1.mat"
            scipy.io.savemat(p, {"N15_M07_F10_KA04_1": root})
            rec = load_mat(p)
        self.assertEqual(rec.bearing, "KA04")
        self.assertEqual(rec.label, BEARINGS["KA04"][0])
        self.assertEqual(rec.cur.shape, (2, n))
        self.assertEqual(rec.vib[1], 7.0)     # vibration_1 found by name, not position


class TestModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = _small_tables(["K001", "K002", "K003", "KA04", "KA15", "KA16",
                               "KI04", "KI14", "KI16"], reps=2)

    def test_all_models_output_distributions(self):
        for m in model_zoo():
            m.fit(self.t["clean"])
            p = m.predict_proba(self.t["corr"])
            self.assertEqual(p.shape, (len(self.t["corr"]["y"]), 3))
            np.testing.assert_allclose(p.sum(1), 1, atol=1e-6, err_msg=m.name)

    def test_gate_routes_away_from_dead_vibration(self):
        g = ReliabilityGated().fit(self.t["clean"])
        corr = self.t["corr"]
        m = corr["tag"] == "vib:dropout:None"
        w = g.weights({k: v[m] for k, v in corr.items()})
        np.testing.assert_allclose(w[:, 0], 0.0)

    def test_reproducible_tables(self):
        a = _small_tables(["K001"], n_aug=2)
        b = _small_tables(["K001"], n_aug=2)
        np.testing.assert_array_equal(a["aug"]["fv"], b["aug"]["fv"])



class TestMetricsConfusion(unittest.TestCase):
    def test_cm_counts(self):
        from pufusion.metrics import classification
        y = np.array([0, 0, 1, 2, 2, 2])
        p = np.eye(3)[[0, 1, 1, 2, 0, 2]]
        cm = np.array(classification(y, p)["cm"].split(), int).reshape(3, 3)
        self.assertEqual(cm.sum(), len(y))
        np.testing.assert_array_equal(cm, [[1, 1, 0], [0, 1, 0], [1, 0, 2]])

if __name__ == "__main__":
    unittest.main()
