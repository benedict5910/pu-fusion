import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.gearbox import (
    AXES, FS, SENSORS, condition_split, corrupt, discover, extract, fit_records, replay,
)


class GearboxTests(unittest.TestCase):
    def test_recording_holdout_and_shared_health_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rng = np.random.default_rng(10)
            for profile in ("1000rpm_10Nm", "2000rpm_10Nm"):
                for idx, label in enumerate(("health", "gear_pitting_M", "gear_wear_M"), 1):
                    t = np.arange(FS * 2) / FS
                    wave = idx * np.sin(2 * np.pi * (50 + idx * 70) * t)
                    frame = pd.DataFrame({
                        f"{sensor}_vibration_{axis}": wave + 0.03 * rng.normal(size=len(t))
                        for sensor in SENSORS for axis in AXES
                    })
                    frame.to_csv(root / f"{label}_torque_circulation_{profile}.csv.gz", index=False)
            records = discover(root)
            train, test = condition_split(records, "torque_circulation_2000rpm_10Nm")
            self.assertEqual((len(train), len(test)), (3, 3))
            self.assertFalse({r.id for r in train} & {r.id for r in test})
            self.assertFalse({r.condition for r in train} & {r.condition for r in test})
            with self.assertRaises(ValueError):
                condition_split(records, "absent profile")
            model = fit_records(train, {r.id: extract(r) for r in train})
            held_out = next(r for r in test if r.label == "gear_pitting")
            x, q = extract(held_out, "dropout", "motor")
            for row in replay(model, x, q):
                self.assertEqual((row["motor_weight"], row["gearbox_weight"]), (0, 1))
                self.assertIsNotNone(row["prediction"])
            x, q = extract(held_out, "dropout", "both")
            for row in replay(model, x, q):
                self.assertEqual(row["state"], "SENSOR_FAULT")
                self.assertIsNone(row["prediction"])
                self.assertIsNone(row["fault_score"])

    def test_fault_is_isolated_to_target_sensor(self):
        window = np.ones((2, 3, FS))
        faulty = corrupt(window, "dropout", "gearbox", np.random.default_rng(42))
        np.testing.assert_array_equal(window, 1)
        np.testing.assert_array_equal(faulty[0], 1)
        np.testing.assert_array_equal(faulty[1], 0)
