#!/usr/bin/env python3
"""Build a PICO 4 120 Hz DTBO candidate with a real base-120 panel timing.

v3 ordering fix: libpxrhmdservice.so hardcodes the vendor SF config map
    72 Hz -> [1, 3], 90 Hz -> [0, 3], 120 Hz -> [2, 3]
so the DFPS list must be <90 72 120> (cfg0=90, cfg1=72, cfg2=120).
v2 used <120 90 72> and the 90/120 requests landed on swapped slots.

Root cause fixed versus the old candidate (dfps list only, base 90):
the mode-builder ignores dsi_display_get_dfps_timing() errors, so the
120 entry produced a phantom mode (90 Hz timing labeled 120 Hz) after
"Invalid new_hfp calcluated-499". Making 120 the base timing gives a
real 120 Hz mode; 90/72 become DFPS VFP modes with valid positive math.

Derived clock (verified against live dsi-ctrl-0 state_info):
    pixel_clk = h_total_dsc * v_total * fps
    h_total_dsc = 2160/3 + 54 + 33 + 20 = 827, v_total = 2225
    90 Hz  -> 165,606,750 Hz pixel (matches live state_info exactly)
    120 Hz -> 220,809,000 Hz pixel -> bit ~1.325 GHz/lane, byte ~165.6 MHz
    DFPS porch math conserves v_total * fps, so every mode keeps the base clock.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

TARGET_INDEX = 5
NODE_MARKER = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
DFPS = "qcom,dsi-supported-dfps-list"
MAX_FPS = "qcom,mdss-dsi-max-refresh-rate"
MIN_FPS = "qcom,mdss-dsi-min-refresh-rate"
FRAME_RATE = "qcom,mdss-dsi-panel-framerate"


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def parse_props(blob: bytes) -> dict[str, dict[str, object]]:
    from build_candidate_dtbo import parse_fdt_properties

    props = {
        prop["name"]: prop
        for prop in parse_fdt_properties(blob)
        if NODE_MARKER in str(prop["path"])
    }
    for name in (DFPS, MAX_FPS, MIN_FPS, FRAME_RATE):
        if name not in props:
            raise ValueError(f"missing property {name}")
    return props


def cells(value: bytes) -> list[int]:
    return list(struct.unpack(">" + "I" * (len(value) // 4), value))


def build(baseline: bytes) -> tuple[bytes, dict[str, object]]:
    from build_candidate_dtbo import dtbo_entries

    entries = dtbo_entries(baseline)
    size, offset = entries[TARGET_INDEX]
    target = bytearray(baseline[offset : offset + size])
    props = parse_props(target)
    if cells(bytes(props[DFPS]["value"])) != [90, 72]:
        raise ValueError(f"baseline dfps mismatch: {cells(bytes(props[DFPS]['value']))}")
    if cells(bytes(props[MAX_FPS]["value"])) != [90]:
        raise ValueError("baseline max fps mismatch")
    if cells(bytes(props[FRAME_RATE]["value"])) != [90]:
        raise ValueError("baseline panel framerate mismatch")

    # grow dfps <90 72> -> <90 72 120> (insert one cell, shift the FDT tail)
    # order matches the hardcoded vendor map in libpxrhmdservice.so
    insert_at = int(props[DFPS]["value_offset"]) + int(props[DFPS]["value_length"])
    target[insert_at:insert_at] = b"\0\0\0\0"
    set_u32(target, int(props[DFPS]["header_offset"]) + 4, 12)
    set_u32(target, int(props[DFPS]["value_offset"]), 90)
    set_u32(target, int(props[DFPS]["value_offset"]) + 4, 72)
    set_u32(target, int(props[DFPS]["value_offset"]) + 8, 120)
    set_u32(target, 4, len(target))          # FDT totalsize
    set_u32(target, 12, u32(target, 12) + 4)  # off_dt_strings

    for name, value in ((MAX_FPS, 120), (FRAME_RATE, 120)):
        props = parse_props(target)
        set_u32(target, int(props[name]["value_offset"]), value)

    updated = bytearray(baseline)
    updated[offset : offset + size] = target
    entries_offset = u32(updated, 20)
    set_u32(updated, entries_offset + TARGET_INDEX * 32, len(target))
    for index in range(TARGET_INDEX + 1, len(entries)):
        base = entries_offset + index * 32
        set_u32(updated, base + 4, u32(updated, base + 4) + 4)
    set_u32(updated, 4, u32(updated, 4) + 4)
    updated = updated[: len(baseline)]

    v_total = 2160 + 57 + 4 + 4
    audit = {
        "target_index": TARGET_INDEX,
        "target_offset": hex(offset),
        "baseline_dfps": [90, 72],
        "candidate_dfps": [90, 72, 120],
        "baseline_max_fps": [90],
        "candidate_max_fps": [120],
        "baseline_frame_rate": [90],
        "candidate_frame_rate": [120],
        "dfps_90_vfp": 57 + (v_total * 30) // 90,
        "dfps_72_vfp": 57 + (v_total * 48) // 72,
        "clock_base120_pixel_hz": 827 * 2225 * 120,
        "clock_base120_bit_hz_per_lane": 827 * 2225 * 120 * 6,
        "clock_90_live_pixel_hz": 827 * 2225 * 90,
    }
    return bytes(updated), audit


def validate(baseline: bytes, candidate: bytes, audit: dict[str, object]) -> dict[str, object]:
    from build_candidate_dtbo import dtbo_entries

    old_entries = dtbo_entries(baseline)
    new_entries = dtbo_entries(candidate)
    if len(old_entries) != len(new_entries):
        raise ValueError("entry count changed")
    for index, ((old_size, old_off), (new_size, new_off)) in enumerate(zip(old_entries, new_entries)):
        old_blob = baseline[old_off : old_off + old_size]
        new_blob = candidate[new_off : new_off + new_size]
        if index == TARGET_INDEX:
            props = parse_props(new_blob)
            if cells(bytes(props[DFPS]["value"])) != [90, 72, 120]:
                raise ValueError("candidate dfps validation failed")
            if cells(bytes(props[MAX_FPS]["value"])) != [120]:
                raise ValueError("candidate max fps validation failed")
            if cells(bytes(props[FRAME_RATE]["value"])) != [120]:
                raise ValueError("candidate frame rate validation failed")
            if cells(bytes(props[MIN_FPS]["value"])) != [72]:
                raise ValueError("candidate min fps validation failed")
        elif old_blob != new_blob:
            raise ValueError(f"non-target entry {index} changed")
    if len(candidate) != len(baseline):
        raise ValueError("candidate must stay partition-sized")
    changed = [i for i, (a, b) in enumerate(zip(baseline, candidate)) if a != b]
    return {
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "baseline_size": len(baseline),
        "candidate_size": len(candidate),
        "container_bytes_changed": len(changed),
        "first_changed_offset": hex(changed[0]),
        "last_changed_offset": hex(changed[-1]),
    }


def main() -> None:
    directory = Path(__file__).resolve().parent
    baseline = (directory / "dtbo-current.img").read_bytes()
    candidate, audit = build(baseline)
    validation = validate(baseline, candidate, audit)
    out = directory / "dtbo-120hz-v3-order90-72-120.img"
    out.write_bytes(candidate)
    report = [
        "PICO 4 120 Hz base-timing DTBO candidate audit (v3)",
        "",
        "Design: panel-framerate 90 -> 120 (real base timing),",
        "        dfps <90 72> -> <90 72 120>, max-refresh-rate 90 -> 120.",
        "        Order matches the hardcoded vendor map in libpxrhmdservice.so:",
        "        72 Hz -> cfg1, 90 Hz -> cfg0, 120 Hz -> cfg2.",
        "        90/72 become DFPS VFP modes at the 120 Hz base clock.",
        "        Old-candidate phantom-120 (negative VFP) is impossible here.",
        "",
        *[f"{k}: {v}" for k, v in audit.items()],
        "",
        *[f"{k}: {v}" for k, v in validation.items()],
        "",
        "This image has NOT been written to any partition by this script.",
    ]
    (directory / "dtbo-120hz-base120-audit.txt").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print("\n".join(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
