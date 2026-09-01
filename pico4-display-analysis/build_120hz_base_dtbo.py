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
DFPS_PROPERTY = "qcom,dsi-supported-dfps-list"
MAX_FPS_PROPERTY = "qcom,mdss-dsi-max-refresh-rate"

BASELINE_FRAMERATE = 90
BASELINE_VFP = 57

# PHY timings validated by the vendor elsewhere in this same DTBO. Removing the
# property and hoping the driver would recompute produced a black screen with a
# corrupted band at the bottom, so an explicit table is used instead. Each entry
# is (bit clock in Hz, 14 timing bytes) and the closest one at or above the
# target clock is picked.
PHY_TIMING_REFERENCES = [
    (1_015_600_000, "00 22 09 09 19 17 09 09 09 02 04 00 1d 0e"),  # r66451_fhd_plus_144hz
    (1_088_000_000, "00 24 0a 0a 1a 24 0a 0a 09 02 04 00 1e 0f"),  # rdp370f_fsc_mode_fhd
    (1_146_500_000, "00 25 0a 0a 1b 25 0a 0a 0a 02 04 00 1f 0f"),  # sharp/jdi_493_120
    (1_256_200_000, "00 2a 0a 0b 1b 26 0b 0b 0a 02 04 00 22 10"),  # innolux_nt57900_90
    # No vendor table exists above 1256 MHz, and 120 Hz needs 1291.5 MHz. These
    # counts are the innolux_nt57900 table scaled by the clock ratio 1.0281 and
    # rounded up, since D-PHY entries are minimum times expressed in byte-clock
    # counts: too small violates the specification, slightly large only costs
    # overhead.
    (1_291_509_360, "00 2b 0a 0b 1c 27 0b 0b 0a 02 04 00 23 10"),  # scaled, not vendor-validated
]

# Confirmed against DSI_VIDEO_MODE_TOTAL = 0x0adc033a on the running device:
# htotal - 1 = 0x033a, so the compressed horizontal total is 827.
COMPRESSED_HTOTAL = 827
# Observed on the device: dsi0pll_bitclk_src / dsi0pll_pclk_src = 993551184 / 165591864.
BIT_CLOCK_RATIO = 6
V_ACTIVE = 2160
V_BACK_PORCH = 4
V_PULSE_WIDTH = 4

# Compressed horizontal active, i.e. 2160 / 3 with DSC at 8bpp from 24bpp.
H_ACTIVE_COMPRESSED = 720
BASELINE_H_PORCHES = (54, 33, 20)  # front, back, pulse width


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


def v_total_for(v_front_porch: int) -> int:
    return V_ACTIVE + V_BACK_PORCH + v_front_porch + V_PULSE_WIDTH


def derive(fps: int, pixel_clock: int, base_vfp: int) -> tuple[int, int]:
    """Return the vertical total and front porch the driver will derive."""
    v_total = pixel_clock // (COMPRESSED_HTOTAL * fps)
    return v_total, base_vfp + (v_total - v_total_for(base_vfp))


def pick_phy_timings(bit_clock: int) -> tuple[int, bytes]:
    for reference, table in PHY_TIMING_REFERENCES:
        if reference >= bit_clock:
            return reference, bytes(int(x, 16) for x in table.split())
    reference, table = PHY_TIMING_REFERENCES[-1]
    return reference, bytes(int(x, 16) for x in table.split())


