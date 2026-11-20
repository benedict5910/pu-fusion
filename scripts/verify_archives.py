"""Verify downloaded Paderborn archives before use.

For each <code>.rar: size + MD5 against the Zenodo record, extraction (libarchive), file-name
pattern, 80 .mat files = 4 operating conditions x 20 repetitions, required channels at 64 kHz,
and the fact-sheet damage component against the label in config.py.

  python -I scripts/verify_archives.py ARCHIVE.rar [...] --dest data/raw --report data/verify.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from pufusion.config import BEARINGS, CLASS_NAMES, OPERATING_CONDITIONS, parse_filename  # noqa: E402
from pufusion.data import load_mat  # noqa: E402
from extract_rar import extract  # noqa: E402

REF = {l.split()[0]: (int(l.split()[1]), l.split()[2]) for l in
       (ROOT / "scripts/windows/zenodo_15845309_md5.txt").read_text().splitlines() if l.strip()}


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fact_sheet(pdf: Path) -> dict:
    try:
        txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return {}
    out = {}
    for line in txt.splitlines():
        s = line.split()
        if "Component" in s:            # one column per damage; damage 1 = primary
            comps = s[s.index("Component") + 1:]
            out["component"] = comps[0] if comps else None
            out["all_components"] = comps
        if s[:1] == ["Mode"]:
            out["modes"] = line.split("Mode", 1)[1].split("  ")
            out["modes"] = [m.strip() for m in out["modes"] if m.strip()]
        if "Pitch" in line and "diameter" in line:
            out["pitch_diameter_mm"] = s[-1]
        if line.strip().startswith("Damage method"):
            out["damage_method"] = " ".join(s[2:])
        if "Symptom" in s:
            out["symptom"] = s[-1]
    return out


def verify(arc: Path, dest: Path) -> dict:
    code = arc.stem
    r = {"code": code, "bytes": arc.stat().st_size}
    size, ref = REF.get(code, (None, None))
    r["md5"] = md5(arc)
    r["md5_ok"] = r["md5"] == ref and r["bytes"] == size
    files = extract(str(arc), str(dest))
    mats = sorted(Path(f) for f in files if f.endswith(".mat"))
    r["n_mat"] = len(mats)
    r["other_files"] = sorted(Path(f).name for f in files if not f.endswith(".mat"))
    meta = [parse_filename(m.stem) for m in mats]
    r["names_ok"] = all(m["bearing"] == code for m in meta)
    per = collections.Counter(m["condition"] for m in meta)
    r["per_condition"] = dict(per)
    r["layout_ok"] = set(per) == set(OPERATING_CONDITIONS) and all(v == 20 for v in per.values())
    bad, lens = [], []
    for m in mats:
        try:
            rec = load_mat(m)
            lens.append(len(rec.vib))
        except Exception as e:  # recorded, never guessed
            bad.append(f"{m.name}: {e}")
    r["unreadable"] = bad
    r["samples_min_max"] = [min(lens), max(lens)] if lens else None
    r["fs_ok"] = bool(lens) and abs(min(lens) / 4.0 - 64000) / 64000 < 0.02
    pdf = next((Path(f) for f in files if Path(f).name == f"{code}.pdf"), None)
    fs = fact_sheet(pdf) if pdf else {}
    r["fact_sheet"] = fs
    cls = BEARINGS[code][0] if code in BEARINGS else None
    expect = {0: None, 1: "OR", 2: "IR"}.get(cls)
    r["label"] = CLASS_NAMES[cls] if cls is not None else "excluded"
    r["label_ok"] = (cls == 0 and fs.get("component") in (None, "n/a", "-")) or fs.get("component") == expect
    r["ALL_OK"] = all(r[k] for k in ("md5_ok", "names_ok", "layout_ok", "fs_ok", "label_ok")) and not bad
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    rep = Path(a.report)
    old = json.loads(rep.read_text()) if rep.exists() else {}
    for arc in map(Path, a.archives):
        r = verify(arc, Path(a.dest))
        old[r["code"]] = r
        print(f"{r['code']}: ALL_OK={r['ALL_OK']} md5={r['md5_ok']} mat={r['n_mat']} layout={r['layout_ok']} "
              f"fs={r['fs_ok']} label={r['label']}/{r['fact_sheet'].get('component')} "
              f"pitch={r['fact_sheet'].get('pitch_diameter_mm')} unreadable={len(r['unreadable'])}")
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main()
