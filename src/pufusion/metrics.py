"""Evaluation metrics: classification, alarm behaviour, calibration, latency."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import balanced_accuracy_score, f1_score

from .config import HEALTHY


def classification(y, p) -> dict:
    yhat = p.argmax(1)
    fault = y != HEALTHY
    alarm = yhat != HEALTHY
    return {
        "macro_f1": float(f1_score(y, yhat, average="macro", labels=[0, 1, 2], zero_division=0)),
        "bal_acc": float(balanced_accuracy_score(y, yhat)),
        # window-level alarm behaviour (fault vs healthy, ignoring fault type)
        "false_alarm_rate": float(alarm[~fault].mean()) if (~fault).any() else float("nan"),
        "miss_rate": float((~alarm[fault]).mean()) if fault.any() else float("nan"),
        "nll": float(-np.log(p[np.arange(len(y)), y] + 1e-9).mean()),
        "brier": float(((p - np.eye(3)[y]) ** 2).sum(1).mean()),
        "ece": ece(y, p),
    }


def ece(y, p, n_bins=15) -> float:
    conf, pred = p.max(1), p.argmax(1)
    bins = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(e)


def alarm_stream(p_fault, k=2, n=3, thr=0.5):
    """k-of-n rule on per-window fault probability; returns boolean alarm per window."""
    hits = (np.asarray(p_fault) > thr).astype(int)
    out = np.zeros(len(hits), bool)
    for i in range(len(hits)):
        out[i] = hits[max(0, i - n + 1): i + 1].sum() >= k
    return out


def replay_latency(p_healthy_stream, p_fault_stream, win_s=0.5, **rule) -> dict:
    """Simulated healthy->fault switch on concatenated test windows.

    This is a *replay* of recorded windows, not an online run-to-failure
    experiment: it measures how fast the alarm logic reacts to a step change in
    bearing condition, and how often it fires on healthy data.
    """
    pf = np.concatenate([p_healthy_stream, p_fault_stream])
    alarms = alarm_stream(pf, **rule)
    onset = len(p_healthy_stream)
    after = np.where(alarms[onset:])[0]
    return {
        "latency_s": float((after[0] + 1) * win_s) if len(after) else float("nan"),
        # count alarm *events* (rising edges) during the healthy part
        "false_alarms_per_hour": float(
            (alarms[0] + np.sum(alarms[1:onset] & ~alarms[:onset - 1])) / (onset * win_s) * 3600),
    }
