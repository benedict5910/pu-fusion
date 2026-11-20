"""OB4 interactive replay: the window-by-window session must reproduce the batch virtual testbed.

For every default testbed scenario whose recording is available, the scenario's fault plan is replayed through
ReplaySession and compared with testbed.run_scenario: per-window state, diagnosis availability, predicted label,
sensor status and rule must be identical; fault evidence and fusion weights equal to 1e-9 (bearing, float64) or 1e-6
(gearbox, float32 data); and the SQLite store
must receive the same windows and the same state-change events. Gearbox scenarios run only when the held-out
MCC5-THU recordings are present (data/mcc5, data/mcc5_demo or the dashboard cache) and are skipped otherwise.
"""
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pufusion import testbed as T  # noqa: E402
from pufusion import testbed_session as S  # noqa: E402
from pufusion.store import HealthStore  # noqa: E402

CTX = T.Context()
# Numerical tolerance for fault evidence / fusion weights. Bearing features are float64: 1e-9. Gearbox recordings and
# features are float32 (eps 1.19e-7); scoring one window at a time instead of one batch changes the BLAS summation
# order, which moves the evidence by 1-2 float32 ulps (measured max 1.8e-7). 1e-6 = ~8 ulps. States, labels, rules,
# sensor status and logged events must still be identical.
TOL = {"bearing": 1e-9, "gearbox": 1e-6}
BEARING_OK = all(p.exists() for p in CTX.bearing_recs.values())


def _close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=0, abs_tol=tol)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)

    def store(self, name):
        s = HealthStore(Path(self.tmp.name) / f"{name}.db")
        self.addCleanup(s.close)
        return s

    def compare(self, scn):
        ref_store, ses_store = self.store(f"ref-{scn.name}"), self.store(f"ses-{scn.name}")
        ref = T.run_scenario(scn, CTX, ref_store, asset="a")
        ses = S.run_plan(S.ReplaySession(CTX, scn.subsystem, scn.recording, ses_store, "a"), scn)
        got = [S.trace_row(f) for f in ses.frames]
        self.assertEqual(len(got), len(ref["trace"]))
        for k, (g, r) in enumerate(zip(got, ref["trace"])):
            for key in ("window", "fault", "target", "state", "diagnosis_available", "fault_type", "rule", "status"):
                self.assertEqual(g[key], r[key], f"{scn.name} window {k + 1}: {key}")
            tol = TOL[scn.subsystem]
            self.assertTrue(_close(g["p_fault"], r["p_fault"], tol), f"{scn.name} window {k + 1}: p_fault "
                            f"{g['p_fault']!r} vs {r['p_fault']!r}")
            for s in g["weights"]:
                self.assertTrue(_close(g["weights"][s], r["weights"][s], tol), f"{scn.name} window {k + 1}: weight {s}")
        self.assertEqual(ses.acks, ref["acks"])
        ev_ref = [(e["from_state"], e["to_state"], e["rule"], e["ts"]) for e in ref_store.events("a")]
        ev_ses = [(e["from_state"], e["to_state"], e["rule"], e["ts"]) for e in ses_store.events("a")]
        self.assertEqual(ev_ses, ev_ref, f"{scn.name}: logged events")
        h_ref, h_ses = ref_store.history("a", limit=10 ** 6), ses_store.history("a", limit=10 ** 6)
        self.assertEqual([h["state"] for h in h_ses], [h["state"] for h in h_ref])
        self.assertEqual([h["fault_type"] for h in h_ses], [h["fault_type"] for h in h_ref])
        # the testbed's own safety checks pass on the session's log as well
        checks = T.check(scn, {"asset": "a", "trace": got, "acks": ses.acks}, ses_store)
        self.assertTrue(all(p for _, p, _ in checks), [c for c in checks if not c[1]])


@unittest.skipUnless(BEARING_OK, "held-out Paderborn recordings not in data/raw")
class TestBearingEquivalence(_Base):
    def test_all_bearing_scenarios(self):
        for scn in [s for s in T.default_scenarios() if s.subsystem == "bearing"]:
            with self.subTest(scn.name):
                self.compare(scn)


