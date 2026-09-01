#!/usr/bin/env python3
"""Build a structural probe DTBO with an explicit LS026B3SA panel clock rate.

This is intentionally not a complete 120 Hz timing patch. It only verifies
that PICO's private DSI driver accepts qcom,mdss-dsi-panel-clockrate on the
active Sharp LS026B3SA node. No image produced by this script is flashed
implicitly.
"""

from __future__ import annotations

import hashlib
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_END = 9
DT_TABLE_MAGIC = 0xD7B7AB1E
TARGET_INDEX = 5
TARGET_NODE = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
CLOCK_PROPERTY = b"qcom,mdss-dsi-panel-clockrate"
DEFAULT_BIT_CLOCK_HZ = 1_291_509_360


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def put_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def align4(value: int) -> int:
    return (value + 3) & ~3


def entries(image: bytes) -> list[tuple[int, int]]:
    if u32(image, 0) != DT_TABLE_MAGIC or u32(image, 12) != 32:
        raise ValueError("unexpected DTBO container")
    count, base = u32(image, 16), u32(image, 20)
    return [(u32(image, base + i * 32), u32(image, base + i * 32 + 4)) for i in range(count)]


def parse_nodes(blob: bytes) -> tuple[int, int, bytes, dict[str, int]]:
    if u32(blob, 0) != FDT_MAGIC:
        raise ValueError("not an FDT")
    struct_off, strings_off, strings_size = u32(blob, 8), u32(blob, 12), u32(blob, 32)
    strings = blob[strings_off : strings_off + strings_size]
    position = struct_off
    stack: list[str] = []
    node_ends: dict[str, int] = {}
    while True:
        token = u32(blob, position)
        position += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", position)
            stack.append(blob[position:end].decode("utf-8", "replace"))
            position = align4(end + 1)
        elif token == FDT_END_NODE:
            path = "/" + "/".join(item for item in stack if item)
            node_ends[path] = position - 4
            stack.pop()
        elif token == FDT_PROP:
            length = u32(blob, position)
            position = align4(position + 8 + length)
        elif token == FDT_END:
            return struct_off, strings_off, strings, node_ends
        else:
            raise ValueError(f"unexpected token {token} at {position - 4:#x}")


def build(image: bytes, bit_clock: int) -> tuple[bytes, dict[str, object]]:
    all_entries = entries(image)
    old_size, offset = all_entries[TARGET_INDEX]
    target = bytearray(image[offset : offset + old_size])
    struct_off, strings_off, strings, node_ends = parse_nodes(target)
    name_off = strings.find(CLOCK_PROPERTY)
    if name_off < 0:
        raise ValueError("clockrate property name is not in the FDT strings block")
    target_path = next(path for path in node_ends if TARGET_NODE in path and "/timing@" not in path)
    insert_at = node_ends[target_path]

    # FDT_PROP token, length, name offset, then a big-endian u32 value.
    prop = struct.pack(">III I", FDT_PROP, 4, name_off, bit_clock)
    target[insert_at:insert_at] = prop
    put_u32(target, 4, len(target))
    put_u32(target, 12, strings_off + len(prop))
    put_u32(target, 36, u32(target, 36) + len(prop))

    # Ensure the new property can be rediscovered using the same parser.
    _, _, new_strings, _ = parse_nodes(bytes(target))
    if new_strings.find(CLOCK_PROPERTY) != name_off:
        raise ValueError("FDT strings offset changed unexpectedly")

    candidate = bytearray(image)
    candidate[offset : offset + old_size] = target
    entries_base = u32(candidate, 20)
    put_u32(candidate, entries_base + TARGET_INDEX * 32, len(target))
    for index in range(TARGET_INDEX + 1, len(all_entries)):
        field = entries_base + index * 32 + 4
        put_u32(candidate, field, u32(candidate, field) + len(prop))
    put_u32(candidate, 4, u32(candidate, 4) + len(prop))
    candidate = candidate[: len(image)]
    if len(candidate) != len(image):
        raise ValueError("candidate must remain partition-sized")
    return bytes(candidate), {
        "target_index": TARGET_INDEX,
        "property": CLOCK_PROPERTY.decode(),
        "bit_clock_hz": bit_clock,
        "target_size": f"{old_size} -> {len(target)}",
        "bytes_inserted": len(prop),
        "baseline_sha256": hashlib.sha256(image).hexdigest(),
        "candidate_sha256": hashlib.sha256(bytes(candidate)).hexdigest(),
    }


def main() -> None:
    if len(sys.argv) not in (3, 4):
        raise SystemExit(f"usage: {sys.argv[0]} <input-dtbo> <output-dtbo> [bit-clock-hz]")
    bit_clock = int(sys.argv[3]) if len(sys.argv) == 4 else DEFAULT_BIT_CLOCK_HZ
    image = open(sys.argv[1], "rb").read()
    candidate, audit = build(image, bit_clock)
    open(sys.argv[2], "wb").write(candidate)
    for key, value in audit.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
