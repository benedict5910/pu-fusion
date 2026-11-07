"""End-to-end regression checks for presentation mode on real Streamlit."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAVE_STREAMLIT = importlib.util.find_spec("streamlit") is not None


@unittest.skipUnless(HAVE_STREAMLIT, "needs Streamlit")
class TestPresentationDashboard(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=120).run()
        self.assertFalse(app.exception)
        return app

    @staticmethod
    def click(app, label):
        next(button for button in app.button if button.label == label).click().run()

    @staticmethod
    def metrics(app):
        return {metric.label: metric.value for metric in app.metric}

    def test_only_presentation_pages_and_verified_results(self):
        app = self.app()
        nav = app.sidebar.radio[0]
        self.assertEqual(nav.value, "System Dashboard")
        self.assertEqual(nav.options, ["Overview", "System Dashboard", "Simulation", "Results"])
        self.assertEqual(self.metrics(app)["Overall system state"], "Awaiting replay")
        for page in nav.options:
            app.sidebar.radio[0].set_value(page).run()
            self.assertFalse(app.exception, app.exception)
        self.assertEqual(len(app.dataframe), 2)
        self.assertIn("0.533", app.dataframe[0].value["Clean"].tolist())
        self.assertIn("0.565", app.dataframe[1].value["Gated fusion"].tolist())

    def test_bearing_dropout_is_reflected_in_unified_view(self):
        app = self.app()
        app.sidebar.radio[0].set_value("Simulation").run()
        app.selectbox[1].select("dropout").run()
        app.selectbox[2].select("both").run()
        self.click(app, "Run simulation")
        self.assertFalse(app.exception or app.error)
        self.assertEqual(self.metrics(app)["Predicted condition"], "Unavailable")
        self.assertEqual(self.metrics(app)["Model confidence"], "Unavailable")
        self.assertEqual(self.metrics(app)["Health state"], "Sensor fault")
        self.assertTrue(any("Clean vs corrupted signal" in item.value for item in app.markdown))
        app.sidebar.radio[0].set_value("System Dashboard").run()
        self.assertFalse(app.exception)
        self.assertEqual(self.metrics(app)["Overall system state"], "Sensor fault")
        self.assertEqual(self.metrics(app)["Gearbox state"], "Awaiting replay")

    @unittest.skipUnless(len(list((ROOT / "data" / "mcc5").glob("*.csv*"))) >= 12, "needs local gearbox pilot data")
    def test_clean_system_and_gearbox_simulation(self):
        app = self.app()
        self.click(app, "Run clean system replay")
        self.assertFalse(app.exception or app.error)
        self.assertEqual(self.metrics(app)["Bearing state"], "Inspect")
        self.assertEqual(self.metrics(app)["Gearbox state"], "Inspect")
        app.radio(key="system_component").set_value("Gearbox").run()
        self.assertEqual(self.metrics(app)["Predicted condition"], "Gear pitting")
        self.assertTrue(self.metrics(app)["Model confidence"].endswith("%"))
        app.sidebar.radio[0].set_value("Simulation").run()
        app.radio(key="simulation_component").set_value("Gearbox").run()
        app.selectbox[1].select("dropout").run()
        self.click(app, "Run simulation")
        self.assertFalse(app.exception or app.error)
        self.assertEqual(app.dataframe[0].value["Fusion weight"].tolist(), ["0%", "100%"])
        app.selectbox[2].select("both").run()
        self.assertNotIn("Predicted condition", self.metrics(app))
        self.click(app, "Run simulation")
        self.assertFalse(app.exception or app.error)
        self.assertEqual(self.metrics(app)["Health state"], "Sensor fault")
        app.sidebar.radio[0].set_value("System Dashboard").run()
        self.assertEqual(self.metrics(app)["Bearing state"], "Inspect")
        self.assertEqual(self.metrics(app)["Gearbox state"], "Sensor fault")
        self.assertEqual(self.metrics(app)["Overall system state"], "Inspect")
