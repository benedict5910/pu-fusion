"""Regression checks for frozen results and dashboard display helpers."""
import sys
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
