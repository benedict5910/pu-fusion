"""Virtual testbed (OB4): scenario runner, safety checks, and the same path through the dashboard script.

Bearing scenarios need only committed files (models/demo_models.pkl, data/raw/{K004,KA22,KI18}).
Gearbox scenarios need the three held-out MCC5-THU demo recordings (data/mcc5, data/mcc5_demo or the
dashboard's download cache) and are skipped otherwise.
"""
import importlib.util
import json
import os
import runpy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pufusion import gearbox as G  # noqa: E402
from pufusion import testbed as T  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

HAVE_DATA = (ROOT / "models" / "demo_models.pkl").exists() and (ROOT / "data" / "raw" / "KI18").exists()
HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None
MANIFEST = ROOT / "models" / "gearbox_demo_manifest.json"


def _gearbox_dir():
    d = T.gearbox_data_dir()
    if d is None or not MANIFEST.exists():
        return None
    names = set(json.loads(MANIFEST.read_text())["recordings"])
    return d if names <= {p.name for p in d.glob("*.csv*")} else None


GB_DIR = _gearbox_dir() if HAVE_DATA else None


@unittest.skipUnless(HAVE_DATA, "held-out bearing recordings / demo model not present")
class TestVirtualTestbed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = T.Context(GB_DIR)
        cls.db = tempfile.mktemp(suffix=".db")
        cls.store = HealthStore(cls.db)
        cls.scn = {s.name: s for s in T.default_scenarios()}

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        os.unlink(cls.db)

    def run_one(self, name, asset=None):
        scn = self.scn[name]
        run = T.run_scenario(scn, self.ctx, self.store, asset or f"t-{name}")
        return scn, run, T.check(scn, run, self.store)

    def test_all_bearing_scenarios_pass_their_checks(self):
        for name, scn in self.scn.items():
            if scn.subsystem != "bearing":
                continue
            _, run, checks = self.run_one(name)
            self.assertEqual([c for c in checks if not c[1]], [], name)
            self.assertEqual(len(run["trace"]), sum(s.n for s in scn.segments))

    def test_dual_failure_suspends_diagnosis_and_logs_nothing_diagnostic(self):
        _, run, _ = self.run_one("bearing-dual-failure-healthy", "t-dual")
        outage = [w for w in run["trace"] if w["segment"] == 1]
        self.assertTrue(all(w["state"] == "SENSOR_FAULT" and not w["diagnosis_available"] for w in outage))
        hist = self.store.history("t-dual")
        self.assertTrue(all(h["p_fault"] is None and h["fault_type"] is None for h in hist[1:9]))
        self.assertIsNotNone(hist[9]["p_fault"])                       # diagnosis resumes on restoration
        ev = [(e["from_state"], e["to_state"]) for e in self.store.events("t-dual")]
        self.assertEqual(ev[0], ("NORMAL", "SENSOR_FAULT"))
        self.assertEqual(ev[1][0], "SENSOR_FAULT")

    def test_acknowledgement_is_logged_and_never_returns_to_normal(self):
        _, run, _ = self.run_one("bearing-fault-ack", "t-ack")
        self.assertEqual(run["acks"], [(12, True)])
        self.assertEqual(run["trace"][12]["state"], "WARNING")
        rules = [e["rule"] for e in self.store.events("t-ack")]
        self.assertTrue(any("NOT verified" in r for r in rules))
        self.assertEqual(run["trace"][-1]["state"], "INSPECT")          # persistent evidence re-latches

    def test_checks_detect_a_violation(self):
        scn, run, checks = self.run_one("bearing-dual-failure-healthy", "t-neg")
        self.assertTrue(all(c[1] for c in checks))
        run["trace"][3]["state"], run["trace"][3]["diagnosis_available"] = "NORMAL", True   # tampered trace
        failed = [c[0] for c in T.check(scn, run, self.store) if not c[1]]
        self.assertIn("all sensors failed -> diagnosis suspended, state SENSOR_FAULT or latched INSPECT", failed)
        self.assertIn("one logged event per state change", failed)
        self.assertIn("no diagnostic values stored while suspended", [c[0] for c in checks])

    @unittest.skipUnless(GB_DIR, "held-out MCC5-THU demo recordings not present")
    def test_all_gearbox_scenarios_pass_their_checks(self):
        for name, scn in self.scn.items():
            if scn.subsystem != "gearbox":
                continue
            _, run, checks = self.run_one(name)
            self.assertEqual([c for c in checks if not c[1]], [], name)

    @unittest.skipUnless(GB_DIR, "held-out MCC5-THU demo recordings not present")
    def test_gearbox_fallback_and_recovery(self):
        _, run, _ = self.run_one("gearbox-motor-dropout", "t-gb-motor")
        tr = run["trace"]
        self.assertTrue(all(w["weights"]["motor"] == 0.0 and w["weights"]["gearbox"] == 1.0 for w in tr[15:30]))
        self.assertTrue(all(w["weights"]["motor"] > 0 for w in tr[30:]))
        self.assertTrue(all(w["fault_type"] == "gear_pitting" for w in tr[15:30]))
        _, run, _ = self.run_one("gearbox-dual-failure-healthy", "t-gb-dual")
        self.assertEqual({w["state"] for w in run["trace"][5:25]}, {"SENSOR_FAULT"})
        self.assertEqual(run["trace"][25]["state"], "NORMAL")           # healthy gearbox: back to NORMAL

    def test_store_record_withholds_values_when_suspended(self):
        row = {"state": "SENSOR_FAULT", "diagnosis_available": False, "fault_score": None, "prediction": None,
               "confidence": None, "gearbox_weight": 0.0, "motor_weight": 0.0, "recommendation_list": [],
               "reliability": {"gearbox": {"score": 0.0}, "motor": {"score": 0.0}}}
        r = G.store_record(row, "a", "s", "rec")
        self.assertTrue(all(r[k] is None for k in ("p_fault", "fault_type", "confidence", "w_vib", "w_cur")))