def rename_tcon_slot(fdt: bytearray, fps: int) -> str | None:
    """Repoint one of the per-rate nt57900 command slots at a new rate.

    PICO's panel driver looks the TCON bring-up sequence up by refresh rate:
    qcom,mdss-dsi-post-<rate>-nt57900-on-command. Only 72, 90 and 120 exist, and
    booting at any other rate leaves the bridge chip without its start sequence,
    which shows up as a completely dark panel even though the DSI link itself is
    clean. Renaming a donor slot in the FDT strings block gives the new rate a
    sequence to find. The donor is chosen to have the same number of digits so
    the strings block keeps its exact length.
    """
    if fps in (72, 90, 120):
        return None
    donor = "90" if fps < 100 else "120"
    strings_offset = u32(fdt, 12)
    strings_size = u32(fdt, 32)
    block = bytes(fdt[strings_offset : strings_offset + strings_size])
    renamed = []
    for template in ("qcom,mdss-dsi-post-{}-nt57900-on-command",
                     "qcom,mdss-dsi-on-{}-nt57900-command-state"):
        old = template.format(donor).encode()
        new = template.format(fps).encode()
        if len(old) != len(new):
            raise ValueError("Donor slot has a different digit count")
        position = block.find(old)
        if position < 0 or block.find(old, position + 1) >= 0:
            raise ValueError(f"Expected exactly one {old.decode()} in the strings block")
        fdt[strings_offset + position : strings_offset + position + len(new)] = new
        renamed.append(f"{old.decode()} -> {new.decode()}")
    return "; ".join(renamed)


