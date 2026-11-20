"""OB4 CAD model: geometry consistency, mechanical interference, and sensor-to-data mapping.

The sensor map is the link between the CAD model and the replay code, so these tests check it against the code
itself (channel names the loaders read, dictionary keys the monitoring code uses), not against a copy.
"""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pufusion import data as PD  # noqa: E402
from pufusion import drivetrain_cad as D  # noqa: E402
from pufusion import gearbox as G  # noqa: E402

FREECAD_REPORT = ROOT / "cad" / "out" / "freecad_report.json"


class TestSensorMap(unittest.TestCase):
    def test_four_sensors_two_per_subsystem(self):
        self.assertEqual([s["id"] for s in D.SENSORS], ["S1", "S2", "S3", "S4"])
        self.assertEqual(sorted(s["subsystem"] for s in D.SENSORS), ["bearing", "bearing", "gearbox", "gearbox"])

    def test_bearing_channels_are_the_ones_the_loader_reads(self):
        by_code = {s["code"]: s for s in D.SENSORS if s["subsystem"] == "bearing"}
        self.assertEqual(by_code["vib"]["channels"], [PD.VIB])
        self.assertEqual(tuple(by_code["cur"]["channels"]), PD.CUR)

    def test_gearbox_channels_are_the_ones_the_loader_reads(self):
        by_code = {s["code"]: s for s in D.SENSORS if s["subsystem"] == "gearbox"}
        self.assertEqual(set(by_code), set(G.SENSORS))
        for sensor in G.SENSORS:
            self.assertEqual(by_code[sensor]["channels"], [f"{sensor}_vibration_{a}" for a in G.AXES])

    def test_sample_rates(self):
        fs = {s["id"]: s["fs_hz"] for s in D.SENSORS}
        self.assertEqual(fs["S3"], G.FS)
        self.assertEqual(fs["S4"], G.FS)
        from pufusion.config import FS_HIGH
        self.assertEqual(fs["S1"], FS_HIGH)

    def test_each_sensor_sits_on_its_mount(self):
        parts = {p["name"]: p for p in D.parts()}
        for s in D.SENSORS:
            sb = D.bbox(D.resolve(s["geom"]))
            mb = D.part_bbox(parts[s["mount"]])
            gap = max(max(sb[k] - mb[k + 3], mb[k] - sb[k + 3], 0.0) for k in range(3))
            self.assertAlmostEqual(gap, 0.0, places=6, msg=f"{s['id']} not in contact with {s['mount']}")

    def test_sensors_mounted_on_the_monitored_component(self):
        comp = {p["name"]: p["component"] for p in D.parts()}
        self.assertEqual(comp[D.SENSORS[0]["mount"]], "test_bearing")       # S1 on the test-bearing housing
        self.assertEqual(comp[D.SENSORS[3]["mount"]], "gearbox")            # S4 on the gearbox housing
        self.assertEqual(comp[D.SENSORS[2]["mount"]], "motor")              # S3 on the motor frame
        self.assertEqual(D.SENSORS[1]["mount"], "motor_supply_cable")       # S2 on the supply cable

    def test_written_sensor_map_matches_the_model(self):
        p = ROOT / "cad" / "out" / "sensor_map.json"
        if not p.exists():
            self.skipTest("run cad/make_drawings.py first")
        self.assertEqual(json.loads(p.read_text()), json.loads(json.dumps(D.sensor_map())))

    def test_map_says_representative(self):
        note = D.sensor_map()["note"]
        self.assertIn("Representative", note)
        self.assertIn("two different rigs", note)


