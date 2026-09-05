#!/usr/bin/env python3
"""Audit the PICO refresh-selector source and APK without touching a device."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


EXPECTED_SOURCES = Path("app/src/main/java/com/picoxr/refreshselector/RefreshRateHook.java")
EXPECTED_SCOPE_ARRAYS = Path("app/src/main/res/values/arrays.xml")
DEFAULT_APK = Path("app/build/outputs/apk/debug/app-debug.apk")
REQUIRED_SOURCES = (
    "private static final int[] RATES = {72, 90};",
    "private static final String PENDING_RATE_KEY",
    "private static final String STOCK_TARGET_KEY",
    "pending != target",
)
FORBIDDEN_SOURCES = (
    "jdi493120",
    "pico_refresh_selector_choice",
    "Unsupported refresh rate",
    'XposedHelpers.callStaticMethod(utils, "v1", true)',
)
FORBIDDEN_PACKAGE_PATTERNS = (
    "jdi493120",
    "pico_refresh_selector_choice",
    "Unsupported refresh rate",
    "requested 120 Hz",
    "injected native popup rates=[72, 90, 120]",
)


class AuditFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def grep_bytes(data: bytes, needle: str) -> bool:
    return needle.encode("utf-8") in data


def audit_sources(root: Path) -> None:
    source = root / EXPECTED_SOURCES
    scopes = root / EXPECTED_SCOPE_ARRAYS
    require(source.is_file(), f"missing {EXPECTED_SOURCES}")
    require(scopes.is_file(), f"missing {EXPECTED_SCOPE_ARRAYS}")

    text = source.read_text(encoding="utf-8")
    manifest_text = scopes.read_text(encoding="utf-8")

    for required in REQUIRED_SOURCES:
        require(required in text, f"source missing invariant: {required}")
    for forbidden in FORBIDDEN_SOURCES:
        require(forbidden not in text, f"source contains forbidden pattern: {forbidden}")

    items = re.findall(r"<item>(.*?)</item>", manifest_text, re.DOTALL)
    require(items == ["com.picovr.settings"], f"unexpected Xposed scope: {items!r}")


def dex_files(apk: Path):
    with zipfile.ZipFile(apk) as archive:
        names = [name for name in archive.namelist() if re.fullmatch(r"classes\d*\.dex", name)]
        require(names, "APK has no classes*.dex")
        for name in sorted(names):
            yield name, archive.read(name)


def audit_apk(apk: Path) -> None:
    require(apk.is_file(), f"missing {apk}")
    package_dexes = {name: data for name, data in dex_files(apk)}
    module_names = [
        name for name, data in package_dexes.items() if grep_bytes(data, "PicoRefreshSelector")
    ]
    require(len(module_names) == 1, f"expected one module dex, found {module_names}")

    for forbidden in FORBIDDEN_PACKAGE_PATTERNS:
        require(
            not any(grep_bytes(data, forbidden) for name, data in package_dexes.items()),
            f"APK contains forbidden pattern: {forbidden}",
        )

    required = [
        "requested stock-only",
        "PicoRefreshSelector: invalid or absent refresh restore ticket",
        "PicoRefreshSelector: deferred stock restore pending=",
    ]
    module_dex = package_dexes[module_names[0]]
    for pattern in required:
        require(grep_bytes(module_dex, pattern), f"module dex missing {pattern}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=Path.cwd(), type=Path, help="project root")
    parser.add_argument("--apk", type=Path, help="APK to audit")
    args = parser.parse_args()

    root = args.root.resolve()
    apk = (args.apk or root / DEFAULT_APK).resolve()
    expected_hash = "81d92a15b18bf42f734d94296e4390f1ec0f095288b3a2a14114815c8826b0c5"

    try:
        audit_sources(root)
        audit_apk(apk)
        actual_hash = sha256(apk)
        require(actual_hash == expected_hash, f"APK hash changed: {actual_hash}")
    except AuditFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"PASS: source invariants, APK contents, and SHA-256 {actual_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
