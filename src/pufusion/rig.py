"""Low-cost ESP32 test rig: frame protocol, sources, windowing and a healthy-baseline
anomaly detector.

Why a separate model: the rig samples vibration at 3.2 kHz (ADXL345) and the
current of a DC motor, whereas Paderborn records 64 kHz vibration and inverter
phase currents of a different machine. Paderborn-trained models are therefore
NEVER applied to rig signals. On the rig we use:
  1. the label-free reliability assessor (refitted on rig healthy data), and
  2. a healthy-baseline anomaly detector (Mahalanobis distance), validated on
     separate healthy and seeded-fault sessions recorded on the rig.

Binary frame RIG2 (little-endian), sent by firmware/rig_esp32/rig_esp32.ino:
  b"RIG2" | header (64 B) | i16 vib[n_vib] | u16 cur_adc[n_cur] | u16 checksum
  header = u32 seq, t_us, dt_us,
           u32 vib_first, vib_ref_idx, vib_ref_us,   (absolute index of vib[0]; index+micros of newest sample)
           u32 cur_first, cur_ref_idx, cur_ref_us,
           u16 n_vib, n_cur, f32 rpm, temp_c, vbus_adc,
           u16 vib_overruns, adc_pool_ovf, vib_drops, cur_drops, adc_bad_ch, flags
checksum = sum of all bytes after the magic and before the checksum, mod 65536.
Sample indices make gaps exact (missing samples -> NaN) and (index, micros) pairs let the host
measure each stream's true sample rate, drift and jitter (see TimingAnalyzer).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.preprocessing import StandardScaler

from .config import fault_frequencies
from .features import generic_features, quality_indicators, vibration_features

MAGIC = b"RIG2"
_HDR = struct.Struct("<IIIIIIIIIHHfffHHHHHH")
HDR_FIELDS = ("seq", "t_us", "dt_us", "vib_first", "vib_ref_idx", "vib_ref_us", "cur_first", "cur_ref_idx",
              "cur_ref_us", "n_vib", "n_cur", "rpm", "temp_c", "vbus_adc", "vib_overruns", "adc_pool_ovf",
              "vib_drops", "cur_drops", "adc_bad_ch", "flags")
assert _HDR.size == 64


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
    vbus_scale: float = 3.3 / 4095 * 122 / 22   # ADC counts -> volts (100k/22k divider)
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
def encode_frame(hdr: dict, vib_raw, cur_adc) -> bytes:
    vib_raw = np.asarray(vib_raw, dtype="<i2")
    cur_adc = np.asarray(cur_adc, dtype="<u2")
    h = {f: 0 for f in HDR_FIELDS}
    h.update(hdr, n_vib=len(vib_raw), n_cur=len(cur_adc))
    body = _HDR.pack(*(h[f] for f in HDR_FIELDS)) + vib_raw.tobytes() + cur_adc.tobytes()
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
            h = dict(zip(HDR_FIELDS, _HDR.unpack_from(self.buf, 4)))
            nv, nc = h["n_vib"], h["n_cur"]
            if nv > 20000 or nc > 20000:          # garbage header: skip this magic
                del self.buf[:4]; self.bad += 1; continue
            total = 4 + _HDR.size + 2 * nv + 2 * nc + 2
            if len(self.buf) < total:
                return out
            body = bytes(self.buf[4:total - 2])
            (chk,) = struct.unpack_from("<H", self.buf, total - 2)
            if sum(body) & 0xFFFF != chk:
                del self.buf[:4]; self.bad += 1; continue
            off = _HDR.size
            h["vib"] = np.frombuffer(body, "<i2", nv, off).copy()
            h["cur"] = np.frombuffer(body, "<u2", nc, off + 2 * nv).copy()
            out.append(h)
            del self.buf[:total]


class ClockModel:
    """Least-squares fit of sample index vs. device time (us) for one stream.
    Gives the stream's true rate in the ESP32 clock and maps index <-> time."""

    def __init__(self, nominal_fs: float, min_span_s: float = 2.0, max_points: int = 2000):
        self.nominal, self.min_span, self.max_points = nominal_fs, min_span_s, max_points
        self.idx, self.us = [], []
        self._unwrap, self._last_raw = 0, None

    def add(self, idx: int, us: int):
        if self._last_raw is not None and us < self._last_raw - 2 ** 31:
            self._unwrap += 2 ** 32                   # micros() wraps every ~71.6 min
        self._last_raw = us
        self.idx.append(idx); self.us.append(us + self._unwrap)
        if len(self.idx) > self.max_points:
            self.idx, self.us = self.idx[-self.max_points:], self.us[-self.max_points:]

    def fit(self):
        """Return (fs, t0_us) with t(i) = t0 + i/fs * 1e6; nominal rate until enough span."""
        if len(self.idx) >= 3 and (self.us[-1] - self.us[0]) >= self.min_span * 1e6:
            i, t = np.asarray(self.idx, float), np.asarray(self.us, float)
            slope, t0 = np.polyfit(i, t, 1)             # us per sample
            return 1e6 / slope, t0
        if self.idx:
            return self.nominal, self.us[-1] - self.idx[-1] / self.nominal * 1e6
        return self.nominal, 0.0


