"""Rig-only healthy-baseline anomaly detector (OB4). Paderborn models are never used here.

Protocol: fit on healthy session H1, threshold = 99th percentile of scores on independent
healthy session H2, test on healthy H3/H4 (false alarms) and separate fault sessions
(detection, time to alert). Alert rule: score > threshold in 2 of the last 3 windows.
The detector says "different from healthy"; it does not name a fault type.

Usage: python rig/detector.py --sessions rig/sessions --fit H1 --thr H2 --test H3 H4 F1 F2
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from scipy.stats import kurtosis
from sklearn.covariance import LedoitWolf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigio import load_session  # noqa: E402
from pu.features import quality, Q_NAMES  # noqa: E402
from pu.models import QualityAssessor  # noqa: E402

WIN_S = 0.5
FS_A, FS_C = 3200.0, 5000.0


def _bands(x, fs, edges):
    p = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / fs)
    t = p.sum() + 1e-12
    return [np.log10(p[(f >= a) & (f < b)].sum() / t + 1e-12) for a, b in zip(edges[:-1], edges[1:])]


def window_features(sess):
    ta, A = sess["accel_t_us"] / 1e6, sess["accel"].astype(float) * 0.0039   # g
    tc, C = sess["current_t_us"] / 1e6, sess["current"].astype(float)
    t0, t1 = max(ta[0], tc[0]), min(ta[-1], tc[-1])
    feats, quals, starts = [], [], []
    for s in np.arange(t0, t1 - WIN_S, WIN_S):
        ma, mc = (ta >= s) & (ta < s + WIN_S), (tc >= s) & (tc < s + WIN_S)
        if ma.sum() < 0.9 * FS_A * WIN_S or mc.sum() < 0.9 * FS_C * WIN_S:
            continue                                   # incomplete window: logged by count only
        a = A[ma] - A[ma].mean(0)
        mag = np.linalg.norm(a, axis=1)
        c = C[mc] - C[mc].mean()
        f = [np.log10(np.sqrt((a ** 2).mean(0)) + 1e-9)[i] for i in range(3)]
        f += [np.log10(kurtosis(mag, fisher=False) + 1e-9), mag.max() / (np.sqrt((mag ** 2).mean()) + 1e-9)]
        f += _bands(mag, FS_A, np.linspace(0, 1600, 9))
        f += [np.log10(np.sqrt((c ** 2).mean()) + 1e-9)]
        f += _bands(c, FS_C, [0, 50, 150, 300, 600, 1200, 2500])
        if "rpm" in sess:
            mr = (sess["rpm_t_us"] / 1e6 >= s) & (sess["rpm_t_us"] / 1e6 < s + WIN_S)
            f.append(float(np.mean(sess["rpm"][mr])) if mr.any() else np.nan)
        feats.append(f)
        quals.append(np.concatenate([quality(mag), quality(c)]))
        starts.append(s - t0)
    F = np.array(feats)
    if F.shape[1] and np.isnan(F[:, -1]).all():
        F = F[:, :-1]
    return np.nan_to_num(F), np.array(quals), np.array(starts)


class Detector:
    def fit(self, F):
        self.mu, self.sd = F.mean(0), F.std(0) + 1e-9
        self.cov = LedoitWolf().fit((F - self.mu) / self.sd)
        return self

    def score(self, F):
        return np.sqrt(self.cov.mahalanobis((F - self.mu) / self.sd))


def alerts(scores, thr):
    above = (scores > thr).astype(int)
    al = np.zeros_like(above)
    for i in range(2, len(above)):
        al[i] = above[i - 2:i + 1].sum() >= 2
    return al


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=str(Path(__file__).resolve().parent / "sessions"))
    ap.add_argument("--fit", default="H1")
    ap.add_argument("--thr", default="H2")
    ap.add_argument("--test", nargs="+", default=["H3", "H4"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    root = Path(a.sessions)
    S = {k: load_session(root / k) for k in [a.fit, a.thr] + a.test}
    W = {k: window_features(v) for k, v in S.items()}
    det = Detector().fit(W[a.fit][0])
    qa = QualityAssessor().fit(W[a.fit][1][:, :7]), QualityAssessor().fit(W[a.fit][1][:, 7:])
    thr = float(np.quantile(det.score(W[a.thr][0]), 0.99))
    rep = {"fit": a.fit, "threshold_session": a.thr, "threshold": thr,
           "n_windows": {k: int(len(v[0])) for k, v in W.items()}, "sessions": {}}
    for k in a.test:
        F, Q, st = W[k]
        sc = det.score(F)
        al = alerts(sc, thr)
        lab = S[k]["meta"]["label"]
        r = {"label": lab, "window_exceed_rate": float((sc > thr).mean()),
             "alert_rate": float(al.mean()),
             "first_alert_s": float(st[np.argmax(al)]) if al.any() else None,
             "flag_rate_accel": float(qa[0].flag(Q[:, :7]).mean()),
             "flag_rate_current": float(qa[1].flag(Q[:, 7:]).mean())}
        r["interpretation"] = ("false-alarm rate" if lab == "healthy" else "detection rate") + \
            f" (2-of-3 rule) = {r['alert_rate']:.3f}"
        rep["sessions"][k] = r
    out = Path(a.out) if a.out else root / "detector_report.json"
    out.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
