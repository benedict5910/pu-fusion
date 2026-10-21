"""SYNTHETIC rig byte-stream generator - for testing the host software ONLY.
Produces frames exactly as the firmware would; results from it are never rig results.

Usage: python rig/simulate.py <out_dir>   (writes SIM_H1..SIM_H4, SIM_F1 sessions)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rigio import build_frame, Parser, to_session, save_session, timing_report  # noqa: E402


def stream(seconds, fault=False, seed=0, drop_every=0, corrupt_every=0):
    rng = np.random.default_rng(seed)
    out = bytearray()
    seq = 0
    na, nc = int(3200 * seconds), int(5000 * seconds)
    ta = np.arange(na) / 3200
    tc = np.arange(nc) / 5000
    acc = rng.normal(0, 0.05, (na, 3)) + [0, 0, 1.0]
    acc[:, 0] += 0.03 * np.sin(2 * np.pi * 25 * ta)
    if fault:
        for t0 in np.arange(0, seconds, 1 / 76.0):
            i = int(t0 * 3200)
            L = min(20, na - i)
            acc[i:i + L, 0] += 0.4 * np.exp(-np.arange(L) / 4) * np.sin(2 * np.pi * 900 * np.arange(L) / 3200)
    cur = 2500 + 300 * np.sin(2 * np.pi * 50 * tc) + rng.normal(0, 5, nc)
    if fault:
        cur += 8 * np.sin(2 * np.pi * 76 * tc)
    events = []
    for i in range(0, na, 16):
        blk = np.round(acc[i:i + 16] / 0.0039).astype("<i2")
        events.append((ta[min(i + 15, na - 1)], 1, blk.tobytes(), len(blk)))
    for i in range(0, nc, 64):
        blk = np.round(cur[i:i + 64]).astype("<u2")
        events.append((tc[min(i + 63, nc - 1)], 2, blk.tobytes(), len(blk)))
    for t in np.arange(0, seconds, 0.1):
        events.append((t, 3, np.array([40000, int(t * 25)], "<u4").tobytes(), 1))
    for t in np.arange(1, seconds, 1.0):
        events.append((t, 4, np.zeros(3, "<u4").tobytes(), 1))
    events.sort(key=lambda e: e[0])
    for k, (t, ft, pl, n) in enumerate(events):
        fr = bytearray(build_frame(ft, seq, int(t * 1e6) + 123456, n, pl))
        seq += 1
        if drop_every and k % drop_every == 0:
            continue
        if corrupt_every and k % corrupt_every == 0:
            fr[-3] ^= 0xFF
        out += fr
    return bytes(out)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, fault, seed in [("SIM_H1", 0, 1), ("SIM_H2", 0, 2), ("SIM_H3", 0, 3), ("SIM_H4", 0, 4),
                              ("SIM_F1", 1, 5)]:
        p = Parser()
        b = stream(60, bool(fault), seed)
        for i in range(0, len(b), 4096):
            p.feed(b[i:i + 4096])
        sess = to_session(p, {"session": name, "label": "fault" if fault else "healthy",
                              "notes": "SYNTHETIC simulator output - not a rig recording"})
        save_session(sess, out / name)
        print(name, timing_report(sess)["PASS"])
    # negative test: dropped and corrupted frames must FAIL the acceptance test
    p = Parser()
    p.feed(stream(10, False, 9, drop_every=50, corrupt_every=70))
    print("faulty-link test PASS flag (expected False):",
          timing_report(to_session(p, {"session": "SIM_BAD", "label": "healthy"}))["PASS"],
          "crc_errors", p.crc_errors)
