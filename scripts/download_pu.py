"""Download and extract Paderborn bearing archives (run on your own machine).

Data licence: CC BY-NC 4.0 (non-commercial academic use, citation required).
Cite: Lessmeier et al., PHME 2016, and KAt-DataCenter, Paderborn University.

Usage
  python scripts/download_pu.py --subset starter      # 12 bearings, ~1.9 GB
  python scripts/download_pu.py --subset all          # 32 archives, ~5.1 GB
  python scripts/download_pu.py --bearings K001 KA04  # explicit list

Extraction needs one of: `unrar`, `7z`, `bsdtar`, or the `rarfile` package with
an unrar backend. On Windows, 7-Zip works.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pufusion.config import BEARINGS, EXCLUDED_COMBINED  # noqa: E402

BASE = "https://groups.uni-paderborn.de/kat/BearingDataCenter/"
# Zenodo mirror (record 15845309): sizes match the official listing; MD5s from Zenodo.
ZENODO = "https://zenodo.org/records/15845309/files/{code}.rar?download=1"
_MD5_FILE = Path(__file__).resolve().parent / "windows" / "zenodo_15845309_md5.txt"
ZENODO_MD5 = {l.split()[0]: (int(l.split()[1]), l.split()[2])
              for l in _MD5_FILE.read_text().splitlines() if l.strip()} if _MD5_FILE.exists() else {}


def md5_ok(path: Path, code: str) -> bool:
    if code not in ZENODO_MD5:
        return True                     # no reference checksum (official source)
    size, ref = ZENODO_MD5[code]
    if path.stat().st_size != size:
        return False
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == ref
# Starter subset: enough for a first bearing-disjoint split (4 healthy,
# 4 real OR, 4 real IR) - every class has unseen bearings at test time.
STARTER = ["K001", "K002", "K003", "K004",
           "KA04", "KA15", "KA16", "KA22",
           "KI04", "KI14", "KI16", "KI18"]


def download(code: str, out: Path, source: str = "zenodo") -> Path:
    dst = out / f"{code}.rar"
    if dst.exists() and dst.stat().st_size > 1_000_000 and md5_ok(dst, code):
        print(f"[skip] {dst.name} already present (verified)")
        return dst
    url = ZENODO.format(code=code) if source == "zenodo" else BASE + f"{code}.rar"
    tmp = dst.with_suffix(".part")
    print(f"[get ] {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    tmp.replace(dst)
    if source == "zenodo" and not md5_ok(dst, code):
        raise SystemExit(f"{dst.name}: MD5/size mismatch against Zenodo record - not used")
    return dst


def extract(archive: Path, out: Path) -> None:
    target = out / archive.stem
    if target.exists() and any(target.rglob("*.mat")):
        print(f"[skip] {archive.stem} already extracted")
        return
    target.mkdir(parents=True, exist_ok=True)
    for cmd in (["unrar", "x", "-o+", str(archive), str(out) + "/"],
                ["7z", "x", "-y", f"-o{out}", str(archive)],
                ["bsdtar", "-xf", str(archive), "-C", str(out)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            return
    try:
        import rarfile
        rarfile.RarFile(archive).extractall(out)
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"No RAR extractor available ({e}). Install 7-Zip or unrar.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", choices=["starter", "all"], default="starter")
    ap.add_argument("--bearings", nargs="*")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--no-extract", action="store_true")
    ap.add_argument("--source", choices=["zenodo", "official"], default="zenodo")
    a = ap.parse_args()
    codes = a.bearings or (STARTER if a.subset == "starter" else sorted(BEARINGS) + EXCLUDED_COMBINED)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for c in codes:
        arc = download(c, out, a.source)
        if not a.no_extract:
            extract(arc, out)
    print("done:", len(codes), "archives in", out)


if __name__ == "__main__":
    main()
