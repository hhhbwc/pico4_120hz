#!/usr/bin/env python3
"""Assemble the flashable Magisk module zip with correct Unix attributes.

Magisk's built-in extractor skips zip entries without Unix permission bits
(python zipfile defaults external_attr to 0), so every entry here gets
explicit 0644/0755 attributes.

The patched vendor lib and META-INF live in the repository. Four 25 MB dtbo
images are bundled — CN and Phoenix_ovs (b9666) 120Hz/stock pairs — because
the bootloader selects a different entry index on each variant and the
installer selects the pair by the unit's stock hash. The images stay out of
git; build them with build_120_init120_inplace.py / build_120_ovs.py (hashes
are verified here and by the installer).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

MODULE_SRC = Path(__file__).resolve().parent
ANALYSIS = MODULE_SRC.parent.parent / "pico4-display-analysis"
DTBO_CN = ANALYSIS / "dtbo-120hz-v6-init120.img"
DTBO_OVS = ANALYSIS / "dtbo-120hz-v6-kona-mtp.img"
DTBO_STOCK_CN = ANALYSIS / "recovery-edl" / "dtbo-stock-5.13.7.img"
DTBO_STOCK_OVS = ANALYSIS / "dtbo-stock-phoenix_ovs.img"
LIB = ANALYSIS / "libpxrhmdservice.patched.so"
OUT = ANALYSIS / "pico4-120hz-v1.2.0.zip"

# must match the constants in customize.sh
DTBO_CN_SHA256 = "f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"
DTBO_OVS_SHA256 = "d138d5d68e64be3209b8d5024c7f10fd120dc3d2d83fd703a31fe09b3a6b5123"
DTBO_STOCK_CN_SHA256 = "307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
DTBO_STOCK_OVS_SHA256 = "f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992"
PATCHED_LIB_SHA256 = "8b4431d4c8f7ebec4bdead981800780347f376e10da10bdb90d6f2977187c829"


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
    parser.add_argument("--out", type=Path, default=OUT, help="output zip path")
    args = parser.parse_args()

    for path, expected, label in (
        (args.dtbo_cn, DTBO_CN_SHA256, "CN 120Hz"),
        (DTBO_OVS, DTBO_OVS_SHA256, "Phoenix_ovs 120Hz"),
        (DTBO_STOCK_CN, DTBO_STOCK_CN_SHA256, "stock CN"),
        (DTBO_STOCK_OVS, DTBO_STOCK_OVS_SHA256, "stock Phoenix_ovs"),
    ):
        path = path.resolve()
        if not path.is_file():
            print(f"missing {label} dtbo image at {path}\n"
                  "place the official 5.13.7 stock image and the v6 init120 image there",
                  file=sys.stderr)
            return 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            print(f"{path} is not the verified {label} image ({expected})", file=sys.stderr)
            return 1
    if not LIB.is_file():
        print(f"missing patched lib at {LIB}\n"
              "build it with pico4-display-analysis/patch_hmdservice_cfgmap.py --verify",
              file=sys.stderr)
        return 1
    if hashlib.sha256(LIB.read_bytes()).hexdigest() != PATCHED_LIB_SHA256:
        print(f"{LIB} does not match the shipped patched lib", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.out, "w") as zf:
        add(zf, "module.prop", MODULE_SRC / "module.prop", 0o644)
        add(zf, "customize.sh", MODULE_SRC / "customize.sh", 0o755)
        add(zf, "service.sh", MODULE_SRC / "service.sh", 0o755)
        add(zf, "post-fs-data.sh", MODULE_SRC / "post-fs-data.sh", 0o755)
        add(zf, "uninstall.sh", MODULE_SRC / "uninstall.sh", 0o755)
        add(zf, "system/etc/pvr/pxr_config.txt", MODULE_SRC / "system/etc/pvr/pxr_config.txt", 0o644)
        add(zf, "dtbo-cn.img", args.dtbo_cn.resolve(), 0o644)
        add(zf, "dtbo-ovs.img", DTBO_OVS.resolve(), 0o644)
        add(zf, "dtbo-stock-cn.img", DTBO_STOCK_CN.resolve(), 0o644)
        add(zf, "dtbo-stock-ovs.img", DTBO_STOCK_OVS.resolve(), 0o644)
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