def build(baseline: bytes, fps: int, base_vfp: int,
          h_porches: tuple[int, int, int] | None = None) -> tuple[bytes, dict[str, object]]:
    entries = dtbo_entries(baseline)
    size, offset = entries[TARGET_INDEX]
    fdt = bytearray(baseline[offset : offset + size])
    properties = parse_fdt_properties(fdt)

    h_front = node_property(properties, "qcom,mdss-dsi-h-front-porch")
    h_back = node_property(properties, "qcom,mdss-dsi-h-back-porch")
    h_pulse = node_property(properties, "qcom,mdss-dsi-h-pulse-width")
    framerate = node_property(properties, "qcom,mdss-dsi-panel-framerate")
    front_porch = node_property(properties, "qcom,mdss-dsi-v-front-porch")
    phy_timings = node_property(properties, "qcom,mdss-dsi-panel-phy-timings")
    dfps = node_property(properties, DFPS_PROPERTY)
    maximum = node_property(properties, MAX_FPS_PROPERTY)

    if u32(bytes(framerate["value"]), 0) != BASELINE_FRAMERATE:
        raise ValueError("Unexpected baseline panel framerate")
    if u32(bytes(front_porch["value"]), 0) != BASELINE_VFP:
        raise ValueError("Unexpected baseline vertical front porch")
    if list(struct.unpack(">3I", bytes(dfps["value"]))) != [120, 90, 72]:
        raise ValueError("Input must already carry the <120 90 72> DFPS list")
    if u32(bytes(maximum["value"]), 0) != 120:
        raise ValueError("Input must already carry max-refresh-rate = 120")

    # The DFPS list and the maximum have to name the same rate as the base
    # timing. Leaving 120 in the list while the base timing is, say, 110 Hz makes
    # the driver derive a 120 Hz mode whose vertical total lands below the active
    # area, and booting into that mode is what produces a black screen with a
    # corrupted band along the bottom.
    set_u32(fdt, int(dfps["value_offset"]), fps)
    set_u32(fdt, int(maximum["value_offset"]), fps)

    set_u32(fdt, int(framerate["value_offset"]), fps)
    set_u32(fdt, int(front_porch["value_offset"]), base_vfp)

    # Horizontal blanking is the only remaining way to lower the link rate at a
    # fixed frame rate, since the vertical total is already at its floor.
    if h_porches is None:
        h_porches = BASELINE_H_PORCHES
    else:
        for prop, value in zip((h_front, h_back, h_pulse), h_porches):
            set_u32(fdt, int(prop["value_offset"]), value)
    h_total = H_ACTIVE_COMPRESSED + sum(h_porches)

    v_total = v_total_for(base_vfp)
    pixel_clock = h_total * v_total * fps
    bit_clock = pixel_clock * BIT_CLOCK_RATIO
    reference, table = pick_phy_timings(bit_clock)
    globals()["COMPRESSED_HTOTAL"] = h_total
    if int(phy_timings["value_length"]) != len(table):
        raise ValueError("PHY timing table length does not match the property")
    phy_offset = int(phy_timings["value_offset"])
    fdt[phy_offset : phy_offset + len(table)] = table

    tcon_rename = rename_tcon_slot(fdt, fps)

    candidate = bytearray(baseline)
    candidate[offset : offset + size] = fdt
    if len(candidate) != len(baseline):
        raise ValueError("Candidate must remain exactly partition-sized")

    verify = parse_fdt_properties(bytes(fdt))
    if bytes(node_property(verify, "qcom,mdss-dsi-panel-phy-timings")["value"]) != table:
        raise ValueError("PHY timing patch did not apply")
    if u32(bytes(node_property(verify, "qcom,mdss-dsi-panel-framerate")["value"]), 0) != fps:
        raise ValueError("Framerate patch did not apply")
    if u32(bytes(node_property(verify, "qcom,mdss-dsi-v-front-porch")["value"]), 0) != base_vfp:
        raise ValueError("Front porch patch did not apply")
    verified_dfps = list(struct.unpack(">3I", bytes(node_property(verify, DFPS_PROPERTY)["value"])))
    if verified_dfps[0] != fps or u32(bytes(node_property(verify, MAX_FPS_PROPERTY)["value"]), 0) != fps:
        raise ValueError("DFPS list or maximum was not aligned with the base timing")
    for rate in verified_dfps:
        if COMPRESSED_HTOTAL * pixel_clock // (COMPRESSED_HTOTAL * rate) < V_ACTIVE + V_BACK_PORCH + V_PULSE_WIDTH:
            raise ValueError(f"Derived timing for {rate} Hz would fall below the active area")

    audit = {
        "target_size": size,
        "framerate": f"{BASELINE_FRAMERATE} -> {fps}",
        "v_front_porch": f"{BASELINE_VFP} -> {base_vfp}",
        "h_porches": f"{BASELINE_H_PORCHES} -> {h_porches}",
        "compressed_htotal": f"{H_ACTIVE_COMPRESSED + sum(BASELINE_H_PORCHES)} -> {h_total}",
        "v_total_base": v_total,
        "pixel_clock_hz": pixel_clock,
        "bit_clock_hz": bit_clock,
        "phy_reference_hz": reference,
        "phy_timings": table.hex(" "),
        "tcon_slot": tcon_rename or "native rate, no rename needed",
        "dfps_list": verified_dfps,
        "derived": {rate: derive(rate, pixel_clock, base_vfp) for rate in verified_dfps[1:]},
        "bytes_changed": sum(1 for a, b in zip(baseline, bytes(candidate)) if a != b),
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(bytes(candidate)).hexdigest(),
    }
    return bytes(candidate), audit


def main() -> None:
    if len(sys.argv) not in (3, 5, 8):
        raise SystemExit(
            f"usage: {sys.argv[0]} <input-dtbo> <output-dtbo> [fps] [base-vfp] [hfp] [hbp] [hpw]")
    fps = int(sys.argv[3]) if len(sys.argv) >= 5 else 120
    base_vfp = int(sys.argv[4]) if len(sys.argv) >= 5 else 1
    h_porches = tuple(int(x) for x in sys.argv[5:8]) if len(sys.argv) == 8 else None
    baseline = open(sys.argv[1], "rb").read()
    candidate, audit = build(baseline, fps, base_vfp, h_porches)
    open(sys.argv[2], "wb").write(candidate)
    print(f"PICO 4 Sharp LS026B3SA {fps} Hz base-timing candidate")
    for key, value in audit.items():
        print(f"  {key}: {value}")
    current = 165_591_864
    print(f"  pixel clock change: {audit['pixel_clock_hz'] / current:.4f}x of the measured {current} Hz")


if __name__ == "__main__":
    main()
