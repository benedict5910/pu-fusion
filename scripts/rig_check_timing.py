"""Acquisition self-test for the ESP32 rig: sample rates, clock drift, jitter, gaps, overruns.

  python scripts/rig_check_timing.py --port COM5 --seconds 120
  python scripts/rig_check_timing.py --replay data/rig/H1.bin          # re-analyse a recording
  python scripts/rig_check_timing.py --simulate --seconds 60 --vib-clock-err 0.02

Prints a JSON report and exits 1 if any acquisition check fails. Run it once after
assembling the rig and again whenever wiring changes. The measured rates are what the
feature extractor uses, so a few-percent ADXL345 rate error is corrected, not ignored.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.rig import FrameParser, SerialRigSource, SimulatedRigSource, TimingAnalyzer, load_rig_config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port")
    g.add_argument("--replay")
    g.add_argument("--simulate", action="store_true")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--vib-clock-err", type=float, default=0.0)
    ap.add_argument("--config", default="configs/rig.json")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_rig_config(a.config)
    parser, ta = FrameParser(), TimingAnalyzer(cfg)
    if a.replay:
        for fr in parser.feed(Path(a.replay).read_bytes()):
            ta.add(fr)
        source = f"replay {a.replay}"
    else:
        src = SerialRigSource(a.port) if a.port else SimulatedRigSource(cfg, vib_clock_err=a.vib_clock_err)
        source = f"serial {a.port}" if a.port else "SIMULATED"
        t0, n_frames = time.time(), int(a.seconds / cfg.frame_s)
        while len(ta.frames) < n_frames and (a.simulate or time.time() - t0 < a.seconds + 10):
            for fr in parser.feed(src.read()):
                ta.add(fr)
    rep = {"source": source, **ta.report(parser.bad)}
    txt = json.dumps(rep, indent=2)
    print(txt)
    if a.out:
        Path(a.out).write_text(txt)
    ok = "checks" in rep and all(rep["checks"].values())
    print("\nACQUISITION CHECK:", "PASS" if ok else "FAIL",
          "" if ok else [k for k, v in rep.get("checks", {}).items() if not v])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
