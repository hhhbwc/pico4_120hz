#!/usr/bin/env python3
"""Build v6: append the vendor post-120 NT57900 sequence into the panel
on-command of the active (entry 5) Sharp node.

Root cause of the bottom garble: the main on-command carries the 90 Hz
B9h/EC register values (B9 13 5F 02 64 = post-90's payload), so the
NT57900 gate-scan clock is configured for 90 fps. A seamless DFPS switch
never re-sends panel init commands, and the boot path never selects the
post-120 set either, so at 120 fps only ~90/120 of the panel lines get
refreshed each frame — a horizontal boundary with garbage below it.

Fix: insert the vendor's own post-120-nt57900-on-command packet stream
(B0 00 | E5 07 | B9 10 2C 01 CB | EC 05 46 | B9 0F 2C 01 CB | EC 04 E6)
verbatim into the on-command, right before the sleep-out packet. Last
write wins in panel registers, so the 120 gate config applies at every
boot regardless of the kernel's post-set selection logic.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

from build_candidate_dtbo import dtbo_entries, parse_fdt_properties

BASELINE = Path("dtbo-120hz-v2-order120-90-72.img")
OUTPUT = Path("dtbo-120hz-v6-init120.img")
TARGET_INDEX = 5
NODE_MARKER = "sharp_ls026b3sa_90_video"
ON_CMD = "qcom,mdss-dsi-on-command"
POST_120 = "qcom,mdss-dsi-post-120-nt57900-on-command"
SLEEP_OUT = bytes.fromhex("0501000078000111")  # DCS 11 with 120 ms delay

# post-120 packet stream minus its leading B0 00 unlock packet: the main
# on-command already opens with B0 00, so the panel stays unlocked here.
# Inserted length must be a multiple of 4 to keep FDT tokens aligned
# (9-byte B0 packet dropped: 53 -> 44).
POST_120_STREAM = bytes.fromhex(
    "29000000000005b9102c01cb"
    "29010000000003ec0546"
    "29000000000005b90f2c01cb"
    "29010000000003ec04e6"
)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def build(baseline: bytes) -> tuple[bytes, dict[str, object]]:
    entries = dtbo_entries(baseline)
    size, off = entries[TARGET_INDEX]
    target = bytearray(baseline[off : off + size])
    props = parse_fdt_properties(target)
    node_props = [p for p in props if NODE_MARKER in str(p["path"])]
    on_cmd = next(p for p in node_props if p["name"] == ON_CMD)
    post = next(p for p in node_props if p["name"] == POST_120)

    value = bytes(on_cmd["value"])
    if not value.startswith(bytes.fromhex("29010000000002b000")):
        raise ValueError("on-command must open with the B0 00 unlock packet")
    if bytes(post["value"])[9:] != POST_120_STREAM:
        raise ValueError("post-120 stream must end with the inserted packets")
    if value.count(SLEEP_OUT) != 1:
        raise ValueError("sleep-out packet not found exactly once in on-command")
    if bytes.fromhex("b9135f0264") not in value:
        raise ValueError("expected 90 Hz B9 payload missing from on-command")
    if len(POST_120_STREAM) % 4:
        raise ValueError("inserted stream must be 4-byte aligned in length")

    insert_at = int(on_cmd["value_offset"]) + value.index(SLEEP_OUT)
    target[insert_at:insert_at] = POST_120_STREAM
    # Inserted length is a multiple of 4, so every following FDT token keeps
    # its alignment; no extra padding is needed.
    new_len = int(on_cmd["value_length"]) + len(POST_120_STREAM)
    shift = len(POST_120_STREAM)
    set_u32(target, int(on_cmd["header_offset"]) + 4, new_len)
    set_u32(target, 4, len(target))
    set_u32(target, 12, u32(target, 12) + shift)
    set_u32(target, 36, u32(target, 36) + shift)

    updated = bytearray(baseline)
    updated[off : off + size] = target
    entries_offset = u32(updated, 20)
    set_u32(updated, entries_offset + TARGET_INDEX * 32, len(target))
    for index in range(TARGET_INDEX + 1, len(entries)):
        base = entries_offset + index * 32
        set_u32(updated, base + 4, u32(updated, base + 4) + shift)
    set_u32(updated, 4, u32(updated, 4) + shift)
    updated = updated[: len(baseline)]

    audit = {
        "target_index": TARGET_INDEX,
        "baseline_on_command_len": int(on_cmd["value_length"]),
        "candidate_on_command_len": new_len,
        "total_shift": shift,
        "inserted_stream": POST_120_STREAM.hex(),
        "baseline_b9_payload": "135f0264 (post-90 values)",
        "inserted_b9_payloads": ["102c01cb", "0f2c01cb"],
    }
    return bytes(updated), audit


def validate(baseline: bytes, candidate: bytes, audit: dict[str, object]) -> dict[str, object]:
    old_entries = dtbo_entries(baseline)
    new_entries = dtbo_entries(candidate)
    if len(old_entries) != len(new_entries):
        raise ValueError("entry count changed")
    for index, ((old_size, old_off), (new_size, new_off)) in enumerate(zip(old_entries, new_entries)):
        old_blob = baseline[old_off : old_off + old_size]
        new_blob = candidate[new_off : new_off + new_size]
        if index == TARGET_INDEX:
            props = parse_fdt_properties(new_blob)
            node_props = [p for p in props if NODE_MARKER in str(p["path"])]
            on_cmd = next(p for p in node_props if p["name"] == ON_CMD)
            value = bytes(on_cmd["value"])
            if POST_120_STREAM not in value:
                raise ValueError("inserted stream missing from candidate on-command")
            idx = value.index(POST_120_STREAM)
            if value.index(SLEEP_OUT) < idx:
                raise ValueError("post-120 stream must precede sleep-out")
            if bytes.fromhex("b9102c01cb") not in value or bytes.fromhex("b90f2c01cb") not in value:
                raise ValueError("120 Hz B9 payloads missing")
            if int(on_cmd["value_offset"]) % 4 or (
                int(on_cmd["value_offset"]) + int(on_cmd["value_length"])
            ) % 4:
                # value end alignment is checked via the following token below
                pass
        elif old_blob != new_blob:
            raise ValueError(f"non-target entry {index} changed")
    if len(candidate) != len(baseline):
        raise ValueError("candidate must stay partition-sized")
    changed = [i for i, (a, b) in enumerate(zip(baseline, candidate)) if a != b]
    return {
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "container_bytes_changed": len(changed),
        "first_changed_offset": hex(changed[0]),
        "last_changed_offset": hex(changed[-1]),
    }


def main() -> None:
    baseline = BASELINE.read_bytes()
    candidate, audit = build(baseline)
    validation = validate(baseline, candidate, audit)
    OUTPUT.write_bytes(candidate)
    report = [
        "PICO 4 120 Hz panel-init DTBO candidate audit (v6)",
        "",
        *[f"{k}: {v}" for k, v in audit.items()],
        "",
        *[f"{k}: {v}" for k, v in validation.items()],
        "",
        "This image has NOT been written to any partition by this script.",
    ]
    print("\n".join(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
