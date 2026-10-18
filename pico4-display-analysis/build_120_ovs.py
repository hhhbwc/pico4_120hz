#!/usr/bin/env python3
"""Build the 120 Hz DTBO for global (Phoenix_ovs / kona-MTP) PICO 4 units.

ro.boot.dtbo_idx=6 on these units selects the "kona MTP" entry (the author's
CN unit selects "kona-iot MTP"), so this patches entry 6 IN PLACE with the
proven v6 panel patch and leaves the stock table order untouched:

  python build_120_ovs.py

Validates, then writes dtbo-120hz-v6-kona-mtp.img and prints hashes. The image
is never written to any partition by this script.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_candidate_dtbo import TARGET_NODE, dtbo_entries, parse_fdt_properties  # noqa: E402
from build_120_init120_inplace import ON_CMD, POST_120_STREAM, build, patch_entry  # noqa: E402

STOCK = Path("dtbo-stock-phoenix_ovs.img")
OUT = Path("dtbo-120hz-v6-kona-mtp.img")
AUTHOR_V6 = Path("dtbo-120hz-v6-init120.img")
TARGET_INDEX = 6  # ro.boot.dtbo_idx on global units; live model = "kona MTP"


def sharp_props(blob: bytes) -> dict:
    return {
        (str(p["path"]).replace(TARGET_NODE, "N"), p["name"]): bytes(p["value"])
        for p in parse_fdt_properties(blob)
        if TARGET_NODE in str(p["path"])
    }


def main() -> int:
    stock = STOCK.read_bytes()
    entries = dtbo_entries(stock)
    size, off = entries[TARGET_INDEX]
    patched_entry = patch_entry(stock[off : off + size])
    shift = len(patched_entry) - size

    out = build(stock, TARGET_INDEX)

    # table consistency: only the target entry's size changed; entries after it
    # shift by `shift`; earlier entries and order are untouched
    new_entries = dtbo_entries(out)
    assert new_entries[TARGET_INDEX][0] == size + shift
    for i, (sz, o) in enumerate(entries):
        nsz, no = new_entries[i]
        if i < TARGET_INDEX:
            assert (nsz, no) == (sz, o), f"entry {i} unexpectedly moved"
        elif i == TARGET_INDEX:
            assert (nsz, no) == (size + shift, o), "target entry size/offset wrong"
            assert out[no : no + nsz] == patched_entry, "target entry content wrong"
        else:
            assert (nsz, no) == (sz, o + shift), f"entry {i} not shifted correctly"
        if i != TARGET_INDEX:
            assert out[no : no + nsz] == stock[o : o + sz], f"entry {i} content changed"
    assert len(out) == len(stock), "image must stay partition-sized"

    # semantic checks on the patched entry (each prop appears once in the subtree)
    props = sharp_props(patched_entry)
    by_name = {name: value for (_, name), value in props.items()}
    assert by_name["qcom,dsi-supported-dfps-list"] == bytes.fromhex("000000780000005a00000048")
    assert by_name["qcom,mdss-dsi-max-refresh-rate"] == b"\x00\x00\x00\x78"
    assert by_name["qcom,mdss-dsi-panel-framerate"] == b"\x00\x00\x00\x78"
    on_cmd_value = by_name[ON_CMD]
    assert POST_120_STREAM in on_cmd_value, "on-command missing stream"
    assert on_cmd_value.index(POST_120_STREAM) < on_cmd_value.index(bytes.fromhex("0501000078000111"))

    # the panel subtree must be byte-identical to the author's patched one:
    # every entry ships the same panel fragment, so same patch -> same result
    v6 = AUTHOR_V6.read_bytes()
    v6_size, v6_off = dtbo_entries(v6)[5]
    assert sharp_props(patched_entry) == sharp_props(v6[v6_off : v6_off + v6_size]), \
        "panel subtree differs from author's v6"

    OUT.write_bytes(out)
    print(f"patched entry {TARGET_INDEX} (kona MTP) in place; {shift} bytes inserted")
    print(f"  stock: {STOCK}  sha256={hashlib.sha256(stock).hexdigest()}")
    print(f"  built: {OUT}  sha256={hashlib.sha256(out).hexdigest()}")
    print("  panel subtree verified byte-identical to the author's boot-tested v6")
    print("  nothing was written to any partition")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
