"""Dashboard regression tests that need no browser.

- research.py reads the frozen results unchanged (snapshot of SUMMARY.txt / p1.csv values)
- ui.py renders labels, states and the schematic safely
- the dashboard script runs headless through every view with a Streamlit stand-in, on the real
  held-out recordings, and keeps the safety behaviour (ack -> WARNING, outage -> no diagnosis,
  recovery -> WARNING held, live rig -> not connected). Skipped if data/models are absent, and
  skipped where real Streamlit is installed (tests/test_dashboard_apptest.py covers it there).
"""
import importlib.util
import os
import runpy
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import research as R  # noqa: E402
import ui  # noqa: E402

RES = ROOT / "results" / "starter"
HAVE_RESULTS = (RES / "SUMMARY.txt").exists()
HAVE_DATA = (ROOT / "models" / "demo_models.pkl").exists() and (ROOT / "data" / "raw" / "KI18").exists()
HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None


@unittest.skipUnless(HAVE_RESULTS, "frozen results not present")
class TestResearchReaders(unittest.TestCase):
    def test_summary_values_unchanged(self):
        s = R.parse_summary(RES / "SUMMARY.txt")
        self.assertEqual(s["p1"]["runs"], 11)
        self.assertEqual(s["p3"]["runs"], 8)
        g, v = s["p1"]["models"]["gated_both"], s["p1"]["models"]["vib_only"]
        self.assertEqual(g["clean"], (0.533, 0.172))
        self.assertEqual(g["heldout"], (0.455, 0.146))
        self.assertEqual(v["heldout"], (0.470, 0.141))
        self.assertAlmostEqual(g["far"], 0.470)
        self.assertEqual(len(s["p1"]["tests"]), 24)
        self.assertEqual(s["leaky"]["models"]["early_fusion"]["clean"], (0.983, 0.002))

    def test_no_holm_significant_claim(self):
        h = R.headline(RES)
        self.assertEqual(h["n_significant_holm"], 0)
        self.assertLess(h["gated_heldout"], h["vib_heldout"])        # gated does not beat vibration-only

    def test_confusion_matrix_snapshot(self):
        cm = R.summed_cm(RES / "p1.csv", "gated_both")
        self.assertEqual(cm, [[5958, 3230, 1688], [1761, 4485, 3315], [1259, 2816, 5519]])
        rows = R.cm_long(cm)
        for t in R.CLASSES:
            self.assertAlmostEqual(sum(r["share"] for r in rows if r["true"] == t), 1.0)

    def test_quality_table(self):
        q = R.quality_table(RES / "quality.json")
        clean = {r["sensor"]: r["false_flag"] for r in q if r["family"] == "clean"}
        self.assertAlmostEqual(clean["vib"], 0.016)
        self.assertAlmostEqual(clean["cur"], 0.0122)


class TestUiHelpers(unittest.TestCase):
    def test_source_labels_distinct(self):
        tags = {k: v["tag"] for k, v in ui.SOURCES.items()}
        self.assertEqual(set(tags), {"benchmark", "simulated", "live", "results"})
        self.assertEqual(len(set(tags.values())), 4)
        self.assertIn("not measured", ui.SOURCES["simulated"]["title"])
        self.assertIn("not connected", ui.SOURCES["live"]["title"])
        for mode, kind in ui.MODE_SOURCE.items():
            self.assertIn(kind, ui.SOURCES, mode)

    def test_state_banner_escapes_and_labels(self):
        h = ui.state_banner("SENSOR_FAULT", "<script>x</script>", "meta")
        self.assertIn("SENSOR FAULT", h)
        self.assertNotIn("<script>", h)

    def test_timestamp_format(self):
        import time
        t = time.mktime((2026, 10, 22, 1, 23, 4, 0, 0, -1))
        self.assertEqual(ui.fmt_ts(t), "22 Oct 2026, 01:23:04")
        self.assertEqual(ui.fmt_ts(t, False), "01:23:04")
        self.assertEqual(ui.fmt_ts(None), "-")

    def test_svgs_are_well_formed(self):
        for st_ in ui.STATE_COLOR:
            ET.fromstring(ui.component_svg(st_, "ok", "failed", "BENCHMARK"))
        ET.fromstring(ui.pipeline_html())
        t = ui.event_table([{"ts": 0, "from_state": "INSPECT", "to_state": "WARNING", "rule": "a < b & c"}])
        ET.fromstring(t)
        self.assertIn("a &lt; b &amp; c", t)
        ET.fromstring(ui.grid([ui.card('a', 'b')], 180))

    def test_demo_uses_only_held_out_recordings(self):
        held = {"K004", "KA22", "KI18"}
        for s in ui.DEMO_STEPS:
            if s["action"] in ("run", "ack"):
                self.assertIn(s["asset"], held)
                self.assertEqual(s["rec"].split("_")[3], s["asset"])
        if HAVE_DATA:
            import pickle
            b = pickle.load(open(ROOT / "models" / "demo_models.pkl", "rb"))
            self.assertEqual(set(b["holdout"]), held)
            self.assertTrue(held.isdisjoint(set(b["trained_on"])))