class _Stream:
    def __init__(self, nominal_fs, max_gap):
        self.clock = ClockModel(nominal_fs)
        self.next_idx, self.start_idx = None, None
        self.buf = np.zeros(0, np.float32)
        self.gap_events, self.gap_samples, self.max_gap = 0, 0, max_gap

    def push(self, first, data, ref_idx, ref_us):
        if self.next_idx is None:
            self.next_idx = self.start_idx = first
        gap = first - self.next_idx
        if gap < 0 or gap > self.max_gap:              # device reset or absurd jump: restart stream
            self.next_idx = self.start_idx = first
            self.buf = np.zeros(0, np.float32)
            gap = 0
        if gap:
            self.gap_events += 1; self.gap_samples += gap
            self.buf = np.concatenate([self.buf, np.full(gap, np.nan, np.float32)])
        self.buf = np.concatenate([self.buf, np.asarray(data, np.float32)])
        self.next_idx = first + len(data)
        if ref_idx >= 0 and ref_us:
            self.clock.add(ref_idx, ref_us)

    def take(self, i0, i1):
        """Return samples with absolute indices [i0, i1) and drop everything before i1."""
        a, b = i0 - self.start_idx, i1 - self.start_idx
        out = self.buf[a:b]
        self.buf, self.start_idx = self.buf[b:], i1
        return out


class WindowAssembler:
    """Frames -> time-aligned windows in physical units.

    Both streams are cut on the SAME device-time grid using each stream's fitted
    clock, so a few-percent ADXL345 rate error cannot slowly misalign vibration
    and current. Missing samples (dropped frames, ring overruns) are NaN, which
    the reliability assessor reports as link loss. Each window carries the
    measured sample rates, which the feature extractor uses."""

    def __init__(self, cfg: RigConfig):
        self.cfg = cfg
        self.v = _Stream(cfg.fs_vib, int(cfg.fs_vib * 10))
        self.c = _Stream(cfg.fs_cur, int(cfg.fs_cur * 10))
        self.t_next = None
        self.meta = []
        self.last_counters = {}

    def push(self, fr: dict) -> list[dict]:
        cfg = self.cfg
        self.v.push(fr["vib_first"], fr["vib"] * cfg.vib_g_per_lsb, fr["vib_ref_idx"], fr["vib_ref_us"])
        self.c.push(fr["cur_first"], cfg.amps(fr["cur"]), fr["cur_ref_idx"], fr["cur_ref_us"])
        self.meta.append((fr["rpm"], fr["temp_c"], fr["vbus_adc"] * cfg.vbus_scale))
        self.last_counters = {k: fr[k] for k in ("vib_overruns", "adc_pool_ovf", "vib_drops", "cur_drops",
                                                  "adc_bad_ch", "flags")}
        out = []
        fsv, t0v = self.v.clock.fit()
        fsc, t0c = self.c.clock.fit()
        to_idx = lambda t, fs, t0: int(round((t - t0) * fs / 1e6))
        if self.t_next is None:                        # start where both streams have data
            self.t_next = max(t0v + self.v.start_idx / fsv * 1e6, t0c + self.c.start_idx / fsc * 1e6)
        while True:
            t1 = self.t_next + cfg.window_s * 1e6
            iv0, iv1 = to_idx(self.t_next, fsv, t0v), to_idx(t1, fsv, t0v)
            ic0, ic1 = to_idx(self.t_next, fsc, t0c), to_idx(t1, fsc, t0c)
            if iv1 > self.v.next_idx or ic1 > self.c.next_idx:
                break
            iv0, ic0 = max(iv0, self.v.start_idx), max(ic0, self.c.start_idx)
            vib, cur = self.v.take(iv0, iv1), self.c.take(ic0, ic1)
            m = np.asarray(self.meta, dtype=float)
            nanmean = lambda col: float(np.nanmean(col)) if np.isfinite(col).any() else float("nan")
            out.append({"vib": vib, "cur": cur, "fs_vib": float(fsv), "fs_cur": float(fsc),
                        "t_us": float(self.t_next), "rpm": nanmean(m[:, 0]), "temp_c": nanmean(m[:, 1]),
                        "vbus": nanmean(m[:, 2]), "counters": dict(self.last_counters)})
            self.meta = self.meta[-1:]
            self.t_next = t1
        return out