@unittest.skipUnless(HAVE_DATA, "held-out recordings / demo model not present")
@unittest.skipIf(HAVE_STREAMLIT, "real Streamlit present: run scripts/windows/run_tests.bat for the AppTest suite")
class TestDashboardSimulation(unittest.TestCase):
    """Fault onset and recovery inside ONE dashboard run, and the final-validation views."""

    @classmethod
    def setUpClass(cls):
        import fake_streamlit as F
        cls.st = F.install()
        cls.db = tempfile.mktemp(suffix=".db")
        os.environ["IVHM_DB"] = cls.db
        cls.st.session_state.clear()
        cls.st.PRESS.clear()

    def run_app(self, press=None, **ss):
        self.st.session_state.update(ss)
        if press:
            self.st.PRESS.add(press)
        self.st.LOG.clear()
        runpy.run_path(str(ROOT / "app" / "dashboard.py"))
        return "\n".join(self.st.LOG)

    def test_bearing_outage_and_recovery_in_one_run(self):
        self.run_app(view="Live Diagnostics", component="Bearing", mode="Benchmark replay")
        out = self.run_app("▶ Run monitoring", rec="N15_M07_F10_KI18_1", asset="sim-KI18", nwin=8, pace=0.0,
                           target="both", fam="dropout", fault_from=4, fault_to=6)
        self.assertIn("(windows 4-6)", out)
        self.assertIn("Diagnosis suspended", out)                       # alert shown during the outage
        hist = HealthStore(self.db).history("sim-KI18")
        self.assertEqual(len(hist), 8)
        self.assertEqual([h["p_fault"] is None for h in hist], [False] * 3 + [True] * 3 + [False] * 2)
        self.assertEqual([h["state"] for h in hist[3:6]], ["SENSOR_FAULT"] * 3)
        ev = [(e["from_state"], e["to_state"]) for e in HealthStore(self.db).events("sim-KI18")]
        self.assertIn(("WARNING", "SENSOR_FAULT"), ev)
        after = [to for frm, to in ev if frm == "SENSOR_FAULT"]
        self.assertEqual(len(after), 1)
        self.assertIn(after[0], ("WARNING", "INSPECT"))                 # an outage never resets to NORMAL
        self.assertTrue(self.st.session_state["last"]["diag_ok"])       # diagnosing again at the end
        self.st.session_state.update(fault_from=1, fault_to=120, target="none")

    def test_final_validation_is_displayed(self):
        if not (ROOT / "results" / "final" / "summary.json").exists():
            self.skipTest("results/final/summary.json not built")
        out = self.run_app(view="Overview")
        self.assertIn("Final validation", out)
        for gone in ("OB1", "OB2", "OB3", "OB4"):
            self.assertNotIn(gone, out)
        out = self.run_app(view="Research Lab")
        self.assertIn("Virtual testbed", out)
        self.assertIn("not significantly", out)
        self.assertGreaterEqual(out.count("<table rows="), 5)

    @unittest.skipUnless(GB_DIR, "held-out MCC5-THU demo recordings not present")
    def test_gearbox_sensor_loss_and_recovery_in_one_run(self):
        cache = Path(tempfile.gettempdir()) / "ivhm_mcc5_demo"
        cache.mkdir(exist_ok=True)
        for name in json.loads(MANIFEST.read_text())["recordings"]:      # stands in for the release download
            if not (cache / name).exists():
                shutil.copyfile(GB_DIR / name, cache / name)
        os.environ["IVHM_MCC5"] = str(ROOT / "data" / "no-mcc5-here")
        try:
            rec = "gear_pitting_M_torque_circulation_1000rpm_10Nm.csv"
            self.run_app(view="Live Diagnostics", component="Gearbox", asset="sim-gb", gb_rec=rec, nwin=30, pace=0.0,
                         gb_target="motor", gb_fam="dropout", fault_from=11, fault_to=20)
            out = self.run_app("▶ Run monitoring")
            self.assertIn("(windows 11-20)", out)
            hist = HealthStore(self.db).history("sim-gb")
            self.assertEqual(len(hist), 30)
            self.assertTrue(all(h["w_cur"] == 0.0 and h["w_vib"] == 1.0 for h in hist[10:20]))   # motor excluded
            self.assertTrue(all(h["w_cur"] > 0 for h in hist[:10] + hist[20:]))                  # and restored
            self.assertTrue(all(h["fault_type"] == "gear_pitting" for h in hist[10:20]))
            self.run_app("▶ Run monitoring", asset="sim-gb-both", gb_target="both", fault_from=6, fault_to=15)
            hist = HealthStore(self.db).history("sim-gb-both")
            self.assertTrue(all(h["p_fault"] is None for h in hist[5:15]))
            self.assertTrue(all(h["p_fault"] is not None for h in hist[15:]))
        finally:
            os.environ.pop("IVHM_MCC5", None)
            self.st.session_state.update(component="Bearing", fault_from=1, fault_to=120, gb_target="none")


if __name__ == "__main__":
    unittest.main()
