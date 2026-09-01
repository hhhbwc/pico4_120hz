#!/usr/bin/env python3
"""Rebase the PICO 4 Sharp panel node onto a real 120 Hz base timing.

The panel uses ``dfps_immediate_porch_mode_vfp``: the pixel clock is programmed
once from the default timing and every other rate is produced by *lengthening*
the vertical front porch. That direction is one-way, so a 90 Hz base timing can
never yield 120 Hz -- the driver would need a negative front porch, which is the
``Invalid new_hfp calcluated-499`` message seen in dmesg.

This script therefore moves the default timing to 120 Hz so the lower rates can
be derived from it, mirroring how PICO's own ``*_493_120_new_video`` nodes are
built. Three edits are applied, all strictly in place so the FDT keeps its exact
size:

    qcom,mdss-dsi-panel-framerate    90 -> 120
    qcom,mdss-dsi-v-front-porch      57 -> 14
    qcom,mdss-dsi-panel-phy-timings  replaced with FDT_NOP words

The PHY timings are dropped rather than recomputed by hand: the DT values belong
to the old 993 MHz bit clock and would be wrong at the new one. With the
property gone the driver falls back to ``dsi_phy_hw_calculate_timing_params``,
which this kernel exports.

Input is the DFPS candidate produced by build_candidate_dtbo.py, which already
carries ``qcom,dsi-supported-dfps-list = <120 90 72>`` and
``qcom,mdss-dsi-max-refresh-rate = <120>``.
"""

from __future__ import annotations

import hashlib
import struct
import sys

DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

TARGET_NODE = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
TARGET_INDEX = 5

BASELINE_FRAMERATE = 90
CANDIDATE_FRAMERATE = 120
BASELINE_VFP = 57
CANDIDATE_VFP = 14

# Confirmed against DSI_VIDEO_MODE_TOTAL = 0x0adc033a on the running device:
# htotal - 1 = 0x033a, so the compressed horizontal total is 827.
COMPRESSED_HTOTAL = 827
V_ACTIVE = 2160
V_BACK_PORCH = 4
V_PULSE_WIDTH = 4


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def align4(value: int) -> int:
    return (value + 3) & ~3


def dtbo_entries(image: bytes) -> list[tuple[int, int]]:
    if u32(image, 0) != DT_TABLE_MAGIC:
        raise ValueError("Not an Android DTBO image")
    if u32(image, 12) != 32:
        raise ValueError("Unexpected DTBO entry size")
    count = u32(image, 16)
    base = u32(image, 20)
    return [(u32(image, base + i * 32), u32(image, base + i * 32 + 4)) for i in range(count)]


def parse_fdt_properties(blob: bytes) -> list[dict[str, object]]:
    if u32(blob, 0) != FDT_MAGIC:
        raise ValueError("Not an FDT blob")
    strings_offset = u32(blob, 12)
    strings_size = u32(blob, 32)
    strings = blob[strings_offset : strings_offset + strings_size]
    position = u32(blob, 8)
    stack: list[str] = []
    found: list[dict[str, object]] = []
    while True:
        token = u32(blob, position)
        position += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", position)
            stack.append(blob[position:end].decode("utf-8", "replace"))
            position = align4(end + 1)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            header = position - 4
            length = u32(blob, position)
            name_offset = u32(blob, position + 4)
            value_offset = position + 8
            position = align4(value_offset + length)
            name_end = strings.index(b"\0", name_offset)
            found.append(
                {
                    "path": "/" + "/".join(item for item in stack if item),
                    "name": strings[name_offset:name_end].decode("utf-8", "replace"),
                    "header_offset": header,
                    "value_offset": value_offset,
                    "value_length": length,
                    "region_end": position,
                    "value": blob[value_offset : value_offset + length],
                }
            )
        elif token == FDT_END:
            return found
        elif token != FDT_NOP:
            raise ValueError(f"Unexpected FDT token {token} at {position - 4:#x}")


def node_property(properties: list[dict[str, object]], name: str) -> dict[str, object]:
    matches = [
        prop
        for prop in properties
        if prop["name"] == name and TARGET_NODE in str(prop["path"])
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} in the target node, found {len(matches)}")
    return matches[0]


def derive(fps: int, pixel_clock: int) -> tuple[int, int]:
    """Return the vertical total and front porch the driver will derive."""
    v_total = pixel_clock // (COMPRESSED_HTOTAL * fps)
    v_front_porch = CANDIDATE_VFP + (v_total - candidate_v_total())
    return v_total, v_front_porch


