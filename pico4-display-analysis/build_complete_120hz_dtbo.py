#!/usr/bin/env python3
"""Build a complete LS026B3SA 120 Hz timing candidate.

This is an offline builder only. It starts from the stock DTBO and changes the
active Sharp timing@0 to a 120 Hz VFP base, adds the 120/90/72 DFPS list, uses a
PHY table scaled for the target link, and inserts panel-clockrate into timing@0
(where Qualcomm's dsi_panel_parse_timing() actually reads it).
"""
from __future__ import annotations
import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("candidate", BASE / "build_candidate_dtbo.py")
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

TARGET = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
INDEX = 5
CLOCK_NAME = b"qcom,mdss-dsi-panel-clockrate"
CLOCK_HZ = 1_291_509_360
PHY = bytes.fromhex("00 2b 0a 0b 1c 27 0b 0b 0a 02 04 00 23 10")


def parse(blob: bytes) -> list[dict[str, object]]:
    if M.u32(blob, 0) != M.FDT_MAGIC:
        raise ValueError("not FDT")
    so, ss, sl = M.u32(blob, 8), M.u32(blob, 12), M.u32(blob, 32)
    strings = blob[ss:ss + sl]
    pos, stack, out = so, [], []
    while True:
        token = M.u32(blob, pos); pos += 4
        if token == M.FDT_BEGIN_NODE:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode("utf-8", "replace"))
            pos = M.align4(end + 1)
        elif token == M.FDT_END_NODE:
            stack.pop()
        elif token == M.FDT_PROP:
            header = pos - 4
            length, noff = M.u32(blob, pos), M.u32(blob, pos + 4)
            value = pos + 8
            end = M.align4(value + length)
            name_end = strings.index(b"\0", noff)
            out.append({"path": "/" + "/".join(x for x in stack if x),
                        "name": strings[noff:name_end].decode("utf-8", "replace"),
                        "header_offset": header, "value_offset": value,
                        "value_length": length, "region_end": end,
                        "value": blob[value:value + length]})
            pos = end
        elif token == M.FDT_END:
            return out
        elif token == M.FDT_NOP:
            continue
        else:
            raise ValueError(f"bad token {token} at {pos - 4:#x}")


def prop(props, name, timing=False):
    hits = [p for p in props if p["name"] == name and TARGET in str(p["path"])
            and (("/timing@" in str(p["path"])) == timing)]
    if len(hits) != 1:
        raise ValueError(f"expected one {name}, timing={timing}; got {len(hits)}")
    return hits[0]


def cell(p):
    v = bytes(p["value"])
    if len(v) != 4:
        raise ValueError(f"not one cell: {p['name']}")
    return M.u32(v, 0)


def node_end(blob, match, exclude=None):
    pos, stack = M.u32(blob, 8), []
    while True:
        token = M.u32(blob, pos); pos += 4
        if token == M.FDT_BEGIN_NODE:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode("utf-8", "replace")); pos = M.align4(end + 1)
        elif token == M.FDT_END_NODE:
            path = "/" + "/".join(x for x in stack if x)
            if match in path and (exclude is None or exclude not in path): return pos - 4
            stack.pop()
        elif token == M.FDT_PROP: pos = M.align4(pos + 8 + M.u32(blob, pos))
        elif token == M.FDT_END: raise ValueError("node end not found")


def build(image):
    entries = M.dtbo_entries(image); old_size, offset = entries[INDEX]
    fdt = bytearray(image[offset:offset + old_size]); ps = parse(bytes(fdt))
    fr = prop(ps, "qcom,mdss-dsi-panel-framerate", True)
    vf = prop(ps, "qcom,mdss-dsi-v-front-porch", True)
    mx = prop(ps, "qcom,mdss-dsi-max-refresh-rate", False)
    df = prop(ps, "qcom,dsi-supported-dfps-list", False)
    phy = prop(ps, "qcom,mdss-dsi-panel-phy-timings", True)
    if cell(fr) != 90 or cell(vf) != 57 or cell(mx) != 90 or bytes(df["value"]) != struct.pack(">2I", 90, 72):
        raise ValueError("input must be the stock DTBO")
    if len(PHY) != int(phy["value_length"]): raise ValueError("unexpected PHY length")
    M.set_u32(fdt, int(fr["value_offset"]), 120)
    M.set_u32(fdt, int(vf["value_offset"]), 1)
    M.set_u32(fdt, int(mx["value_offset"]), 120)
    fdt[int(phy["value_offset"]):int(phy["value_offset"]) + len(PHY)] = PHY
    at = int(df["value_offset"]) + int(df["value_length"])
    fdt[at:at] = b"\0\0\0\0"
    M.set_u32(fdt, int(df["header_offset"]) + 4, 12)
    fdt[int(df["value_offset"]):int(df["value_offset"]) + 12] = struct.pack(">3I", 120, 90, 72)
    M.set_u32(fdt, 4, len(fdt)); M.set_u32(fdt, 12, M.u32(fdt, 12) + 4); M.set_u32(fdt, 36, M.u32(fdt, 36) + 4)
    strings_off, strings_size = M.u32(fdt, 12), M.u32(fdt, 32)
    noff = bytes(fdt[strings_off:strings_off + strings_size]).find(CLOCK_NAME)
    if noff < 0: raise ValueError("clock property name absent")
    ins = node_end(bytes(fdt), TARGET + "/qcom,mdss-dsi-display-timings/timing@0")
    clock_prop = struct.pack(">IIII", M.FDT_PROP, 4, noff, CLOCK_HZ)
    fdt[ins:ins] = clock_prop
    M.set_u32(fdt, 4, len(fdt)); M.set_u32(fdt, 12, M.u32(fdt, 12) + len(clock_prop)); M.set_u32(fdt, 36, M.u32(fdt, 36) + len(clock_prop))
    check = parse(bytes(fdt))
    assert cell(prop(check, "qcom,mdss-dsi-panel-framerate", True)) == 120
    assert cell(prop(check, "qcom,mdss-dsi-v-front-porch", True)) == 1
    assert cell(prop(check, "qcom,mdss-dsi-max-refresh-rate", False)) == 120
    assert bytes(prop(check, "qcom,dsi-supported-dfps-list", False)["value"]) == struct.pack(">3I", 120, 90, 72)
    assert cell(prop(check, CLOCK_NAME.decode(), True)) == CLOCK_HZ
    out = bytearray(image); out[offset:offset + old_size] = fdt
    table = M.u32(out, 20); M.set_u32(out, table + INDEX * 32, len(fdt)); delta = len(fdt) - old_size
    for i in range(INDEX + 1, len(entries)): M.set_u32(out, table + i * 32 + 4, M.u32(out, table + i * 32 + 4) + delta)
    M.set_u32(out, 4, M.u32(out, 4) + delta); out = out[:len(image)]
    return bytes(out), {"target_size": f"{old_size}->{len(fdt)}", "inserted": delta, "clock_hz": CLOCK_HZ, "sha256": hashlib.sha256(out).hexdigest()}


def main():
    if len(sys.argv) != 3: raise SystemExit(f"usage: {sys.argv[0]} INPUT OUTPUT")
    out, audit = build(Path(sys.argv[1]).read_bytes()); Path(sys.argv[2]).write_bytes(out)
    for k, v in audit.items(): print(f"{k}: {v}")


if __name__ == "__main__": main()
