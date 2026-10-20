#!/usr/bin/env python3
"""Build 120 Hz candidates by patching the *post-120* NT57900 command property.

Why this exists
---------------
v6 inserted the vendor 120 stream into the panel's on-command, before
sleep-out. A kprobe trace on 5.13.7 shows the display driver already calls
dsi_panel_post_enable_120_nt57900() after dsi_bridge_enable() and sends the
DT property ``qcom,mdss-dsi-post-120-nt57900-on-command`` (tx type 0x5).
That property is the sequence the bridge actually receives in its 120 state;
the v6 injection is a second, earlier copy that is most likely discarded by
sleep-out/display-on.

Each candidate here starts from the verified stock image, applies the v6
enablement (framerate 120, DFPS [120,90,72], max-refresh 120), and then
rewrites only the post-120 property:

  post120-e5      vendor 120 packets + E5 07 after B0
  post120-d5      vendor 120 packets + D5 after each EC
  post120-e5d5    both, mirroring the vendor post-90 structure
  noinject-*      same, with the redundant on-command injection removed

Usage:
  python build_post120_variants.py <stock.img> <out-dir>
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_candidate_dtbo import (  # noqa: E402
    TARGET_NODE,
    align4,
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
    SLEEP_OUT,
    STOCK_ON_LEN,
    STOCK_PHY,
    packets,
    patch_entry,
    pkt,
)

POST120 = "qcom,mdss-dsi-post-120-nt57900-on-command"
VENDOR_POST120 = bytes.fromhex(
    "29000000000002b000"
    "29000000000005b9102c01cb"
    "29010000000003ec0546"
    "29000000000005b90f2c01cb"
    "29010000000003ec04e6"
)
CONTROL_STREAM = bytes.fromhex(
    "29000000000005b9102c01cb"
    "29010000000003ec0546"
    "29000000000005b90f2c01cb"
    "29010000000003ec04e6"
)

B0 = pkt(bytes.fromhex("b000"), last=0)
E5 = pkt(bytes.fromhex("e507"), last=0)
B9A = pkt(bytes.fromhex("b9102c01cb"), last=0)
ECA = pkt(bytes.fromhex("ec0546"), last=1)
B9B = pkt(bytes.fromhex("b90f2c01cb"), last=0)
ECB = pkt(bytes.fromhex("ec04e6"), last=1)
D5 = pkt(bytes.fromhex("d5000000000000"), last=1)

POST120_VARIANTS = {
    "post120-control": VENDOR_POST120,
    "post120-e5": B0 + E5 + B9A + ECA + B9B + ECB,
    "post120-d5": B0 + B9A + ECA + D5 + B9B + ECB + D5,
    "post120-e5d5": B0 + E5 + B9A + ECA + D5 + B9B + ECB + D5,
}
NOINJECT_VARIANTS = {
    "noinject-control": VENDOR_POST120,
    "noinject-e5d5": POST120_VARIANTS["post120-e5d5"],
}


def prop_unique(blob: bytes, name: str) -> dict:
    hits = [p for p in parse_fdt_properties(blob)
            if p["name"] == name and TARGET_NODE in str(p["path"])]
    if len(hits) != 1:
        raise ValueError(f"{name}: expected exactly one LS026 match, got {len(hits)}")
    return hits[0]


def enable_only(blob: bytes) -> bytes:
    """Set 120 modes without inserting anything into the on-command."""
    buf = bytearray(blob)
    maxfps = prop_unique(blob, MAXFPS)
    framerate = prop_unique(blob, FRAMERATE)
    dfps = prop_unique(blob, DFPS)
    if bytes(maxfps["value"]) != struct.pack(">I", 90):
        raise ValueError("max-refresh-rate is not 90")
    if bytes(framerate["value"]) != struct.pack(">I", 90):
        raise ValueError("panel-framerate is not 90")
    if bytes(dfps["value"]) != struct.pack(">2I", 90, 72):
        raise ValueError("dfps list is not [90, 72]")
    set_u32(buf, int(maxfps["value_offset"]), 120)
    set_u32(buf, int(framerate["value_offset"]), 120)

    at = int(dfps["value_offset"])
    buf[at:at] = struct.pack(">I", 120)
    set_u32(buf, int(dfps["header_offset"]) + 4, len(dfps["value"]) + 4)
    net = 4
    set_u32(buf, 4, u32(buf, 4) + net)
    set_u32(buf, 12, u32(buf, 12) + net)
    set_u32(buf, 36, u32(buf, 36) + net)
    if u32(buf, 4) != len(buf):
        raise ValueError("FDT totalsize mismatch after enable_only")
    out = bytes(buf)
    parse_fdt_properties(out)
    return out


def replace_prop(blob: bytes, name: str, new_value: bytes) -> bytes:
    prop = prop_unique(blob, name)
    voff = int(prop["value_offset"])
    old_len = int(prop["value_length"])
    hdr = int(prop["header_offset"])
    old_pad = align4(voff + old_len) - (voff + old_len)
    new_pad = (-len(new_value)) % 4
    if any(blob[voff + old_len:voff + old_len + old_pad]):
        raise ValueError(f"{name}: padding is not zero")
    before = blob[:voff]
    after = blob[voff + old_len + old_pad:]
    out = bytearray(before) + new_value + b"\x00" * new_pad + after
    set_u32(out, hdr + 4, len(new_value))
    delta = (len(new_value) + new_pad) - (old_len + old_pad)
    set_u32(out, 4, u32(blob, 4) + delta)
    set_u32(out, 12, u32(blob, 12) + delta)
    set_u32(out, 36, u32(blob, 36) + delta)
    if u32(out, 4) != len(out):
        raise ValueError(f"{name}: FDT totalsize mismatch after replace")
    result = bytes(out)
    parse_fdt_properties(result)
    return result


def build_candidate(stock: bytes, post120: bytes, inject: bool) -> bytes:
    size, offset = dtbo_entries(stock)[ENTRY_INDEX]
    entry = stock[offset:offset + size]
    if inject:
        entry = patch_entry(entry, CONTROL_STREAM)
    else:
        entry = enable_only(entry)
    vendor = prop_unique(entry, POST120)
    if bytes(vendor["value"]) != VENDOR_POST120:
        raise ValueError("unexpected stock post-120 property")
    if post120 != VENDOR_POST120:
        entry = replace_prop(entry, POST120, post120)

    shift = len(entry) - size
    img = bytearray(stock)
    img[offset:offset + size] = entry
    entries_offset = u32(img, 20)
    set_u32(img, entries_offset + ENTRY_INDEX * 32, len(entry))
    for other in range(ENTRY_INDEX + 1, len(dtbo_entries(stock))):
        base = entries_offset + other * 32
        set_u32(img, base + 4, u32(img, base + 4) + shift)
    set_u32(img, 4, u32(img, 4) + shift)
    return bytes(img[:len(stock)])


def validate(stock: bytes, candidate: bytes, post120: bytes, inject: bool) -> dict:
    old_entries = dtbo_entries(stock)
    new_entries = dtbo_entries(candidate)
    if len(old_entries) != len(new_entries):
        raise ValueError("entry count changed")
    for i, ((osz, ooff), (nsz, noff)) in enumerate(zip(old_entries, new_entries)):
        old_blob = stock[ooff:ooff + osz]
        new_blob = candidate[noff:noff + nsz]
        parse_fdt_properties(new_blob)
        if i != ENTRY_INDEX and old_blob != new_blob:
            raise ValueError(f"non-target entry {i} changed")

    size, offset = new_entries[ENTRY_INDEX]
    blob = candidate[offset:offset + size]
    on_cmd = bytes(prop_unique(blob, ON_CMD)["value"])
    if inject:
        if len(on_cmd) != STOCK_ON_LEN + len(CONTROL_STREAM):
            raise ValueError("on-command length mismatch")
        at = STOCK_ON_LEN - 16
        if on_cmd[at:at + len(CONTROL_STREAM)] != CONTROL_STREAM:
            raise ValueError("control stream not before sleep-out")
    else:
        if len(on_cmd) != STOCK_ON_LEN:
            raise ValueError("on-command was modified in no-inject build")
    if on_cmd.count(SLEEP_OUT) != 1:
        raise ValueError("sleep-out count changed")
    if bytes(prop_unique(blob, POST120)["value"]) != post120:
        raise ValueError("post-120 property mismatch")
    if bytes(prop_unique(blob, FRAMERATE)["value"]) != struct.pack(">I", 120):
        raise ValueError("framerate not 120")
    if bytes(prop_unique(blob, MAXFPS)["value"]) != struct.pack(">I", 120):
        raise ValueError("max refresh not 120")
    if bytes(prop_unique(blob, DFPS)["value"]) != struct.pack(">3I", 120, 90, 72):
        raise ValueError("dfps not [120, 90, 72]")
    if bytes(prop_unique(blob, PHY)["value"]) != STOCK_PHY:
        raise ValueError("PHY changed")
    packets(on_cmd)
    packets(post120)
    return {
        "entry_size": size,
        "post120_len": len(post120),
        "on_command_len": len(on_cmd),
        "sha256": hashlib.sha256(candidate).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stock")
    ap.add_argument("out_dir")
    args = ap.parse_args()

    stock = Path(args.stock).read_bytes()
    if hashlib.sha256(stock).hexdigest() != \
            "307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac":
        raise SystemExit("stock image is not the verified 307e7021 CN DTBO")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(n, v, True) for n, v in POST120_VARIANTS.items()]
    jobs += [(n, v, False) for n, v in NOINJECT_VARIANTS.items()]
    for name, post120, inject in jobs:
        candidate = build_candidate(stock, post120, inject)
        report = validate(stock, candidate, post120, inject)
        path = out_dir / f"dtbo-120-{name}.img"
        path.write_bytes(candidate)
        print(f"{name:20s} inject={inject!s:5s} post120={report['post120_len']:3d}B "
              f"oncmd={report['on_command_len']:3d}B entry={report['entry_size']}")
        print(f"  sha256 {report['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
