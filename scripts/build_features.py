"""Extract features from raw .mat files (or from SYNTHETIC signals for smoke tests).

  python scripts/build_features.py --raw data/raw --out data/features.npz --jobs 4
  python scripts/build_features.py --synthetic --out data/synthetic_features.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS, OPERATING_CONDITIONS, parse_filename  # noqa: E402
from pufusion.data import find_mat_files, load_mat  # noqa: E402
from pufusion.dataset import TableBuilder, process_recording, save_tables  # noqa: E402


def _work(job):
    kind, arg, opts = job
    if kind == "mat":
        try:
            rec = load_mat(arg)
        except Exception as e:  # unreadable files are logged and skipped, never guessed
            return None, f"{Path(arg).name}: {e}"
    else:
        from pufusion.synthetic import synth_recording
        rec = synth_recording(*arg, seconds=opts["synthetic_seconds"])
    b = {k: TableBuilder() for k in ("clean", "aug", "corr")}
    process_recording(rec, b, win_s=opts["win"], n_aug=opts["n_aug"], eval_windows=opts["eval_windows"])
    return {k: v.rows for k, v in b.items()}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/features.npz")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--synthetic-reps", type=int, default=2)
    ap.add_argument("--synthetic-seconds", type=float, default=1.0)
    ap.add_argument("--win", type=float, default=0.5)
    ap.add_argument("--n-aug", type=int, default=1)
    ap.add_argument("--eval-windows", type=int, default=1)
    ap.add_argument("--max-reps", type=int, default=20, help="repetitions per bearing/condition")
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    opts = vars(a)

    if a.synthetic:
        jobs = [("syn", (b, c, r), opts) for b in BEARINGS for c in OPERATING_CONDITIONS
                for r in range(1, a.synthetic_reps + 1)]
    else:
        files = [f for f in find_mat_files(a.raw) if parse_filename(f.stem)["repetition"] <= a.max_reps]
        if not files:
            raise SystemExit(f"no Paderborn .mat files under {a.raw}; run scripts/download_pu.py first")
        jobs = [("mat", str(f), opts) for f in files]
    print(f"{len(jobs)} recordings, win={a.win}s, n_aug={a.n_aug}, eval_windows={a.eval_windows}")

    merged = {k: TableBuilder() for k in ("clean", "aug", "corr")}
    errors, t0 = [], time.time()
    with ProcessPoolExecutor(a.jobs) if a.jobs > 1 else _Serial() as ex:
        for i, (rows, err) in enumerate(ex.map(_work, jobs, chunksize=4)):
            if err:
                errors.append(err); continue
            for k in merged:
                for col, vals in rows[k].items():
                    merged[k].rows[col].extend(vals)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(jobs)}  {time.time() - t0:.0f}s")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    save_tables(a.out, merged)
    meta = {"source": "SYNTHETIC" if a.synthetic else str(a.raw), "options": opts,
            "n_rows": {k: len(v.rows["y"]) for k, v in merged.items()}, "errors": errors}
    Path(a.out).with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta["n_rows"]), f"errors={len(errors)}", f"{time.time() - t0:.0f}s")


class _Serial:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def map(self, fn, it, chunksize=1): return map(fn, it)


if __name__ == "__main__":
    main()
