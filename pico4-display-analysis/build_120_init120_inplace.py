#!/usr/bin/env python3
"""Build the 120 Hz DTBO for a PICO 4 by patching one stock entry in place.

Unlike the author's chain (which rebuilt the table with the panel entry
reordered to index 5), this keeps the stock entry order and rewrites only the
panel entry the bootloader actually selects, so the image stays stock-shaped
for the unit it was built from:

  - qcom,dsi-supported-dfps-list  [90, 72] -> [120, 90, 72]  (+4 bytes)
  - qcom,mdss-dsi-max-refresh-rate      90  -> 120
  - qcom,mdss-dsi-panel-framerate       90  -> 120   (timing@0)
  - qcom,mdss-dsi-on-command: the vendor post-120 NT57900 packet stream is
    inserted before the sleep-out packet (+44 bytes, the author's v6 fix)

Usage: python build_120_init120_inplace.py <stock.img> <entry-index> <out.img>
       python build_120_init120_inplace.py --selftest <stock.img> <v6.img>

The selftest patches entry 7 (the byte-identical pre-patch twin of the
author's panel entry) and requires the result to match the author's patched
entry exactly — proving the chain without access to his stock image.
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

NODE = TARGET_NODE
DFPS = "qcom,dsi-supported-dfps-list"
MAXFPS = "qcom,mdss-dsi-max-refresh-rate"
FRAMERATE = "qcom,mdss-dsi-panel-framerate"
ON_CMD = "qcom,mdss-dsi-on-command"
# vendor post-120 NT57900 stream minus its leading B0 00 unlock packet
POST_120_STREAM = bytes.fromhex(
    "29000000000005b9102c01cb"
    "29010000000003ec0546"
    "29000000000005b90f2c01cb"
    "29010000000003ec04e6"
)
SLEEP_OUT = bytes.fromhex("0501000078000111")  # DCS 11 with 120 ms delay


def prop_for(blob: bytes, name: str, timing: bool) -> dict:
    props = parse_fdt_properties(blob)
    hits = [
        p
        for p in props
        if p["name"] == name
        and NODE in str(p["path"])
        and (("timing@" in str(p["path"])) == timing)
    ]
    assert len(hits) == 1, f"{name}: expected exactly one match, got {len(hits)}"
    return hits[0]


def patch_entry(blob: bytes) -> bytes:
    buf = bytearray(blob)

    def check(cond: bool, msg: str) -> None:
        if not cond:
            raise ValueError(msg)

    on_cmd = prop_for(blob, ON_CMD, timing=True)  # lives inside timing@0
    value = bytes(on_cmd["value"])
    check(value.startswith(bytes.fromhex("29010000000002b000")), "on-command must open with B0 00 unlock")
    check(value.count(SLEEP_OUT) == 1, "sleep-out packet not found exactly once")
    check(bytes.fromhex("b9135f0264") in value, "expected 90 Hz B9 payload missing")
    check(POST_120_STREAM not in value, "post-120 stream already present")
    check(len(POST_120_STREAM) % 4 == 0, "inserted stream must be 4-byte aligned")

    maxfps = prop_for(blob, MAXFPS, timing=False)
    framerate = prop_for(blob, FRAMERATE, timing=True)
    dfps = prop_for(blob, DFPS, timing=False)
    check(bytes(maxfps["value"]) == b"\x00\x00\x00\x5a", "max-refresh-rate is not 90")
    check(bytes(framerate["value"]) == b"\x00\x00\x00\x5a", "panel-framerate is not 90")
    check(
        bytes(dfps["value"]) == bytes.fromhex("0000005a00000048"),
        "dfps list is not [90, 72]",
    )

    # length-neutral rewrites first, then insertions from the highest offset
    # down so recorded offsets stay valid
    set_u32(buf, int(maxfps["value_offset"]), 120)
    set_u32(buf, int(framerate["value_offset"]), 120)

    insertions = []
    # each: (insert_offset, payload, address of the property's length field,
    #        bump size_dt_struct?). The author's v2 handled the dfps growth by
    #        bumping totalsize and off_dt_strings but NOT size_dt_struct, and
    #        his shipped v6 (boot-verified on hardware) carries that +4
    #        undercount; we mirror it byte-exactly. libfdt walks to the
    #        FDT_END token, so the undercounted field is never trusted.
    insertions.append((int(dfps["value_offset"]), struct.pack(">I", 120), int(dfps["header_offset"]) + 4, False))
    insert_at = int(on_cmd["value_offset"]) + value.index(SLEEP_OUT)
    insertions.append((insert_at, POST_120_STREAM, int(on_cmd["header_offset"]) + 4, True))

    for offset, payload, len_field, bump_struct in sorted(insertions, key=lambda t: t[0], reverse=True):
        buf[offset:offset] = payload
        set_u32(buf, len_field, u32(buf, len_field) + len(payload))
        shift = len(payload)
        set_u32(buf, 4, u32(buf, 4) + shift)  # totalsize
        set_u32(buf, 12, u32(buf, 12) + shift)  # off_dt_strings
        if bump_struct:
            set_u32(buf, 36, u32(buf, 36) + shift)  # size_dt_struct

    out = bytes(buf)
    parse_fdt_properties(out)  # must remain a valid FDT
    return out


def build(stock: bytes, index: int) -> bytes:
    entries = dtbo_entries(stock)
    size, off = entries[index]
    patched = patch_entry(stock[off : off + size])
    shift = len(patched) - size

    img = bytearray(stock)
    img[off : off + size] = patched
    entries_offset = u32(img, 20)
    set_u32(img, entries_offset + index * 32, len(patched))
    for other in range(index + 1, len(entries)):
        base = entries_offset + other * 32
        set_u32(img, base + 4, u32(img, base + 4) + shift)
    set_u32(img, 4, u32(img, 4) + shift)  # dtbo header total_size
    out = bytes(img[: len(stock)])
    assert len(out) == len(stock), "image size must stay partition-sized"
    return out


def selftest(stock_path: str, v6_path: str) -> None:
    stock = Path(stock_path).read_bytes()
    v6 = Path(v6_path).read_bytes()

    # locate the author's patched entry in v6: the only one whose parsed
    # on-command property carries the post-120 stream (raw byte search hits
    # every entry, since the stream exists natively in the post-120 property)
    def has_stream(blob: bytes) -> bool:
        p = prop_for(blob, ON_CMD, timing=True)
        return POST_120_STREAM in bytes(p["value"])

    v6_entries = dtbo_entries(v6)
    v6_idx = [i for i, (sz, of) in enumerate(v6_entries) if has_stream(v6[of : of + sz])]
    assert len(v6_idx) == 1, f"expected one patched v6 entry, got {v6_idx}"
    v6_idx = v6_idx[0]
    v6_sz, v6_off = v6_entries[v6_idx]
    patched_ref = v6[v6_off : v6_off + v6_sz]

    # the author's chain reordered entries, so find our stock entry whose
    # patched result should equal his: try every entry, expect exactly one hit
    hits = []
    for i, (sz, of) in enumerate(dtbo_entries(stock)):
        try:
            if patch_entry(stock[of : of + sz]) == patched_ref:
                hits.append(i)
        except ValueError:
            continue
    print(f"author's patched entry: v6 index {v6_idx} ({v6_sz} bytes)")
    print(f"stock entries whose patched form matches it exactly: {hits}")
    if len(hits) != 1:
        raise SystemExit(f"SELFTEST FAILED: expected exactly one matching entry, got {hits}")
    print(f"SELFTEST PASSED: patch_entry(stock[{hits[0]}]) == author's patched blob, byte-for-byte")
    return


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    stock_path, index, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    stock = Path(stock_path).read_bytes()
    out = build(stock, index)
    Path(out_path).write_bytes(out)
    print(f"patched entry {index}: {stock_path} -> {out_path}")
    print(f"  stock sha256: {hashlib.sha256(stock).hexdigest()}")
    print(f"  built sha256: {hashlib.sha256(out).hexdigest()}")
    print("  (image not written anywhere else; flash manually after review)")


if __name__ == "__main__":
    main()
