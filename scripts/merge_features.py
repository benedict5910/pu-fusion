"""Merge feature files built separately (e.g. an archive that arrived later) into one file.

  python scripts/merge_features.py OUT.npz IN1.npz IN2.npz [...]
Refuses to merge if any bearing appears in more than one input (no duplicated recordings).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.dataset import concat, load_tables  # noqa: E402


def main(out, *ins):
    tabs = [load_tables(p) for p in ins]
    seen = {}
    for p, t in zip(ins, tabs):
        for b in np.unique(t["clean"]["bearing"]):
            if b in seen:
                raise SystemExit(f"bearing {b} in both {seen[b]} and {p}")
            seen[b] = p
    flat = {}
    for name in tabs[0]:
        merged = concat(*(t[name] for t in tabs if name in t))
        for k, v in merged.items():
            flat[f"{name}__{k}"] = v
    np.savez_compressed(out, **flat)
    metas = [json.loads(Path(p).with_suffix(".json").read_text()) for p in ins]
    meta = {"source": " + ".join(sorted({m["source"] for m in metas})), "merged_from": list(ins),
            "options": metas[0]["options"], "errors": sum((m["errors"] for m in metas), []),
            "n_rows": {k: int(len(flat[f"{k}__y"])) for k in tabs[0]}}
    Path(out).with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta["n_rows"]), "bearings:", sorted(seen))


if __name__ == "__main__":
    main(*sys.argv[1:])
