#!/usr/bin/env python3
"""Classify the device-pulled DTBO: stock (90Hz) vs already 120Hz-modified.

Robust: only the four complete panel entries parse cleanly; the twelve stub
entries are detected by raw byte search, never fed to the FDT parser.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_120_init120_inplace import patch_entry, POST_120_STREAM  # noqa: E402
from build_candidate_dtbo import (  # noqa: E402
    DFPS_PROPERTY,
    MAX_FPS_PROPERTY,
    TARGET_NODE,
    decode_cells,
    dtbo_entries,
    parse_fdt_properties,
)

FRAMERATE_NAME = "qcom,mdss-dsi-panel-framerate"


def entry_state(blob: bytes) -> dict:
    has_node = TARGET_NODE.encode() in blob
    has_stream = POST_120_STREAM in blob
    patchable = False
    reason = ""
    if has_node:
        try:
            patch_entry(blob)
            patchable = True
        except Exception as ex:  # noqa: BLE001
            reason = str(ex)
    # detailed decode only when the panel node exists
    dfps = maxf = fr = None
    if has_node:
        try:
            props = parse_fdt_properties(blob)
            for name, sink in (
                (DFPS_PROPERTY, "dfps"),
                (MAX_FPS_PROPERTY, "max"),
                (FRAMERATE_NAME, "fr"),
            ):
                for p in props:
                    if p["name"] == name and TARGET_NODE in str(p["path"]):
                        try:
                            v = decode_cells(bytes(p["value"]))
                            if sink == "dfps":
                                dfps = v
                            elif sink == "max":
                                maxf = v
                            else:
                                fr = v
                        except Exception:  # noqa: BLE001
                            pass
                        break
        except Exception:  # noqa: BLE001
            pass
    return dict(
        has_node=has_node, has_stream=has_stream, patchable=patchable,
        reason=reason, dfps=dfps, maxf=maxf, fr=fr,
    )


def main() -> int:
    path = HERE / "dtbo-device-pulled.img"
    blob = path.read_bytes()
    entries = dtbo_entries(blob)
    print(f"image sha256: {hashlib.sha256(blob).hexdigest()}")
    print(f"entry count : {len(entries)}")
    print()
    patchable_idx = []
    already_120 = []
    for i, (sz, off) in enumerate(entries):
        e = blob[off : off + sz]
        st = entry_state(e)
        if st["has_node"] and st["patchable"]:
            tag = "STOCK90 (patchable)"
            patchable_idx.append(i)
        elif st["has_node"] and st["has_stream"]:
            tag = "ALREADY-120"
            already_120.append(i)
        elif st["has_node"]:
            tag = "node-not-patchable"
        else:
            tag = "no-panel-node (stub)"
        print(f"[{i:2}] {sz:>7}B  {tag}")
        if st["has_node"]:
            print(f"       dfps={st['dfps']} max={st['maxf']} framerate={st['fr']}  reason={st['reason'][:60]}")
        print(f"[{i:2}] {sz:>7}B  {tag}")
        if st["has_node"]:
            print(f"       dfps={st['dfps']} max={st['maxf']} framerate={st['fr']}")
    print()
    print(f"patchable(stock) entries : {patchable_idx}")
    print(f"already-120Hz entries   : {already_120}")
    if patchable_idx and not already_120:
        print("\nVERDICT: dtbo is STOCK (90Hz) -> safe to build 120Hz from it.")
    elif already_120 and not patchable_idx:
        print("\nVERDICT: dtbo is ALREADY a 120Hz mod -> do not re-patch; "
              "obtain the matching stock baseline instead.")
    elif already_120 and patchable_idx:
        print("\nVERDICT: MIXED -> investigate before flashing.")
    else:
        print("\nVERDICT: no complete panel node found -> not a buildable baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
