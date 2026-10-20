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

``--verify`` recomputes the shipped output, compares it byte-for-byte against
the lib committed to the repository, and only then writes. ``--v7`` refuses to
overwrite that committed lib, so a diagnostic run cannot poison the file the
packagers hash-check.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

SHIPPED_LIB_SHA256 = "8b4431d4c8f7ebec4bdead981800780347f376e10da10bdb90d6f2977187c829"
COMMITTED_LIB = Path(__file__).resolve().parent / "libpxrhmdservice.patched.so"

# The HMD service writes the requested logical rate into the ConfigurationService
# key "displayRefreshRate". The SDK selects its TimeWarp/exposure rules from
# that key, so a shell request of 72 would otherwise pull the 72 Hz calibration
# onto the 120 Hz scan. Force the two snprintf sites to 120.
RATE_FORCE_SITES = (0x37070, 0x37190)
RATE_FORCE_OLD = bytes.fromhex("e303142a")  # mov w3, w20
RATE_FORCE_NEW = bytes.fromhex("030f8052")  # mov w3, #120

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


def patch(src: bytes, mapping: dict, force_config_120: bool = False) -> bytes:
    data = bytearray(src)
    for addr, (lo, hi) in mapping.items():
        struct.pack_into("<II", data, addr, lo, hi)
    if force_config_120:
        for addr in RATE_FORCE_SITES:
            if data[addr:addr + 4] != RATE_FORCE_OLD:
                raise ValueError(f"unexpected instruction at 0x{addr:X}: {data[addr:addr + 4].hex()}")
            data[addr:addr + 4] = RATE_FORCE_NEW
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
                        help="compare the result against the committed shipped lib before writing")
    args = parser.parse_args()

    if args.v7 and args.verify:
        parser.error("--verify checks the shipped mapping and cannot be combined with --v7")

    src_path = Path(args.src)
    dst = Path(args.dst)
    if not src_path.is_file():
        print(f"missing stock lib at {src_path}", file=sys.stderr)
        return 1
    src = src_path.read_bytes()
    for name, addr in RATE_SITES.items():
        if addr + 8 > len(src):
            print(f"{src_path} is too small for the {name} site at 0x{addr:X}", file=sys.stderr)
            return 1

    mode = "v7" if args.v7 else "shipped"
    out = patch(src, MAPPINGS[mode], force_config_120=(mode == "shipped"))
    print(f"mode: {mode}")
    if mode == "shipped":
        print("  config-rate sites 0x37070/0x37190: forced to 120")
    report(src, out)
    digest = hashlib.sha256(out).hexdigest()
    print("output sha256:", digest)

    if args.v7 and dst.resolve() == COMMITTED_LIB.resolve():
        print(f"REFUSING to overwrite the shipped lib {COMMITTED_LIB} with the diagnostic\n"
              "--v7 mapping; pass an explicit output path", file=sys.stderr)
        return 1

    if args.verify:
        if digest != SHIPPED_LIB_SHA256:
            print(f"VERIFY FAILED: output hash != shipped constant {SHIPPED_LIB_SHA256}", file=sys.stderr)
            return 1
        if not COMMITTED_LIB.is_file():
            print(f"VERIFY FAILED: committed {COMMITTED_LIB} is missing", file=sys.stderr)
            return 1
        if out != COMMITTED_LIB.read_bytes():
            print(f"VERIFY FAILED: differs from committed {COMMITTED_LIB.name}", file=sys.stderr)
            return 1
        print(f"verified byte-identical to committed {COMMITTED_LIB.name}")

    dst.write_bytes(out)
    print("written:", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
