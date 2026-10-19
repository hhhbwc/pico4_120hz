"""Offline firmware forensics for the PICO 4 120 Hz project.

Parses, from the official 5.13.7 firmware zip (CN and INTL):
  * firmware-update/vbmeta.img  -> AVB flags and descriptors
  * boot.img                    -> ARM64 header, kernel version, AVB footer
  * kernel IKCONFIG             -> already extracted to config-5.13.7.txt

Usage: python fw_forensics.py
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
DOWNLOADS = pathlib.Path("D:/newpico/downloads")
FIRMWARE = {
    "CN": "5.13.7_CN_b9650.zip",
    "INTL": "5.13.7_INTL_b9665.zip",
}


def read_member(zip_path: pathlib.Path, member: str) -> bytes | None:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if member not in names:
            return None
        return z.read(member)


def parse_vbmeta(d: bytes) -> dict:
    maj, mi = struct.unpack("<II", d[4:12])
    auth_sz, aux_sz = struct.unpack("<QQ", d[12:28])
    (algo,) = struct.unpack("<I", d[28:32])
    fields = struct.unpack("<11Q", d[32:120])
    (ho, hs, so, ss, po, ps, mo, ms, do, ds, ri) = fields
    flags, rl = struct.unpack("<II", d[120:128])
    release = d[128:176].split(b"\x00")[0].decode("utf-8", "replace")
    return dict(
        size=len(d), libavb=f"{maj}.{mi}", algo=algo, auth=auth_sz, aux=aux_sz,
        desc_off=do, desc_size=ds, flags=flags, rollback=ri, release=release,
        hashtree_disabled=bool(flags & 1), verification_disabled=bool(flags & 2),
    )


def parse_boot(d: bytes) -> dict:
    out = {}
    out["magic"] = d[:8]
    (ks, ka, rs, ra, ss, sa, ta, ps, hv, osv) = struct.unpack("<10I", d[8:48])
    out.update(kernel_size=ks, ramdisk_size=rs, page_size=ps, header_version=hv)
    out["name"] = d[48:64].split(b"\x00")[0].decode("utf-8", "replace")
    out["cmdline"] = d[64:576].split(b"\x00")[0].decode("utf-8", "replace")
    k = d[ps : ps + ks]
    m = re.search(rb"Linux version [0-9][^\x00]{0,140}", k)
    out["kernel_version"] = m.group().decode("utf-8", "replace") if m else None
    out["arm64_magic"] = d[0x38:0x3C]
    # AVB footer lives in the last 64 bytes of a partition image
    f = d[-64:]
    if f[:4] == b"AVBf":
        (vmaj, vmin) = struct.unpack("<II", f[4:12])
        (orig, vbo, vbs) = struct.unpack("<QQQ", f[12:36])
        out.update(avb_footer=dict(version=f"{vmaj}.{vmin}", original_image_size=orig,
                                   vbmeta_offset=vbo, vbmeta_size=vbs))
    else:
        out["avb_footer"] = None
    return out


def main() -> int:
    for tag, name in FIRMWARE.items():
        zp = DOWNLOADS / name
        if not zp.is_file():
            print(f"{tag}: {zp} missing")
            continue
        print(f"\n########## {tag}  ({name}) ##########")

        vb = read_member(zp, "firmware-update/vbmeta.img")
        if vb:
            info = parse_vbmeta(vb)
            print(f"vbmeta.img   size={info['size']} libavb={info['libavb']} "
                  f"algo={info['algo']} release={info['release']!r}")
            print(f"             FLAGS={info['flags']:#x} "
                  f"hashtree_disabled={info['hashtree_disabled']} "
                  f"verification_disabled={info['verification_disabled']} "
                  f"descriptors_size={info['desc_size']} rollback={info['rollback']}")
            if info["desc_size"] == 0:
                print("             -> ZERO DESCRIPTORS: no partition is bound to a")
                print("                hash/hashtree, so AVB verification is inert.")

        boot = read_member(zp, "boot.img")
        if boot:
            info = parse_boot(boot)
            print(f"boot.img     magic={info['magic']} arm64={info['arm64_magic']} "
                  f"page={info['page_size']} kernel={info['kernel_size']} "
                  f"ramdisk={info['ramdisk_size']} hdr_v={info['header_version']}")
            print(f"             kernel: {info['kernel_version']}")
            print(f"             name={info['name']!r}")
            print(f"             avb_footer: {info['avb_footer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
