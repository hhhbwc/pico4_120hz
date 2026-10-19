"""Disassemble a kernel function by symbol name, from the extracted boot.img.

Usage:
    python kdis.py SYMBOL [SYMBOL ...]

The ARM64 Image maps a virtual address to a file offset as
    file_offset = va - _text_va
because arch/arm64's vmlinux.lds.S defines `_text = .` at the top of
.head.text, i.e. at byte 0 of the Image (verified: the Image header's
"ARMd" magic sits at 0x38 and the byte at _text is the .head.text branch).
"""
from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG = HERE.parent / ".boot-cn.img"
SYMS = HERE / "kallsyms-5.13.7.txt"
PAGE = 4096


def load_image() -> bytes:
    data = IMG.read_bytes()
    (ks,) = struct.unpack("<I", data[8:12])
    return data[PAGE : PAGE + ks]


def symbols() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in SYMS.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        out.setdefault(parts[2], addr)
    return out


def main() -> int:
    from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs

    names = sys.argv[1:]
    if not names:
        print(__doc__)
        return 1
    img = load_image()
    syms = symbols()
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = False

    for name in names:
        va = syms.get(name)
        if va is None:
            print(f"!! {name}: not in kallsyms")
            continue
        text = 0xFFFFFF9021280000
        off = va - text
        # a function ends at the next symbol
        end = va
        for other in sorted(syms.values()):
            if other > va:
                end = other
                break
        n = min(end - va, 0x800)
        code = img[off : off + n]
        print(f"\n=== {name}  va={va:#x}  file={off:#x}  size={n} ===")
        for insn in md.disasm(code, va):
            print(f"{insn.address:#x}  {insn.mnemonic:<10} {insn.op_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