@unittest.skipUnless(CTX.gearbox is not None and CTX.gearbox_recs, "held-out MCC5-THU recordings not available")
class TestGearboxEquivalence(_Base):
    def test_all_gearbox_scenarios(self):
        for scn in [s for s in T.default_scenarios() if s.subsystem == "gearbox"]:
            with self.subTest(scn.name):
                self.compare(scn)


@unittest.skipUnless(BEARING_OK, "held-out Paderborn recordings not in data/raw")
class TestPlaybackControls(_Base):
    def session(self, rec="KI18"):
        return S.ReplaySession(CTX, "bearing", rec, self.store("p"), "p")

    def test_step_advances_one_window_and_logs_it(self):
        s = self.session()
        f = s.step()
        self.assertEqual(f["window"], 1)
        self.assertEqual(s.i, 1)
        self.assertEqual(len(s.store.history("p", limit=100)), 1)

    def test_reset_restarts_from_window_one_with_a_fresh_tracker(self):
        s = self.session()
        first = [S.trace_row(f) for f in s.run(10)]
        self.assertNotEqual(s.state, "NORMAL")          # KI18 (inner-race damage) escalates within 10 windows
        s.reset()
        self.assertEqual((s.i, s.state, s.frames), (0, "NORMAL", []))
        again = [S.trace_row(f) for f in s.run(10)]
        self.assertEqual(again, first)                 # deterministic: same recording, same seeds, same result

    def test_stepping_equals_running(self):
        a, b = self.session(), self.session()
        stepped = [S.trace_row(a.step()) for _ in range(9)]
        ran = [S.trace_row(f) for f in b.run(9)]
        self.assertEqual(stepped, ran)

    def test_fault_changes_apply_from_the_next_window(self):
        s = self.session("KA22")
        s.run(3)
        s.set_fault("dropout", "vib")
        f = s.step()
        self.assertEqual((f["fault"], f["target"]), ("dropout", "vib"))
        self.assertEqual(f["status"]["vib"], "failed")
        self.assertEqual(f["weights"]["vib"], 0.0)       # single-sensor fallback: dead sensor gets zero weight
        self.assertTrue(f["diagnosis_available"])
        s.set_fault(None)
        self.assertIsNone(s.step()["fault"])

    def test_dual_sensor_failure_abstains(self):
        s = self.session("K004")
        s.step()
        s.set_fault("stuck", "both")
        f = s.step()
        self.assertFalse(f["diagnosis_available"])
        self.assertIsNone(f["p_fault"])
        self.assertIsNone(f["probs"])
        self.assertEqual(f["weights"], {"vib": None, "cur": None})
        self.assertEqual(f["state"], "SENSOR_FAULT")

    def test_noise_and_clipping_are_injected_on_the_selected_sensor_only(self):
        s = self.session("KA22")
        clean = s.step()["signals"]["channels"]
        s.reset()
        s.set_fault("clipping", "vib", 0.05)
        clip = s.step()["signals"]["channels"]
        self.assertLess(max(abs(clip["vibration_1"])), max(abs(clean["vibration_1"])))
        self.assertTrue((clip["phase_current_1"] == clean["phase_current_1"]).all())

    def test_acknowledge_only_when_inspect(self):
        s = self.session()
        self.assertFalse(s.acknowledge())                # NORMAL: nothing to acknowledge
        while s.state != "INSPECT":
            s.step()
        self.assertTrue(s.acknowledge())
        self.assertEqual(s.state, "WARNING")

    def test_invalid_inputs_are_rejected(self):
        s = self.session()
        with self.assertRaises(ValueError):
            s.set_fault("dropout", "gearbox")            # gearbox sensor on a bearing session
        with self.assertRaises(ValueError):
            s.set_fault("melting", "vib")
        with self.assertRaises(KeyError):
            S.ReplaySession(CTX, "bearing", "K001", self.store("x"), "x")   # training bearing, not held out


if __name__ == "__main__":
    unittest.main()
