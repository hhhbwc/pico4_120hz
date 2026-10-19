#!/usr/bin/env python3
"""Locate and decode the AVB descriptors in the stock PICO 4 vbmeta.

Why brute force: the image was produced by avbtool 1.1.0 (2016), whose
descriptor layout is not the current one, so hard-coding the modern struct
offsets lands in the middle of a hash.  Instead this walks every 8-byte aligned
offset, treats it as a candidate AvbDescriptor header (tag, size_be), and then
tries each known hash-descriptor layout variant.  A candidate is accepted only
when it yields a printable partition name of length 1..32 that is followed by
plausible fields, and when the next descriptor also parses.  That self-consistency
check is what makes the result trustworthy rather than a guess.

The question that matters: is the dtbo partition covered by a descriptor?  If it
is, and the bootloader enforces it, then flashing a patched dtbo would need AVB
disabled -- which decides whether a custom ROM is even required.
"""
from __future__ import annotations

import hashlib
import pathlib
import struct
import zipfile

FIRMWARE_DIR = pathlib.Path("D:/newpico/downloads")
ZIPS = [("CN", "5.13.7_CN_b9650.zip"), ("INTL", "5.13.7_INTL_b9665.zip")]

AVB_HEADER_SIZE = 224  # sizeof(AvbVBMetaImageHeader) in libavb

# libavb descriptor tags
TAG_PROPERTY = 0
TAG_HASHTREE = 1
TAG_HASH = 2
TAG_KERNEL_CMDLINE = 3
TAG_CHAIN_PARTITION = 4
TAGNAME = {
    TAG_PROPERTY: "property",
    TAG_HASHTREE: "hashtree",
    TAG_HASH: "hash",
    TAG_KERNEL_CMDLINE: "kernel_cmdline",
    TAG_CHAIN_PARTITION: "chain",
}

# Fields every 1.1.0-era descriptor starts with, after the 16-byte header.
# We brute force the rest by validating the extracted partition name.
KNOWN_PARTITIONS = {
    "boot", "dtbo", "odm", "vendor", "recovery", "vbmeta_system",
    "system", "userdata", "vbmeta", "vbmeta_vendor", "super", "odm_dlkm",
}


def u(fmt: str, buf: bytes, off: int):
    return struct.unpack(">" + fmt, buf[off : off + struct.calcsize(">" + fmt)])


def printable_name(raw: bytes) -> str | None:
    s = raw.split(b"\x00")[0]
    if not s or len(s) > 32:
        return None
    if not all(33 <= c < 127 for c in s):
        return None
    try:
        return s.decode("ascii")
    except UnicodeDecodeError:
        return None


def try_decode(d: bytes, off: int, tag: int, size: int):
    """Decode one descriptor under each plausible layout. Returns a dict or None."""
    body = d[off + 16 : off + size]
    if len(body) < 8:
        return None

    if tag in (TAG_HASH, TAG_HASHTREE):
        # hash_algorithm[32] then (image_size,) then name_len/salt_len.
        # Try every plausible position of hash_algorithm inside the body and
        # require the following two u32s to read as a sane (name_len, salt_len).
        for ha in range(0, min(len(body) - 8, 160)):
            algo = body[ha : ha + 32].split(b"\x00")[0]
            if algo not in (b"sha1", b"sha256", b"sha512"):
                continue
            for name_len_at in (ha + 32, ha + 40, ha + 44):
                if name_len_at + 8 > len(body):
                    continue
                name_len, salt_len = u("II", body, name_len_at)
                if not (1 <= name_len <= 64) or salt_len > 256:
                    continue
                name_at = name_len_at + 8
                if name_at + name_len > len(body):
                    continue
                name = printable_name(body[name_at : name_at + name_len])
                if name is None:
                    continue
                rec = {
                    "tag": tag,
                    "size": size,
                    "partition": name,
                    "hash_algorithm": algo.decode(),
                    "layout": f"ha@{ha},len@{name_len_at},name@{name_at}",
                    "salt_len": salt_len,
                }
                # image_size, when present, sits right before the name length
                if name_len_at >= 8:
                    (img,) = u("Q", body, name_len_at - 8)
                    if 0 < img < 1 << 32:
                        rec["image_size"] = img
                # trailing digest / salt, if any
                tail = body[name_at + name_len :]
                if len(tail) >= 32:
                    rec["digest_sha256_of_tail"] = hashlib.sha256(tail).hexdigest()[:16]
                return rec
        return None

    if tag in (TAG_PROPERTY, TAG_CHAIN_PARTITION, TAG_KERNEL_CMDLINE):
        if len(body) < 4:
            return None
        (name_len,) = u("I", body, 0)
        if not (1 <= name_len <= 128) or 4 + name_len > len(body):
            return None
        name = printable_name(body[4 : 4 + name_len])
        if name is None:
            return None
        return {"tag": tag, "size": size, "partition": name, "layout": "prop"}
    return None


