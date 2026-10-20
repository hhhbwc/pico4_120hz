#!/usr/bin/env python3
"""Build panel-level 120 Hz candidates on top of the verified stock DTBO.

Every candidate starts from the byte-verified stock image, applies the v6
enablement (panel-framerate 120, DFPS [120,90,72], max-refresh 120, vendor
post-120 B9/EC stream before sleep-out), and then varies only the NT57900
post-init stream:

  control    v6 as shipped: vendor post-120 stream with its leading B0 00
             packet stripped (44 B)
  b0         vendor post-120 stream with B0 00 kept (53 B)
  e5         B0 00 + E5 07 + 120 B9/EC pairs (62 B)
  d5         B0 00 + 120 B9/EC pairs, each followed by D5 (81 B)
  e5d5       B0 00 + E5 07 + 120 B9/EC pairs, each followed by D5 (90 B)
  b0both     v6 stream unchanged (44 B), then B0 00 + 120 B9/EC on page 0, then F1 08 (106 B)

The 72/90 vendor post streams both carry B0 00, E5 07 and a D5 after every
EC; the 120 stream is the only one that omits them. This builder keeps the
FDT 4-byte aligned when an odd-length stream is inserted by shrinking the
on-command property's trailing padding, and validates the whole image.

Usage:
  python build_120_panel_variants.py <stock.img> <out-dir> [--only NAME ...]
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

ENTRY_INDEX = 5
DFPS = "qcom,dsi-supported-dfps-list"
MAXFPS = "qcom,mdss-dsi-max-refresh-rate"
FRAMERATE = "qcom,mdss-dsi-panel-framerate"
ON_CMD = "qcom,mdss-dsi-on-command"
PHY = "qcom,mdss-dsi-panel-phy-timings"
SLEEP_OUT = bytes.fromhex("0501000078000111")
STOCK_ON_LEN = 314
STOCK_PHY = bytes.fromhex("0022080819230908090204001c0d")


def pkt(payload: bytes, last: int, wait: int = 0, typ: int = 0x29) -> bytes:
    return bytes([typ, last, 0, 0, wait >> 8, wait & 0xFF, len(payload)]) + payload


def post_120_packets(keep_b0: bool) -> bytes:
    out = b""
    if keep_b0:
        out += pkt(bytes.fromhex("b000"), last=0)
    out += pkt(bytes.fromhex("b9102c01cb"), last=0)
    out += pkt(bytes.fromhex("ec0546"), last=1)
    out += pkt(bytes.fromhex("b90f2c01cb"), last=0)
    out += pkt(bytes.fromhex("ec04e6"), last=1)
    return out


def rate_pairs_with_d5(with_e5: bool, with_d5: bool) -> bytes:
    out = pkt(bytes.fromhex("b000"), last=0)
    if with_e5:
        out += pkt(bytes.fromhex("e507"), last=0)
    for b9, ec in (("b9102c01cb", "ec0546"), ("b90f2c01cb", "ec04e6")):
        out += pkt(bytes.fromhex(b9), last=0)
        out += pkt(bytes.fromhex(ec), last=1)
        if with_d5:
            out += pkt(bytes.fromhex("d5000000000000"), last=1)
    return out


STREAMS = {
    "control": post_120_packets(keep_b0=False),
    "b0": post_120_packets(keep_b0=True),
    "e5": rate_pairs_with_d5(with_e5=True, with_d5=False),
    "d5": rate_pairs_with_d5(with_e5=False, with_d5=True),
    "e5d5": rate_pairs_with_d5(with_e5=True, with_d5=True),
    # v6's wrong-page writes are kept verbatim (they are empirically required to
    # avoid an all-white panel), then the same 120 B9/EC pairs are written to
    # page 0, and F1 08 restores the page state stock has before sleep-out.
    "b0both": post_120_packets(keep_b0=False)
              + rate_pairs_with_d5(with_e5=False, with_d5=False)
              + pkt(bytes.fromhex("f108"), last=1),
}


def packets(value: bytes) -> list[bytes]:
    i = 0
    out = []
    while i < len(value):
        if i + 7 > len(value):
            raise ValueError(f"truncated packet at {i}")
        length = value[i + 6]
        end = i + 7 + length
        if end > len(value):
            raise ValueError(f"packet at {i} overruns value")
        out.append(value[i:end])
        i = end
    return out


def prop_for(blob: bytes, name: str, timing: bool) -> dict:
    props = parse_fdt_properties(blob)
    hits = [
        p for p in props
        if p["name"] == name
        and TARGET_NODE in str(p["path"])
        and (("timing@" in str(p["path"])) == timing)
    ]
    if len(hits) != 1:
        raise ValueError(f"{name}: expected exactly one match, got {len(hits)}")
    return hits[0]


def patch_entry(blob: bytes, stream: bytes) -> bytes:
    buf = bytearray(blob)
    on_cmd = prop_for(blob, ON_CMD, timing=True)
    value = bytes(on_cmd["value"])
    if len(value) != STOCK_ON_LEN:
        raise ValueError(f"unexpected stock on-command length {len(value)}")
    if value.count(SLEEP_OUT) != 1:
        raise ValueError("sleep-out packet not found exactly once")
    if bytes(prop_for(blob, PHY, timing=True)["value"]) != STOCK_PHY:
        raise ValueError("stock PHY table changed")
    if not stream:
        raise ValueError("empty stream")
    packets(stream)

    maxfps = prop_for(blob, MAXFPS, timing=False)
    framerate = prop_for(blob, FRAMERATE, timing=True)
    dfps = prop_for(blob, DFPS, timing=False)
    if bytes(maxfps["value"]) != struct.pack(">I", 90):
        raise ValueError("max-refresh-rate is not 90")
    if bytes(framerate["value"]) != struct.pack(">I", 90):
        raise ValueError("panel-framerate is not 90")
    if bytes(dfps["value"]) != struct.pack(">2I", 90, 72):
        raise ValueError("dfps list is not [90, 72]")

    set_u32(buf, int(maxfps["value_offset"]), 120)
    set_u32(buf, int(framerate["value_offset"]), 120)

    insert_at = int(on_cmd["value_offset"]) + value.index(SLEEP_OUT)
    pad_start = int(on_cmd["value_offset"]) + len(value)
    old_pad = align4(pad_start) - pad_start
    new_len = len(value) + len(stream)
    new_pad = (-new_len) % 4
    if new_pad > old_pad:
        raise ValueError(f"stream needs more padding ({new_pad}) than stock has ({old_pad})")
    remove_pad = old_pad - new_pad
    if any(buf[pad_start:pad_start + old_pad]):
        raise ValueError("stock on-command padding is not zero")

    # highest offsets first so earlier recorded offsets stay valid
    del buf[pad_start + old_pad - remove_pad:pad_start + old_pad]
    buf[insert_at:insert_at] = stream
    set_u32(buf, int(on_cmd["header_offset"]) + 4, new_len)

    dfps_insert = int(dfps["value_offset"])
    buf[dfps_insert:dfps_insert] = struct.pack(">I", 120)
    set_u32(buf, int(dfps["header_offset"]) + 4, len(dfps["value"]) + 4)

    net = len(stream) - remove_pad + 4
    set_u32(buf, 4, u32(buf, 4) + net)   # totalsize
    set_u32(buf, 12, u32(buf, 12) + net)  # off_dt_strings
    set_u32(buf, 36, u32(buf, 36) + net)  # size_dt_struct
    if u32(buf, 4) != len(buf):
        raise ValueError("FDT totalsize mismatch after patch")
    out = bytes(buf)
    parse_fdt_properties(out)
    return out


def build(stock: bytes, stream: bytes) -> bytes:
    entries = dtbo_entries(stock)
    size, offset = entries[ENTRY_INDEX]
    patched = patch_entry(stock[offset:offset + size], stream)
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
    return out


def validate(stock: bytes, candidate: bytes, stream: bytes) -> dict:
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
    on_cmd = bytes(prop_for(blob, ON_CMD, timing=True)["value"])
    if len(on_cmd) != STOCK_ON_LEN + len(stream):
        raise ValueError("on-command length mismatch")
    at = STOCK_ON_LEN - 16  # stock sleep-out begins at value offset 298
    if on_cmd[at:at + len(stream)] != stream:
        raise ValueError("stream not inserted before sleep-out")
    if on_cmd.count(SLEEP_OUT) != 1:
        raise ValueError("sleep-out duplicated")
    if bytes(prop_for(blob, FRAMERATE, timing=True)["value"]) != struct.pack(">I", 120):
        raise ValueError("framerate not 120")
    if bytes(prop_for(blob, MAXFPS, timing=False)["value"]) != struct.pack(">I", 120):
        raise ValueError("max refresh not 120")
    if bytes(prop_for(blob, DFPS, timing=False)["value"]) != struct.pack(">3I", 120, 90, 72):
        raise ValueError("dfps not [120, 90, 72]")
    if bytes(prop_for(blob, PHY, timing=True)["value"]) != STOCK_PHY:
        raise ValueError("PHY changed")
    packets(on_cmd)
    return {
        "entry_size": size,
        "on_command_len": len(on_cmd),
        "stream_len": len(stream),
        "sha256": hashlib.sha256(candidate).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stock")
    ap.add_argument("out_dir")
    ap.add_argument("--only", nargs="*", choices=sorted(STREAMS), default=sorted(STREAMS))
    args = ap.parse_args()

    stock = Path(args.stock).read_bytes()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if hashlib.sha256(stock).hexdigest() != "307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac":
        raise SystemExit("stock image is not the verified 307e7021 CN DTBO")

    for name in args.only:
        stream = STREAMS[name]
        candidate = build(stock, stream)
        report = validate(stock, candidate, stream)
        path = out_dir / f"dtbo-120-panel-{name}.img"
        path.write_bytes(candidate)
        print(f"{name}: {path.name}  stream={len(stream)}B  oncmd={report['on_command_len']}B")
        print(f"  sha256 {report['sha256']}")
        print(f"  stream {stream.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
