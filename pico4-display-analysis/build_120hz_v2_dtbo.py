#!/usr/bin/env python3
"""Build the corrected LS026B3SA 120 Hz candidate (v2).

Why v2 exists: the two earlier candidates failed for *identifiable* reasons, and
this builder removes exactly those variables while adding nothing new:

  * build_120hz_base  changed framerate/vfp but the PLL did not follow (pclk
    stayed at 165.6 MHz), and it NOP'd the PHY table hoping the driver would
    recompute -- a compound change with two unverified assumptions.
  * build_complete    added qcom,mdss-dsi-panel-clockrate, but on-device
    measurement (see LS026B3SA_120HZ_FULL_CONFIG.md section 2/4) shows the PLL
    is *derived*: pclk is always exactly htotal x vtotal x fps and bitclk is
    always exactly 6x pclk. The stock node has no clockrate property and the
    driver does not need one. So clockrate is a no-op here and is NOT added.

What the measurement implies: writing a 120 Hz geometry into timing@0 makes the
driver program pclk = 827 x 2182 x 120 = 216.5 MHz and bitclk = 1.299 GHz by
itself. The only thing that genuinely has no stock reference at that link rate
is the 14-byte DSI PHY v4.0 timing table (highest native panel is 1088 MHz).
Linear extrapolation across the 5 calibration panels produced absurd values
(see the analysis doc), so the defensible choice is to NOP the property and let
the kernel's dsi_phy_hw_calculate_timing_params (v4.0 ops confirmed present in
/proc/kallsyms) compute it for the real clock.

Edits applied to the active LS026B3SA node (entry index 5), in place so the FDT
keeps its size:

    qcom,mdss-dsi-panel-framerate    90 -> 120            (timing@0)
    qcom,mdss-dsi-v-front-porch      57 -> 14             (timing@0)  vtotal 2182
    qcom,dsi-supported-dfps-list     <90 72> -> <120 90 72>           (node)
    qcom,mdss-dsi-max-refresh-rate   <90> -> <120>                    (node)
    qcom,mdss-dsi-panel-phy-timings  14 bytes -> FDT_NOP words (optional, on by default)

Not touched on purpose:
    * no qcom,mdss-dsi-panel-clockrate (driver derives the clock from geometry)
    * the NT57900 post-*-on-command slots -- the stock 120 sequence is complete
      for this panel's bridge dialect (see analysis doc section 5.2); it is not
      a truncated Innolux table and Innolux values cannot be transplanted.

Input must be the STOCK dtbo (dfps <90 72>, max 90, framerate 90, vfp 57).
The image keeps its exact partition size; only the target FDT grows, which the
DTBO entry table absorbs by shifting later entries, and the tail is truncated
back to the original image size (the last bytes of a dtbo partition are padding).

usage: build_120hz_v2_dtbo.py INPUT_STOCK_DTBO OUTPUT [--keep-phy]
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

TARGET = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
INDEX = 5

# Verified against DSI_VIDEO_MODE_TOTAL = 0x0adc033a and the measured
# dsi0pll clocks on the running device.
COMPRESSED_HTOTAL = 827
V_ACTIVE = 2160
V_BACK_PORCH = 4
V_PULSE_WIDTH = 4
NEW_FPS = 120
NEW_VFP = 14                      # vtotal 2160+4+4+14 = 2182
PIXEL_CLOCK = COMPRESSED_HTOTAL * (V_ACTIVE + V_BACK_PORCH + V_PULSE_WIDTH + NEW_VFP) * NEW_FPS
BIT_CLOCK = PIXEL_CLOCK * 6       # measured ratio on this panel is exactly 6


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def put_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, value)


def align4(value: int) -> int:
    return (value + 3) & ~3


def dtbo_entries(image: bytes) -> list[tuple[int, int]]:
    if u32(image, 0) != DT_TABLE_MAGIC:
        raise ValueError("not an Android DTBO image")
    if u32(image, 12) != 32:
        raise ValueError("unexpected DTBO entry size")
    count = u32(image, 16)
    base = u32(image, 20)
    return [(u32(image, base + i * 32), u32(image, base + i * 32 + 4)) for i in range(count)]


def parse(blob: bytes) -> list[dict[str, object]]:
    if u32(blob, 0) != FDT_MAGIC:
        raise ValueError("not an FDT")
    so, ss, sl = u32(blob, 8), u32(blob, 12), u32(blob, 32)
    strings = blob[ss:ss + sl]
    pos, stack, out = so, [], []
    while True:
        token = u32(blob, pos); pos += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode("utf-8", "replace"))
            pos = align4(end + 1)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            header = pos - 4
            length, noff = u32(blob, pos), u32(blob, pos + 4)
            value = pos + 8
            end = align4(value + length)
            name_end = strings.index(b"\0", noff)
            out.append({"path": "/" + "/".join(x for x in stack if x),
                        "name": strings[noff:name_end].decode("utf-8", "replace"),
                        "header_offset": header, "value_offset": value,
                        "value_length": length, "region_end": end,
                        "value": blob[value:value + length]})
            pos = end
        elif token == FDT_END:
            return out
        elif token == FDT_NOP:
            continue
        else:
            raise ValueError(f"bad token {token} at {pos - 4:#x}")


def prop(props, name, timing):
    hits = [p for p in props if p["name"] == name and TARGET in str(p["path"])
            and (("/timing@" in str(p["path"])) == timing)]
    if len(hits) != 1:
        raise ValueError(f"expected one {name} (timing={timing}), got {len(hits)}")
    return hits[0]


def cell(p) -> int:
    v = bytes(p["value"])
    if len(v) != 4:
        raise ValueError(f"not a single cell: {p['name']}")
    return u32(v, 0)


def build(image: bytes, nop_phy: bool) -> tuple[bytes, dict[str, object]]:
    entries = dtbo_entries(image)
    old_size, offset = entries[INDEX]
    fdt = bytearray(image[offset:offset + old_size])
    ps = parse(bytes(fdt))

    fr = prop(ps, "qcom,mdss-dsi-panel-framerate", True)
    vf = prop(ps, "qcom,mdss-dsi-v-front-porch", True)
    mx = prop(ps, "qcom,mdss-dsi-max-refresh-rate", False)
    df = prop(ps, "qcom,dsi-supported-dfps-list", False)
    phy = prop(ps, "qcom,mdss-dsi-panel-phy-timings", True)

    # insist on the untouched stock node so the diff stays auditable
    if cell(fr) != 90 or cell(vf) != 57 or cell(mx) != 90:
        raise ValueError("input must be the stock DTBO (framerate/vfp/max not 90/57/90)")
    if bytes(df["value"]) != struct.pack(">2I", 90, 72):
        raise ValueError("input must be the stock DTBO (dfps list not <90 72>)")

    put_u32(fdt, int(fr["value_offset"]), NEW_FPS)
    put_u32(fdt, int(vf["value_offset"]), NEW_VFP)
    put_u32(fdt, int(mx["value_offset"]), NEW_FPS)

    # dfps list grows 8 -> 12 bytes: insert one zero cell, then write 3 cells
    at = int(df["value_offset"]) + int(df["value_length"])
    fdt[at:at] = b"\0\0\0\0"
    put_u32(fdt, int(df["header_offset"]) + 4, 12)
    fdt[int(df["value_offset"]):int(df["value_offset"]) + 12] = struct.pack(">3I", 120, 90, 72)
    grow = 4
    put_u32(fdt, 4, len(fdt))
    put_u32(fdt, 12, u32(fdt, 12) + grow)
    put_u32(fdt, 36, u32(fdt, 36) + grow)

    phy_action = "kept stock 993MHz table"
    if nop_phy:
        # reparse after the insertion shifted offsets
        ps = parse(bytes(fdt))
        phy = prop(ps, "qcom,mdss-dsi-panel-phy-timings", True)
        start = int(phy["header_offset"])
        end = int(phy["region_end"])
        nops = (end - start) // 4
        for i in range(nops):
            put_u32(fdt, start + i * 4, FDT_NOP)
        phy_action = "NOP'd (kernel v4.0 calculator recomputes at 1.299GHz)"

    # verify
    check = parse(bytes(fdt))
    assert cell(prop(check, "qcom,mdss-dsi-panel-framerate", True)) == NEW_FPS
    assert cell(prop(check, "qcom,mdss-dsi-v-front-porch", True)) == NEW_VFP
    assert cell(prop(check, "qcom,mdss-dsi-max-refresh-rate", False)) == NEW_FPS
    assert bytes(prop(check, "qcom,dsi-supported-dfps-list", False)["value"]) == struct.pack(">3I", 120, 90, 72)

    # DFPS sanity: 90 and 72 must land on positive front porches
    base_vtotal = V_ACTIVE + V_BACK_PORCH + V_PULSE_WIDTH + NEW_VFP
    derived = {}
    for rate in (90, 72):
        vt = PIXEL_CLOCK // (COMPRESSED_HTOTAL * rate)
        vfp = NEW_VFP + (vt - base_vtotal)
        assert vt >= V_ACTIVE + V_BACK_PORCH + V_PULSE_WIDTH, f"{rate}Hz vtotal underflows"
        derived[rate] = (vt, vfp)

    out = bytearray(image)
    out[offset:offset + old_size] = fdt
    table = u32(out, 20)
    delta = len(fdt) - old_size
    put_u32(out, table + INDEX * 32, len(fdt))
    for i in range(INDEX + 1, len(entries)):
        put_u32(out, table + i * 32 + 4, u32(out, table + i * 32 + 4) + delta)
    put_u32(out, 4, u32(out, 4) + delta)
    out = out[:len(image)]

    audit = {
        "target_entry": INDEX,
        "framerate": "90 -> 120",
        "v_front_porch": "57 -> 14",
        "vtotal_120": base_vtotal,
        "dfps": "<90 72> -> <120 90 72>",
        "pixel_clock_hz": PIXEL_CLOCK,
        "bit_clock_hz": BIT_CLOCK,
        "phy_timings": phy_action,
        "derived_90hz": derived[90],
        "derived_72hz": derived[72],
        "clockrate_property": "not added (clock is derived from geometry)",
        "nt57900_sequences": "untouched (stock 120 sequence is complete for this bridge)",
        "image_size": len(out),
        "sha256": hashlib.sha256(bytes(out)).hexdigest(),
    }
    return bytes(out), audit


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep_phy = "--keep-phy" in sys.argv
    if len(args) != 2:
        raise SystemExit(__doc__)
    out, audit = build(Path(args[0]).read_bytes(), nop_phy=not keep_phy)
    Path(args[1]).write_bytes(out)
    print(f"LS026B3SA 120 Hz candidate v2 (phy {'kept' if keep_phy else 'NOP->kernel-calc'})")
    for k, v in audit.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
