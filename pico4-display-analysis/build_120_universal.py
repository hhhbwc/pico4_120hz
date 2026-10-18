#!/usr/bin/env python3
"""Build a 120 Hz DTBO that covers every PICO 4 unit, with PHY variants.

Two things this script does differently from the single-entry builders:

1.  It patches **every** dtbo entry that carries a complete LS026B3SA panel
    node, instead of one hard-coded index. Only four entries in the stock
    image do (kona standalone MTP, kona-iot MTP, kona MTP, kona MTP (WS));
    the other twelve carry a 70-property stub. Which one the bootloader
    picks differs between regions — the author's CN unit boots kona-iot MTP,
    global units boot kona MTP — but their panel blobs are byte-identical,
    so patching all four yields one image that works on either.

    The CN and INTL firmware images hold the same sixteen entries in
    different orders, which is why index-based targeting is fragile.

2.  It can rewrite the DSI PHY timing table, which the shipped v6 left at
    its 90 Hz calibration. v6 keeps the stock 14-byte table (computed for a
    993 MHz bit clock) while running the link at 1325 MHz, a 33% overclock.
    `--phy nop` drops the property so the kernel's v4.0 calculator derives
    values from the real clock; `--phy scale` multiplies each byte by the
    clock ratio to preserve absolute timings.

Usage:
    python build_120_universal.py STOCK.img OUT.img [--phy keep|nop|scale]
    python build_120_universal.py STOCK.img --list

Nothing is written to any device.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_120_init120_inplace import ON_CMD, POST_120_STREAM, patch_entry  # noqa: E402
from build_candidate_dtbo import (  # noqa: E402
    TARGET_NODE,
    dtbo_entries,
    parse_fdt_properties,
    set_u32,
    u32,
)

PHY_PROP = "qcom,mdss-dsi-panel-phy-timings"
FDT_NOP = 4

# bit clock at 90 Hz vs 120 Hz on this panel: 827 * 2225 * fps * 6
BASE_BITCLOCK = 827 * 2225 * 90 * 6
NEW_BITCLOCK = 827 * 2225 * 120 * 6


def complete_panel_entries(blob: bytes) -> list[int]:
    """Indices whose panel node is a patchable LS026B3SA one.

    Every entry in the stock image carries a
    qcom,mdss-dsi-post-120-nt57900-on-command property, so its mere presence
    proves nothing. Only four entries carry the full node (79 properties vs a
    70-property stub elsewhere) and only those satisfy patch_entry's
    preconditions, so "can it actually be patched" is the honest test.
    """
    out = []
    for i, (size, off) in enumerate(dtbo_entries(blob)):
        try:
            patch_entry(blob[off : off + size])
        except Exception:
            continue
        out.append(i)
    return out


def nop_property(buf: bytearray, prop: dict) -> None:
    # FDT_PROP header is token(4) + len(4) + nameoff(4), then the value
    start = int(prop["header_offset"])
    end = start + 12 + ((int(prop["value_length"]) + 3) & ~3)
    for off in range(start, end, 4):
        set_u32(buf, off, FDT_NOP)


def scale_property(buf: bytearray, prop: dict, ratio: float) -> None:
    voff = int(prop["value_offset"])
    for i in range(int(prop["value_length"])):
        old = buf[voff + i]
        if old == 0:
            continue
        new = round(old * ratio)
        if new < old:  # never shorten a timing parameter
            new = old
        if new > 0xFF:
            raise ValueError(f"PHY byte {i} ({old}) overflows after scaling")
        buf[voff + i] = new


def apply_phy(entry: bytes, mode: str) -> bytes:
    if mode == "keep":
        return entry
    buf = bytearray(entry)
    hits = [
        p for p in parse_fdt_properties(entry)
        if p["name"] == PHY_PROP and TARGET_NODE in str(p["path"])
    ]
    if len(hits) != 1:
        raise ValueError(f"{PHY_PROP}: expected exactly one match, got {len(hits)}")
    prop = hits[0]
    if mode == "nop":
        nop_property(buf, prop)
    elif mode == "scale":
        scale_property(buf, prop, NEW_BITCLOCK / BASE_BITCLOCK)
    else:
        raise SystemExit(f"unknown --phy mode: {mode}")
    out = bytes(buf)
    parse_fdt_properties(out)  # must stay a valid FDT
    return out


def rebuild(stock: bytes, patched: dict[int, bytes]) -> bytes:
    """Reassemble the image from patched and untouched entries in order."""
    entries = dtbo_entries(stock)
    header_size = u32(stock, 8)
    entries_offset = u32(stock, 20)
    page_size = u32(stock, 24)

    blobs: list[bytes] = []
    for i, (size, off) in enumerate(entries):
        blobs.append(patched.get(i, stock[off : off + size]))

    data_offset = entries_offset + len(entries) * 32
    img = bytearray(stock[:data_offset])
    offsets: list[int] = []
    cursor = data_offset
    for blob in blobs:
        offsets.append(cursor)
        img.extend(blob)
        cursor += len(blob)

    for i, blob in enumerate(blobs):
        base = entries_offset + i * 32
        set_u32(img, base, len(blob))
        set_u32(img, base + 4, offsets[i])

    # keep the image partition-sized; trailing padding is restored below
    total = len(img)
    if total < len(stock):
        img.extend(b"\x00" * (len(stock) - total))
    if page_size:
        rem = len(img) % page_size
        if rem:
            img.extend(b"\x00" * (page_size - rem))
    if len(img) > len(stock):
        raise ValueError(f"patched image exceeds partition size: {len(img)} > {len(stock)}")
    set_u32(img, 4, len(img))
    return bytes(img)


def build(stock: bytes, mode: str) -> tuple[bytes, list[int]]:
    targets = complete_panel_entries(stock)
    if not targets:
        raise SystemExit("no entry carries a complete LS026B3SA node")
    patched = {}
    for i in targets:
        size, off = dtbo_entries(stock)[i]
        entry = patch_entry(stock[off : off + size])
        patched[i] = apply_phy(entry, mode)
    return rebuild(stock, patched), targets


def verify(stock: bytes, out: bytes, targets: list[int]) -> None:
    assert len(out) == len(stock), "image must stay partition-sized"
    old = dtbo_entries(stock)
    new = dtbo_entries(out)
    assert len(old) == len(new), "entry count changed"
    for i, (sz, off) in enumerate(old):
        nsz, noff = new[i]
        a, b = stock[off : off + sz], out[noff : noff + nsz]
        if i in targets:
            hits = [
                p for p in parse_fdt_properties(b)
                if p["name"] == ON_CMD
                and TARGET_NODE in str(p["path"])
                and "timing@0" in str(p["path"])
            ]
            assert len(hits) == 1, f"entry {i}: {len(hits)} on-command matches"
            assert POST_120_STREAM in bytes(hits[0]["value"]), f"entry {i}: post-120 stream missing"
        else:
            assert a == b, f"entry {i} changed unexpectedly"


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[2] == "--list":
        blob = Path(sys.argv[1]).read_bytes()
        idx = complete_panel_entries(blob)
        print(f"patchable entries: {idx}")
        for i, (size, off) in enumerate(dtbo_entries(blob)):
            print(f"  [{i}] {size:>7} bytes {'<= patch' if i in idx else ''}")
        return 0
    if len(sys.argv) not in (3, 5):
        raise SystemExit(__doc__)
    stock_path, out_path = sys.argv[1], sys.argv[2]
    mode = "keep"
    if len(sys.argv) == 5:
        if sys.argv[3] != "--phy":
            raise SystemExit(__doc__)
        mode = sys.argv[4]

    stock = Path(stock_path).read_bytes()
    out, targets = build(stock, mode)
    verify(stock, out, targets)
    Path(out_path).write_bytes(out)
    print(f"stock : {hashlib.sha256(stock).hexdigest()}")
    print(f"built : {hashlib.sha256(out).hexdigest()}")
    print(f"mode  : phy={mode}, entries patched={targets}")
    print(f"size  : {len(out)}")
    print("(nothing written to any device; flash manually after review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
