#!/usr/bin/env python3
"""Patch libpxrhmdservice.so config-id constants for the v6 DTBO mode order.

The kernel enumerates DFPS modes as [120, 90, 72] (cfg0=120, cfg1=90,
cfg2=72) while the stock lib hardcodes 72->cfg1, 90->cfg0, 120->cfg2, so
rate requests never land on the real 120 config. Two mappings exist:

* ``--shipped`` (default) — every rate request is rewritten to cfg0, the
  120 config. The panel physically never leaves 120, which sidesteps the
  vfp-grow black screen (any DFPS switch away from 120 fails, see README
  section 2.6 / known issue 1). Cost: the shell's idle 72 Hz request also
  lands on cfg0 and the desktop's fps monitor retries (the CPU burn
  reported in issue #2). This is the mapping shipped in Releases v1.0.0+;
  it must stay byte-identical to the lib committed next to this script.
* ``--v7`` — the "true three-rate" experiment (120->cfg0, 90->cfg1,
  72->cfg2). Kills the retry storm but a real down-switch from 120
  triggers the vfp-grow black screen. Diagnostics only; do NOT flash.

The device's stock lib can be pulled with:
  adb pull /system/lib64/libpxrhmdservice.so

``--verify`` recomputes the shipped output and compares it byte-for-byte
against the lib committed to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

SHIPPED_LIB_SHA256 = "32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea"
COMMITTED_LIB = Path(__file__).resolve().parent / "libpxrhmdservice.patched.so"

# Rate-request sites inside libpxrhmdservice.so (vaddr == file offset).
# Each site stores a <II> pair: [SF config index, PICO marker 3].
RATE_SITES = {
    "120Hz": 0x17B18,
    "90Hz": 0x17B80,
    "72Hz": 0x17C20,
}

MAPPINGS = {
    # (lo, hi) written at every site: config 0 = the 120 Hz DFPS config.
    "shipped": {addr: (0, 3) for addr in RATE_SITES.values()},
    # True three-rate mapping against kernel order [120, 90, 72].
    "v7": {RATE_SITES["120Hz"]: (0, 3), RATE_SITES["90Hz"]: (1, 3), RATE_SITES["72Hz"]: (2, 3)},
}


def patch(src: bytes, mapping: dict) -> bytes:
    data = bytearray(src)
    for addr, (lo, hi) in mapping.items():
        struct.pack_into("<II", data, addr, lo, hi)
    return bytes(data)


def report(src: bytes, out: bytes) -> None:
    for name, addr in RATE_SITES.items():
        old = struct.unpack_from("<II", src, addr)
        new = struct.unpack_from("<II", out, addr)
        print(f"  {name} site 0x{addr:X}: {old} -> {new}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", nargs="?", default="libpxrhmdservice.so", help="stock lib input path")
    parser.add_argument("dst", nargs="?", default="libpxrhmdservice.patched.so", help="patched lib output path")
    parser.add_argument("--v7", action="store_true",
                        help="build the diagnostic true-three-rate mapping instead of the shipped all->cfg0 mapping")
    parser.add_argument("--verify", action="store_true",
                        help="after patching, compare the output against the committed shipped lib")
    args = parser.parse_args()

    src = Path(args.src).read_bytes()
    mode = "v7" if args.v7 else "shipped"
    out = patch(src, MAPPINGS[mode])
    print(f"mode: {mode}")
    report(src, out)
    digest = hashlib.sha256(out).hexdigest()
    print("output sha256:", digest)

    Path(args.dst).write_bytes(out)
    print("written:", args.dst)

    if args.verify and not args.v7:
        if digest != SHIPPED_LIB_SHA256:
            print(f"VERIFY FAILED: output hash != shipped constant {SHIPPED_LIB_SHA256}", file=sys.stderr)
            return 1
        committed = COMMITTED_LIB.read_bytes()
        if out != committed:
            print(f"VERIFY FAILED: differs from committed {COMMITTED_LIB.name}", file=sys.stderr)
            return 1
        print(f"verified byte-identical to committed {COMMITTED_LIB.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