class TimingAnalyzer:
    """Offline timing verification over a capture: true sample rates, ppm error,
    jitter of the (index, time) references, gaps, drops, overruns, frame cadence."""

    def __init__(self, cfg: RigConfig):
        self.cfg, self.frames = cfg, []

    def add(self, fr):
        self.frames.append({k: v for k, v in fr.items() if k not in ("vib", "cur")})

    def report(self, bad_checksums=0) -> dict:
        F = self.frames
        if len(F) < 3:
            return {"frames": len(F), "error": "too few frames"}
        out = {"frames": len(F), "bad_checksums": bad_checksums,
               "seq_gaps": int(sum(max(0, b["seq"] - a["seq"] - 1) for a, b in zip(F, F[1:])))}
        dt = np.diff(np.unwrap(np.array([f["t_us"] for f in F], float), period=2 ** 32))
        out["frame_interval_ms"] = {"mean": float(dt.mean() / 1e3), "sd": float(dt.std() / 1e3),
                                    "max": float(dt.max() / 1e3)}
        for s, nominal in (("vib", self.cfg.fs_vib), ("cur", self.cfg.fs_cur)):
            idx = np.array([f[f"{s}_ref_idx"] for f in F], float)
            us = np.unwrap(np.array([f[f"{s}_ref_us"] for f in F], float), period=2 ** 32)
            slope, icpt = np.polyfit(idx, us, 1)
            resid = us - (slope * idx + icpt)
            fs = 1e6 / slope
            first = np.array([f[f"{s}_first"] for f in F], np.int64)
            n = np.array([f[f"n_{s}"] for f in F], np.int64)
            gaps = first[1:] - (first[:-1] + n[:-1])
            out[s] = {"fs_measured": float(fs), "ppm_vs_nominal": float((fs / nominal - 1) * 1e6),
                      "ref_jitter_us_rms": float(resid.std()), "ref_jitter_us_max": float(np.abs(resid).max()),
                      "gap_events": int((gaps > 0).sum()), "gap_samples": int(gaps[gaps > 0].sum()),
                      "samples_received": int(n.sum()),
                      "duration_s": float((us[-1] - us[0]) / 1e6)}
        last = F[-1]
        out["device_counters"] = {k: int(last[k]) for k in ("vib_overruns", "adc_pool_ovf", "vib_drops",
                                                             "cur_drops", "adc_bad_ch")}
        out["adxl_ok"] = bool(last["flags"] & 1)
        out["adc_ok"] = bool(last["flags"] & 2)
        # skew between streams = difference of their clock models at a common index-free time
        out["checks"] = {
            "no_checksum_errors": bad_checksums == 0,
            "no_sample_gaps": out["vib"]["gap_samples"] == 0 and out["cur"]["gap_samples"] == 0,
            "no_device_overruns": all(v == 0 for v in out["device_counters"].values()),
            "vib_rate_within_5pct": abs(out["vib"]["ppm_vs_nominal"]) < 50000,
            "cur_rate_within_0.5pct": abs(out["cur"]["ppm_vs_nominal"]) < 5000,
            "sensors_detected": out["adxl_ok"] and out["adc_ok"],
        }
        return out