def candidate_v_total() -> int:
    return V_ACTIVE + V_BACK_PORCH + CANDIDATE_VFP + V_PULSE_WIDTH


def build(baseline: bytes) -> tuple[bytes, dict[str, object]]:
    entries = dtbo_entries(baseline)
    size, offset = entries[TARGET_INDEX]
    fdt = bytearray(baseline[offset : offset + size])
    properties = parse_fdt_properties(fdt)

    framerate = node_property(properties, "qcom,mdss-dsi-panel-framerate")
    front_porch = node_property(properties, "qcom,mdss-dsi-v-front-porch")
    phy_timings = node_property(properties, "qcom,mdss-dsi-panel-phy-timings")
    dfps = node_property(properties, "qcom,dsi-supported-dfps-list")
    maximum = node_property(properties, "qcom,mdss-dsi-max-refresh-rate")

    if u32(bytes(framerate["value"]), 0) != BASELINE_FRAMERATE:
        raise ValueError("Unexpected baseline panel framerate")
    if u32(bytes(front_porch["value"]), 0) != BASELINE_VFP:
        raise ValueError("Unexpected baseline vertical front porch")
    if list(struct.unpack(">3I", bytes(dfps["value"]))) != [120, 90, 72]:
        raise ValueError("Input must already carry the <120 90 72> DFPS list")
    if u32(bytes(maximum["value"]), 0) != 120:
        raise ValueError("Input must already carry max-refresh-rate = 120")

    set_u32(fdt, int(framerate["value_offset"]), CANDIDATE_FRAMERATE)
    set_u32(fdt, int(front_porch["value_offset"]), CANDIDATE_VFP)

    start = int(phy_timings["header_offset"])
    end = int(phy_timings["region_end"])
    if (end - start) % 4:
        raise ValueError("PHY timing region is not word aligned")
    for position in range(start, end, 4):
        set_u32(fdt, position, FDT_NOP)

    candidate = bytearray(baseline)
    candidate[offset : offset + size] = fdt
    if len(candidate) != len(baseline):
        raise ValueError("Candidate must remain exactly partition-sized")

    verify = parse_fdt_properties(bytes(fdt))
    if any(
        prop["name"] == "qcom,mdss-dsi-panel-phy-timings" and TARGET_NODE in str(prop["path"])
        for prop in verify
    ):
        raise ValueError("PHY timings are still present after patching")
    if u32(bytes(node_property(verify, "qcom,mdss-dsi-panel-framerate")["value"]), 0) != CANDIDATE_FRAMERATE:
        raise ValueError("Framerate patch did not apply")
    if u32(bytes(node_property(verify, "qcom,mdss-dsi-v-front-porch")["value"]), 0) != CANDIDATE_VFP:
        raise ValueError("Front porch patch did not apply")

    v_total = candidate_v_total()
    pixel_clock = COMPRESSED_HTOTAL * v_total * CANDIDATE_FRAMERATE
    audit = {
        "target_index": TARGET_INDEX,
        "target_offset": offset,
        "target_size": size,
        "framerate": f"{BASELINE_FRAMERATE} -> {CANDIDATE_FRAMERATE}",
        "v_front_porch": f"{BASELINE_VFP} -> {CANDIDATE_VFP}",
        "phy_timings": f"{end - start} bytes replaced with FDT_NOP",
        "compressed_htotal": COMPRESSED_HTOTAL,
        "v_total_120": v_total,
        "pixel_clock_hz": pixel_clock,
        "derived": {fps: derive(fps, pixel_clock) for fps in (90, 72)},
        "bytes_changed": sum(1 for a, b in zip(baseline, bytes(candidate)) if a != b),
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(bytes(candidate)).hexdigest(),
    }
    return bytes(candidate), audit


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <input-dtbo> <output-dtbo>")
    baseline = open(sys.argv[1], "rb").read()
    candidate, audit = build(baseline)
    open(sys.argv[2], "wb").write(candidate)
    print("PICO 4 Sharp LS026B3SA 120 Hz base-timing candidate")
    for key, value in audit.items():
        print(f"  {key}: {value}")
    current = 165_591_864
    print(f"  pixel clock change: {audit['pixel_clock_hz'] / current:.4f}x of the measured {current} Hz")


if __name__ == "__main__":
    main()
