#!/usr/bin/env python3
"""Audit the PICO refresh-selector source, Magisk module, and (optionally) APK.

Checks the v1.0.x invariants: the lock-120 selector semantics in the Xposed
hook, the component-wise firmware gate + stock-lib whitelist in customize.sh,
and the boot-time panel resync in service.sh. Exits non-zero on the first
failure.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

HOOK_SOURCE = Path("app/src/main/java/com/picoxr/refreshselector/RefreshRateHook.java")
SCOPE_ARRAYS = Path("app/src/main/res/values/arrays.xml")
MAGISK_DIR = Path("magisk-module")

# Lock-120 selector semantics (v1.0.0+): three rates, explicit vendor state,
# pinning through SurfaceFlinger with PICO's private marker.
REQUIRED_HOOK = (
    "private static final int[] RATES = {72, 90, 120};",
    "private static final String CHOICE_KEY = \"pico_refresh_selector_choice\";",
    "private static final String LIVE_SWITCH_KEY = \"pico_refresh_selector_live_switch\";",
    "PICO_CONFIG_MARKER = 3",
    "new int[] {configIndex, PICO_CONFIG_MARKER}",
    "case 120: type = \"jdi493120\";",
    "sdk_refreshRate",
)
FORBIDDEN_HOOK = (
    "private static final int[] RATES = {72, 90};",  # pre-v7 stock-only era
    "PENDING_RATE_KEY",
    "STOCK_TARGET_KEY",
    '"v1", true',  # Utils.v1 writes jdi49390 on Phoenix, never use for 120
)

# Firmware gate must be component-wise, never a whole-fingerprint match.
REQUIRED_CUSTOMIZE = (
    '"$(getprop ro.product.device)" != "PICOA8110"',
    "5.13.7*",
    '"$(getprop ro.pvr.hmd.type)" != "SHARP5K"',
    "ro.build.id",  # firmware version lives here; incremental is smartcm.<ts>
    "ro.build.version.incremental",  # kept only as a fallback
    "BASE_LIB_SHA256=",
    "c290a9f51214ff37b415c309c5facf80542024d40c22e5ae3cdeff9825a31fef",
    "PATCHED_LIB_SHA256=",  # accept the active overlay on upgrade/reinstall
    "STOCK_DTBO_CN=",  # CN (Phoenix) and global (Phoenix_ovs) order the same
    "STOCK_DTBO_OVS=",  # sixteen entries differently; match on stock hash
    "STOCK_DTBO_INTL=",
    "V6_DTBO_CN=",
    "V6_DTBO_OVS=",
    "V6_DTBO_INTL=",
    "DTBO_ENTRY=",  # per-variant image, never a single dtbo.img
    "screen_fix_once",  # one-shot resync armed only when dtbo is flashed
    "Bundled libpxrhmdservice.so is corrupt",  # extracted overlay verified
    "PREV_LIB_SHA256=",  # v1.0.0 lib accepted on upgrade
    "uninstall.sh",  # stock restore runs from the module dir
    "dtbo-stock-cn.img",  # verified per-variant stock images for uninstall
    "dtbo-stock-ovs.img",
    "dtbo-ovs.img",  # international Phoenix_ovs 120Hz image
    "Bundled $STOCK_ENTRY is corrupt",  # error is explicit for either variant
    "sha256_file",
)
FORBIDDEN_CUSTOMIZE = (
    "EXPECTED_FINGERPRINT=",  # whole-string gate rejected Phoenix_ovs (issue #2)
    "smartcm.1761755159",
)

REQUIRED_SERVICE = (
    "sdk_refreshRate,120",
    "sys.pvr.display.type 120.000000",
    "MODDIR/screen_fix_once",  # one-shot resync, first boot after flash only
    "NOSCREENFIX",  # documented opt-out file
    "KEYCODE_POWER",
    "os_eyebuffer_width,2160",  # native eye buffer, GPU headroom
    "sdk_eyebufferX,2160",
)

REQUIRED_MODULE_PROP = (
    "id=pico4_120hz",
)

# Strings the running dex must carry (module identity + chosen-rate restore).
REQUIRED_DEX_STRINGS = (
    "PicoRefreshSelector",
    "pico_refresh_selector_choice",
    "sdk_refreshRate",
)


class AuditFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def read(path: Path) -> str:
    require(path.is_file(), f"missing {path}")
    return path.read_text(encoding="utf-8")


def audit_sources(root: Path) -> None:
    hook = read(root / HOOK_SOURCE)
    for required in REQUIRED_HOOK:
        require(required in hook, f"hook source missing invariant: {required}")
    for forbidden in FORBIDDEN_HOOK:
        require(forbidden not in hook, f"hook source contains forbidden pattern: {forbidden}")

    items = re.findall(r"<item>(.*?)</item>", read(root / SCOPE_ARRAYS), re.DOTALL)
    require(items == ["com.picovr.settings"], f"unexpected Xposed scope: {items!r}")


def audit_magisk_module(root: Path) -> None:
    customize = read(root / MAGISK_DIR / "customize.sh")
    for required in REQUIRED_CUSTOMIZE:
        require(required in customize, f"customize.sh missing invariant: {required}")
    for forbidden in FORBIDDEN_CUSTOMIZE:
        require(forbidden not in customize, f"customize.sh contains forbidden pattern: {forbidden}")

    service = read(root / MAGISK_DIR / "service.sh")
    for required in REQUIRED_SERVICE:
        require(required in service, f"service.sh missing invariant: {required}")

    module_prop = read(root / MAGISK_DIR / "module.prop")
    for required in REQUIRED_MODULE_PROP:
        require(required in module_prop, f"module.prop missing invariant: {required}")

    # A pinned version string here is what let module.prop ship v1.2.0 while the
    # installer banner and the published zip said v1.2.1 - compare them instead.
    prop_ver = re.search(r"^version=(v[\d.]+)$", module_prop, re.M)
    banner_ver = re.search(r"Pico4 120Hz Display Unlock (v[\d.]+)", customize)
    require(prop_ver is not None and banner_ver is not None
            and prop_ver.group(1) == banner_ver.group(1),
            f"module.prop version and installer banner disagree: "
            f"{prop_ver and prop_ver.group(1)} vs {banner_ver and banner_ver.group(1)}")
    require(re.search(r"^versionCode=\d+$", module_prop, re.M) is not None,
            "module.prop versionCode is missing or not numeric")


def audit_apk(root: Path, apk: Path, expected_hash: str | None) -> None:
    require(apk.is_file(), f"missing {apk} (build it first or pass --apk)")
    with zipfile.ZipFile(apk) as archive:
        dexes = {name: archive.read(name) for name in archive.namelist()
                 if re.fullmatch(r"classes\d*\.dex", name)}
    require(dexes, "APK has no classes*.dex")
    for needle in REQUIRED_DEX_STRINGS:
        require(
            any(needle.encode("utf-8") in data for data in dexes.values()),
            f"APK dexes missing string: {needle}",
        )
    if expected_hash:
        actual = hashlib.sha256(apk.read_bytes()).hexdigest()
        require(actual == expected_hash, f"APK hash changed: {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path, help="pico-refresh-selector project root")
    parser.add_argument("--apk", type=Path, help="APK to audit (default: skip APK checks)")
    parser.add_argument("--expect-apk-hash", help="pin the APK SHA-256")
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        audit_sources(root)
        print("PASS: Xposed hook source + scope")
        audit_magisk_module(root)
        print("PASS: Magisk module (customize.sh gate, service.sh resync, module.prop)")
        if args.apk:
            audit_apk(root, args.apk.resolve(), args.expect_apk_hash)
            print("PASS: APK contents")
    except AuditFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
