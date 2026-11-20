"""OB4 interactive 3D view: the GLB geometry against the parametric CAD model, and the viewer's arguments against
the replay frames they are derived from.

* GLB tests run wherever cad/out/ivhm_drivetrain.glb exists (written on the project PC by cad/export_glb.py from the
  verified STEP export). They check every node's identity (part, component, sensor id, mount, explode offset) and its
  tessellated extents against pufusion.drivetrain_cad - an independent check of the FreeCAD -> STEP -> GLB chain.
* cad3d_args tests check that every value the viewer displays comes from the frame (no hard-coded state or value).
"""
import hashlib
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "app", ROOT / "src", Path(__file__).resolve().parent):
    sys.path.insert(0, str(p))

from pufusion import drivetrain_cad as D  # noqa: E402
from pufusion import glb  # noqa: E402

GLB = ROOT / "cad" / "out" / "ivhm_drivetrain.glb"
REPORT = ROOT / "cad" / "out" / "glb_export_report.json"
HAVE_GLB = GLB.exists()
TOL = 0.15 + 0.05            # linear deflection of the export + the build's bbox tolerance (mm)


class TestGlbWriter(unittest.TestCase):
    def test_round_trip(self):
        import tempfile
        nodes = [{"name": "a", "extras": {"kind": "part", "component": "x"}, "material": 0,
                  "positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "normals": [0, 0, 1] * 3, "indices": [0, 1, 2],
                  "lines": [0, 0, 0, 1, 0, 0]}]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.glb"
            glb.write_glb(str(path), nodes, [{"name": "m", "rgb": (1, 0, 0)}], {"units": "mm"})
            doc, binary = glb.read_glb(str(path))
        mesh_nodes = [n for n in doc["nodes"] if "mesh" in n]
        self.assertEqual([n["name"] for n in mesh_nodes], ["a"])
        pos, nrm, idx, lines = glb.node_geometry(doc, binary, mesh_nodes[0])
        self.assertEqual((pos, idx, lines), ([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2], [0, 0, 0, 1, 0, 0]))
        self.assertEqual(doc["nodes"][-1]["children"], [0])                    # root node with the unit conversion


@unittest.skipUnless(HAVE_GLB, "cad/out/ivhm_drivetrain.glb not built (scripts/windows/export_glb.bat)")
class TestGlbAgainstCadModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.bin = glb.read_glb(str(GLB))
        cls.nodes = {n["name"]: n for n in cls.doc["nodes"] if "mesh" in n}
        cls.parts = {p["name"]: p for p in D.parts()}

    def geom(self, name):
        return glb.node_geometry(self.doc, self.bin, self.nodes[name])

    def test_one_node_per_solid_with_its_identity(self):
        expected = set(self.parts) | {f"{s['id']} {s['label']}" for s in D.SENSORS}
        self.assertEqual(set(self.nodes), expected)
        self.assertEqual(len(self.nodes), len(D.parts()) + len(D.SENSORS))
        for name, p in self.parts.items():
            ex = self.nodes[name]["extras"]
            self.assertEqual((ex["kind"], ex["part"], ex["component"]), ("part", name, p["component"]), name)
            self.assertEqual(ex["explode"], list(D.explode_offset(p)), name)
            self.assertEqual(ex.get("finish"), p["finish"], name)

    def test_sensor_identity_mount_and_explode(self):
        for s in D.SENSORS:
            ex = self.nodes[f"{s['id']} {s['label']}"]["extras"]
            self.assertEqual((ex["sensor_id"], ex["subsystem"], ex["code"], ex["mount"]),
                             (s["id"], s["subsystem"], s["code"], s["mount"]))
            mount_off = D.explode_offset(self.parts[s["mount"]])
            self.assertEqual(ex["explode"], [a + 40 * b for a, b in zip(mount_off, s["axis"])])

    def test_tessellated_extents_match_the_parametric_model(self):
        worst = 0.0
        for name, n in self.nodes.items():
            pos = self.geom(name)[0]
            got = [min(pos[0::3]), min(pos[1::3]), min(pos[2::3]), max(pos[0::3]), max(pos[1::3]), max(pos[2::3])]
            if n["extras"]["kind"] == "part":
                want = D.part_bbox(self.parts[name])
            else:
                want = D.bbox(D.resolve(next(s for s in D.SENSORS if s["id"] == n["extras"]["sensor_id"])["geom"]))
            dev = max(abs(a - b) for a, b in zip(got, want))
            worst = max(worst, dev)
            self.assertLessEqual(dev, TOL, name)
        self.assertLessEqual(worst, TOL)

    def test_sensor_markers_at_the_mapped_positions(self):
        for s in D.SENSORS:
            pos = self.geom(f"{s['id']} {s['label']}")[0]
            c = [(min(pos[k::3]) + max(pos[k::3])) / 2 for k in range(3)]
            for a, b in zip(c, D.sensor_position(s)):
                self.assertAlmostEqual(a, b, delta=TOL)

    def test_mesh_is_well_formed(self):
        for name in self.nodes:
            pos, nrm, idx, lines = self.geom(name)
            nv = len(pos) // 3
            self.assertEqual(len(nrm), len(pos), name)
            self.assertTrue(idx and len(idx) % 3 == 0 and max(idx) < nv, name)
            for i in range(0, len(nrm), 3 * 97):                       # sampled: unit normals
                self.assertAlmostEqual(math.sqrt(nrm[i] ** 2 + nrm[i + 1] ** 2 + nrm[i + 2] ** 2), 1.0, places=3)
        with_edges = {n for n in self.nodes if self.geom(n)[3]}                # B-rep feature edges
        self.assertEqual(with_edges, {n for n in self.nodes if "_ball_" not in n})   # spheres have only seams

    def test_export_report_matches_the_file(self):
        rep = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertTrue(rep["passed"])
        self.assertEqual(rep["matching"]["missing"], [])
        self.assertEqual(rep["glb_sha256"], hashlib.sha256(GLB.read_bytes()).hexdigest())
        self.assertEqual(self.doc["asset"]["extras"]["step_sha256"], rep["step_sha256"])