# ------------------------------------------------------------------- sources
class SimulatedRigSource:
    """SIMULATED rig (for development and a hardware-free demo). Produces real
    RIG2 binary frames so the whole parsing and timing path is exercised. Not data.

    Timing imperfections can be injected to test the host: ``vib_clock_err`` /
    ``cur_clock_err`` (fractional rate error, e.g. 0.02 = +2 %), ``ref_jitter_us``,
    ``drop_every`` (drop 100 vibration samples every N frames, as a ring overrun would)."""

    def __init__(self, cfg=None, condition="healthy", rpm=1800.0, seed=0,
                 vib_clock_err=0.0, cur_clock_err=0.0, ref_jitter_us=0.0, drop_every=0):
        self.cfg, self.condition, self.rpm = cfg or RigConfig(), condition, rpm
        self.rng = np.random.default_rng(seed)
        self.seq, self.t = 0, 0.0
        self.sensor_fault = None              # e.g. "vib_dropout", "cur_noise", "vib_clip", "frame_loss"
        self.res_f = 900.0
        self.fsv = self.cfg.fs_vib * (1 + vib_clock_err)
        self.fsc = self.cfg.fs_cur * (1 + cur_clock_err)
        self.jit, self.drop_every = ref_jitter_us, drop_every
        self.iv = self.ic = 0                 # next sample index per stream
        self.vib_drops = 0

    def _signals(self, tv, tc):
        c, rng = self.cfg, self.rng
        ff = fault_frequencies(self.rpm, c.geometry)
        unb = 0.15 if self.condition == "unbalance" else 0.05
        vib = unb * np.sin(2 * np.pi * ff["fr"] * tv) + rng.normal(0, 0.03, len(tv))
        if self.condition == "outer_race":
            ph = (tv * ff["bpfo"]) % 1.0
            vib += 0.25 * np.exp(-ph / ff["bpfo"] * 400) * np.sin(2 * np.pi * self.res_f * tv)
        amps = 1.2 + 0.08 * np.sin(2 * np.pi * 12 * ff["fr"] * tc) + self.rng.normal(0, 0.01, len(tc))
        if self.condition in ("outer_race", "unbalance"):
            amps += 0.03 * np.sin(2 * np.pi * ff["fr"] * tc)
        return vib, amps

    def read(self) -> bytes:
        c = self.cfg
        t_end = self.t + c.frame_s
        nv_end, nc_end = int(t_end * self.fsv), int(t_end * self.fsc)
        if self.drop_every and self.seq % self.drop_every == self.drop_every - 1:
            self.iv += 100; self.vib_drops += 100          # samples lost on the device
        iv = np.arange(self.iv, max(self.iv, nv_end)); ic = np.arange(self.ic, nc_end)
        vib, amps = self._signals(iv / self.fsv, ic / self.fsc)
        sf = self.sensor_fault
        if sf == "vib_dropout":
            vib = np.zeros_like(vib)
        if sf == "vib_clip":
            vib = np.clip(vib, -0.05, 0.05)
        if sf == "cur_noise":
            amps = amps + self.rng.normal(0, 0.3, len(amps))
        vib_raw = np.clip(np.round(vib / c.vib_g_per_lsb), -32768, 32767)
        adc = np.clip(np.round((amps * c.acs_v_per_a + c.cur_zero_v) / c.divider / c.adc_vref * c.adc_max), 0, c.adc_max)
        us = lambda t: int(t * 1e6 + abs(self.rng.normal(0, self.jit))) % 2 ** 32 if self.jit else int(t * 1e6) % 2 ** 32
        hdr = {"seq": self.seq, "t_us": int(t_end * 1e6) % 2 ** 32, "dt_us": int(c.frame_s * 1e6),
               "vib_first": self.iv, "vib_ref_idx": max(nv_end - 1, 0), "vib_ref_us": us((nv_end - 1) / self.fsv),
               "cur_first": self.ic, "cur_ref_idx": max(nc_end - 1, 0), "cur_ref_us": us((nc_end - 1) / self.fsc),
               "rpm": self.rpm, "temp_c": 38.0 + self.rng.normal(0, 0.1),
               "vbus_adc": 12.0 / c.vbus_scale + self.rng.normal(0, 2), "vib_drops": self.vib_drops, "flags": 3}
        frame = encode_frame(hdr, vib_raw, adc)
        self.iv, self.ic = max(self.iv, nv_end), nc_end
        self.seq += 1
        self.t = t_end
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
    """Features at the MEASURED sample rates carried by the window (nominal if absent)."""
    rpm = win["rpm"] if np.isfinite(win["rpm"]) and win["rpm"] > 60 else 1500.0
    fsv, fsc = win.get("fs_vib", cfg.fs_vib), win.get("fs_cur", cfg.fs_cur)
    return {
        "fv": vibration_features(win["vib"], fsv, rpm, band=cfg.vib_band, geom=cfg.geometry),
        "fc": generic_features(win["cur"], fsc),
        "qv": quality_indicators(win["vib"], fsv),
        "qc": quality_indicators(win["cur"], fsc),
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


def collect_windows(source, cfg: RigConfig, n_windows: int, max_reads=100000, raw_sink=None, timing=None):
    """Read from a source until n_windows are assembled. Optionally tee raw bytes
    to ``raw_sink`` (a binary file) and frame headers to a TimingAnalyzer."""
    parser, asm, wins = FrameParser(), WindowAssembler(cfg), []
    for _ in range(max_reads):
        data = source.read()
        if raw_sink is not None and data:
            raw_sink.write(data)
        for fr in parser.feed(data):
            if timing is not None:
                timing.add(fr)
            wins += asm.push(fr)
        if len(wins) >= n_windows:
            return wins[:n_windows], parser.bad
    return wins, parser.bad
