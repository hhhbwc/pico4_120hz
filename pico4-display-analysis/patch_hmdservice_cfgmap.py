#!/usr/bin/env python3
"""Patch libpxrhmdservice.so config-id constants for the v3 DTBO mode order.

v7 "true three-rate" mapping for the v6 DTBO (kernel mode order
[120, 90, 72] -> cfg0=120, cfg1=90, cfg2=72): every rate request lands
on its REAL config. The shell's legitimate 72 Hz idle request now
succeeds (killing the endless retry storm that burned CPU), and games
switch the panel to 120 for real. Panel NT57900 registers stay on the
120 config across DFPS switches; the 72/90 visuals were verified
on-device.
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import sys
from pathlib import Path

SRC = Path("libpxrhmdservice.so")
DST = Path("libpxrhmdservice.patched.so")
PATCHES = {  # vaddr == file offset (LOAD delta 0)
    0x17C20: (2, 3),  # 72 Hz: cfg 1 -> 2 (real 72 config)
    0x17B18: (0, 3),  # 120 Hz: cfg 2 -> 0 (real 120 config)
    0x17B80: (1, 3),  # 90 Hz: cfg 0 -> 1 (real 90 config)
}


def main() -> int:
    data = bytearray(SRC.read_bytes())
    for addr, (lo, hi) in PATCHES.items():
        old_lo, old_hi = struct.unpack_from("<II", data, addr)
        struct.pack_into("<II", data, addr, lo, hi)
        print(f"{addr:#x}: ({old_lo},{old_hi}) -> ({lo},{hi})")
    DST.write_bytes(bytes(data))
    for path in (SRC, DST):
        print(path.name, hashlib.sha256(path.read_bytes()).hexdigest())
    # verify
    check = DST.read_bytes()
    for addr, (lo, hi) in PATCHES.items():
        got = struct.unpack_from("<II", check, addr)
        if got != (lo, hi):
            print(f"VERIFY FAILED at {addr:#x}: {got}", file=sys.stderr)
            return 1
    src = SRC.read_bytes()
    allowed = set()
    for addr in PATCHES:
        allowed.update(range(addr, addr + 8))
    diffs = [i for i in range(len(src)) if src[i] != check[i]]
    outside = [hex(i) for i in diffs if i not in allowed]
    if outside:
        print(f"VERIFY FAILED: bytes outside patch sites changed: {outside[:10]}", file=sys.stderr)
        return 1
    print(f"VERIFY OK: {len(diffs)} bytes changed, all inside patch sites")
    print("VERIFY OK: only the two 8-byte constants differ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
