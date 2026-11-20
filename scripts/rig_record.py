"""Record a labelled rig session (or a SIMULATED one) to data/rig/<session>.npz.

  python scripts/rig_record.py --calibrate-zero --port COM5         # motor OFF: measures current-sensor offset
  python scripts/rig_record.py --port COM5 --session H1 --label healthy --minutes 5
  python scripts/rig_record.py --simulate --session SIM_H1 --label healthy --minutes 2

Record healthy and seeded-fault sessions on DIFFERENT days / remounts; the
evaluation in rig_train.py is split by session, never by window.
"""
import argparse
import json
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.rig import (SerialRigSource, SimulatedRigSource, TimingAnalyzer, collect_windows,  # noqa: E402
                          load_rig_config, save_rig_config)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--sim-condition", default=None, help="healthy | outer_race | unbalance (default: --label)")
    ap.add_argument("--session")
    ap.add_argument("--label", choices=["healthy", "outer_race", "unbalance", "contaminated"])
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--notes", default="")
    ap.add_argument("--calibrate-zero", action="store_true")
    ap.add_argument("--config", default="configs/rig.json")
    a = ap.parse_args()
    cfg = load_rig_config(a.config)
    if a.simulate:
        cond = a.sim_condition or a.label or "healthy"
        src, kind = SimulatedRigSource(cfg, cond, seed=zlib.crc32(a.session.encode())), "SIMULATED"
    else:
        if not a.port:
            raise SystemExit("--port is required (or use --simulate)")
        src, kind = SerialRigSource(a.port), "rig"

    if a.calibrate_zero:
        wins, _ = collect_windows(src, cfg, 20)
        adc_v = np.nanmean([np.nanmean(w["cur"]) * cfg.acs_v_per_a + cfg.cur_zero_v for w in wins])
        cfg.cur_zero_v = float(adc_v)
        save_rig_config(cfg, a.config)
        print(f"current-sensor zero = {adc_v:.4f} V saved to {a.config}")
        return

    n = int(a.minutes * 60 / cfg.window_s)
    t0 = time.time()
    out = Path("data/rig") / f"{a.session}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    ta = TimingAnalyzer(cfg)
    with open(out.with_suffix(".bin"), "wb") as raw:          # raw frames, for re-analysis
        wins, bad = collect_windows(src, cfg, n, raw_sink=raw, timing=ta)
    # windows can differ by a sample or two (measured rates); store as object arrays
    obj = lambda k: np.array([w[k] for w in wins], dtype=object)
    np.savez_compressed(out, vib=obj("vib"), cur=obj("cur"), fs_vib=np.array([w["fs_vib"] for w in wins]),
                        fs_cur=np.array([w["fs_cur"] for w in wins]),
                        rpm=np.array([w["rpm"] for w in wins]), temp_c=np.array([w["temp_c"] for w in wins]),
                        vbus=np.array([w["vbus"] for w in wins]))
    timing = ta.report(bad)
    meta = {"session": a.session, "label": a.label, "source": kind, "windows": len(wins),
            "corrupt_frames": bad, "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": round(time.time() - t0, 1), "notes": a.notes,
            "acquisition_checks": timing.get("checks"), "timing": timing}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != 'timing'}))
    if meta['acquisition_checks'] and not all(meta['acquisition_checks'].values()):
        print('WARNING: acquisition checks failed - see', out.with_suffix('.json'))


if __name__ == "__main__":
    main()
