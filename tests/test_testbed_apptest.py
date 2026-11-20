"""OB4 Virtual Testbed view on the REAL Streamlit app (streamlit.testing AppTest).

Runs where Streamlit and the held-out recordings are installed (project PC: scripts/windows/run_tests.bat).
Uses a temporary SQLite file, never data/health.db.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None
HAVE_DATA = (ROOT / "models" / "demo_models.pkl").exists() and (ROOT / "data" / "raw" / "KI18").exists()


@unittest.skipUnless(HAVE_STREAMLIT and HAVE_DATA, "needs Streamlit and the held-out recordings")
class TestVirtualTestbedAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["IVHM_DB"] = tempfile.mktemp(suffix=".db")

    def app(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=600)
        at.run()
        self.assertFalse(at.exception, at.exception)
        at.sidebar.radio(key="view").set_value("Virtual Testbed").run()
        self.assertFalse(at.exception, at.exception)
        return at

    def press(self, at, key):
        [b for b in at.button if b.key == key][0].click().run()
        self.assertFalse(at.exception, f"{key}: {at.exception}")

    def test_bearing_controls_faults_and_sync(self):
        from pufusion import testbed as T
        from pufusion import testbed_session as S
        from pufusion.store import HealthStore
        at = self.app()
        at.sidebar.radio(key="tb_sub").set_value("Bearing").run()
        at.sidebar.selectbox(key="tb_rec").set_value("KI18").run()
        at.session_state["tb_pace"] = 0.0
        sess = at.session_state["tb_session"]
        self.press(at, "tb_step")
        self.assertEqual(at.session_state["tb_session"].i, 1)
        at.session_state["tb_stop_bearing"] = 12
        self.press(at, "tb_run")
        sess = at.session_state["tb_session"]
        self.assertEqual(sess.i, 12)
        ref = S.ReplaySession(T.Context(), "bearing", "KI18", HealthStore(tempfile.mktemp(suffix=".db")), "ref")
        self.assertEqual([f["state"] for f in sess.frames], [f["state"] for f in ref.run(12)])
        # a 12-window Run must show one set of waveforms (S1, S2), not one set per window
        wave_captions = [c.value for c in at.caption if "waveform" in c.value]
        self.assertEqual(len(wave_captions), 2, wave_captions)
        at.sidebar.radio(key="tb_target").set_value("vib").run()
        at.sidebar.selectbox(key="tb_fam").set_value("dropout").run()
        self.press(at, "tb_step")
        f = at.session_state["tb_session"].frames[-1]
        self.assertEqual((f["fault"], f["status"]["vib"], f["weights"]["vib"]), ("dropout", "failed", 0.0))
        self.assertTrue(f["diagnosis_available"])                   # single-sensor fallback
        at.sidebar.radio(key="tb_target").set_value("both").run()
        at.sidebar.selectbox(key="tb_fam").set_value("stuck").run()
        self.press(at, "tb_step")
        f = at.session_state["tb_session"].frames[-1]
        self.assertFalse(f["diagnosis_available"])                  # dual-sensor abstention
        self.assertIsNone(f["probs"])
        self.press(at, "tb_reset")
        self.assertEqual(at.session_state["tb_session"].i, 0)
        text = "\n".join(m.value for m in at.markdown)
        self.assertIn("REPRESENTATIVE DRIVETRAIN", text)
        self.assertIn("not a physics", text)

    @unittest.skipUnless(__import__("pufusion.testbed", fromlist=["x"]).gearbox_data_dir() is not None,
                         "held-out MCC5-THU recordings not present")
    def test_gearbox_replay_and_motor_dropout(self):
        at = self.app()
        at.sidebar.radio(key="tb_sub").set_value("Gearbox").run()
        self.assertFalse(at.exception, at.exception)
        at.session_state["tb_pace"] = 0.0
        at.session_state["tb_stop_gearbox"] = 20
        self.press(at, "tb_run")
        sess = at.session_state["tb_session"]
        self.assertEqual(sess.i, 20)
        at.sidebar.radio(key="tb_target").set_value("motor").run()
        at.sidebar.selectbox(key="tb_fam").set_value("dropout").run()
        self.press(at, "tb_step")
        f = at.session_state["tb_session"].frames[-1]
        self.assertEqual((f["status"]["motor"], f["weights"]["motor"]), ("failed", 0.0))
        self.assertTrue(f["diagnosis_available"])

    def test_other_views_still_render(self):
        at = self.app()
        for v in ("Overview", "Live Diagnostics", "Research Lab", "History & Reports", "Virtual Testbed"):
            at.sidebar.radio(key="view").set_value(v).run()
            self.assertFalse(at.exception, f"{v}: {at.exception}")


if __name__ == "__main__":
    unittest.main()
