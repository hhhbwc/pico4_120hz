#!/usr/bin/env python3
"""Validate kallsyms and patch sig_enforce data variable in an ARM64 boot image.

The kernel inlines is_module_sig_enforced() into module_sig_check, so patching
the function body has no effect.  Instead we zero the sig_enforce bool variable
itself, which is read via adrp+ldrb at the inlined call site.
"""
from pathlib import Path
import hashlib
import struct
import sys

HERE = Path(__file__).resolve().parent
BOOT_IN = HERE / "boot-current-device.img"
BOOT_OUT = HERE / "boot-current-sig-data-disabled.img"
KERNEL_FILE = HERE.parent / "kernel-device.img"

ANDROID_MAGIC = b"ANDROID!"
KERNEL_PAYLOAD_OFFSET = 0x1000
IMAGE_MAGIC_OFFSET_IN_KERNEL = 0x38
IMAGE_MAGIC = b"ARMd"

N_SYMS = 123242
ADDRESSES_START = 0x1629400
NAMES_START = 0x16A1C00
MARKERS_START = 0x1839C00
TOKEN_TABLE_START = 0x183AC00
TOKEN_INDEX_START = 0x183B000
TARGET_NAME = "is_module_sig_enforced"
TARGET_INDEX = 4364
TARGET_REL_OFFSET = 0xEA358

# sig_enforce data variable: adrp x8,#0x1fb6000; ldrb w0,[x8,#0xd8]
# -> file offset 0x1fb60d8 in kernel-device.img
SIG_ENFORCE_KERNEL_OFF = 0x1FB60D8
SIG_ENFORCE_BOOT_OFF = KERNEL_PAYLOAD_OFFSET + SIG_ENFORCE_KERNEL_OFF
SIG_ENFORCE_ORIGINAL = 0x01
SIG_ENFORCE_PATCHED = 0x00

# Also patch the function body for belt-and-suspenders: if the function is
# ever called directly, make it return false.
FUNC_KERNEL_OFF = TARGET_REL_OFFSET
FUNC_BOOT_OFF = KERNEL_PAYLOAD_OFFSET + FUNC_KERNEL_OFF
FUNC_ORIGINAL = bytes.fromhex("68 f6 00 90 00 61 43 39 c0 03 5f d6")
FUNC_PATCHED = bytes.fromhex("00 00 80 52 c0 03 5f d6")


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_token_table(data):
    tokens = []
    off = TOKEN_TABLE_START
    for _ in range(256):
        end = data.find(b"\0", off)
        if end < 0:
            raise ValueError("unterminated kallsyms token table")
        tokens.append(data[off:end])
        off = end + 1
    return tokens


def decode_name(data, name_off, tokens):
    length = data[name_off]
    raw = data[name_off + 1:name_off + 1 + length]
    expanded = b"".join(tokens[x] for x in raw)
    if not expanded:
        raise ValueError("empty kallsyms name")
    return expanded[1:].decode("ascii"), name_off + 1 + length


def validate_tables(kernel):
    if len(kernel) <= TOKEN_INDEX_START + 512:
        raise ValueError("kernel is too small for kallsyms tables")
    if kernel[IMAGE_MAGIC_OFFSET_IN_KERNEL:IMAGE_MAGIC_OFFSET_IN_KERNEL + 4] != IMAGE_MAGIC:
        raise ValueError("missing ARM64 Image magic")
    tokens = decode_token_table(kernel)
    token_index = [struct.unpack_from("<H", kernel, TOKEN_INDEX_START + 2 * i)[0]
                   for i in range(256)]
    if token_index[0] != 0 or max(token_index) > 895:
        raise ValueError("invalid kallsyms token index")
    for i, idx in enumerate(token_index):
        if idx >= sum(len(t) + 1 for t in tokens):
            raise ValueError(f"token index {i} is out of range")
    off = NAMES_START
    target = None
    decoded = 0
    while decoded < N_SYMS:
        if off >= MARKERS_START:
            raise ValueError("kallsyms names overrun marker table")
        length = kernel[off]
        if length == 0:
            raise ValueError(f"zero-length kallsyms record at index {decoded}")
        name, next_off = decode_name(kernel, off, tokens)
        if decoded == TARGET_INDEX:
            target = (name, off, next_off)
        off = next_off
        decoded += 1
    if any(kernel[off:MARKERS_START]):
        raise ValueError(f"nonzero data between names end {off:#x} and markers")
    if target is None or target[0] != TARGET_NAME:
        raise ValueError(f"target symbol mismatch: {target}")
    rel = u32(kernel, ADDRESSES_START + TARGET_INDEX * 4)
    if rel != TARGET_REL_OFFSET:
        raise ValueError(f"target address offset {rel:#x} != {TARGET_REL_OFFSET:#x}")
    return target, rel


