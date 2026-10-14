"""Tests for the IVHM layer: reliability, explanations, health states, logging, rig path.
All signals here are SYNTHETIC/SIMULATED; these tests check code behaviour, not accuracy."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pufusion import corruption as C  # noqa: E402
from pufusion.data import windows  # noqa: E402
from pufusion.explain import deletion_check, explain_gated, linear_contributions  # noqa: E402
from pufusion.features import CUR_FEATURE_NAMES, VIB_FEATURE_NAMES, quality_indicators  # noqa: E402
from pufusion.health import INSPECT, NORMAL, SENSOR_FAULT, WARNING, HealthTracker  # noqa: E402
from pufusion.models import ReliabilityGated  # noqa: E402
from pufusion.monitor import SOURCE_BENCHMARK, SOURCE_SIM, BenchmarkDiagnoser, MonitorEngine, RigDiagnoser  # noqa: E402
from pufusion.reliability import ReliabilityAssessor, SensorReliability  # noqa: E402
from pufusion.rig import (FrameParser, RigAnomalyDetector, RigConfig, SimulatedRigSource,  # noqa: E402
                          TimingAnalyzer, WindowAssembler, encode_frame, rig_features)
from pufusion.store import HealthStore  # noqa: E402
from pufusion.synthetic import synth_recording  # noqa: E402
from test_pipeline import _small_tables  # noqa: E402

FS = 64_000
OK = SensorReliability(1.0, "ok")
DEAD = SensorReliability(0.0, "failed", ["dead or stuck sensor"])


def _assessor():
    Q = []
    for b in ("K001", "KA04", "KI04"):
        for r in (1, 2, 3):
            rec = synth_recording(b, "N15_M07_F10", r, seconds=1.0)
            Q += [quality_indicators(v, FS) for _, v, _ in windows(rec, 0.25)]
    return ReliabilityAssessor().fit(np.array(Q))


class TestReliability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = _assessor()
        cls.v = synth_recording("K002", "N15_M07_F10", 9, seconds=0.25).vib

    def _assess(self, fam, sev):
        return self.a.assess(quality_indicators(C.apply(self.v, fam, sev, np.random.default_rng(0)), FS))

    def test_clean_is_ok(self):
        self.assertEqual(self.a.assess(quality_indicators(self.v, FS)).status, "ok")

    def test_failures_and_causes(self):
        self.assertEqual(self._assess("dropout", None).status, "failed")
        self.assertEqual(self._assess("stuck", None).status, "failed")
        self.assertIn("broadband noise", self._assess("noise", -5).reasons)
        self.assertIn("clipping / saturation", self._assess("clipping", 0.2).reasons)
        self.assertIn("impulsive spikes (EMI or connector)", self._assess("spikes", 100).reasons)


class TestExplain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = _small_tables(["K001", "K002", "KA04", "KA15", "KI04", "KI14"], reps=2)
        cls.g = ReliabilityGated().fit(cls.t["clean"])

    def test_names_match_features(self):
        self.assertEqual(len(VIB_FEATURE_NAMES), self.t["clean"]["fv"].shape[1])
        self.assertEqual(len(CUR_FEATURE_NAMES), self.t["clean"]["fc"].shape[1])

    def test_contributions_reconstruct_logits(self):
        pipe, x = self.g.ev, self.t["clean"]["fv"][0]
        clf = pipe.steps[-1][1]
        logp = np.log(pipe.predict_proba(x[None])[0])
        for c in range(len(clf.classes_)):
            contrib = linear_contributions(pipe, x, clf.classes_[c]).sum()
            intercept = clf.intercept_[c] - clf.intercept_.mean()
            self.assertAlmostEqual(contrib + intercept, logp[c] - logp.mean(), places=6)

    def test_explain_gated(self):
        one = {k: v[:1] for k, v in self.t["clean"].items()}
        e = explain_gated(self.g, one)
        for key in ("predicted", "confidence", "sensor_weights", "vibration_evidence", "gate_drivers", "faithfulness_drop"):
            self.assertIn(key, e)
        self.assertIsInstance(deletion_check(self.g.ev, one["fv"][0], 0), float)


class TestHealth(unittest.TestCase):
    def test_escalation_latch_and_ack(self):
        h = HealthTracker()
        self.assertEqual(h.update(0.1, None, {"vib": OK, "cur": OK}).state, NORMAL)
        states = [h.update(0.95, "outer_race", {"vib": OK, "cur": OK}).state for _ in range(4)]
        self.assertEqual(states[1], WARNING)
        self.assertEqual(states[-1], INSPECT)
        a = h.update(0.0, None, {"vib": OK, "cur": OK})
        self.assertEqual(a.state, INSPECT)                     # latched
        h.acknowledge()
        self.assertEqual(h.update(0.0, None, {"vib": OK, "cur": OK}).state, NORMAL)

    def test_warning_recovers_after_quiet_windows(self):
        h = HealthTracker()
        for _ in range(2):
            h.update(0.6, None, {"vib": OK})
        states = [h.update(0.1, None, {"vib": OK}).state for _ in range(12)]
        self.assertEqual(states[0], WARNING)
        self.assertEqual(states[-1], NORMAL)

    def test_sensor_failures(self):
        h = HealthTracker()
        a = h.update(None, None, {"vib": DEAD, "cur": DEAD})
        self.assertEqual(a.state, SENSOR_FAULT)
        self.assertFalse(a.diagnosis_available)
        a = h.update(0.1, None, {"vib": DEAD, "cur": OK})
        self.assertTrue(a.diagnosis_available)
        self.assertTrue(any("Vibration sensor failed" in r for r in a.recommendations))
        self.assertTrue(any("relies on: Current" in r for r in a.recommendations))


class TestStore(unittest.TestCase):
    def test_log_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            s = HealthStore(Path(d) / "h.db")
            s.log_window({"asset": "a", "source": "SIMULATED rig", "state": "NORMAL", "p_fault": 0.1,
                          "readings": {"rpm": 1500}, "recommendations": []})
            s.log_event("a", "SIMULATED rig", "NORMAL", "WARNING", "rule", ["watch trend"])
            self.assertEqual(len(s.history("a")), 1)
            self.assertEqual(s.history("a")[0]["readings"], '{"rpm": 1500}')
            html = Path(s.export_html(Path(d) / "r.html", "a")).read_text()
            self.assertIn("SIMULATED rig", html)
            self.assertIn("watch trend", html)
            self.assertIn("p_fault", Path(s.export_csv(Path(d) / "r.csv", "a")).read_text())


class TestRig(unittest.TestCase):
    def test_protocol_roundtrip_chunked_and_corrupt(self):
        f1 = encode_frame({"seq": 1, "vib_first": 0, "vib_ref_idx": 799, "vib_ref_us": 250000},
                          np.arange(800) - 400, np.full(1250, 2048))
        f2 = encode_frame({"seq": 2, "vib_first": 800, "rpm": 1501.0}, np.zeros(800), np.zeros(1250))
        bad = bytearray(f2); bad[40] ^= 0xFF
        stream = b"junk" + f1 + bytes(bad) + f2
        p, got = FrameParser(), []
        for i in range(0, len(stream), 97):
            got += p.feed(stream[i:i + 97])
        self.assertEqual([g["seq"] for g in got], [1, 2])
        self.assertEqual(p.bad, 1)
        np.testing.assert_array_equal(got[0]["vib"], np.arange(800) - 400)
        self.assertEqual(got[0]["vib_ref_us"], 250000)
        self.assertAlmostEqual(got[1]["rpm"], 1501.0, places=3)

    def test_firmware_header_layout_matches_parser(self):
        """Compile the firmware's own Header struct on the host and decode its bytes."""
        import re, shutil, subprocess
        if not shutil.which("g++"):
            self.skipTest("g++ not available")
        ino = (Path(__file__).resolve().parents[1] / "firmware/rig_esp32/rig_esp32.ino").read_text()
        struct_src = re.search(r"#pragma pack\(push, 1\)(.*?)#pragma pack\(pop\)", ino, re.S).group(0)
        prog = ("#include <cstdint>\n#include <cstdio>\n#include <cmath>\n" + struct_src + "\n"
                "int main(){Header h={};h.seq=7;h.t_us=123456;h.dt_us=250001;h.vib_first=11;h.vib_ref_idx=12;"
                "h.vib_ref_us=13;h.cur_first=21;h.cur_ref_idx=22;h.cur_ref_us=23;h.n_vib=0;h.n_cur=0;h.rpm=1499.5f;"
                "h.temp_c=36.25f;h.vbus_adc=1234.5f;h.vib_overruns=1;h.adc_pool_ovf=2;h.vib_drops=3;h.cur_drops=4;"
                "h.adc_bad_ch=5;h.flags=3;fwrite(\"RIG2\",1,4,stdout);fwrite(&h,sizeof h,1,stdout);"
                "const unsigned char*p=(const unsigned char*)&h;unsigned s=0;for(unsigned i=0;i<sizeof h;i++)s+=p[i];"
                "unsigned short c=s&0xFFFF;fwrite(&c,2,1,stdout);return 0;}")
        with tempfile.TemporaryDirectory() as d:
            src, exe = Path(d) / "h.cpp", Path(d) / "h"
            src.write_text(prog)
            subprocess.run(["g++", "-std=c++17", "-o", str(exe), str(src)], check=True)
            raw = subprocess.run([str(exe)], check=True, capture_output=True).stdout
        fr = FrameParser().feed(raw)
        self.assertEqual(len(fr), 1)
        f = fr[0]
        self.assertEqual((f["seq"], f["t_us"], f["dt_us"], f["vib_first"], f["vib_ref_idx"], f["vib_ref_us"],
                          f["cur_first"], f["cur_ref_idx"], f["cur_ref_us"]), (7, 123456, 250001, 11, 12, 13, 21, 22, 23))
        self.assertEqual((f["vib_overruns"], f["adc_pool_ovf"], f["vib_drops"], f["cur_drops"], f["adc_bad_ch"], f["flags"]),
                         (1, 2, 3, 4, 5, 3))
        self.assertAlmostEqual(f["rpm"], 1499.5, places=3)

    def test_gap_becomes_nan_exactly(self):
        src = SimulatedRigSource(seed=1, drop_every=4)
        p, asm, wins = FrameParser(), WindowAssembler(src.cfg), []
        while len(wins) < 6:
            for fr in p.feed(src.read()):
                wins += asm.push(fr)
        self.assertEqual(asm.v.gap_samples, 100 * asm.v.gap_events)
        self.assertGreater(asm.v.gap_events, 0)
        n_nan = sum(int(np.isnan(w["vib"]).sum()) for w in wins)
        self.assertEqual(n_nan % 100, 0)
        self.assertGreater(n_nan, 0)

    def test_timing_recovers_clock_error_and_aligns_streams(self):
        cfg = RigConfig()
        src = SimulatedRigSource(cfg, seed=2, vib_clock_err=0.02, cur_clock_err=-0.0005, ref_jitter_us=300)
        p, asm, ta, wins = FrameParser(), WindowAssembler(cfg), TimingAnalyzer(cfg), []
        for _ in range(240):                                  # 60 s
            for fr in p.feed(src.read()):
                ta.add(fr); wins += asm.push(fr)
        rep = ta.report(p.bad)
        self.assertAlmostEqual(rep["vib"]["ppm_vs_nominal"], 20000, delta=200)
        self.assertAlmostEqual(rep["cur"]["ppm_vs_nominal"], -500, delta=200)
        self.assertGreater(rep["vib"]["ref_jitter_us_rms"], 50)
        self.assertTrue(rep["checks"]["no_sample_gaps"])
        self.assertFalse(rep["checks"]["vib_rate_within_5pct"] is False)
        late = wins[-10:]
        for w in late:                                       # both streams cover the same 0.5 s
            self.assertAlmostEqual(len(w["vib"]) / w["fs_vib"], 0.5, delta=2 / w["fs_vib"])
            self.assertAlmostEqual(len(w["cur"]) / w["fs_cur"], 0.5, delta=2 / w["fs_cur"])
            self.assertAlmostEqual(w["fs_vib"], 3264, delta=3)
        # alignment: window start times advance by exactly window_s in device time
        np.testing.assert_allclose(np.diff([w["t_us"] for w in late]), 5e5, atol=1)

    def test_timing_flags_drops(self):
        cfg = RigConfig()
        src = SimulatedRigSource(cfg, seed=3, drop_every=10)
        p, ta = FrameParser(), TimingAnalyzer(cfg)
        for _ in range(60):
            for fr in p.feed(src.read()):
                ta.add(fr)
        rep = ta.report(p.bad)
        self.assertFalse(rep["checks"]["no_sample_gaps"])
        self.assertFalse(rep["checks"]["no_device_overruns"])
        self.assertEqual(rep["vib"]["gap_samples"], 100 * rep["vib"]["gap_events"])

    def _session(self, condition, seed, n=24, fault=None):
        src = SimulatedRigSource(condition=condition, seed=seed)
        src.sensor_fault = fault
        p, asm, wins = FrameParser(), WindowAssembler(src.cfg), []
        while len(wins) < n:
            for fr in p.feed(src.read()):
                wins += asm.push(fr)
        return wins[:n]

    def test_rig_pipeline_end_to_end(self):
        cfg = RigConfig()
        feats = lambda ws: {k: np.stack([rig_features(w, cfg)[k] for w in ws]) for k in ("fv", "fc", "qv", "qc")}
        fit, cal = feats(self._session("healthy", 1)), feats(self._session("healthy", 2))
        det = RigAnomalyDetector().fit(fit, cal)
        assess = {"vib": ReliabilityAssessor().fit(fit["qv"]), "cur": ReliabilityAssessor().fit(fit["qc"])}
        with tempfile.TemporaryDirectory() as d:
            eng = MonitorEngine(RigDiagnoser(det, assess, cfg), SOURCE_SIM, store=HealthStore(Path(d) / "h.db"))
            healthy = [eng.step(w, ts=i) for i, w in enumerate(self._session("healthy", 3, 12))]
            fault = [eng.step(w, ts=100 + i) for i, w in enumerate(self._session("outer_race", 4, 12))]
            self.assertEqual(healthy[-1]["state"], NORMAL)
            self.assertEqual(fault[-1]["state"], INSPECT)
            self.assertGreaterEqual(len(eng.store.events()), 1)
            eng.tracker.acknowledge()
            dead = [eng.step(w, ts=200 + i) for i, w in enumerate(self._session("healthy", 5, 4, "vib_dropout"))]
            self.assertEqual(dead[-1]["diagnosis"]["reliability"]["vib"].status, "failed")
            self.assertTrue(dead[-1]["assessment"].diagnosis_available)


class TestBenchmarkEngine(unittest.TestCase):
    def test_benchmark_monitor(self):
        t = _small_tables(["K001", "K002", "KA04", "KA15", "KI04", "KI14"], reps=2)
        g = ReliabilityGated().fit(t["clean"])
        assess = {"vib": ReliabilityAssessor().fit(t["clean"]["qv"]), "cur": ReliabilityAssessor().fit(t["clean"]["qc"])}
        eng = MonitorEngine(BenchmarkDiagnoser(g, assess), SOURCE_BENCHMARK)
        rec = synth_recording("KA16", "N15_M07_F10", 1, seconds=1.0)
        outs = [eng.step({"vib": v, "cur": c, "fs": FS, "condition": rec.condition})
                for _, v, c in windows(rec, 0.25)]
        self.assertIn(outs[-1]["state"], {NORMAL, WARNING, INSPECT})
        self.assertIsNotNone(outs[-1]["explanation"])
        self.assertAlmostEqual(sum(outs[-1]["diagnosis"]["probs"].values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
