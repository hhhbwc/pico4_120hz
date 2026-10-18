#!/usr/bin/env python3
"""Assemble the flashable Magisk module zip with correct Unix attributes.

Magisk's built-in extractor skips zip entries without Unix permission bits
(python zipfile defaults external_attr to 0), so every entry here gets
explicit 0644/0755 attributes.

The patched vendor lib and META-INF live in the repository. Two 25 MB dtbo
images are bundled — one built from the CN stock image, one from the global
(Phoenix_ovs) stock image — because the two firmwares order the same sixteen
dtbo entries differently and the bootloader selects by index. Both images
patch every entry, so the installer only has to match the unit's stock hash,
never its board index. The images stay out of git; build them with
pico4-display-analysis/build_120_universal.py (hash verified here).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

MODULE_SRC = Path(__file__).resolve().parent
ANALYSIS = MODULE_SRC.parent.parent / "pico4-display-analysis"
DTBO_CN = ANALYSIS / "dtbo-120hz-universal-phykeep.img"
DTBO_INTL = ANALYSIS / "dtbo-120hz-universal-intl.img"
LIB = ANALYSIS / "libpxrhmdservice.patched.so"
OUT = ANALYSIS / "pico4-120hz-v1.0.1.zip"

# must match the constants in customize.sh
DTBO_CN_SHA256 = "a57573ae89a26bc37db10d8b258a25f2cf343b042246519144ff3213508ff385"
DTBO_INTL_SHA256 = "0ab8b85ed85203bd0096f4a89f12d18a0746d7bd461a7d7c0e355ace727936e9"
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
    parser.add_argument("--dtbo-cn", type=Path, default=DTBO_CN, help="120Hz image built from the CN stock dtbo")
    parser.add_argument("--dtbo-intl", type=Path, default=DTBO_INTL, help="120Hz image built from the global stock dtbo")
    parser.add_argument("--out", type=Path, default=OUT, help="output zip path")
    args = parser.parse_args()

    for path, expected, label in (
        (args.dtbo_cn, DTBO_CN_SHA256, "CN"),
        (args.dtbo_intl, DTBO_INTL_SHA256, "global"),
    ):
        path = path.resolve()
        if not path.is_file():
            print(f"missing {label} dtbo image at {path}\n"
                  "build it with pico4-display-analysis/build_120_universal.py",
                  file=sys.stderr)
            return 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            print(f"{path} is not the verified {label} image ({expected})", file=sys.stderr)
            return 1
    if hashlib.sha256(LIB.read_bytes()).hexdigest() != PATCHED_LIB_SHA256:
        print(f"{LIB} does not match the shipped patched lib", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.out, "w") as zf:
        add(zf, "module.prop", MODULE_SRC / "module.prop", 0o644)
        add(zf, "customize.sh", MODULE_SRC / "customize.sh", 0o755)
        add(zf, "service.sh", MODULE_SRC / "service.sh", 0o755)
        add(zf, "dtbo-cn.img", args.dtbo_cn.resolve(), 0o644)
        add(zf, "dtbo-intl.img", args.dtbo_intl.resolve(), 0o644)
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
