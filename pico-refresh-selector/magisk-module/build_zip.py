#!/usr/bin/env python3
"""Assemble the flashable Magisk module zip with correct Unix attributes.

Magisk's built-in extractor skips zip entries without Unix permission bits
(python zipfile defaults external_attr to 0), so every entry here gets
explicit 0644/0755 attributes.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

MODULE_SRC = Path(__file__).resolve().parent.parent / "magisk-module"
META_INF = Path(__file__).resolve().parent.parent.parent / ".release-repo" / "META-INF"
DTBO = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "dtbo-120hz-v6-init120.img"
LIB = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "libpxrhmdservice.patched.so"
OUT = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "pico4-120hz-v1.0.0.zip"


def add(zf: zipfile.ZipFile, arcname: str, src: Path, mode: int) -> None:
    info = zipfile.ZipInfo(arcname)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    data = src.read_bytes()
    if arcname.endswith(".sh") or arcname == "module.prop":
        data = data.replace(b"\r\n", b"\n")  # shell cannot parse CRLF
    zf.writestr(info, data)


def main() -> int:
    if not DTBO.is_file() or not LIB.is_file():
        print("missing dtbo-120hz-v6-init120.img or libpxrhmdservice.patched.so", file=sys.stderr)
        return 1
    with zipfile.ZipFile(OUT, "w") as zf:
        add(zf, "module.prop", MODULE_SRC / "module.prop", 0o644)
        add(zf, "customize.sh", MODULE_SRC / "customize.sh", 0o755)
        add(zf, "service.sh", MODULE_SRC / "service.sh", 0o755)
        add(zf, "dtbo.img", DTBO, 0o644)
        add(zf, "system/lib64/libpxrhmdservice.so", LIB, 0o644)
        meta = META_INF / "com" / "google" / "android"
        add(zf, "META-INF/com/google/android/update-binary", meta / "update-binary", 0o755)
        add(zf, "META-INF/com/google/android/updater-script", meta / "updater-script", 0o644)
    with zipfile.ZipFile(OUT) as zf:
        for info in zf.infolist():
            print(f"{oct(info.external_attr >> 16)} {info.file_size:>9} {info.filename}")
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
