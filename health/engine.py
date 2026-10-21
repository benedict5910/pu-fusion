"""OB3 shared health decision layer.

* Portable inference: exported logistic models (JSON) evaluated with numpy only.
* Health policy (fixed, transparent rules from the approved methodology):
    - evidence e = 1 - P(healthy) from the gated fusion model
    - WARNING  : e > 0.5 in >= 2 of the last 6 windows
    - INSPECT  : e > 0.8 in >= 4 of the last 6 windows; latched until acknowledged
    - 6 consecutive quiet windows (e <= 0.5) clear a WARNING
    - SENSOR_FAULT: no reliable sensor in the window -> diagnosis suspended
      (one unreliable sensor -> diagnosis continues on the other, marked "degraded")
* Explanations: exact linear feature contributions (class logit minus healthy logit).
"""
from __future__ import annotations
import json
from collections import deque
from dataclasses import dataclass, field
import numpy as np

CLASSES = ["healthy", "outer race fault", "inner race fault"]

PLAIN = {
    "v_rms": "vibration RMS level", "v_std": "vibration spread", "v_kurt": "vibration impulsiveness (kurtosis)",
    "v_skew": "vibration asymmetry", "v_crest": "vibration crest factor", "v_p2p": "vibration peak-to-peak",
    "v_shape": "vibration shape factor", "v_impulse": "vibration impulse factor",
    "v_env_bpfo1": "envelope peak at outer-race frequency (BPFO)", "v_env_bpfo2": "envelope peak at 2x BPFO",
    "v_env_bpfo3": "envelope peak at 3x BPFO", "v_env_bpfi1": "envelope peak at inner-race frequency (BPFI)",
    "v_env_bpfi2": "envelope peak at 2x BPFI", "v_env_bpfi3": "envelope peak at 3x BPFI",
    "v_env_fr": "envelope peak at shaft speed",
    "c_rms": "current RMS level", "c_res_ratio": "current residual energy (after removing supply harmonics)",
    "c_h3": "current 3rd harmonic", "c_h5": "current 5th harmonic", "c_h7": "current 7th harmonic",
    "c_sb_bpfo1": "current sidebands at supply +/- BPFO", "c_sb_bpfo2": "current sidebands at supply +/- 2xBPFO",
    "c_sb_bpfi1": "current sidebands at supply +/- BPFI", "c_sb_bpfi2": "current sidebands at supply +/- 2xBPFI",
    "c_res_kurt": "current residual impulsiveness", "c_res_crest": "current residual crest factor",
}
for i in range(8):
    PLAIN[f"v_band{i}"] = f"vibration energy share, band {i * 4}-{(i + 1) * 4} kHz"
for i, (a, b) in enumerate([(0, 100), (100, 300), (300, 600), (600, 1000), (1000, 2000),
                            (2000, 5000), (5000, 10000), (10000, 32000)]):
    PLAIN[f"c_band{i}"] = f"current energy share, {a}-{b} Hz"

ADVICE = {
    1: "Schedule inspection of the outer race / housing seat; check lubrication and mounting.",
    2: "Schedule inspection of the inner race / shaft fit; check lubrication and load.",
    "vib": "Check accelerometer mounting, cable and connector before trusting vibration.",
    "cur": "Check current-sensor wiring, clamp position and ADC range.",
}


# ----------------------------------------------------------------------------- portable model
def _softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class Linear:
    def __init__(self, d):
        self.mean, self.scale = np.array(d["mean"]), np.array(d["scale"])
        self.coef, self.intercept = np.array(d["coef"]), np.array(d["intercept"])
        self.names = d.get("names")

    def z(self, X):
        return (np.asarray(X, float) - self.mean) / self.scale

    def proba(self, X):
        s = self.z(X) @ self.coef.T + self.intercept
        if self.coef.shape[0] == 1:
            p = 1 / (1 + np.exp(-s[:, 0]))
            return np.column_stack([1 - p, p])
        return _softmax(s)


