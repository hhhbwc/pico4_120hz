#!/usr/bin/env python3
"""Assemble the Phoenix_ovs (global / kona-MTP) variant of the flashable zip.

Identical packaging to build_zip.py, but the installer hashes are swapped for
the global-unit baselines and the bundled dtbo is the entry-6 in-place build:

  stock dtbo baseline : f4d6073c...  (global 5.13.7, ro.boot.dtbo_idx=6)
  patched dtbo target : d138d5d6...  (dtbo-120hz-v6-kona-mtp.img)

The author's customize.sh is reused verbatim except for the two dtbo hash
constants (asserted to each appear exactly once) and module.prop becoming
v1.0.1-ovs / versionCode 3. The firmware gate is inherited unchanged: upstream
customize.sh already checks ro.build.id (ro.build.version.incremental is a
smartcm.<timestamp> build number on every 5.13.7 unit, CN and global alike).
All text entries are CRLF-normalized (a core.autocrlf checkout leaks CRLF into
every text file, not just .sh).

Requires dtbo-120hz-v6-kona-mtp.img, produced by build_120_ovs.py from a
Phoenix_ovs stock dump (dtbo-stock-phoenix_ovs.img) — not committed here.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

MODULE_SRC = Path(__file__).resolve().parent
REPO = MODULE_SRC.parent.parent
DTBO = REPO / "pico4-display-analysis" / "dtbo-120hz-v6-kona-mtp.img"
LIB = REPO / "pico4-display-analysis" / "libpxrhmdservice.patched.so"
OUT = REPO / "pico4-display-analysis" / "pico4-120hz-v1.0.1-phoenix_ovs.zip"

DTBO_SHA256 = "d138d5d68e64be3209b8d5024c7f10fd120dc3d2d83fd703a31fe09b3a6b5123"
PATCHED_LIB_SHA256 = "32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea"

AUTHOR_STOCK_HASH = "307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
OVS_STOCK_HASH = "f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992"
AUTHOR_V6_HASH = "f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"

def replace_once(text: str, old: str, new: str, what: str) -> str:
    assert text.count(old) == 1, f"{what}: expected exactly one occurrence of {old[:20]}..."
    return text.replace(old, new)


def add(zf: zipfile.ZipFile, arcname: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(arcname)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    if not arcname.endswith((".img", ".so")):
        data = data.replace(b"\r\n", b"\n")
    zf.writestr(info, data)


def main() -> int:
    dtbo = DTBO.read_bytes()
    assert hashlib.sha256(dtbo).hexdigest() == DTBO_SHA256, "bundled dtbo hash mismatch"
    lib = LIB.read_bytes()
    assert hashlib.sha256(lib).hexdigest() == PATCHED_LIB_SHA256, "patched lib hash mismatch"

    customize = (MODULE_SRC / "customize.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    customize = replace_once(customize, AUTHOR_STOCK_HASH, OVS_STOCK_HASH, "stock dtbo hash")
    customize = replace_once(customize, AUTHOR_V6_HASH, DTBO_SHA256, "target dtbo hash")
    customize = replace_once(
        customize, "Pico4 120Hz Display Unlock v1.0.1", "Pico4 120Hz Display Unlock v1.0.1-ovs", "banner"
    )

    module_prop = (MODULE_SRC / "module.prop").read_text(encoding="utf-8")
    module_prop = replace_once(module_prop, "version=v1.0.1", "version=v1.0.1-ovs", "version")
    module_prop = replace_once(module_prop, "versionCode=2", "versionCode=3", "versionCode")

    with zipfile.ZipFile(OUT, "w") as zf:
        add(zf, "module.prop", module_prop.encode(), 0o644)
        add(zf, "customize.sh", customize.encode(), 0o755)
        add(zf, "service.sh", (MODULE_SRC / "service.sh").read_bytes(), 0o755)
        add(zf, "dtbo.img", dtbo, 0o644)
        add(zf, "system/lib64/libpxrhmdservice.so", lib, 0o644)
        meta = MODULE_SRC / "META-INF" / "com" / "google" / "android"
        add(zf, "META-INF/com/google/android/update-binary", meta.joinpath("update-binary").read_bytes(), 0o755)
        add(zf, "META-INF/com/google/android/updater-script", meta.joinpath("updater-script").read_bytes(), 0o644)

    with zipfile.ZipFile(OUT) as zf:
        for info in zf.infolist():
            print(f"{oct(info.external_attr >> 16)} {info.file_size:>9} {info.filename}")
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"BUILD FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
