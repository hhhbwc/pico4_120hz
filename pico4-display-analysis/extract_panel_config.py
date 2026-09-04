#!/usr/bin/env python3
"""Extract display configuration of DSI panel nodes from a PICO 4 DTBO image.

Offline analysis only; writes nothing to any device. For each matching panel
node this prints every property of the node itself, of its
qcom,mdss-dsi-display-timings/timing@N children and of its DSC child, plus the
per-rate NT57900 TCON command slots. The goal is to replace hand-waving about
"missing 120 Hz configuration" with an exact inventory of what the stock
LS026B3SA node carries and what a complete candidate must change.

usage: extract_panel_config.py dtbo-current.img [node-filter]
"""

from __future__ import annotations

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


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


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


class Node:
    __slots__ = ("path", "props")

    def __init__(self, path: str) -> None:
        self.path = path
        self.props: list[tuple[str, bytes]] = []


def parse_fdt(blob: bytes) -> list[Node]:
    if u32(blob, 0) != FDT_MAGIC:
        raise ValueError("not an FDT")
    struct_off = u32(blob, 8)
    strings_off = u32(blob, 12)
    strings = blob[strings_off : strings_off + u32(blob, 32)]
    pos = struct_off
    stack: list[str] = []
    nodes: dict[str, Node] = {}
    order: list[Node] = []
    while True:
        token = u32(blob, pos)
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode("utf-8", "replace"))
            path = "/" + "/".join(x for x in stack if x)
            node = Node(path)
            nodes[path] = node
            order.append(node)
            pos = align4(end + 1)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            length, noff = u32(blob, pos), u32(blob, pos + 4)
            value_off = pos + 8
            pos = align4(value_off + length)
            name_end = strings.index(b"\0", noff)
            name = strings[noff:name_end].decode("utf-8", "replace")
            nodes["/" + "/".join(x for x in stack if x)].props.append(
                (name, blob[value_off : value_off + length])
            )
        elif token == FDT_END:
            return order
        elif token == FDT_NOP:
            continue
        else:
            raise ValueError(f"unexpected token {token}")


def fmt_value(name: str, value: bytes) -> str:
    if not value:
        return "<empty>"
    if len(value) % 4 == 0 and len(value) <= 64:
        cells = [str(u32(value, i)) for i in range(0, len(value), 4)]
        return "<" + " ".join(cells) + ">"
    if all(32 <= b < 127 or b == 0 for b in value):
        return repr(value.rstrip(b"\0").decode("ascii", "replace"))
    return value.hex(" ")


def interesting(name: str) -> bool:
    keys = (
        "timing", "clock", "phy", "dsc", "pps", "tcon", "nt57900", "framerate",
        "refresh", "dfps", "porch", "pulse", "active", "lane", "bpp", "compress",
        "traffic", "transfer", "dma", "vid", "cmd", "init", "on-", "off-",
        "h-", "v-", "width", "height", "topology", "mode", "pll", "byte",
        "panel-", "display-", "qcom,mdss-dsi",
    )
    low = name.lower()
    return any(k in low for k in keys)


def dump(node: Node) -> None:
    print(f"\n### {node.path}")
    for name, value in node.props:
        if interesting(name):
            print(f"  {name} [{len(value)}B] = {fmt_value(name, value)}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    image = Path(sys.argv[1]).read_bytes()
    node_filter = sys.argv[2] if len(sys.argv) > 2 else ""
    for index, (size, offset) in enumerate(dtbo_entries(image)):
        nodes = parse_fdt(image[offset : offset + size])
        panels = [
            n for n in nodes
            if "mdss_dsi" in n.path and "timing@" not in n.path
            and "display-timings" not in n.path and not n.path.endswith("/dsc")
        ]
        for panel in panels:
            if node_filter and node_filter not in panel.path:
                continue
            print(f"\n===== dtbo[{index}] panel: {panel.path} =====")
            related = [n for n in nodes if n.path == panel.path or n.path.startswith(panel.path + "/")]
            for node in related:
                dump(node)


if __name__ == "__main__":
    main()