class PortableModel:
    """Gated fusion (vibration expert, current expert, quality assessors, gate)."""

    def __init__(self, path_or_dict):
        d = json.load(open(path_or_dict)) if isinstance(path_or_dict, str) else path_or_dict
        self.meta = d["meta"]
        self.vib, self.cur = Linear(d["vib"]), Linear(d["cur"])
        self.gate_v, self.gate_c = d["gate_v"], d["gate_c"]
        self.gv = Linear(self.gate_v) if isinstance(self.gate_v, dict) else None
        self.gc = Linear(self.gate_c) if isinstance(self.gate_c, dict) else None
        self.qa = {s: {k: np.array(v) if k != "names" else v for k, v in d[f"qa_{s}"].items()}
                   for s in ("vib", "cur")}
        self.vib_names, self.cur_names = d["vib"]["names"], d["cur"]["names"]

    def qscores(self, s, Q):
        qa = self.qa[s]
        Q = np.asarray(Q, float)
        z = np.maximum(Q - qa["hi"], 0) + np.maximum(qa["lo"] - Q, 0)
        return np.where(np.isfinite(z), z / qa["scale"], 0.0)

    def dead(self, s, Q):
        n = self.qa[s]["names"]
        Q = np.asarray(Q, float)
        return (Q[:, n.index("nan_frac")] > 0.5) | (Q[:, n.index("flat_frac")] > 0.5)

    @staticmethod
    def _conf(P):
        P = np.clip(P, 1e-9, 1)
        s = np.sort(P, axis=1)
        ent = -(P * np.log(P)).sum(1) / np.log(P.shape[1])
        return np.column_stack([s[:, -1], s[:, -1] - s[:, -2], ent])

    def predict(self, Xv, Xc, Qv, Qc):
        Pv, Pc = self.vib.proba(Xv), self.cur.proba(Xc)
        Sv, Sc = self.qscores("vib", Qv), self.qscores("cur", Qc)
        fv = np.hstack([np.log1p(np.minimum(Sv, 100)), self._conf(Pv)])
        fc = np.hstack([np.log1p(np.minimum(Sc, 100)), self._conf(Pc)])
        wv = self.gv.proba(fv)[:, 1] if self.gv else np.full(len(fv), self.gate_v)
        wc = self.gc.proba(fc)[:, 1] if self.gc else np.full(len(fc), self.gate_c)
        dv, dc = self.dead("vib", Qv), self.dead("cur", Qc)
        wv, wc = np.where(dv, 0, wv), np.where(dc, 0, wc)
        both = (wv + wc) < 1e-9
        wv, wc = np.where(both, 0.5, wv), np.where(both, 0.5, wc)
        P = (wv[:, None] * Pv + wc[:, None] * Pc) / (wv + wc)[:, None]
        return {"P": P, "Pv": Pv, "Pc": Pc, "w_v": wv / (wv + wc), "w_c": wc / (wv + wc),
                "flag_v": (Sv > 0).any(1), "flag_c": (Sc > 0).any(1), "dead_v": dv, "dead_c": dc,
                "both_dead": both, "Sv": Sv, "Sc": Sc}

    def explain(self, xv, xc, k_cls, w_v, w_c, top=5):
        """Exact linear contributions to (logit_k - logit_healthy) for each expert, weighted by
        the gate weight of that expert. Returns list of (feature, plain text, contribution)."""
        out = []
        for lin, x, w, names in ((self.vib, xv, w_v, self.vib_names), (self.cur, xc, w_c, self.cur_names)):
            if w <= 0:
                continue
            z = lin.z(np.asarray(x, float)[None, :])[0]
            c = (lin.coef[k_cls] - lin.coef[0]) * z * w
            for j in np.argsort(-np.abs(c))[:top]:
                out.append((names[j], PLAIN.get(names[j], names[j]), float(c[j])))
        out.sort(key=lambda t: -abs(t[2]))
        return out[:top]


# ----------------------------------------------------------------------------- policy
@dataclass
class HealthPolicy:
    warn_thr: float = 0.5
    warn_k: int = 2
    insp_thr: float = 0.8
    insp_k: int = 4
    n: int = 6
    clear_quiet: int = 6
    hist: deque = field(default_factory=lambda: deque(maxlen=6))
    state: str = "NORMAL"
    latched: bool = False
    quiet: int = 0

    def step(self, evidence: float, reliable_v: bool, reliable_c: bool) -> dict:
        if not (reliable_v or reliable_c):
            self.state_out = "SENSOR_FAULT"
            return {"state": "SENSOR_FAULT", "latched_inspect": self.latched,
                    "mode": "diagnosis suspended: no reliable sensor"}
        mode = "normal" if (reliable_v and reliable_c) else \
            f"degraded: diagnosing on {'vibration' if reliable_v else 'current'} only"
        self.hist.append(evidence)
        h = list(self.hist)
        n_warn = sum(e > self.warn_thr for e in h)
        n_insp = sum(e > self.insp_thr for e in h)
        self.quiet = self.quiet + 1 if evidence <= self.warn_thr else 0
        if n_insp >= self.insp_k:
            self.latched = True
        if self.latched:
            self.state = "INSPECT"
        elif n_warn >= self.warn_k:
            self.state = "WARNING"
        elif self.state == "WARNING" and self.quiet < self.clear_quiet:
            self.state = "WARNING"
        else:
            self.state = "NORMAL"
        return {"state": self.state, "latched_inspect": self.latched, "mode": mode}

    def acknowledge(self):
        self.latched = False
        self.hist.clear()
        self.quiet = 0
        self.state = "NORMAL"
