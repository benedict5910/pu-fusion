"""Tests for the OB2 corrected detector (reliability_v2) and the GatedV2 fusion rule."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pufusion.corruption import HELD_OUT_FAMILIES, TRAIN_FAMILIES  # noqa: E402
from pufusion.reliability import ReliabilityAssessor  # noqa: E402
from pufusion.reliability_v2 import (CONT, FAILED, OK, ConditionAwareAssessor, V2Config,  # noqa: E402
                                     _seen_tags, apply_baseline, build_baselines, repetition)

RNG = np.random.default_rng(0)


def _q(n, center, spread=0.05):
    q = np.zeros((n, 7))
    q[:, CONT] = center + spread * RNG.standard_normal((n, 4))
    return q


class TestV2Detector(unittest.TestCase):
    def test_original_class_unchanged(self):
        # the dashboard's v1 assessor keeps its documented defaults
        a = ReliabilityAssessor()
        self.assertEqual((a.q_lo, a.q_hi, a.margin), (0.5, 99.5, 0.25))

    def test_hard_rules_kept(self):
        A = ConditionAwareAssessor(V2Config("box", False)).fit(_q(300, 0.0), np.array(["c"] * 300))
        q = _q(1, 0.0)
        q[0, 1] = 1.0                                    # 100 % flat = dead/stuck
        self.assertEqual(A.status(q, np.array(["c"]))[0], FAILED)

    def test_per_condition_catches_shift_pooled_misses(self):
        # two conditions with very different normal levels; a shift that stays inside the
        # pooled range but is far outside its own condition's range
        Q = np.vstack([_q(400, 0.0), _q(400, 1.0)])
        cond = np.array(["a"] * 400 + ["b"] * 400)
        probe = _q(50, 0.5)
        pooled = ConditionAwareAssessor(V2Config("box", False)).fit(Q, cond)
        per = ConditionAwareAssessor(V2Config("box", True)).fit(Q, cond)
        pc = np.array(["a"] * 50)
        self.assertLess(pooled.flagged(probe, pc).mean(), 0.1)
        self.assertGreater(per.flagged(probe, pc).mean(), 0.9)

    def test_clean_false_flags_low_on_training_like_data(self):
        Q, cond = _q(500, 0.3), np.array(["a"] * 500)
        for cfg in (V2Config("box", True), V2Config("maha", True, alpha=99.5)):
            A = ConditionAwareAssessor(cfg).fit(Q, cond)
            self.assertLess(A.flagged(_q(500, 0.3), cond).mean(), 0.05, cfg.name)

    def test_baseline_deviation_and_missing_baseline_is_flagged(self):
        tab = {"bearing": np.array(["B1"] * 4), "condition": np.array(["c"] * 4),
               "stem": np.array(["N15_M07_F10_K001_1", "N15_M07_F10_K001_1", "N15_M07_F10_K001_2",
                                 "N15_M07_F10_K001_2"]), "qv": _q(4, 2.0, 0.0)}
        bl = build_baselines(tab, "qv")
        dev = apply_baseline(tab["qv"], tab["bearing"], tab["condition"], bl)
        self.assertTrue(np.allclose(dev[:, CONT], 0.0))
        miss = apply_baseline(tab["qv"][:1], np.array(["B2"]), np.array(["c"]), bl)
        self.assertTrue(np.isnan(miss[:, CONT]).all())
        cfg = V2Config("box", False, baseline=True)
        A = ConditionAwareAssessor(cfg).fit(_q(300, 0.0), np.array(["c"] * 300))
        self.assertNotEqual(A.status(miss, np.array(["c"]))[0], OK)

    def test_repetition_parse(self):
        self.assertEqual(list(repetition(["N15_M07_F10_KI18_1", "N09_M07_F10_K004_17"])), [1, 17])

    def test_selection_never_uses_withheld_families(self):
        tags = np.array([f"vib:{f}:x" for f in TRAIN_FAMILIES + HELD_OUT_FAMILIES])
        seen = _seen_tags(tags)
        self.assertTrue(seen[: len(TRAIN_FAMILIES)].all())
        self.assertFalse(seen[len(TRAIN_FAMILIES):].any())


class TestGatedV2Rule(unittest.TestCase):
    def test_exclusion_and_abstain(self):
        from pufusion.fusion_v2 import GatedV2

        class Stub(GatedV2):
            def __init__(self):
                self.prior = np.array([0.2, 0.3, 0.5])

            def _probs(self, t):
                n = len(t["y"])
                return np.tile([1.0, 0.0, 0.0], (n, 1)), np.tile([0.0, 0.0, 1.0], (n, 1))

            def weights(self, t, pv=None, pc=None):
                return np.full((len(t["y"]), 2), 0.5)

            def flags(self, t):
                return np.array([False, True, False, True]), np.array([False, False, True, True])

        p, ab = Stub().predict_with_abstain({"y": np.zeros(4, int)})
        self.assertTrue(np.allclose(p[0], [0.5, 0.0, 0.5]))       # both ok -> learned gate
        self.assertTrue(np.allclose(p[1], [0.0, 0.0, 1.0]))       # vib flagged -> current only
        self.assertTrue(np.allclose(p[2], [1.0, 0.0, 0.0]))       # cur flagged -> vibration only
        self.assertEqual(list(ab), [False, False, False, True])   # both flagged -> abstain


if __name__ == "__main__":
    unittest.main()
