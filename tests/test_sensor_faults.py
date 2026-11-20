import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.sensor_faults import SCENARIOS, inject


class SensorFaultTests(unittest.TestCase):
    def test_scenarios_are_seeded_and_leave_source_intact(self):
        x = np.sin(np.arange(12800) * 0.123) + 0.3
        original = x.copy()
        for family in SCENARIOS:
            with self.subTest(family=family):
                a = inject(x, family, np.random.default_rng(9), 12800)
                b = inject(x, family, np.random.default_rng(9), 12800)
                np.testing.assert_array_equal(a, b)
                self.assertEqual(a.shape, x.shape)
                self.assertTrue(np.isfinite(a).all())
                self.assertFalse(np.array_equal(a, x))
        np.testing.assert_array_equal(x, original)

    def test_physical_effects(self):
        fs = 12800
        x = np.sin(np.arange(fs) * 0.123) + 0.3

        def fault(name):
            return inject(x, name, np.random.default_rng(9), fs)

        self.assertTrue(np.all(fault("dropout") == 0))
        self.assertTrue(np.all(fault("stuck") == x[0]))
        self.assertTrue(0.15 < np.mean(fault("intermittent") == 0) <= 0.2)
        self.assertAlmostEqual(np.max(np.abs(fault("clipping"))), 0.2 * np.max(np.abs(x)))
        noise = fault("noise") - x
        self.assertAlmostEqual(10 * np.log10(np.mean(x**2) / np.mean(noise**2)), 0, delta=0.2)
        np.testing.assert_allclose(np.diff(fault("gain")), 2 * np.diff(x))
        self.assertTrue(90 <= np.count_nonzero(fault("spikes") != x) <= 100)
