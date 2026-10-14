"""Low-cost ESP32 test rig: frame protocol, sources, windowing and a healthy-baseline
anomaly detector.

Why a separate model: the rig samples vibration at 3.2 kHz (ADXL345) and the
current of a DC motor, whereas Paderborn records 64 kHz vibration and inverter
phase currents of a different machine. Paderborn-trained models are therefore
NEVER applied to rig signals. On the rig we use:
  1. the label-free reliability assessor (refitted on rig healthy data), and
  2. a healthy-baseline anomaly detector (Mahalanobis distance), validated on
     separate healthy and seeded-fault sessions recorded on the rig.

Binary frame (little-endian), sent by firmware/rig_esp32/rig_esp32.ino:
  b"RIG1" | u32 seq | u32 t_ms | u16 n_vib | u16 n_cur | f32 rpm | f32 temp_c |
  f32 vbus | i16 vib[n_vib] | u16 cur_adc[n_cur] | u16 checksum
checksum = sum of all bytes after the magic and before the checksum, mod 65536.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.preprocessing import StandardScaler

from .config import fault_frequencies
from .features import generic_features, quality_indicators, vibration_features

MAGIC = b"RIG1"
_HDR = struct.Struct("<IIHHfff")


@dataclass
class RigConfig:
    fs_vib: int = 3200
    fs_cur: int = 5000
    frame_s: float = 0.25
    window_s: float = 0.5
    vib_g_per_lsb: float = 0.0039          # ADXL345 full-resolution mode
    adc_vref: float = 3.3
    adc_max: int = 4095
    divider: float = 1.5                   # 10k/20k divider on the 5 V ACS712 output
    acs_v_per_a: float = 0.185             # ACS712-05B
    cur_zero_v: float = 2.5                # measure with motor off (scripts/rig_record.py --calibrate-zero)
    vib_band: tuple = (300, 1500)
    # Bearing on the rig: set from YOUR bearing's datasheet (default: 608 deep-groove)
    geometry: dict = field(default_factory=lambda: {"n_balls": 7, "d": 3.969, "D": 15.0})

    @property
    def n_vib(self): return int(self.fs_vib * self.frame_s)

    @property
    def n_cur(self): return int(self.fs_cur * self.frame_s)

    def amps(self, adc):
        v = np.asarray(adc, dtype=np.float64) * self.adc_vref / self.adc_max * self.divider
        return (v - self.cur_zero_v) / self.acs_v_per_a


# ------------------------------------------------------------------ protocol
def encode_frame(seq, t_ms, vib_raw, cur_adc, rpm, temp_c, vbus) -> bytes:
    vib_raw = np.asarray(vib_raw, dtype="<i2")
    cur_adc = np.asarray(cur_adc, dtype="<u2")
    body = _HDR.pack(seq, t_ms, len(vib_raw), len(cur_adc), rpm, temp_c, vbus) + vib_raw.tobytes() + cur_adc.tobytes()
    return MAGIC + body + struct.pack("<H", sum(body) & 0xFFFF)


class FrameParser:
    """Incremental parser: feed arbitrary byte chunks, get complete valid frames.
    Corrupt frames (bad checksum) are dropped and counted; the parser resyncs on MAGIC."""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0

    def feed(self, data: bytes) -> list[dict]:
        self.buf += data
        out = []
        while True:
            i = self.buf.find(MAGIC)
            if i < 0:
                del self.buf[:-3]
                return out
            del self.buf[:i]
            if len(self.buf) < 4 + _HDR.size:
                return out
            seq, t_ms, nv, nc, rpm, temp, vbus = _HDR.unpack_from(self.buf, 4)
            total = 4 + _HDR.size + 2 * nv + 2 * nc + 2
            if nv > 20000 or nc > 20000:          # garbage header: skip this magic
                del self.buf[:4]; self.bad += 1; continue
            if len(self.buf) < total:
                return out
            body = bytes(self.buf[4:total - 2])
            (chk,) = struct.unpack_from("<H", self.buf, total - 2)
            if sum(body) & 0xFFFF != chk:
                del self.buf[:4]; self.bad += 1; continue
            off = _HDR.size
            vib = np.frombuffer(body, "<i2", nv, off)
            cur = np.frombuffer(body, "<u2", nc, off + 2 * nv)
            out.append({"seq": seq, "t_ms": t_ms, "vib": vib.copy(), "cur": cur.copy(),
                        "rpm": rpm, "temp_c": temp, "vbus": vbus})
            del self.buf[:total]


class WindowAssembler:
    """Frames -> fixed windows in physical units. Lost frames (sequence gaps)
    become NaN samples, which the reliability assessor reports as link loss."""

    def __init__(self, cfg: RigConfig):
        self.cfg = cfg
        self.per_win = int(round(cfg.window_s / cfg.frame_s))
        self.frames, self.last_seq = [], None

    def push(self, fr: dict) -> list[dict]:
        out = []
        if self.last_seq is not None:
            for _ in range(max(0, min(fr["seq"] - self.last_seq - 1, 40))):
                self._append({"vib": np.full(self.cfg.n_vib, np.nan), "cur": np.full(self.cfg.n_cur, np.nan),
                              "rpm": np.nan, "temp_c": np.nan, "vbus": np.nan, "t_ms": None}, out)
        self.last_seq = fr["seq"]
        g = {"vib": fr["vib"] * self.cfg.vib_g_per_lsb, "cur": self.cfg.amps(fr["cur"]),
             "rpm": fr["rpm"], "temp_c": fr["temp_c"], "vbus": fr["vbus"], "t_ms": fr["t_ms"]}
        self._append(g, out)
        return out

    def _append(self, g, out):
        self.frames.append(g)
        if len(self.frames) == self.per_win:
            f = self.frames
            nanmean = lambda k: float(np.nanmean([x[k] for x in f])) if any(np.isfinite(x[k]) for x in f) else float("nan")
            out.append({"vib": np.concatenate([x["vib"] for x in f]).astype(np.float32),
                        "cur": np.concatenate([x["cur"] for x in f]).astype(np.float32),
                        "rpm": nanmean("rpm"), "temp_c": nanmean("temp_c"), "vbus": nanmean("vbus"),
                        "t_ms": next((x["t_ms"] for x in f if x["t_ms"] is not None), None)})
            self.frames = []


# ------------------------------------------------------------------- sources
class SimulatedRigSource:
    """SIMULATED rig (for development and a hardware-free demo). Produces real
    binary frames so the whole parsing path is exercised. Not data."""

    def __init__(self, cfg=None, condition="healthy", rpm=1800.0, seed=0):
        self.cfg, self.condition, self.rpm = cfg or RigConfig(), condition, rpm
        self.rng = np.random.default_rng(seed)
        self.seq, self.t = 0, 0.0
        self.sensor_fault = None              # e.g. "vib_dropout", "cur_noise", "vib_clip", "frame_loss"
        self.res_f = 900.0

    def _frame_signals(self):
        c, rng = self.cfg, self.rng
        ff = fault_frequencies(self.rpm, c.geometry)
        tv = self.t + np.arange(c.n_vib) / c.fs_vib
        tc = self.t + np.arange(c.n_cur) / c.fs_cur
        unb = 0.15 if self.condition == "unbalance" else 0.05
        vib = unb * np.sin(2 * np.pi * ff["fr"] * tv) + rng.normal(0, 0.03, c.n_vib)
        if self.condition == "outer_race":
            ph = (tv * ff["bpfo"]) % 1.0
            vib += 0.25 * np.exp(-ph / ff["bpfo"] * 400) * np.sin(2 * np.pi * self.res_f * tv)
        amps = 1.2 + 0.08 * np.sin(2 * np.pi * 12 * ff["fr"] * tc) + rng.normal(0, 0.01, c.n_cur)
        if self.condition in ("outer_race", "unbalance"):
            amps += 0.03 * np.sin(2 * np.pi * ff["fr"] * tc)
        return vib, amps

    def read(self) -> bytes:
        c = self.cfg
        vib, amps = self._frame_signals()
        sf = self.sensor_fault
        if sf == "vib_dropout":
            vib = np.zeros_like(vib)
        if sf == "vib_clip":
            vib = np.clip(vib, -0.05, 0.05)
        if sf == "cur_noise":
            amps = amps + self.rng.normal(0, 0.3, len(amps))
        vib_raw = np.clip(np.round(vib / c.vib_g_per_lsb), -32768, 32767)
        adc = np.clip(np.round((amps * c.acs_v_per_a + c.cur_zero_v) / c.divider / c.adc_vref * c.adc_max), 0, c.adc_max)
        frame = encode_frame(self.seq, int(self.t * 1000), vib_raw, adc, self.rpm,
                             38.0 + self.rng.normal(0, 0.1), 12.0 + self.rng.normal(0, 0.02))
        self.seq += 1
        self.t += c.frame_s
        if sf == "frame_loss" and self.rng.random() < 0.3:
            return b""
        return frame


class SerialRigSource:
    """Real hardware over USB serial. Requires `pip install pyserial`."""

    def __init__(self, port, baud=921600):
        import serial  # noqa: PLC0415
        self.ser = serial.Serial(port, baud, timeout=0.05)

    def read(self) -> bytes:
        return self.ser.read(8192)


# ------------------------------------------------------------ rig features
def rig_features(win: dict, cfg: RigConfig) -> dict:
    rpm = win["rpm"] if np.isfinite(win["rpm"]) and win["rpm"] > 60 else 1500.0
    return {
        "fv": vibration_features(win["vib"], cfg.fs_vib, rpm, band=cfg.vib_band, geom=cfg.geometry),
        "fc": generic_features(win["cur"], cfg.fs_cur),
        "qv": quality_indicators(win["vib"], cfg.fs_vib),
        "qc": quality_indicators(win["cur"], cfg.fs_cur),
    }


class RigAnomalyDetector:
    """Healthy-baseline detector, one per sensor: Mahalanobis distance of the
    window's features from healthy rig data (Ledoit-Wolf covariance).
    Threshold = ``quantile`` of distances on a SEPARATE healthy calibration
    session. ``evidence`` is 0.5 at the threshold; it is a score, not a probability."""

    def __init__(self, quantile=0.995):
        self.q = quantile

    def _fit_one(self, F_fit, F_cal):
        sc = StandardScaler().fit(F_fit)
        cov = LedoitWolf().fit(np.clip(sc.transform(F_fit), -8, 8))
        d_cal = cov.mahalanobis(np.clip(sc.transform(F_cal), -8, 8))
        return {"sc": sc, "cov": cov, "thr": float(np.quantile(d_cal, self.q))}

    def fit(self, fit_feats: dict, cal_feats: dict):
        self.m = {s: self._fit_one(fit_feats[k], cal_feats[k]) for s, k in (("vib", "fv"), ("cur", "fc"))}
        return self

    def evidence(self, feats: dict) -> dict:
        out = {}
        for s, k in (("vib", "fv"), ("cur", "fc")):
            m = self.m[s]
            d = m["cov"].mahalanobis(np.clip(m["sc"].transform(np.atleast_2d(feats[k])), -8, 8))
            out[s] = 1 / (1 + np.exp(-(d - m["thr"]) / (0.25 * m["thr"] + 1e-9)))
        return out

    @staticmethod
    def combine(ev: dict, reliability: dict):
        """Reliability-weighted evidence over usable sensors (None if none usable)."""
        w = {s: r.score for s, r in reliability.items() if r.status != "failed"}
        if not sum(w.values()):
            return None
        return float(sum(w[s] * np.ravel(ev[s])[0] for s in w) / sum(w.values()))


def load_rig_config(path="configs/rig.json") -> RigConfig:
    import json
    from pathlib import Path
    p = Path(path)
    return RigConfig(**json.loads(p.read_text())) if p.exists() else RigConfig()


def save_rig_config(cfg: RigConfig, path="configs/rig.json"):
    import dataclasses
    import json
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    d = dataclasses.asdict(cfg)
    d["vib_band"] = list(d["vib_band"])
    Path(path).write_text(json.dumps(d, indent=2))


def collect_windows(source, cfg: RigConfig, n_windows: int, max_reads=100000):
    """Read from a source until n_windows are assembled."""
    parser, asm, wins = FrameParser(), WindowAssembler(cfg), []
    for _ in range(max_reads):
        for fr in parser.feed(source.read()):
            wins += asm.push(fr)
        if len(wins) >= n_windows:
            return wins[:n_windows], parser.bad
    return wins, parser.bad
