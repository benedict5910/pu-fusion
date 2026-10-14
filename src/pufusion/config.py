"""Dataset metadata for the Paderborn (KAt) bearing dataset.

Sources (verified 2026-10-15):
- https://mb.uni-paderborn.de/en/kat/research/bearing-datacenter/data-sets-and-download
- https://mb.uni-paderborn.de/en/kat/research/bearing-datacenter/operating-conditions
- https://groups.uni-paderborn.de/kat/BearingDataCenter/  (32 .rar archives, 152-178 MB each)
- Lessmeier et al., PHME 2016 (Tables 4-6) for damage location.

Licence: CC BY-NC 4.0, non-commercial academic use, citation required.

IMPORTANT: the damage-location labels below follow Lessmeier et al. (2016).
Before reporting results, cross-check every code against the fact sheets that
ship inside each archive (scripts/verify_labels.py prints them for review).
"""
from __future__ import annotations

FS_HIGH = 64_000          # vibration and phase currents, Hz
FILE_SECONDS = 4.0
N_REPETITIONS = 20        # measurements per bearing per operating condition

OPERATING_CONDITIONS = {
    # name: (rpm, load torque Nm, radial force N)
    "N15_M07_F10": (1500, 0.7, 1000),
    "N09_M07_F10": (900, 0.7, 1000),
    "N15_M01_F10": (1500, 0.1, 1000),
    "N15_M07_F04": (1500, 0.7, 400),
}

# Class indices
HEALTHY, OUTER, INNER = 0, 1, 2
CLASS_NAMES = ["healthy", "outer_race", "inner_race"]

# code -> (class, origin) ; origin in {"healthy", "artificial", "real"}
BEARINGS: dict[str, tuple[int, str]] = {
    **{f"K00{i}": (HEALTHY, "healthy") for i in range(1, 7)},
    # artificial damage (EDM, drilling, electric engraving)
    "KA01": (OUTER, "artificial"), "KA03": (OUTER, "artificial"),
    "KA05": (OUTER, "artificial"), "KA06": (OUTER, "artificial"),
    "KA07": (OUTER, "artificial"), "KA08": (OUTER, "artificial"),
    "KA09": (OUTER, "artificial"),
    "KI01": (INNER, "artificial"), "KI03": (INNER, "artificial"),
    "KI05": (INNER, "artificial"), "KI07": (INNER, "artificial"),
    "KI08": (INNER, "artificial"),
    # real damage from accelerated lifetime tests
    "KA04": (OUTER, "real"), "KA15": (OUTER, "real"), "KA16": (OUTER, "real"),
    "KA22": (OUTER, "real"), "KA30": (OUTER, "real"),
    "KI04": (INNER, "real"), "KI14": (INNER, "real"), "KI16": (INNER, "real"),
    "KI17": (INNER, "real"), "KI18": (INNER, "real"), "KI21": (INNER, "real"),
}
# Combined inner+outer damage: excluded from the 3-class task (kept for an
# optional open-set / "unknown fault" check, never silently relabelled).
EXCLUDED_COMBINED = ["KB23", "KB24", "KB27"]

# Ball bearing 6203 geometry (Lessmeier et al. 2016). Verify vs fact sheet.
N_BALLS = 8
BALL_DIAMETER_MM = 6.75
PITCH_DIAMETER_MM = 28.55


def fault_frequencies(rpm: float) -> dict[str, float]:
    """Kinematic bearing frequencies (Hz), zero contact angle."""
    fr = rpm / 60.0
    r = BALL_DIAMETER_MM / PITCH_DIAMETER_MM
    return {
        "fr": fr,
        "bpfo": N_BALLS / 2 * fr * (1 - r),
        "bpfi": N_BALLS / 2 * fr * (1 + r),
        "bsf": PITCH_DIAMETER_MM / (2 * BALL_DIAMETER_MM) * fr * (1 - r * r),
        "ftf": fr / 2 * (1 - r),
    }


def parse_filename(stem: str) -> dict:
    """'N15_M07_F10_KA01_1' -> condition, bearing, repetition."""
    parts = stem.split("_")
    if len(parts) != 5:
        raise ValueError(f"unexpected Paderborn file name: {stem}")
    cond = "_".join(parts[:3])
    if cond not in OPERATING_CONDITIONS:
        raise ValueError(f"unknown operating condition in {stem}")
    return {"condition": cond, "bearing": parts[3], "repetition": int(parts[4])}