class TestViewerArgs(unittest.TestCase):
    """cad3d_args: what the 3D viewer shows is a function of the replay frame only."""

    @classmethod
    def setUpClass(cls):
        if "streamlit" not in sys.modules and importlib.util.find_spec("streamlit") is None:
            import fake_streamlit as F
            F.install()
        import testbed_view as TV
        import ui
        cls.TV, cls.ui = TV, ui

    def frame(self, state="WARNING", vib="failed", cur="ok", w_vib=0.0, w_cur=1.0, ok=True):
        return {"window": 5, "recording_window": 5, "ground_truth": "inner_race", "fault_label": "dropout on vib",
                "state": state, "rule": "some rule", "diagnosis_available": ok, "p_fault": float("nan") if not ok else 0.7,
                "fault_type": "inner_race", "probs": {"healthy": 0.3, "inner_race": 0.7} if ok else None,
                "status": {"vib": vib, "cur": cur},
                "reliability": {"vib": {"status": vib, "score": 0.0, "reasons": ["dead"]},
                                "cur": {"status": cur, "score": 0.93, "reasons": []}},
                "weights": {"vib": w_vib if ok else None, "cur": w_cur if ok else None}}

    def test_colours_and_values_come_from_the_frame(self):
        f = self.frame()
        a = self.TV.cad3d_args("bearing", f, model_url="model/x.glb")
        self.assertEqual(a["part_fill"], {"test_bearing": self.ui.STATE_COLOR["WARNING"]})
        self.assertEqual(a["sensor_fill"]["S1"], self.ui.REL_COLOR["failed"])
        self.assertEqual(a["sensor_fill"]["S2"], self.ui.REL_COLOR["ok"])
        self.assertEqual(a["sensor_fill"]["S3"], self.TV.INACTIVE)
        s1, s2, s3 = a["sensors"]["S1"], a["sensors"]["S2"], a["sensors"]["S3"]
        self.assertEqual((s1["status"], s1["score"], s1["reasons"], s1["weight"]), ("failed", 0.0, ["dead"], 0.0))
        self.assertEqual((s2["status"], s2["weight"]), ("ok", 1.0))
        self.assertEqual((s3["active"], s3["status"], s3["weight"]), (False, None, None))
        self.assertEqual((a["frame"]["state"], a["frame"]["p_fault"], a["frame"]["probs"]["inner_race"]), ("WARNING", 0.7, 0.7))
        self.assertEqual(a["monitored"], ["test_bearing"])
        self.assertEqual(a["other_monitored"], ["gearbox"])

    def test_no_frame_no_state(self):
        a = self.TV.cad3d_args("gearbox", None, model_url="model/x.glb")
        self.assertIsNone(a["frame"])
        self.assertEqual(a["part_fill"], {})
        self.assertTrue(all(a["sensors"][k]["status"] is None for k in a["sensors"]))

    def test_abstention_is_shown_as_such_and_json_safe(self):
        a = self.TV.cad3d_args("bearing", self.frame("SENSOR_FAULT", "failed", "failed", ok=False), model_url="m")
        self.assertFalse(a["frame"]["diagnosis_available"])
        self.assertIsNone(a["frame"]["probs"])
        self.assertIsNone(a["frame"]["p_fault"])                      # NaN never reaches the browser
        self.assertIsNone(a["sensors"]["S1"]["weight"])
        self.assertEqual(a["part_fill"], {"test_bearing": self.ui.STATE_COLOR["SENSOR_FAULT"]})
        json.dumps(a, allow_nan=False)

    def test_viewer_files_present_and_self_contained(self):
        comp = ROOT / "app" / "cad3d_component"
        html = (comp / "index.html").read_text(encoding="utf-8")
        js = (comp / "viewer.js").read_text(encoding="utf-8")
        self.assertIn('src="viewer.js"', html)
        for text in (html, js):                                          # no external code or data is loaded
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)
        self.assertIn("streamlit:componentReady", js)


if __name__ == "__main__":
    unittest.main()