def verify_and_patch():
    boot = BOOT_IN.read_bytes()
    kernel = KERNEL_FILE.read_bytes()
    if boot[:8] != ANDROID_MAGIC:
        raise ValueError("input is not an Android boot image")
    kernel_size = u32(boot, 8)
    page_size = u32(boot, 0x0C)
    if page_size != 0x8000:
        raise ValueError(f"unexpected Android page size {page_size:#x}")
    if kernel_size != len(kernel):
        raise ValueError(f"kernel size {kernel_size:#x} != extracted {len(kernel):#x}")
    kernel_payload = boot[KERNEL_PAYLOAD_OFFSET:KERNEL_PAYLOAD_OFFSET + len(kernel)]
    legacy_kernel_off = 0xFB02D4
    allowed = set(range(legacy_kernel_off, legacy_kernel_off + 4))
    kernel_diffs = [i for i, (a, b) in enumerate(zip(kernel, kernel_payload))
                    if a != b and i not in allowed]
    if kernel_diffs:
        raise ValueError(f"boot kernel has unexpected differences, first={kernel_diffs[0]:#x}")
    if kernel_payload[legacy_kernel_off:legacy_kernel_off + 4] != bytes.fromhex("1f 20 03 d5"):
        raise ValueError("known legacy signature patch is not present as expected")
    target, rel = validate_tables(kernel)

    # Verify sig_enforce data variable
    sig_val = boot[SIG_ENFORCE_BOOT_OFF]
    if sig_val != SIG_ENFORCE_ORIGINAL:
        raise ValueError(
            f"sig_enforce at {SIG_ENFORCE_BOOT_OFF:#x} = {sig_val:#x}, expected {SIG_ENFORCE_ORIGINAL:#x}")

    # Verify function body (should be original, since device boot has the
    # pre-function-patch state from the initial flash)
    func_actual = boot[FUNC_BOOT_OFF:FUNC_BOOT_OFF + len(FUNC_ORIGINAL)]
    if func_actual != FUNC_ORIGINAL:
        raise ValueError(
            f"function body at {FUNC_BOOT_OFF:#x}: {func_actual.hex()}, expected {FUNC_ORIGINAL.hex()}")

    legacy = boot[0xFB12D4:0xFB12D8]
    if legacy not in (bytes.fromhex("20 02 00 35"), bytes.fromhex("1f 20 03 d5")):
        raise ValueError(f"legacy signature-path bytes changed unexpectedly: {legacy.hex()}")

    out = bytearray(boot)
    # Patch 1: zero the sig_enforce data variable (1 byte)
    out[SIG_ENFORCE_BOOT_OFF] = SIG_ENFORCE_PATCHED
    # Patch 2: override function body to mov w0,#0; ret (8 bytes)
    out[FUNC_BOOT_OFF:FUNC_BOOT_OFF + len(FUNC_PATCHED)] = FUNC_PATCHED

    expected_changes = (
        set(range(SIG_ENFORCE_BOOT_OFF, SIG_ENFORCE_BOOT_OFF + 1)) |
        set(range(FUNC_BOOT_OFF, FUNC_BOOT_OFF + len(FUNC_PATCHED)))
    )
    actual_changes = {i for i, (a, b) in enumerate(zip(boot, out)) if a != b}
    if actual_changes != expected_changes:
        unexpected = actual_changes - expected_changes
        missing = expected_changes - actual_changes
        raise ValueError(
            f"change mismatch: unexpected={sorted(unexpected)[:10]} "
            f"missing={sorted(missing)[:10]}")

    BOOT_OUT.write_bytes(out)
    check = BOOT_OUT.read_bytes()
    if check[SIG_ENFORCE_BOOT_OFF] != SIG_ENFORCE_PATCHED:
        raise ValueError("output sig_enforce verification failed")
    if check[FUNC_BOOT_OFF:FUNC_BOOT_OFF + len(FUNC_PATCHED)] != FUNC_PATCHED:
        raise ValueError("output function body verification failed")

    print(f"target symbol: {target[0]} index={TARGET_INDEX} relative={rel:#x}")
    print(f"sig_enforce data: kernel {SIG_ENFORCE_KERNEL_OFF:#x} boot {SIG_ENFORCE_BOOT_OFF:#x}")
    print(f"  {SIG_ENFORCE_ORIGINAL:#x} -> {SIG_ENFORCE_PATCHED:#x}")
    print(f"function body:    kernel {FUNC_KERNEL_OFF:#x} boot {FUNC_BOOT_OFF:#x}")
    print(f"  {FUNC_ORIGINAL.hex()} -> {FUNC_PATCHED.hex()}")
    print(f"total changed bytes: {len(actual_changes)}")
    print(f"input sha256:  {hashlib.sha256(boot).hexdigest()}")
    print(f"output sha256: {hashlib.sha256(check).hexdigest()}")
    print(f"output: {BOOT_OUT}")


if __name__ == "__main__":
    try:
        verify_and_patch()
    except (OSError, ValueError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
