"""Record one rig session from the ESP32 over USB serial.

Usage (on the laptop connected to the rig):
  python rig/logger.py --port COM5 --seconds 120 --session H1 --label healthy --notes "no load"
Writes rig/sessions/<session>.npz + .json and prints the timing acceptance report.
Requires: pip install pyserial
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rigio import Parser, to_session, save_session, timing_report  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--session", required=True, help="e.g. H1, H2, H3, H4, F1")
    ap.add_argument("--label", required=True, choices=["healthy", "fault"])
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "sessions"))
    a = ap.parse_args()
    import serial  # pyserial
    Path(a.out).mkdir(parents=True, exist_ok=True)
    p = Parser()
    with serial.Serial(a.port, a.baud, timeout=0.05) as s:
        s.reset_input_buffer()
        time.sleep(0.5)
        s.reset_input_buffer()
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            p.feed(s.read(8192))
    meta = {"session": a.session, "label": a.label, "notes": a.notes,
            "recorded": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": a.seconds, "port": a.port}
    sess = to_session(p, meta)
    save_session(sess, Path(a.out) / a.session)
    rep = timing_report(sess)
    (Path(a.out) / f"{a.session}_timing.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    if p.text:
        print("device text:", "".join(p.text)[:500])


if __name__ == "__main__":
    main()
