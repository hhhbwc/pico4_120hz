#!/usr/bin/env python3
"""
Create an experimental copy of the uncompressed ARM64 kernel image.

The branch at kernel offset 0xfb02d4 is a verified signature-related callsite,
but it has not been proven to be the CONFIG_MODULE_SIG_FORCE gate.  This
script is retained for byte-level analysis only and must not be flashed until
the control-flow target is independently confirmed.

The Android boot file stores the kernel payload at raw offset 0x1000, so the
corresponding raw boot-file offset is 0xfb12d4.  The ARM64 Image header is
part of kernel-device.img at +0x38.
"""
import os, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT_IN = os.path.join(os.path.dirname(HERE), "boot-device.img")
BOOT_OUT = os.path.join(HERE, "boot-patched-correct.img")

ANDROID_PAGE_SIZE = 0x1000
IMAGE_HEADER_OFFSET = ANDROID_PAGE_SIZE + 0x38
IMAGE_HEADER_MAGIC = b"ARMd"
KERNEL_PAYLOAD_OFFSET = ANDROID_PAGE_SIZE

# Verified in the uncompressed kernel-device.img signature path.
CBNZ_KERNEL_OFF = 0xfb02d4
CBNZ_BOOT_OFF = KERNEL_PAYLOAD_OFFSET + CBNZ_KERNEL_OFF
CBNZ_ORIGINAL = 0x35000220
CBNZ_PATCHED = 0xd503201f

def main():
    print(f"=== Loading {BOOT_IN} ===")
    with open(BOOT_IN, "rb") as f:
        boot = f.read()
    print(f"  size: {len(boot)} ({hex(len(boot))})")

    # Refuse to operate on a file whose headers do not match the known layout.
    if boot[:8] != b"ANDROID!":
        print("ERROR: missing Android boot magic; refusing to patch")
        sys.exit(1)
    if boot[IMAGE_HEADER_OFFSET:IMAGE_HEADER_OFFSET + 4] != IMAGE_HEADER_MAGIC:
        print("ERROR: missing ARM64 Image magic at 0x1038; refusing to patch")
        sys.exit(1)
    image_kernel_size = struct.unpack_from("<I", boot, 0x08)[0]
    print(f"  Android kernel size: {image_kernel_size:#x}")
    if image_kernel_size < CBNZ_KERNEL_OFF + 4:
        print("ERROR: kernel size does not cover target; refusing to patch")
        sys.exit(1)

    # Verify the expected bytes at the target location
    actual = int.from_bytes(boot[CBNZ_BOOT_OFF:CBNZ_BOOT_OFF + 4], "little")
    print(f"\n=== Verification ===")
    print(f"  Expected at {CBNZ_BOOT_OFF:#x}: 0x{CBNZ_ORIGINAL:08x} (cbnz w0)")
    print(f"  Actual   at {CBNZ_BOOT_OFF:#x}: 0x{actual:08x}")
    if actual != CBNZ_ORIGINAL:
        print(f"\n  ERROR: Actual bytes don't match expected!")
        print(f"  The kernel may have been repacked or the offset is wrong.")
        print(f"  Refusing to patch.  Exit.")
        sys.exit(1)
    print(f"  Match!  Proceeding with patch.")

    # Apply the patch
    boot_patched = bytearray(boot)
    boot_patched[CBNZ_BOOT_OFF:CBNZ_BOOT_OFF + 4] = CBNZ_PATCHED.to_bytes(4, "little")
    print(f"\n=== Patch applied ===")
    print(f"  {CBNZ_BOOT_OFF:#x}: 0x{actual:08x} -> 0x{CBNZ_PATCHED:08x} (nop)")
    print("  This is an unvalidated experimental branch patch; it does not prove enforcement is disabled.")

    # Save
    with open(BOOT_OUT, "wb") as f:
        f.write(boot_patched)
    print(f"\n=== Saved patched boot image ===")
    print(f"  {BOOT_OUT}")
    print(f"  size: {len(boot_patched)} bytes")

    # Verify the patch was applied
    with open(BOOT_OUT, "rb") as f:
        check = f.read()
    patched_val = int.from_bytes(check[CBNZ_BOOT_OFF:CBNZ_BOOT_OFF + 4], "little")
    assert patched_val == CBNZ_PATCHED, "Patch verification failed!"
    print(f"  Verified: {CBNZ_BOOT_OFF:#x} = 0x{patched_val:08x}")

    # Also save a backup of the original boot
    backup = os.path.join(os.path.dirname(HERE), "boot-device.img.bak")
    if not os.path.exists(backup):
        shutil.copy2(BOOT_IN, backup)
        print(f"\n=== Backup saved ===")
        print(f"  {backup}")
    else:
        print(f"\n  Backup already exists: {backup}")

    print(f"\n=== Done ===")
    print("  EXPERIMENTAL ONLY: do not flash this image yet.")
    print("  The branch target still needs control-flow confirmation.")


if __name__ == "__main__":
    main()
