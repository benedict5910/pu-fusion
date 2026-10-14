"""Extract .rar archives with the system libarchive (no unrar/7z needed).

  python -I scripts/extract_rar.py ARCHIVE.rar [...] --dest data/raw

Only regular files are written; absolute paths and '..' components are rejected.
"""
import argparse
import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

_lib = ctypes.CDLL(ctypes.util.find_library("archive") or "libarchive.so.13")
_lib.archive_read_new.restype = ctypes.c_void_p
_lib.archive_read_support_format_all.argtypes = [ctypes.c_void_p]
_lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
_lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
_lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
_lib.archive_entry_pathname.restype = ctypes.c_char_p
_lib.archive_entry_filetype.argtypes = [ctypes.c_void_p]
_lib.archive_entry_filetype.restype = ctypes.c_uint
_lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
_lib.archive_read_data.restype = ctypes.c_ssize_t
_lib.archive_read_data_skip.argtypes = [ctypes.c_void_p]
_lib.archive_error_string.argtypes = [ctypes.c_void_p]
_lib.archive_error_string.restype = ctypes.c_char_p
_lib.archive_read_free.argtypes = [ctypes.c_void_p]
AE_IFREG = 0o100000


def extract(archive: str, dest: str) -> list[str]:
    a = _lib.archive_read_new()
    _lib.archive_read_support_format_all(a)
    _lib.archive_read_support_filter_all(a)
    if _lib.archive_read_open_filename(a, archive.encode(), 1 << 20) != 0:
        raise RuntimeError(f"{archive}: {_lib.archive_error_string(a)}")
    entry, written, buf = ctypes.c_void_p(), [], ctypes.create_string_buffer(1 << 20)
    dest_p = Path(dest).resolve()
    try:
        while True:
            r = _lib.archive_read_next_header(a, ctypes.byref(entry))
            if r == 1:            # ARCHIVE_EOF
                break
            if r < -20:           # ARCHIVE_FATAL / FAILED
                raise RuntimeError(f"{archive}: {_lib.archive_error_string(a)}")
            name = _lib.archive_entry_pathname(entry).decode("utf-8", "replace").replace("\\", "/")
            parts = Path(name).parts
            if (_lib.archive_entry_filetype(entry) & 0o170000) != AE_IFREG or Path(name).is_absolute() or ".." in parts:
                _lib.archive_read_data_skip(a)
                continue
            out = (dest_p / name).resolve()
            if dest_p not in out.parents:
                _lib.archive_read_data_skip(a)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                while True:
                    n = _lib.archive_read_data(a, buf, len(buf))
                    if n < 0:
                        raise RuntimeError(f"{archive}:{name}: {_lib.archive_error_string(a)}")
                    if n == 0:
                        break
                    f.write(buf.raw[:n])
            written.append(str(out))
    finally:
        _lib.archive_read_free(a)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+")
    ap.add_argument("--dest", required=True)
    a = ap.parse_args()
    for arc in a.archives:
        files = extract(arc, a.dest)
        print(f"{os.path.basename(arc)}: {len(files)} files, {sum(f.endswith('.mat') for f in files)} .mat")


if __name__ == "__main__":
    sys.exit(main())