class TestGeometry(unittest.TestCase):
    def test_every_expression_evaluates(self):
        for p in D.parts():
            for pr in p["add"] + p["sub"]:
                r = D.resolve(pr)
                for k, v in r.items():
                    if k == "poly":
                        self.assertGreaterEqual(len(v), 3, p["name"])
                        self.assertTrue(all(math.isfinite(c) for uv in v for c in uv), f"{p['name']}.poly")
                    elif k not in ("type", "axis"):
                        self.assertTrue(math.isfinite(v), f"{p['name']}.{k}")
                dims = [r.get(k) for k in ("L", "W", "H", "r", "h", "ro", "ri", "width") if k in r]
                self.assertTrue(all(d > 0 for d in dims), p["name"])

    def test_no_unexpected_interference(self):
        res = D.interference_check(step=0.5)
        self.assertGreater(res["pairs_checked"], 150)
        self.assertEqual(res["unexpected"], [])

    def test_interference_check_detects_a_clash(self):
        params = dict(D.P)
        params["shoulder_d"] = 50.0                     # shaft shoulder larger than the housing bore
        clash = {frozenset((o["a"], o["b"])) for o in D.interference_check(0.5, params)["unexpected"]}
        self.assertIn(frozenset(("line_shaft", "test_bearing_housing")), clash)

    def test_shafts_coaxial_and_parts_on_the_base(self):
        parts = {p["name"]: p for p in D.parts()}
        h = D.P["shaft_h"]
        for n in ("motor_shaft", "line_shaft", "gearbox_input_shaft", "gearbox_output_shaft", "load_shaft"):
            bb = D.part_bbox(parts[n])
            self.assertAlmostEqual((bb[2] + bb[5]) / 2, h, places=6, msg=n)
        for n in ("motor_riser", "support_bearing_housing", "test_bearing_housing", "gearbox_plinth", "load_pedestal"):
            self.assertAlmostEqual(D.part_bbox(parts[n])[2], 0.0, places=6, msg=n)

    def test_gear_pair_centre_distance(self):
        parts = {p["name"]: p for p in D.parts()}
        pin = D.resolve(parts["pinion"]["add"][0])
        gw = D.resolve(parts["gear_wheel"]["add"][0])
        self.assertAlmostEqual(gw["y"] - pin["y"], D.P["gear_m"] * (D.P["z_pinion"] + D.P["z_gear"]) / 2)

    def test_parametric_change_propagates(self):
        params = dict(D.P)
        params["shaft_h"] = 150.0
        s1 = D.sensor_position(D.SENSORS[0], params)
        self.assertAlmostEqual(s1[2] - D.sensor_position(D.SENSORS[0])[2], 10.0)

    def test_freecad_expressions(self):
        self.assertEqual(D.freecad_expr("shaft_h + mot_d / 2"), "Params.shaft_h + Params.mot_d / 2")
        self.assertEqual(D.freecad_expr("brg_b_x - 8"), "Params.brg_b_x - 8")
        for name in D.P:                                        # aliases must not be FreeCAD unit names
            self.assertNotIn(name, {"h", "m", "s", "g", "t", "mm", "cm", "in", "ft", "deg", "rad", "N", "W"})

    def test_expression_evaluator_rejects_code(self):
        with self.assertRaises(ValueError):
            D.ev("__import__('os').system('x')")

    def test_design_checks(self):
        c = D.design_checks()
        self.assertAlmostEqual(c["motor_torque_Nm"], 1100 / (2 * math.pi * 25), places=2)
        self.assertEqual(c["gear_ratio"], 2.5)
        self.assertGreater(c["critical_speed_margin"], 3)


@unittest.skipUnless(FREECAD_REPORT.exists(), "FreeCAD model not built yet (cad/build_freecad.py)")
class TestFreeCADReport(unittest.TestCase):
    """Evidence from the FreeCAD build on the project PC: the B-rep model matches the parameter model."""

    @classmethod
    def setUpClass(cls):
        cls.r = json.loads(FREECAD_REPORT.read_text())

    def test_build_passed(self):
        self.assertTrue(self.r["passed"], self.r.get("errors"))

    def test_solids_valid_and_match_the_model(self):
        self.assertTrue(self.r["all_parts_valid"])
        self.assertEqual(self.r["recompute_invalid_objects"], [])
        self.assertLess(self.r["bbox_max_deviation_mm"], 0.05)
        self.assertEqual(len(self.r["parts"]), len(D.parts()))

    def test_sensors_match_and_touch_their_mounts(self):
        for s in self.r["sensors"]:
            self.assertLess(s["dev_mm"], 0.05, s["id"])
            self.assertLess(s["gap_to_mount_mm"], 0.05, s["id"])

    def test_no_unexpected_brep_interference(self):
        self.assertEqual(self.r["interference"]["unexpected"], [])

    def test_step_export_and_reimport(self):
        self.assertEqual(self.r["exports"]["STEP assembly"], "ok")
        self.assertLess(self.r["step_reimport"]["relative_difference"], 1e-3)

    def test_spreadsheet_edit_moves_dependent_parts(self):
        self.assertEqual(self.r["edit_test"]["moved_by_mm"], 10.0)


if __name__ == "__main__":
    unittest.main()
