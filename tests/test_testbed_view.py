"""OB4 CAD-linked testbed view: state synchronisation and playback controls through the dashboard script.

Headless (Streamlit stand-in) where real Streamlit is absent; tests/test_testbed_apptest.py runs the same flow on
the real Streamlit app. The CAD colours, sensor table and timeline are checked against the replay frame they were
drawn from, and the frame against an independent ReplaySession run (no value is hard-coded in the view).
"""
import importlib.util
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "app", ROOT / "src", Path(__file__).resolve().parent):
    sys.path.insert(0, str(p))

HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None
HAVE_DATA = (ROOT / "models" / "demo_models.pkl").exists() and (ROOT / "data" / "raw" / "KI18").exists()


class TestCadStateMapping(unittest.TestCase):
    """Pure functions of testbed_view: the colours come only from the frame."""

    @classmethod
    def setUpClass(cls):
        if not HAVE_STREAMLIT:
            import fake_streamlit as F
            F.install()
        import testbed_view as TV
        import ui
        cls.TV, cls.ui = TV, ui

    def frame(self, state, vib, cur):
        return {"state": state, "status": {"vib": vib, "cur": cur},
                "reliability": {"vib": {"status": vib, "score": 0.1, "reasons": []},
                                "cur": {"status": cur, "score": 0.9, "reasons": []}},
                "weights": {"vib": 0.0, "cur": 1.0}}

    def test_monitored_component_takes_the_health_state_colour(self):
        for state, col in self.ui.STATE_COLOR.items():
            cs = self.TV.cad_state("bearing", self.frame(state, "ok", "ok"))
            self.assertEqual(cs["part_fill"], {"test_bearing": col})

    def test_sensor_colours_follow_reliability_and_inactive_sensors_are_grey(self):
        cs = self.TV.cad_state("bearing", self.frame("WARNING", "failed", "degraded"))
        self.assertEqual(cs["sensor_fill"]["S1"], self.ui.REL_COLOR["failed"])
        self.assertEqual(cs["sensor_fill"]["S2"], self.ui.REL_COLOR["degraded"])
        self.assertEqual(cs["sensor_fill"]["S3"], self.TV.INACTIVE)
        self.assertEqual(cs["sensor_fill"]["S4"], self.TV.INACTIVE)

    def test_svg_contains_the_colours(self):
        f = self.frame("INSPECT", "failed", "ok")
        svg = self.TV.cad_svg("bearing", f)
        self.assertIn(self.ui.STATE_COLOR["INSPECT"], svg)
        self.assertIn(self.ui.REL_COLOR["failed"], svg)
        self.assertIn("REPRESENTATIVE", svg)
        import xml.etree.ElementTree as ET
        ET.fromstring(svg)

    def test_no_frame_no_state_colour(self):
        cs = self.TV.cad_state("gearbox", None)
        self.assertEqual(cs["part_fill"], {})


