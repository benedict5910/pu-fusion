"""Rig serial protocol: frame parser, session files, timing acceptance test.

Frame: A5 5A | type u8 | seq u16 | t_us u32 | n u16 | payload | crc16-ccitt(type..payload)
"""
from __future__ import annotations
import json
import struct
from pathlib import Path
import numpy as np

SYNC = b"\xA5\x5A"
HDR = struct.Struct("<BHIH")          # type, seq, t_us, n
PAYLOAD_BYTES = {1: 6, 2: 2, 3: 8, 4: 12}
NOMINAL = {"accel_hz": 3200.0, "current_hz": 5000.0}


def crc16(data: bytes, c: int = 0xFFFF) -> int:
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def build_frame(ftype, seq, t_us, n, payload: bytes) -> bytes:
    h = HDR.pack(ftype, seq & 0xFFFF, t_us & 0xFFFFFFFF, n)
    return SYNC + h + payload + struct.pack("<H", crc16(h + payload))


class Parser:
    """Incremental parser; feed() raw bytes, collects blocks and error counters."""

    def __init__(self):
        self.buf = bytearray()
        self.blocks = {1: [], 2: [], 3: [], 4: []}   # (seq, t_us, ndarray)
        self.crc_errors = 0
        self.resyncs = 0
        self.frames = 0
        self.text = []

    def feed(self, data: bytes):
        self.buf += data
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                if len(self.buf) > 1:
                    self.buf = self.buf[-1:]
                return
            if i > 0:
                junk = bytes(self.buf[:i])
                if junk.strip():
                    self.text.append(junk.decode(errors="replace"))
                self.resyncs += 1
                del self.buf[:i]
            if len(self.buf) < 2 + HDR.size:
                return
            ftype, seq, t_us, n = HDR.unpack_from(self.buf, 2)
            if ftype not in PAYLOAD_BYTES or n > 4096:
                del self.buf[:2]
                self.resyncs += 1
                continue
            plen = n * PAYLOAD_BYTES[ftype] if ftype in (1, 2) else PAYLOAD_BYTES[ftype]
            total = 2 + HDR.size + plen + 2
            if len(self.buf) < total:
                return
            body = bytes(self.buf[2:2 + HDR.size + plen])
            (crc,) = struct.unpack_from("<H", self.buf, total - 2)
            if crc16(body) != crc:
                self.crc_errors += 1
                del self.buf[:2]
                continue
            p = body[HDR.size:]
            if ftype == 1:
                arr = np.frombuffer(p, "<i2").reshape(-1, 3).copy()
            elif ftype == 2:
                arr = np.frombuffer(p, "<u2").copy()
            else:
                arr = np.frombuffer(p, "<u4").copy()
            self.blocks[ftype].append((seq, t_us, arr))
            self.frames += 1
            del self.buf[:total]


def _unwrap_us(t):
    t = np.asarray(t, dtype=np.int64)
    d = np.diff(t)
    d[d < -2 ** 31] += 2 ** 32
    return np.concatenate([[t[0]], t[0] + np.cumsum(d)]) if len(t) else t


def to_session(p: Parser, meta: dict) -> dict:
    """Assemble continuous arrays with per-sample timestamps reconstructed from block-end
    device times (linear spacing inside a block)."""
    out = {"meta": meta}
    for ftype, name in ((1, "accel"), (2, "current")):
        b = p.blocks[ftype]
        if not b:
            continue
        tend = _unwrap_us([x[1] for x in b])
        data = np.concatenate([x[2] for x in b])
        counts = np.array([len(x[2]) for x in b])
        # estimate per-sample period from block end times
        per = np.diff(tend) / counts[1:] if len(b) > 1 else np.array([1e6 / NOMINAL[f"{name}_hz"]])
        dt = float(np.median(per))
        ts = np.concatenate([te - dt * np.arange(c - 1, -1, -1) for te, c in zip(tend, counts)])
        out[name] = data
        out[f"{name}_t_us"] = ts
        out[f"{name}_seq"] = np.array([x[0] for x in b])
    if p.blocks[3]:
        out["rpm_t_us"] = _unwrap_us([x[1] for x in p.blocks[3]])
        per = np.array([x[2][0] for x in p.blocks[3]], dtype=float)
        out["rpm"] = np.where(per > 0, 60e6 / np.maximum(per, 1), 0.0)
    if p.blocks[4]:
        out["status_last"] = p.blocks[4][-1][2].tolist()
    out["errors"] = {"crc_errors": p.crc_errors, "resyncs": p.resyncs, "frames": p.frames}
    allseq = sorted((x[1], x[0]) for k in p.blocks for x in p.blocks[k])
    seq = np.array([s for _, s in allseq], dtype=np.int64)
    gaps = int(((np.diff(seq) % 65536) - 1).clip(0).sum()) if len(seq) > 1 else 0
    out["errors"]["seq_gaps"] = gaps
    return out


def save_session(sess: dict, path: str | Path):
    path = Path(path)
    arrays = {k: v for k, v in sess.items() if isinstance(v, np.ndarray)}
    np.savez_compressed(path.with_suffix(".npz"), **arrays)
    side = {k: v for k, v in sess.items() if not isinstance(v, np.ndarray)}
    path.with_suffix(".json").write_text(json.dumps(side, indent=1, default=float))


def load_session(path: str | Path) -> dict:
    path = Path(path)
    d = dict(np.load(path.with_suffix(".npz")))
    d.update(json.loads(path.with_suffix(".json").read_text()))
    return d


def timing_report(sess: dict, tol=0.02) -> dict:
    """Acceptance test: measured rates within tol of nominal, no seq gaps beyond 0.1 %,
    CRC errors < 0.1 % of frames, no FIFO-full / ADC overrun / TX drop events."""
    rep, ok = {}, True
    for name in ("accel", "current"):
        if name not in sess:
            rep[name] = "missing"
            ok = False
            continue
        t = sess[f"{name}_t_us"]
        n = len(t)
        dur = (t[-1] - t[0]) / 1e6
        rate = (n - 1) / dur if dur > 0 else 0
        nom = NOMINAL[f"{name}_hz"]
        dt = np.diff(t)
        rep[name] = {"samples": int(n), "duration_s": round(dur, 3), "measured_hz": round(rate, 2),
                     "nominal_hz": nom, "rate_error": round(rate / nom - 1, 5),
                     "max_gap_ms": round(float(dt.max()) / 1e3, 3) if n > 1 else None}
        ok &= abs(rate / nom - 1) <= tol
    e = sess["errors"]
    frames = max(e["frames"], 1)
    rep["errors"] = e
    rep["status_last"] = sess.get("status_last")
    ok &= e["crc_errors"] / frames < 1e-3 and e["seq_gaps"] / frames < 1e-3
    if sess.get("status_last"):
        ok &= sum(sess["status_last"]) == 0
    rep["PASS"] = bool(ok)
    return rep
