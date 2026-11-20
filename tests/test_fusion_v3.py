"""Rules of the OB2 gating-research fusion (fusion_v3.combine) on hand-made inputs."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.fusion_v3 import GRIDS, METHODS, combine  # noqa: E402


def _pack(ev, ec, fv, fc):
    n = len(ev)
    return {"pv": np.tile([0.8, 0.1, 0.1], (n, 1)), "pc": np.tile([0.1, 0.8, 0.1], (n, 1)),
            "g": np.tile([0.5, 0.5], (n, 1)), "ev": np.array(ev, float), "ec": np.array(ec, float),
            "fv": np.array(fv, bool), "fc": np.array(fc, bool),
            "skill": np.array([[0.4, 0.3], [0.1, 0.05]]), "prior": np.array([1 / 3] * 3)}


class TestFusionV3(unittest.TestCase):
    def test_failed_sensor_excluded_and_dual_failure_abstains(self):
        k = _pack([1e6, 0, 1e6, 0], [0, 1e6, 1e6, 0], [1, 0, 1, 0], [0, 1, 1, 0])
        for m in METHODS:
            for prm in GRIDS[m]:
                p, ab, w = combine(m, prm, k)
                self.assertEqual(w[0, 0], 0.0); self.assertEqual(p[0].argmax(), 1)   # vib dead -> current
                self.assertEqual(w[1, 1], 0.0); self.assertEqual(p[1].argmax(), 0)   # cur dead -> vibration
                self.assertEqual(ab.tolist(), [False, False, True, False])
                self.assertTrue(np.allclose(p.sum(1), 1))

    def test_mild_degradation_is_kept(self):
        k = _pack([0.5], [0.0], [0], [0])
        self.assertGreater(combine("soft", 10.0, k)[2][0, 0], 0.4)
        self.assertGreater(combine("strength", 1.0, k)[2][0, 0], 0.5)       # degraded vib still stronger
        self.assertEqual(combine("severity", 1.0, k)[2][0, 0], 0.5)         # below theta: gate decides
        self.assertEqual(combine("severity", 0.25, k)[2][0, 0], 0.0)        # above theta: excluded

    def test_extreme_severity_without_failure_never_abstains(self):
        k = _pack([1e6], [1e6], [0], [0])
        for m in METHODS:
            p, ab, w = combine(m, GRIDS[m][0], k)
            self.assertFalse(ab[0]); self.assertTrue(np.isfinite(p).all())


if __name__ == "__main__":
    unittest.main()
