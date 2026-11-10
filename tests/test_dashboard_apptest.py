"""UI regression tests on the REAL Streamlit app (streamlit.testing AppTest).

Runs only where Streamlit and the held-out recordings are installed (the team laptop:
scripts/windows/run_tests.bat). Uses a temporary SQLite file, never data/health.db.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None
HAVE_DATA = (ROOT / "models" / "demo_models.pkl").exists() and (ROOT / "data" / "raw" / "KI18").exists()


@unittest.skipUnless(HAVE_STREAMLIT and HAVE_DATA, "needs Streamlit and the held-out recordings")
class TestDashboardAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["IVHM_DB"] = tempfile.mktemp(suffix=".db")

    def app(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=300)
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def text(at):
        return "\n".join(m.value for m in at.markdown)

    @staticmethod
    def click(at, label):
        [b for b in at.button if b.label == label][0].click().run()

    def test_professor_demo_steps(self):
        at = self.app()
        self.click(at, "▶ Start professor demo")
        self.assertEqual(at.session_state["view"], "Live Diagnostics")
        at.session_state["pace"] = 0.0
        expect = {0: "INSPECT", 1: "WARNING", 2: "SENSOR_FAULT", 3: "INSPECT"}
        for i in range(8):
            [b for b in at.button if b.key == "demo_next"][0].click().run()
            self.assertFalse(at.exception, f"step {i + 1}: {at.exception}")
            if i in expect:
                self.assertEqual(at.session_state["tracker"].state, expect[i], f"step {i + 1}")
        self.assertEqual(at.session_state["view"], "Research Lab")
        [b for b in at.button if b.key == "demo_done"][0].click().run()
        self.assertFalse(at.session_state["demo_on"])
        self.assertFalse(str(at.session_state["asset"]).startswith("demo-"))

    def test_every_view_renders(self):
        at = self.app()
        for v in ("Overview", "Live Diagnostics", "Research Lab", "History & Reports"):
            at.sidebar.radio(key="view").set_value(v).run()
            self.assertFalse(at.exception, f"{v}: {at.exception}")
        at.sidebar.radio(key="view").set_value("Overview").run()
        self.assertIn("BENCHMARK", self.text(at))
        for gone in ("OB1", "OB2", "OB3", "OB4", "DESIGN STAGE"):
            self.assertNotIn(gone, self.text(at))

    def test_ack_and_sensor_failure_on_real_app(self):
        at = self.app()
        at.sidebar.radio(key="view").set_value("Live Diagnostics").run()
        at.session_state["pace"] = 0.0
        at.session_state["nwin"] = 24
        at.session_state["asset"] = "apptest-KI18"
        at.session_state["rec"] = "N15_M07_F10_KI18_1"
        at.run()
        self.click(at, "▶ Run monitoring")
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["last"]["state"], "INSPECT")
        self.click(at, "Acknowledge INSPECT alert")
        self.assertEqual(at.session_state["tracker"].state, "WARNING")
        self.assertIn("confirm the bearing is healthy", self.text(at))
        at.session_state["target"] = "both"
        at.session_state["fam"] = "dropout"
        at.session_state["nwin"] = 6
        at.run()
        self.click(at, "▶ Run monitoring")
        last = at.session_state["last"]
        self.assertEqual(last["state"], "SENSOR_FAULT")
        self.assertFalse(last["diag_ok"])
        self.assertIn("Diagnosis suspended", self.text(at))

    def test_live_rig_not_connected_and_no_fabrication(self):
        at = self.app()
        at.sidebar.radio(key="view").set_value("Live Diagnostics").run()
        at.sidebar.radio(key="mode").set_value("Rig - live").run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("Rig not connected", self.text(at))
        self.assertEqual(at.session_state["asset"], "rig-1")      # sources never share an asset log
        at.sidebar.radio(key="mode").set_value("Rig - simulated").run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["asset"], "sim-rig-1")
        self.assertIn("SIMULATED", self.text(at))


HAVE_MCC5 = len(list((ROOT / "data" / "mcc5").glob("*.csv*"))) == 12 if (ROOT / "data" / "mcc5").is_dir() else False


@unittest.skipUnless(HAVE_STREAMLIT and HAVE_DATA and HAVE_MCC5, "needs Streamlit and the MCC5-THU recordings")
class TestGearboxAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["IVHM_DB"] = tempfile.mktemp(suffix=".db")

    def test_gearbox_clean_motor_dropout_and_dual_dropout(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=600)
        at.run()
        at.sidebar.radio(key="view").set_value("Live Diagnostics").run()
        at.sidebar.radio(key="component").set_value("Gearbox").run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["asset"], "gearbox-1")
        at.session_state["pace"] = 0.0
        at.session_state["nwin"] = 59
        at.session_state["gb_rec"] = "gear_pitting_M_torque_circulation_1000rpm_10Nm.csv"
        for target, check in (("none", "clean"), ("motor", "motor"), ("both", "both")):
            # a fresh asset per scenario: a latched INSPECT (by design) persists through a later sensor outage
            at.session_state["asset"] = f"apptest-gear-{check}"
            at.session_state["gb_target"] = target
            at.session_state["gb_fam"] = "dropout"
            at.run()
            [b for b in at.button if b.label == "▶ Run monitoring"][0].click().run()
            self.assertFalse(at.exception, f"{target}: {at.exception}")
            last = at.session_state["last"]
            if check == "both":
                self.assertEqual(last["state"], "SENSOR_FAULT")
                self.assertFalse(last["diag_ok"])
                self.assertNotIn("probs", last)
            else:
                self.assertEqual(max(last["probs"], key=last["probs"].get), "gear_pitting")
            if check == "motor":
                self.assertEqual(last["weights"]["motor"], 0.0)


if __name__ == "__main__":
    unittest.main()