@unittest.skipUnless(HAVE_DATA, "held-out recordings / demo model not present")
@unittest.skipIf(HAVE_STREAMLIT, "real Streamlit present: covered by test_dashboard_apptest")
class TestDashboardHeadless(unittest.TestCase):
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
        self.st.LOG.clear()
        runpy.run_path(str(ROOT / "app" / "dashboard.py"))
        return "\n".join(self.st.LOG)

    def test_full_sequence(self):
        for v in ("Overview", "Research Lab", "History & Reports", "Live Diagnostics"):
            self.run_app(view=v)
        out = self.run_app(view="Overview")
        self.assertIn("BENCHMARK", out)
        self.assertIn("Design stage".upper(), out)
        self.st.session_state.update(nwin=24, pace=0.0, rec="N15_M07_F10_KI18_1", asset="t-KI18",
                                     mode="Benchmark replay", target="none")
        self.run_app("▶ Run monitoring", view="Live Diagnostics")
        last = self.st.session_state["last"]
        self.assertEqual(last["state"], "INSPECT")
        self.assertEqual(max(last["probs"], key=last["probs"].get), "inner_race")
        out = self.run_app("Acknowledge INSPECT alert")
        self.assertEqual(self.st.session_state["tracker"].state, "WARNING")       # never NORMAL
        self.assertIn("not</b> confirm the bearing is healthy", out)
        out = self.run_app("Acknowledge INSPECT alert")
        self.assertIn("Nothing to acknowledge", out)
        out = self.run_app("▶ Run monitoring", target="both", fam="dropout", nwin=6)
        last = self.st.session_state["last"]
        self.assertEqual(last["state"], "SENSOR_FAULT")
        self.assertFalse(last["diag_ok"])
        self.assertNotIn("probs", last)
        self.assertIn("Diagnosis suspended", out)
        self.run_app("▶ Run monitoring", target="none", nwin=4)
        from pufusion.store import HealthStore
        ev = HealthStore(self.db).events("t-KI18")
        rules = [e["rule"] for e in ev]
        self.assertTrue(any("component condition NOT verified" in r for r in rules))
        held = [e for e in ev if e["from_state"] == "SENSOR_FAULT"]
        self.assertEqual(held[0]["to_state"], "WARNING")                         # outage does not reset to NORMAL
        out = self.run_app(view="History & Reports", hist_asset="t-KI18")
        self.assertEqual(out.count("<download"), 2)
        out = self.run_app("▶ Run monitoring", view="Live Diagnostics", mode="Rig - live")
        self.assertIn("Rig not connected", out)
        self.st.session_state["mode"] = "Benchmark replay"


@unittest.skipUnless(HAVE_DATA, "held-out recordings / demo model not present")
@unittest.skipIf(HAVE_STREAMLIT, "real Streamlit present: covered by test_dashboard_apptest")
class TestCloudSessionIsolation(unittest.TestCase):
    """IVHM_CLOUD=1: each browser session has its own temporary log; no hardware mode."""

    def setUp(self):
        import fake_streamlit as F
        self.st = F.install()
        os.environ["IVHM_CLOUD"] = "1"

    def tearDown(self):
        os.environ.pop("IVHM_CLOUD", None)

    def run_app(self, press=None, **ss):
        self.st.session_state.update(ss)
        if press:
            self.st.PRESS.add(press)
        self.st.LOG.clear()
        runpy.run_path(str(ROOT / "app" / "dashboard.py"))
        return "\n".join(self.st.LOG)

    def test_sessions_do_not_share_history(self):
        self.st.session_state.clear()                                     # viewer A
        self.run_app("▶ Run monitoring", view="Live Diagnostics", nwin=8, pace=0.0, asset="cloud-KI18",
                     rec="N15_M07_F10_KI18_1", mode="Benchmark replay", target="none")
        dir_a = self.st.session_state["_store_dir"]
        out = self.run_app(view="History & Reports", hist_asset="cloud-KI18")
        self.assertEqual(out.count("<download"), 2)
        self.assertTrue(dir_a.startswith(tempfile.gettempdir()))
        self.assertTrue(any(p.startswith("report_cloud-KI18") for p in os.listdir(dir_a)))
        self.st.session_state.clear()                                     # viewer B, fresh session
        out = self.run_app(view="History & Reports")
        self.assertIn("No history yet", out)
        self.assertNotEqual(self.st.session_state["_store_dir"], dir_a)
        out = self.run_app("▶ Run monitoring", view="Live Diagnostics", mode="Rig - live")
        self.assertIn("Rig not connected", out)
        self.assertIn("cloud demo", out)


if __name__ == "__main__":
    unittest.main()
