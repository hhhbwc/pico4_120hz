#!/usr/bin/env python3
"""Build the v6 120 Hz enablement with the vendor 120 vfp (vtotal 2182).

v6 keeps the stock 90 Hz vertical blanking (vfp 57 -> vtotal 2225), which
runs the link at 1.325 GHz.  The vendor 493_120 reference uses vfp 14
(vtotal 2182, 1.299 GHz).  This variant changes only that one timing value.

Usage: python build_120_vfp14.py <stock.img> <out.img>
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_candidate_dtbo import (  # noqa: E402
    TARGET_NODE,
    dtbo_entries,
    parse_fdt_properties,
    set_u32,
    u32,
)
from build_120_panel_variants import (  # noqa: E402
    DFPS,
    ENTRY_INDEX,
    FRAMERATE,
    MAXFPS,
    ON_CMD,
    PHY,
    STOCK_ON_LEN,
    STOCK_PHY,
    STREAMS,
    patch_entry,
    prop_for,
)

VFP = "qcom,mdss-dsi-v-front-porch"
STOCK_VFP = 57
TARGET_VFP = 14


def set_vfp(blob: bytes) -> bytes:
    buf = bytearray(blob)
    prop = prop_for(blob, VFP, timing=True)
    if len(prop["value"]) != 4 or u32(bytes(prop["value"]), 0) != STOCK_VFP:
        raise ValueError("unexpected stock vfp")
    set_u32(buf, int(prop["value_offset"]), TARGET_VFP)
    out = bytes(buf)
    parse_fdt_properties(out)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    stock = Path(sys.argv[1]).read_bytes()
    if hashlib.sha256(stock).hexdigest() != "307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac":
        raise SystemExit("stock image is not the verified 307e7021 CN DTBO")

    entries = dtbo_entries(stock)
    size, offset = entries[ENTRY_INDEX]
    patched = patch_entry(set_vfp(stock[offset:offset + size]), STREAMS["control"])
    shift = len(patched) - size
    img = bytearray(stock)
    img[offset:offset + size] = patched
    entries_offset = u32(img, 20)
    set_u32(img, entries_offset + ENTRY_INDEX * 32, len(patched))
    for other in range(ENTRY_INDEX + 1, len(entries)):
        base = entries_offset + other * 32
        set_u32(img, base + 4, u32(img, base + 4) + shift)
    set_u32(img, 4, u32(img, 4) + shift)
    out = bytes(img[:len(stock)])
    if len(out) != len(stock):
        raise ValueError("image size changed")

    new_entries = dtbo_entries(out)
    for i, ((osz, ooff), (nsz, noff)) in enumerate(zip(entries, new_entries)):
        if i != ENTRY_INDEX and stock[ooff:ooff + osz] != out[noff:noff + nsz]:
            raise ValueError(f"non-target entry {i} changed")
    nsize, noff = new_entries[ENTRY_INDEX]
    blob = out[noff:noff + nsize]
    if u32(bytes(prop_for(blob, VFP, timing=True)["value"]), 0) != TARGET_VFP:
        raise ValueError("vfp not applied")
    if bytes(prop_for(blob, FRAMERATE, timing=True)["value"]) != struct.pack(">I", 120):
        raise ValueError("framerate not 120")
    if bytes(prop_for(blob, MAXFPS, timing=False)["value"]) != struct.pack(">I", 120):
        raise ValueError("max refresh not 120")
    if bytes(prop_for(blob, DFPS, timing=False)["value"]) != struct.pack(">3I", 120, 90, 72):
        raise ValueError("dfps not [120, 90, 72]")
    if bytes(prop_for(blob, PHY, timing=True)["value"]) != STOCK_PHY:
        raise ValueError("PHY changed")
    on_cmd = bytes(prop_for(blob, ON_CMD, timing=True)["value"])
    if len(on_cmd) != STOCK_ON_LEN + len(STREAMS["control"]):
        raise ValueError("on-command length mismatch")
    if on_cmd.count(bytes.fromhex("0501000078000111")) != 1:
        raise ValueError("sleep-out duplicated")

    Path(sys.argv[2]).write_bytes(out)
    print(f"vfp {STOCK_VFP} -> {TARGET_VFP} (vtotal 2225 -> 2182)")
    print(f"sha256 {hashlib.sha256(out).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