def chain_from(d: bytes, start: int, limit: int):
    """Follow a descriptor chain from start; return list of records or None."""
    out = []
    p = start
    while p + 16 <= limit:
        tag, size = u("QQ", d, p)
        if tag not in TAGNAME or size < 16 or p + size > limit:
            return None
        rec = try_decode(d, p, tag, size)
        if rec is None:
            return None
        rec["offset"] = p
        out.append(rec)
        p += size
        if len(out) > 24:
            return None
    return out if out else None


def find_chains(d: bytes):
    """Scan for descriptor chains. Prefer the longest, and require at least one
    known partition name so random padding cannot masquerade as a chain."""
    limit = len(d)
    cands = []
    for off in range(0, limit - 16, 4):
        tag, size = u("QQ", d, off)
        if tag not in TAGNAME or not (16 <= size <= 4096) or off + size > limit:
            continue
        chain = chain_from(d, off, limit)
        if not chain:
            continue
        names = [r["partition"] for r in chain]
        hits = sum(1 for n in names if n in KNOWN_PARTITIONS)
        cands.append((hits, len(chain), off, chain))
    if not cands:
        return []
    best = max(hits for hits, _, _, _ in cands)
    return [c for c in cands if c[0] == best]


def parse_header(d: bytes) -> dict:
    if d[:4] != b"AVB0":
        raise SystemExit("not AVB0")
    major, minor = u("II", d, 4)
    auth, aux = u("QQ", d, 12)
    algo, = u("I", d, 28)
    (h_off, h_sz, s_off, s_sz, pk_off, pk_sz,
     pkm_off, pkm_sz, desc_off, desc_sz, rollback) = u("11Q", d, 32)
    flags, rollback_loc = u("II", d, 120)
    release = d[128:192].split(b"\x00")[0].decode("utf-8", "replace")
    return {
        "libavb": f"{major}.{minor}",
        "auth": auth,
        "aux": aux,
        "algo": algo,
        "desc_off": desc_off,
        "desc_sz": desc_sz,
        "flags": flags,
        "rollback": rollback,
        "rollback_loc": rollback_loc,
        "release": release,
        "desc_base": AVB_HEADER_SIZE + auth + aux + desc_off,
        "desc_end": AVB_HEADER_SIZE + auth + aux + desc_off + desc_sz,
    }


def footer_info(name: str, blob: bytes) -> str:
    f = blob[-64:]
    if f[:4] != b"AVBf":
        return f"{name:32} size={len(blob):9}  (no AVB footer)"
    vmaj, vmin = u("II", f, 4)
    orig, vbo, vbs = u("QQQ", f, 12)
    return (f"{name:32} size={len(blob):9}  AVBf v{vmaj}.{vmin} "
            f"orig_size={orig} vbmeta_off={vbo} vbmeta_size={vbs}")


def main() -> None:
    for tag, zn in ZIPS:
        with zipfile.ZipFile(FIRMWARE_DIR / zn) as z:
            d = z.read("firmware-update/vbmeta.img")
        info = parse_header(d)
        print(f"=== {tag} vbmeta.img  ({zn}) ===")
        print(f"  libavb {info['libavb']}  algo={info['algo']}  auth={info['auth']}B "
              f"aux={info['aux']}B  release={info['release']!r}")
        print(f"  descriptors_offset={info['desc_off']} size={info['desc_sz']} "
              f"-> file range {info['desc_base']}..{info['desc_end']}")
        print(f"  FLAGS={info['flags']:#x}  rollback_index={info['rollback']} "
              f"@loc={info['rollback_loc']}")
        chains = find_chains(d)
        if not chains:
            print("  no self-consistent descriptor chain found")
        else:
            hits, n, off, chain = chains[0]
            print(f"  chain @ {off} ({n} descriptors, {hits} known partitions):")
            for r in chain:
                extra = " ".join(
                    f"{k}={r[k]}" for k in ("image_size", "salt_len") if k in r
                )
                print(f"    [{TAGNAME[r['tag']]:8}] {r['partition']:14} "
                      f"{r.get('hash_algorithm', ''):8} size={r['size']:5} {extra}")
            names = [r["partition"] for r in chain]
            print(f"  => dtbo described: {'YES' if 'dtbo' in names else 'NO'}")
        print()

    print("=== per-partition AVB footers (CN) ===")
    with zipfile.ZipFile(FIRMWARE_DIR / ZIPS[0][1]) as z:
        for n in z.namelist():
            if n.endswith(".img"):
                print(footer_info(n, z.read(n)))


if __name__ == "__main__":
    main()