@unittest.skipUnless(HAVE_DATA, "held-out recordings / demo model not present")
@unittest.skipIf(HAVE_STREAMLIT, "real Streamlit present: covered by test_testbed_apptest")
class TestTestbedViewHeadless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fake_streamlit as F
        cls.st = F.install()
        cls.db = tempfile.mktemp(suffix=".db")
        os.environ["IVHM_DB"] = cls.db
        cls.st.session_state.clear()

    def run_app(self, press=None, **ss):
        self.st.session_state.update(ss)
        if press:
            self.st.PRESS.add(press)
        import fake_streamlit as F
        F.run_script(ROOT / "app" / "dashboard.py")                      # follows st.rerun() like the server
        return "\n".join(self.st.LOG)

    def viewer_args(self):
        """Arguments the 3D viewer was rendered with in the last script run (None if the 2D view was used)."""
        import cad3d
        if not cad3d.SOURCE_GLB.exists():
            return None
        return self.st.COMPONENTS.get("tb_cad3d")

    def check_viewer(self, sess, f, state=None):
        """The 3D viewer shows exactly the frame: state, colours, sensor quality, scores and fusion weights."""
        a = self.viewer_args()
        if a is None:
            return
        import testbed_view as TV
        import ui
        if f is None:
            self.assertIsNone(a["frame"])
            self.assertEqual(a["part_fill"], {})
            return
        st_ = state or f["state"]
        self.assertEqual((a["frame"]["window"], a["frame"]["state"]), (f["window"], st_))
        self.assertEqual(a["part_fill"], {c: ui.STATE_COLOR[st_] for c in a["monitored"]})
        for sid, code in (("S1", "vib"), ("S2", "cur")):
            s = a["sensors"][sid]
            self.assertEqual(s["status"], f["reliability"][code]["status"])
            self.assertAlmostEqual(s["score"], f["reliability"][code]["score"])
            w = f["weights"][code]
            self.assertTrue((s["weight"] is None and w is None) or abs(s["weight"] - w) < 1e-12)
            self.assertEqual(a["sensor_fill"][sid], ui.REL_COLOR[f["status"][code]])
        self.assertEqual(a["sensor_fill"]["S3"], TV.INACTIVE)
        self.assertEqual(a["frame"]["diagnosis_available"], f["diagnosis_available"])

    def test_playback_and_sync(self):
        from pufusion import testbed as T
        from pufusion import testbed_session as S
        from pufusion.store import HealthStore
        import testbed_view as TV
        import ui
        out = self.run_app(view="Virtual Testbed", tb_sub="Bearing", tb_rec="KI18", tb_pace=0.0, tb_target="none")
        self.assertIn("Ready", out)
        self.assertIn("REPRESENTATIVE DRIVETRAIN", out)
        self.assertIn("not a physics", out)
        sess = self.st.session_state["tb_session"]
        self.assertEqual(sess.i, 0)
        self.check_viewer(sess, None)

        out = self.run_app("⏭ Step")                                     # Step: exactly one window
        self.assertEqual(sess.i, 1)
        f = sess.frames[-1]
        self.assertIn(ui.STATE_COLOR[f["state"]], out)
        self.assertIn("window 1 (recording window 1/8)", out)
        self.check_viewer(sess, f)

        self.run_app("▶ Run", tb_stop_bearing=10)                       # Run to the stop window
        self.assertEqual(sess.i, 10)
        self.assertFalse(self.st.session_state["tb_playing"])
        ref = S.ReplaySession(T.Context(), "bearing", "KI18", HealthStore(tempfile.mktemp(suffix=".db")), "ref")
        expect = [S.trace_row(x) for x in ref.run(10)]
        self.assertEqual([S.trace_row(x)["state"] for x in sess.frames], [e["state"] for e in expect])
        self.assertEqual([S.trace_row(x)["fault_type"] for x in sess.frames], [e["fault_type"] for e in expect])
        self.assertEqual(expect[-1]["state"], "INSPECT")                  # KI18 is latched by window 10
        self.check_viewer(sess, sess.frames[-1])

        out = self.run_app("Acknowledge INSPECT")                                      # acknowledgement: INSPECT -> WARNING
        if expect[-1]["state"] == "INSPECT":
            self.assertEqual(sess.state, "WARNING")
            self.assertIn("INSPECT acknowledged and logged", out)
            self.assertIn("INSPECT acknowledged by the operator", out)              # banner shows the new state now
            self.assertIn(ui.STATE_COLOR["WARNING"], out)
            self.check_viewer(sess, sess.frames[-1], state="WARNING")     # the viewer shows the acknowledged state

        self.run_app("⏭ Step", tb_target="vib", tb_fam="dropout")      # fault applies from the next window
        f = sess.frames[-1]
        self.assertEqual((f["fault"], f["target"]), ("dropout", "vib"))
        self.assertEqual(f["weights"]["vib"], 0.0)
        self.assertTrue(f["diagnosis_available"])
        cs = TV.cad_state("bearing", f)
        self.assertEqual(cs["sensor_fill"]["S1"], ui.REL_COLOR["failed"])
        self.check_viewer(sess, f)

        self.run_app("⏭ Step", tb_target="both", tb_fam="stuck")       # dual failure: abstain
        f = sess.frames[-1]
        self.assertFalse(f["diagnosis_available"])
        self.assertIsNone(f["probs"])
        self.check_viewer(sess, f)
        if self.viewer_args() is not None:
            self.assertIsNone(self.viewer_args()["frame"]["probs"])

        out = self.run_app("⟲ Reset", tb_target="none")                 # Reset: new asset, window 0
        new = self.st.session_state["tb_session"]
        self.assertEqual(new.i, 0)
        self.assertNotEqual(new.asset, sess.asset)
        self.assertIn("Ready", out)
        self.check_viewer(new, None)

        ev = HealthStore(self.db).events(sess.asset)
        self.assertTrue(len(ev) >= 1)                                      # state changes were logged

    def test_other_views_unchanged(self):
        out = self.run_app(view="Overview")
        for gone in ("OB1", "OB2", "OB3", "OB4"):
            self.assertNotIn(gone, out)
        self.assertNotIn("Virtual testbed - CAD", out)


if __name__ == "__main__":
    unittest.main()
