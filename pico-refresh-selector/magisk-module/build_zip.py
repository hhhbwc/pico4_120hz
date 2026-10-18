#!/usr/bin/env python3
"""Assemble the flashable Magisk module zip with correct Unix attributes.

Magisk's built-in extractor skips zip entries without Unix permission bits
(python zipfile defaults external_attr to 0), so every entry here gets
explicit 0644/0755 attributes.

The patched vendor lib and META-INF live in the repository; the 25 MB v6
dtbo image is distribution-sized and stays out of git — pass its path with
--dtbo or place it at pico4-display-analysis/dtbo-120hz-v6-init120.img
(extract it from the release zip; the hash is verified either way).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

MODULE_SRC = Path(__file__).resolve().parent
DTBO_DEFAULT = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "dtbo-120hz-v6-init120.img"
LIB = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "libpxrhmdservice.patched.so"
OUT = Path(__file__).resolve().parent.parent.parent / "pico4-display-analysis" / "pico4-120hz-v1.0.1.zip"

V6_DTBO_SHA256 = "f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"
PATCHED_LIB_SHA256 = "32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea"


def add(zf: zipfile.ZipFile, arcname: str, src: Path, mode: int) -> None:
    info = zipfile.ZipInfo(arcname)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    data = src.read_bytes()
    if not arcname.endswith((".img", ".so")):
        # shell cannot parse CRLF, and a core.autocrlf checkout leaks CRLF
        # into every text entry, not just .sh and module.prop
        data = data.replace(b"\r\n", b"\n")
    zf.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtbo", type=Path, default=DTBO_DEFAULT, help="path to the v6 dtbo image")
    parser.add_argument("--out", type=Path, default=OUT, help="output zip path")
    args = parser.parse_args()

    dtbo = args.dtbo.resolve()
    if not dtbo.is_file():
        print(f"missing v6 dtbo image at {dtbo}\n"
              "extract dtbo.img from the v1.0.0 release zip and pass it via --dtbo",
              file=sys.stderr)
        return 1
    if hashlib.sha256(dtbo.read_bytes()).hexdigest() != V6_DTBO_SHA256:
        print(f"{dtbo} is not the verified v6 image ({V6_DTBO_SHA256})", file=sys.stderr)
        return 1
    if hashlib.sha256(LIB.read_bytes()).hexdigest() != PATCHED_LIB_SHA256:
        print(f"{LIB} does not match the shipped patched lib", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.out, "w") as zf:
        add(zf, "module.prop", MODULE_SRC / "module.prop", 0o644)
        add(zf, "customize.sh", MODULE_SRC / "customize.sh", 0o755)
        add(zf, "service.sh", MODULE_SRC / "service.sh", 0o755)
        add(zf, "dtbo.img", dtbo, 0o644)
        add(zf, "system/lib64/libpxrhmdservice.so", LIB, 0o644)
        meta = MODULE_SRC / "META-INF" / "com" / "google" / "android"
        add(zf, "META-INF/com/google/android/update-binary", meta / "update-binary", 0o755)
        add(zf, "META-INF/com/google/android/updater-script", meta / "updater-script", 0o644)
    with zipfile.ZipFile(args.out) as zf:
        for info in zf.infolist():
            print(f"{oct(info.external_attr >> 16)} {info.file_size:>9} {info.filename}")
    print("written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
