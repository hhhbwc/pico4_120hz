#!/usr/bin/env python3
"""Build and audit a PICO 4 120 Hz DFPS DTBO candidate from a known baseline."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

FDT_MAGIC = 0xD00DFEED
DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
TARGET_NODE = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
DFPS_PROPERTY = "qcom,dsi-supported-dfps-list"
MAX_FPS_PROPERTY = "qcom,mdss-dsi-max-refresh-rate"


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def align4(value: int) -> int:
    return (value + 3) & ~3


def dtbo_entries(image: bytes) -> list[tuple[int, int]]:
    if u32(image, 0) != DT_TABLE_MAGIC:
        raise ValueError("Not an Android DTBO image")
    entry_size = u32(image, 12)
    count = u32(image, 16)
    entries_offset = u32(image, 20)
    if entry_size != 32:
        raise ValueError(f"Unexpected DTBO entry size: {entry_size}")
    return [
        (u32(image, entries_offset + index * entry_size), u32(image, entries_offset + index * entry_size + 4))
        for index in range(count)
    ]


def parse_fdt_properties(blob: bytes) -> list[dict[str, object]]:
    if u32(blob, 0) != FDT_MAGIC:
        raise ValueError("Not an FDT blob")
    total = u32(blob, 4)
    structure_offset = u32(blob, 8)
    strings_offset = u32(blob, 12)
    strings_size = u32(blob, 32)
    structure_size = u32(blob, 36)
    if total != len(blob):
        raise ValueError(f"FDT length mismatch: header={total}, blob={len(blob)}")
    strings = blob[strings_offset : strings_offset + strings_size]
    position = structure_offset
    structure_end = structure_offset + structure_size
    stack: list[str] = []
    properties: list[dict[str, object]] = []
    while position < structure_end:
        token = u32(blob, position)
        position += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", position)
            stack.append(blob[position:end].decode("utf-8", "replace"))
            position = align4(end + 1)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            header_offset = position - 4
            value_length = u32(blob, position)
            name_offset = u32(blob, position + 4)
            value_offset = position + 8
            position = align4(value_offset + value_length)
            name_end = strings.index(b"\0", name_offset)
            name = strings[name_offset:name_end].decode("utf-8", "replace")
            properties.append(
                {
                    "path": "/" + "/".join(item for item in stack if item),
                    "name": name,
                    "header_offset": header_offset,
                    "value_offset": value_offset,
                    "value_length": value_length,
                    "value": blob[value_offset : value_offset + value_length],
                }
            )
        elif token == FDT_END:
            break
        elif token != FDT_NOP:
            raise ValueError(f"Unexpected FDT token {token} at {position - 4:#x}")
    return properties


def target_properties(blob: bytes) -> dict[str, dict[str, object]]:
    selected = {
        prop["name"]: prop
        for prop in parse_fdt_properties(blob)
        if TARGET_NODE in str(prop["path"])
    }
    if DFPS_PROPERTY not in selected or MAX_FPS_PROPERTY not in selected:
        raise ValueError("Target Sharp panel DFPS properties were not found")
    return selected


def decode_cells(value: bytes) -> list[int]:
    if len(value) % 4:
        raise ValueError("Property is not made of 32-bit cells")
    return list(struct.unpack(">" + "I" * (len(value) // 4), value))


def build_candidate(baseline: bytes) -> tuple[bytes, dict[str, object]]:
    entries = dtbo_entries(baseline)
    target_index = 5
    target_size, target_offset = entries[target_index]
    target = bytearray(baseline[target_offset : target_offset + target_size])
    properties = target_properties(target)
    dfps = properties[DFPS_PROPERTY]
    maximum = properties[MAX_FPS_PROPERTY]
    if decode_cells(bytes(dfps["value"])) != [90, 72]:
        raise ValueError(f"Unexpected baseline DFPS list: {decode_cells(bytes(dfps['value']))}")
    if decode_cells(bytes(maximum["value"])) != [90]:
        raise ValueError(f"Unexpected baseline maximum refresh rate: {decode_cells(bytes(maximum['value']))}")

    # Expand only the selected FDT property from two cells to three. The insertion
    # shifts the remainder of this FDT; header and container metadata are adjusted.
    insertion_at = int(dfps["value_offset"]) + int(dfps["value_length"])
    target[insertion_at:insertion_at] = b"\0\0\0\0"
    set_u32(target, int(dfps["header_offset"]) + 4, 12)
    target[int(dfps["value_offset"]) : int(dfps["value_offset"]) + 12] = struct.pack(">3I", 120, 90, 72)
    set_u32(target, 4, len(target))
    set_u32(target, 12, u32(target, 12) + 4)
    updated_properties = target_properties(target)
    updated_maximum = updated_properties[MAX_FPS_PROPERTY]
    set_u32(target, int(updated_maximum["value_offset"]), 120)

    updated = bytearray(baseline)
    updated[target_offset : target_offset + target_size] = target
    entries_offset = u32(updated, 20)
    set_u32(updated, entries_offset + target_index * 32, len(target))
    for index in range(target_index + 1, len(entries)):
        size_offset = entries_offset + index * 32
        set_u32(updated, size_offset + 4, u32(updated, size_offset + 4) + 4)
    set_u32(updated, 4, u32(updated, 4) + 4)
    updated = updated[: len(baseline)]

    audit = {
        "target_index": target_index,
        "target_offset": target_offset,
        "baseline_target_size": target_size,
        "candidate_target_size": len(target),
        "baseline_dfps": [90, 72],
        "candidate_dfps": [120, 90, 72],
        "baseline_max_fps": [90],
        "candidate_max_fps": [120],
    }
    return bytes(updated), audit


def validate(baseline: bytes, candidate: bytes, audit: dict[str, object]) -> dict[str, object]:
    old_entries = dtbo_entries(baseline)
    new_entries = dtbo_entries(candidate)
    if len(old_entries) != len(new_entries):
        raise ValueError("DTBO entry count changed")
    target_index = int(audit["target_index"])
    for index, ((old_size, old_offset), (new_size, new_offset)) in enumerate(zip(old_entries, new_entries)):
        old_blob = baseline[old_offset : old_offset + old_size]
        new_blob = candidate[new_offset : new_offset + new_size]
        if index == target_index:
            props = target_properties(new_blob)
            if decode_cells(bytes(props[DFPS_PROPERTY]["value"])) != [120, 90, 72]:
                raise ValueError("Candidate DFPS list failed validation")
            if decode_cells(bytes(props[MAX_FPS_PROPERTY]["value"])) != [120]:
                raise ValueError("Candidate maximum refresh rate failed validation")
        elif old_blob != new_blob:
            raise ValueError(f"Non-target DTBO entry {index} changed")
        parse_fdt_properties(new_blob)
    if len(candidate) != len(baseline):
        raise ValueError("Candidate must remain exactly partition-sized")
    changed = [index for index, (left, right) in enumerate(zip(baseline, candidate)) if left != right]
    return {
        "baseline_size": len(baseline),
        "candidate_size": len(candidate),
        "container_bytes_changed": len(changed),
        "first_changed_offset": hex(changed[0]),
        "last_changed_offset": hex(changed[-1]),
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
    }


def main() -> None:
    directory = Path(__file__).resolve().parent
    baseline_path = directory / "dtbo-current.img"
    candidate_path = directory / "dtbo-120hz-candidate.img"
    report_path = directory / "dtbo-120hz-candidate-audit.txt"
    baseline = baseline_path.read_bytes()
    candidate, build_audit = build_candidate(baseline)
    validation = validate(baseline, candidate, build_audit)
    candidate_path.write_bytes(candidate)
    report = [
        "PICO 4 Sharp LS026B3SA 120 Hz DTBO candidate audit",
        "",
        "Only target FDT properties:",
        "  qcom,dsi-supported-dfps-list: <90 72> -> <120 90 72>",
        "  qcom,mdss-dsi-max-refresh-rate: <90> -> <120>",
        "",
        *[f"{key}: {value}" for key, value in build_audit.items()],
        *[f"{key}: {value}" for key, value in validation.items()],
        "",
        "This file has not been written to any device partition.",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
