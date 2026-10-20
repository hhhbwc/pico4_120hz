#!/usr/bin/env bash
# Dry-run harness for the Magisk installer and the boot-time service script.
#
# Why this exists: the installer only ever runs inside Magisk's recovery
# environment, on a real device, with a real dtbo partition.  Every bug found
# so far (the firmware gate that aborted on 100% of units, the CN/global dtbo
# mismatch, the self-abort on reinstall) was found by reading code, after the
# fact.  This harness mocks the device so the branches can be executed.
#
# The installer is executed verbatim: the tests source it with getprop,
# toybox, dd, unzip, abort, ui_print, set_perm* and friends replaced by shell
# functions reading a scenario description.  Nothing about customize.sh is
# reimplemented here, so the tests cannot drift away from the shipped logic.
#
# Usage:  bash pico-refresh-selector/tools/dryrun_installer.sh [-v]

set -u

# Resolve the script directory without dirname: some Git-for-Windows setups
# provide a dirname shim that does not skip the "--" separator, returns two
# lines, and turns HERE into an invalid path.
SCRIPT_PATH=${BASH_SOURCE[0]}
case "$SCRIPT_PATH" in
    */*) HERE=$(cd -- "${SCRIPT_PATH%/*}" && pwd) || {
             echo "cannot resolve the script directory" >&2; exit 1; } ;;
    *)   HERE=$(pwd) ;;
esac
MODULE_SRC="$HERE/../magisk-module"
CUSTOMIZE="$MODULE_SRC/customize.sh"
SERVICE="$MODULE_SRC/service.sh"
VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

PASS=0
FAIL=0
FAILED_NAMES=()

# Real hashes the installer asserts on, read by key name (the file's declaration
# order is not the order anyone expects, and positional parsing silently
# mis-binds every fixture). Deriving them from customize.sh keeps the harness
# honest: edit the installer and the tests follow.
hash_of() {
    local key="$1"
    tr -d '\r' < "$CUSTOMIZE" \
        | sed -nE "s|^${key}=\"([0-9a-f]+)\"$|\\1|p" | head -1
}
STOCK_CN=$(hash_of STOCK_DTBO_CN)
STOCK_OVS=$(hash_of STOCK_DTBO_OVS)
STOCK_INTL=$(hash_of STOCK_DTBO_INTL)
V6_CN=$(hash_of V6_DTBO_CN)
V6_OVS=$(hash_of V6_DTBO_OVS)
V6_INTL=$(hash_of V6_DTBO_INTL)
BASE_LIB=$(hash_of BASE_LIB_SHA256)
PATCHED_LIB=$(hash_of PATCHED_LIB_SHA256)
PREV_LIB=$(hash_of PREV_LIB_SHA256)
for v in STOCK_CN STOCK_OVS STOCK_INTL V6_CN V6_OVS V6_INTL BASE_LIB PATCHED_LIB PREV_LIB; do
    if [ -z "${!v}" ]; then
        echo "failed to extract a hash from customize.sh ($v)" >&2
        exit 1
    fi
done

# ----------------------------------------------------------------------------
# Scenario description: a set of variables read by the mocked device commands.
#   SCEN_DEVICE      ro.product.device
#   SCEN_BUILD_ID    ro.build.id
#   SCEN_INCREMENTAL ro.build.version.incremental
#   SCEN_PANEL       ro.pvr.hmd.type
#   SCEN_DTBO_HASH   hash returned for the dtbo partition
#   SCEN_LIB_HASH    hash returned for the base lib
#   SCEN_DTBO_BLOCK  whether the dtbo node is a block device
#   SCEN_DD_FAIL     "flash" makes dd fail
#   SCEN_BAD_ZIP     the bundled image hashes wrong
# ----------------------------------------------------------------------------

# service.sh records into this directory instead of shell variables: it runs its
# body inside "( ... ) &", so every variable it sets dies with the subshell.
SPOOL=$(mktemp -d)
# ----------------------------------------------------------------------------
# A real block-device node for the dtbo partition.
#
# customize.sh guards with `[ ! -b "$DTBO_PART" ]`, and `[` is a bash builtin
# that cannot be overridden safely (redefining it segfaults the shell). So the
# harness makes the guard honest the honest way: mknod creates an actual block
# node under a temp tree, and DTBO_PART is pointed at it through the one
# variable the installer reads it from. No installer logic is reimplemented or
# patched, so the test cannot drift from the shipped script.
# ----------------------------------------------------------------------------
FAKE_ROOT=$(mktemp -d)
mkdir -p "$FAKE_ROOT/dev/block/by-name"
DTBO_NODE="$FAKE_ROOT/dev/block/by-name/dtbo"
mknod "$DTBO_NODE" b 7 200 2>/dev/null || {
    echo "cannot create a block node (mknod unavailable); skipping" >&2
    rm -rf "$FAKE_ROOT"; exit 77
}
if [ ! -b "$DTBO_NODE" ]; then
    echo "mknod did not produce a block device; skipping" >&2
    rm -rf "$FAKE_ROOT"; exit 77
fi
# customize.sh hardcodes DTBO_PART, so run it against a copy whose single
# DTBO_PART assignment is redirected at the fake node. The substitution is
# asserted to be exactly one line, and nothing else is touched.
CUSTOMIZE_RUN="$FAKE_ROOT/customize.sh"
# Two redirects, both required because the harness runs on a desktop Linux-ish
# shell rather than in Magisk's recovery environment:
#   DTBO_PART  must be a block device we control, so the [ ! -b ] guard is real
#   TOYBOX     customize.sh calls /system/bin/toybox by absolute path, and a
#               shell function cannot intercept an absolute path
# Both substitutions are asserted to be exactly one line, so a future edit to
# either line makes this harness fail loudly instead of silently testing nothing.
# Rewrite the two device-specific lines. Python does the substitution because
# sed cannot copy a literal "$(...)" into the replacement text without treating
# it as its own syntax.
# Python is used only for the two literal substitutions below. Probe the
# interpreter instead of trusting PATH order: on Windows "python3" can be the
# Microsoft Store stub, which is not a usable Python.
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    for candidate in python3 python py; do
        if command -v "$candidate" >/dev/null 2>&1 \
                && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
            PY=$candidate
            break
        fi
    done
fi
if [ -z "$PY" ]; then
    echo "no working Python 3 found; set PYTHON=/path/to/python3" >&2
    rm -rf "$FAKE_ROOT"; exit 1
fi
"$PY" - "$CUSTOMIZE" "$CUSTOMIZE_RUN" "$DTBO_NODE" <<'PYEOF'
import sys
src, dst, node = sys.argv[1], sys.argv[2], sys.argv[3]
# newline="" on read keeps CRLF visible; the copy must be LF because the shell
# cannot parse CRLF (the same reason build_zip.py normalises its entries).
text = open(src, encoding="utf-8", newline="").read().replace("\r\n", "\n")
subs = [
    ('DTBO_PART="/dev/block/by-name/dtbo"', f'DTBO_PART="{node}"'),
    # Replace the absolute-path applet call with a bare `toybox`, so the
    # harness's shell function takes effect. Going through $TOYBOX would be
    # resolved by PATH inside the command substitution, where functions are not
    # inherited -- that path fails with 127.
    ('output=$(/system/bin/toybox sha256sum -b "$1" 2>/dev/null)',
     'output=$(toybox sha256sum -b "$1" 2>/dev/null)'),
]
for old, new in subs:
    n = text.count(old)
    if n != 1:
        sys.exit(f"expected exactly one occurrence of {old!r}, found {n}")
    text = text.replace(old, new)
open(dst, "w", encoding="utf-8", newline="\n").write(text)
PYEOF
if [ $? -ne 0 ] || [ ! -s "$CUSTOMIZE_RUN" ]; then
    echo "failed to build the redirected installer; refusing to run it" >&2
    rm -rf "$FAKE_ROOT"; exit 1
fi
# BASE_LIB is read with a plain file test and only ever hashed (never read), so
# the mock answers by basename and no real file is needed for it.

reset_scenario() {
    SCEN_DEVICE=PICOA8110
    SCEN_BUILD_ID=5.13.7
    SCEN_INCREMENTAL=smartcm.1761818300
    SCEN_PANEL=SHARP5K
    SCEN_DTBO_HASH="$STOCK_CN"
    SCEN_STOCK_HASH="$STOCK_CN"
    SCEN_LIB_HASH="$BASE_LIB"
    SCEN_DTBO_BLOCK=1
    SCEN_DD_FAIL=""
    SCEN_BAD_ZIP=0
    SCEN_BAD_MODULE_LIB=0
    SCEN_CONFIG_SERVICE_OK=1
    ABORT_MSG=""
    MODPATH=""
    TMPDIR=""
    BACKUP_HASH=""
}

# --- mocked device commands -------------------------------------------------
# shellcheck disable=SC2016
getprop() {
    case "$1" in
        ro.product.device)          echo "$SCEN_DEVICE" ;;
        ro.build.id)                echo "$SCEN_BUILD_ID" ;;
        ro.build.version.incremental) echo "$SCEN_INCREMENTAL" ;;
        ro.pvr.hmd.type)            echo "$SCEN_PANEL" ;;
        # service.sh spins on this one; a mock that returns "" hangs the harness
        sys.boot_completed)         echo "${SCEN_BOOT_COMPLETED:-1}" ;;
        *)                          echo "" ;;
    esac
}
# Side effects the installer must produce are recorded to the spool, not to shell
# variables: customize.sh runs inside a subshell here, so a variable the mock
# increments is discarded when that subshell exits and every assertion sees zero.
record() { echo "$1" >> "$SPOOL/$2"; }

ui_print() {
    record "$*" ui
    [ "$VERBOSE" = 1 ] && echo "    [ui] $*"
    return 0
}
# abort() runs inside run_installer's subshell, so the message cannot travel back
# through a variable. The installer is executed with `set -e` semantics below, so
# a non-zero exit is what the caller observes; the message goes to a spool file.
abort() {
    printf '%s\n' "$*" > "$SPOOL/abort"
    echo "    [abort] $*"
    exit 9
}
set_perm() { return 0; }
set_perm_recursive() { return 0; }
mount_ext_rw() { return 0; }
# The real /sdcard/Download path does not exist on the host, and the installer
# treats chmod as best-effort. Mock it so the harness tests the installer's
# logic rather than this machine's filesystem. SCEN_CHMOD_FAIL can still force
# the failure path if a future test needs it.
chmod() {
    if [ "${SCEN_CHMOD_FAIL:-0}" = "1" ]; then return 1; fi
    return 0
}
sync() { return 0; }

# toybox sha256sum -b <file>: the installer always hashes a real path, so the
# mock answers by path rather than by content. Matching on the basename keeps it
# correct regardless of where the harness roots those paths.
# The scenario-to-hash mapping. Keyed by a substring of the basename rather than
# the exact basename: the Windows shim that wraps mktemp/mknod resolves the fake
# partition node to a ".lnk" symlink, so an exact match on "dtbo" would miss.
# Order matters -- the most specific pattern has to win.
fixture_hash() {
    # The extracted module lib is the patched one shipped in the zip, while
    # $SCEN_LIB_HASH describes the system lib the installer checks first.
    if [ -n "${MODPATH:-}" ]; then
        case "$1" in
            "$MODPATH"/dtbo-stock.img) echo "$SCEN_STOCK_HASH"; return 0 ;;
            "$MODPATH"/*)
                if [ "$SCEN_BAD_MODULE_LIB" = "1" ]; then
                    echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
                else
                    echo "$PATCHED_LIB"
                fi
                return 0 ;;
        esac
    fi
    local base="${1##*/}"
    case "$base" in
        *dtbo-stock-backup.img) echo "$BACKUP_HASH" ;;
        dtbo-cn.img*)           if [ "$SCEN_BAD_ZIP" = 1 ]; then echo "0000000000000000000000000000000000000000000000000000000000000000"; else echo "$V6_CN"; fi ;;
        dtbo-ovs.img*)          if [ "$SCEN_BAD_ZIP" = 1 ]; then echo "0000000000000000000000000000000000000000000000000000000000000000"; else echo "$V6_OVS"; fi ;;
        dtbo-stock-cn.img*)     echo "$STOCK_CN" ;;
        dtbo-stock-ovs.img*)    echo "$STOCK_OVS" ;;
        dtbo-intl.img*)         if [ "$SCEN_BAD_ZIP" = 1 ]; then echo "0000000000000000000000000000000000000000000000000000000000000000"; else echo "$V6_INTL"; fi ;;
        *libpxrhmdservice.so*)  echo "$SCEN_LIB_HASH" ;;
        dtbo*)                  echo "$SCEN_DTBO_HASH" ;;
        *)                      return 1 ;;
    esac
}

# customize.sh defines its own sha256_file() that shells out to
# /system/bin/toybox, so mocking a shell function is not enough -- the real
# helper must return data. This stands in for toybox. It also honours the
# "-b" flag the installer passes and emits toybox's "hash␠␠name" layout,
# because the installer parses that with `set -- $output`.
toybox() {
    # toybox's first non-flag argument is the applet name; the operands follow.
    local cmd="" a
    for a in "$@"; do
        case "$a" in
            -*) ;;
            *) cmd="$a"; break ;;
        esac
    done
    case "$cmd" in
        sha256sum)
            # Operands are every argument after the applet, minus flags.
            local f=""
            shift
            for a in "$@"; do
                case "$a" in
                    -*) ;;
                    *) [ -z "$f" ] && f="$a" ;;
                esac
            done
            [ -n "$f" ] || return 1
            local h
            h=$(fixture_hash "$f") || return 1
            printf '%s  %s\n' "$h" "$f"
            ;;
        *)
            return 1
            ;;
    esac
}

dd() {
    # Parse "if=<in> of=<out>"; the backup must record the pre-flash hash, the
    # flash must move the partition to the patched hash.
    local src="" dst=""
    for arg in "$@"; do
        case "$arg" in
            if=*)  src="${arg#if=}" ;;
            of=*)  dst="${arg#of=}" ;;
        esac
    done
    [ -n "$dst" ] || return 0
    # NOTE: every branch must end in an explicit `return`. Under `set -e` a
    # trailing `[ cond ] && ...` that evaluates false would abort the installer
    # subshell instead of falling through, which silently skips the flash.
    case "${src##*/}" in
        dtbo-cn.img*)
            if [ "$SCEN_DD_FAIL" = "flash" ]; then return 1; fi
            SCEN_DTBO_HASH="$V6_CN"
            record "cn" flashes
            return 0
            ;;
        dtbo-ovs.img*)
            if [ "$SCEN_DD_FAIL" = "flash" ]; then return 1; fi
            SCEN_DTBO_HASH="$V6_OVS"
            record "ovs" flashes
            return 0
            ;;
        dtbo-intl.img*)
            if [ "$SCEN_DD_FAIL" = "flash" ]; then return 1; fi
            SCEN_DTBO_HASH="$V6_INTL"
            record "intl" flashes
            return 0
            ;;
        dtbo*)
            BACKUP_HASH="$SCEN_DTBO_HASH"
            record "$BACKUP_HASH" backups
            return 0
            ;;
    esac
    return 0
}

unzip() {
    # "unzip -o <zip> <entry> -d <dir>" plus the multi-entry module extraction.
    local entries=() a
    for a in "$@"; do
        case "$a" in
            -o|-q) ;;
            -d|-*) ;;
            *) entries+=("$a") ;;
        esac
    done
    [ "$VERBOSE" = 1 ] && echo "    [unzip] ${entries[*]}"
    case "${entries[*]}" in
        *module.prop*)
            # The module extraction: the installer checks the extracted files
            # exist, so materialise them.
            mkdir -p "$MODPATH/system/lib64"
            : > "$MODPATH/module.prop"
            : > "$MODPATH/service.sh"
            : > "$MODPATH/post-fs-data.sh"
            : > "$MODPATH/uninstall.sh"
            : > "$MODPATH/system/lib64/libpxrhmdservice.so"
            ;;
        *dtbo-*)
            # The installer hashes $TMPDIR/<entry> before flashing, so the
            # extracted image has to exist under the name it asked for.
            local e
            for e in "${entries[@]}"; do
                case "${e##*/}" in
                    dtbo-cn.img|dtbo-ovs.img|dtbo-stock-cn.img|dtbo-stock-ovs.img|dtbo-intl.img)
                        mkdir -p "$TMPDIR"
                        : > "$TMPDIR/${e##*/}"
                        ;;
                esac
            done
            ;;
    esac
    return 0
}

# ----------------------------------------------------------------------------
# run_installer <scenario-name> — executes customize.sh in a subshell so the
# mocked functions above are the ones it sees, and captures the exit code.
# ----------------------------------------------------------------------------
run_installer() {
    MODPATH=$(mktemp -d)
    TMPDIR=$(mktemp -d)
    LAST_MODPATH="$MODPATH"
    rm -f "$SPOOL/abort" "$SPOOL/ui" "$SPOOL/flashes" "$SPOOL/backups" "$SPOOL/resync"
    export MODPATH TMPDIR SPOOL
    export ZIPFILE=/dev/null
    (
        # The installer relies on abort() to stop; there is no set -e on device
        # because Magisk runs it with its own wrapper. Enabling errexit here is
        # what makes an abort actually terminate this harness's subshell.
        set -e
        # shellcheck disable=SC1090
        . "$CUSTOMIZE_RUN"
    )
    INSTALL_RC=$?
    ABORT_MSG=$(cat "$SPOOL/abort" 2>/dev/null || true)
    # The marker lives inside MODPATH, which is about to be deleted, so record
    # its presence in the spool before cleanup.
    [ -f "$MODPATH/screen_fix_once" ] && record "armed" resync || true
    rm -rf "$MODPATH" "$TMPDIR"
    return $INSTALL_RC
}

# run_service <scenario-name> — executes service.sh with the mock device.
# SCEN_BOOT_COMPLETED "1" makes it skip the wait loop.
# run_service — executes service.sh against the module dir named by $MODDIR.
# service.sh reads $MODDIR/screen_fix_once, so the caller points MODDIR at a
# directory holding the marker to exercise the post-flash boot, or at an empty
# one for a healthy boot. Results are read back from $SPOOL because the script
# backgrounds its work in a subshell.
run_service() {
    MODDIR="$1"
    # service.sh backgrounds its work in a subshell, so its writes can land after
    # the parent returns. Wipe the spool, run, then wait for the spool files to
    # stop changing before the caller reads them -- otherwise the next case sees
    # the previous case's key events.
    #
    # NOTE: the mocked `sleep` is a no-op, so the polling here must use `command
    # sleep` to bypass the mock -- otherwise this loop spins with no delay and
    # kills the script before it has done anything.
    rm -f "$SPOOL/calls" "$SPOOL/props" "$SPOOL/log" "$SPOOL/events"
    export SPOOL MODDIR
    export NOSCREENFIX="${NOSCREENFIX:-}"
    export SCEN_BOOT_COMPLETED="${SCEN_BOOT_COMPLETED:-1}"
    export SCEN_CONFIG_SERVICE_OK="${SCEN_CONFIG_SERVICE_OK:-1}"
    [ "$VERBOSE" = 1 ] && echo "    [dbg] MODDIR=$MODDIR marker=$([ -f "$MODDIR/screen_fix_once" ] && echo yes || echo no)"
    ( . "$SERVICE" ) &
    local pid=$!
    local last="" cur="" stable=0
    while [ "$stable" -lt 3 ]; do
        command sleep 0.05
        cur=$(cat "$SPOOL/calls" "$SPOOL/props" "$SPOOL/events" 2>/dev/null | cksum)
        if [ "$cur" = "$last" ]; then
            stable=$((stable+1))
        else
            stable=0
            last="$cur"
        fi
    done
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    return 0
}

# Count matching lines in a spool file, always printing exactly one number.
# A bare `grep -c ... || echo 0` would emit two lines when there is no match,
# which breaks the numeric comparisons below.
spool_count() {
    local f="$SPOOL/$1"
    if [ ! -f "$f" ]; then echo 0; return 0; fi
    local n
    n=$(grep -c "$2" "$f" 2>/dev/null) || n=0
    echo "${n:-0}"
}
svc_events() { spool_count events .; }
svc_prop()   { spool_count props "^$1="; }
flashes()    { spool_count flashes .; }
resync_armed(){ spool_count resync armed; }
backups()    { cat "$SPOOL/backups" 2>/dev/null; }
ui_says()    { grep -qF "$1" "$SPOOL/ui" 2>/dev/null && echo 1 || echo 0; }

# mocked service-side commands, used by run_service.
# The installer-visible retry loop in service.sh greps for Result:00000001, so
# report success unless the scenario asks otherwise -- otherwise every scenario
# burns 30 iterations and the harness looks hung.
service() {
    echo "$*" >> "$SPOOL/calls"
    if [ "$1" = "call" ] && [ "${SCEN_CONFIG_SERVICE_OK:-1}" = "1" ]; then
        echo "Result: 00000001"
    fi
    return 0
}
setprop() { echo "$1=$2" >> "$SPOOL/props"; }
log() { echo "$*" >> "$SPOOL/log"; }
sleep() { :; }
input() { echo "$*" >> "$SPOOL/events"; return 0; }

check() {
    local name="$1" cond="$2" detail="${3:-}"
    if [ "$cond" = "1" ]; then
        PASS=$((PASS+1))
        printf '  \033[32mPASS\033[0m %s\n' "$name"
    else
        FAIL=$((FAIL+1))
        FAILED_NAMES+=("$name")
        printf '  \033[31mFAIL\033[0m %s %s\n' "$name" "$detail"
    fi
}

# The installer's abort() messages are asserted separately where the exact
# wording matters; this only checks that the run stopped.
assert_abort() {
    check "$1" "$([ -n "$ABORT_MSG" ] && echo 1 || echo 0)" "expected an abort, got none"
}

assert_no_abort() {
    check "$1" "$([ -z "$ABORT_MSG" ] && echo 1 || echo 0)" "unexpected abort: $ABORT_MSG"
}

banner() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ----------------------------------------------------------------------------
banner "installer: firmware gate"
# ----------------------------------------------------------------------------
reset_scenario; run_installer
assert_no_abort "a stock CN unit installs without aborting"
check "CN stock installs cleanly" "$(printf '%s' "$ABORT_MSG" | grep -q 'ro.product.device' && echo 0 || echo 1)" \
      "aborted on device gate: $ABORT_MSG"

reset_scenario; SCEN_BUILD_ID=""; SCEN_INCREMENTAL="5.13.7"; run_installer
assert_no_abort "falls back to incremental when ro.build.id is empty"

reset_scenario; SCEN_BUILD_ID="5.13.8"; SCEN_INCREMENTAL="smartcm.1"; run_installer
assert_abort "rejects 5.13.8"
case "$ABORT_MSG" in *"5.13.8"*) check "error names the actual build id" 1 ;; *) check "error names the actual build id" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_BUILD_ID=""; SCEN_INCREMENTAL="smartcm.1"; run_installer
assert_abort "rejects when neither id nor incremental matches"

reset_scenario; SCEN_DEVICE="PICOA8111"; run_installer
assert_abort "rejects wrong device"
case "$ABORT_MSG" in *"PICOA8111"*) check "device error names the device" 1 ;; *) check "device error names the device" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_PANEL="JDI"; run_installer
assert_abort "rejects wrong panel"

banner "installer: dtbo baseline selection"
# ----------------------------------------------------------------------------
reset_scenario; SCEN_DTBO_HASH="$STOCK_CN"; SCEN_STOCK_HASH="$STOCK_CN"; run_installer
assert_no_abort "CN stock accepted"
check "CN writes the partition once" "$([ "$(flashes)" = 1 ] && echo 1 || echo 0)" "writes=$(flashes)"
check "CN backs the stock image up before writing" "$([ -n "$(backups)" ] && echo 1 || echo 0)"
check "CN arms the one-shot resync" "$(resync_armed)"
check "CN variant announced" "$(ui_says 'CN / Phoenix')"

reset_scenario; SCEN_DTBO_HASH="$STOCK_OVS"; SCEN_STOCK_HASH="$STOCK_OVS"; run_installer
assert_no_abort "Phoenix_ovs stock accepted"
check "OVS writes the partition once" "$([ "$(flashes)" = 1 ] && echo 1 || echo 0)" "writes=$(flashes)"
check "OVS backs the stock image up before writing" "$([ -n "$(backups)" ] && echo 1 || echo 0)"
check "OVS arms the one-shot resync" "$(resync_armed)"
check "OVS variant announced" "$(ui_says 'global / Phoenix_ovs')"

reset_scenario; SCEN_DTBO_HASH="$STOCK_INTL"; run_installer
assert_abort "other global (bee2b067) stock is rejected"
case "$ABORT_MSG" in *"Unsupported global"*) check "other-global rejection is explicit" 1 ;; *) check "other-global rejection is explicit" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_DTBO_HASH="$V6_CN"; SCEN_STOCK_HASH="$STOCK_CN"; run_installer
assert_no_abort "already-flashed CN reinstalls without flashing"
check "reinstall does not rewrite dtbo" "$([ "$(flashes)" = 0 ] && echo 1 || echo 0)" "writes=$(flashes)"
check "reinstall does not arm resync" "$([ "$(resync_armed)" = 0 ] && echo 1 || echo 0)"

reset_scenario; SCEN_DTBO_HASH="$V6_OVS"; SCEN_STOCK_HASH="$STOCK_OVS"; run_installer
assert_no_abort "already-flashed OVS reinstalls without flashing"
check "OVS reinstall does not rewrite dtbo" "$([ "$(flashes)" = 0 ] && echo 1 || echo 0)"
check "OVS reinstall does not arm resync" "$([ "$(resync_armed)" = 0 ] && echo 1 || echo 0)"

reset_scenario; SCEN_DTBO_HASH="$V6_INTL"; run_installer
assert_abort "other global 120Hz image (0ab8b8) is rejected"
case "$ABORT_MSG" in *"Unsupported global"*) check "other-global 120Hz rejection is explicit" 1 ;; *) check "other-global 120Hz rejection is explicit" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_DTBO_HASH="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"; run_installer
assert_abort "rejects an unknown dtbo baseline"
case "$ABORT_MSG" in *"Unknown dtbo baseline"*) check "unknown-baseline error is explicit" 1 ;; *) check "unknown-baseline error is explicit" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_DTBO_HASH="$BASE_LIB"; run_installer
assert_abort "rejects when the dtbo hash equals the lib hash (catches swapped fixtures)"

banner "installer: overlay lib gate"
# ----------------------------------------------------------------------------
reset_scenario; SCEN_LIB_HASH="$PATCHED_LIB"; run_installer
assert_no_abort "accepts the patched lib (upgrade path)"

reset_scenario; SCEN_LIB_HASH="$PREV_LIB"; run_installer
assert_no_abort "accepts the v1.0.0 patched lib (upgrade path)"

reset_scenario; SCEN_LIB_HASH="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"; run_installer
assert_abort "rejects a foreign overlay lib"

# The installer guards with [ ! -b "$DTBO_PART" ]; remove the fake node so the
# guard trips for the same reason it would on a device with no dtbo partition.
reset_scenario
DTBO_REAL=$(readlink -f "$DTBO_NODE" 2>/dev/null || echo "$DTBO_NODE")
cp -a "$DTBO_NODE" "$FAKE_ROOT/dtbo.node.bak" 2>/dev/null
rm -f "$DTBO_NODE"
run_installer
assert_abort "rejects when the dtbo node is missing"
case "$ABORT_MSG" in *"dtbo partition not found"*) check "missing-node error is explicit" 1 ;; *) check "missing-node error is explicit" 0 "$ABORT_MSG" ;; esac
mknod "$DTBO_NODE" b 7 200 2>/dev/null || cp -a "$FAKE_ROOT/dtbo.node.bak" "$DTBO_NODE"

banner "installer: write path failures"
# ----------------------------------------------------------------------------
reset_scenario; SCEN_BAD_ZIP=1; run_installer
assert_abort "rejects a corrupt bundled image"
case "$ABORT_MSG" in *"corrupt"*) check "corrupt-image error is explicit" 1 ;; *) check "corrupt-image error is explicit" 0 "$ABORT_MSG" ;; esac

reset_scenario; SCEN_BAD_MODULE_LIB=1; run_installer
assert_abort "rejects a corrupt bundled lib"
case "$ABORT_MSG" in
    *"Bundled libpxrhmdservice.so is corrupt"*) check "corrupt-lib error is explicit" 1 ;;
    *) check "corrupt-lib error is explicit" 0 "$ABORT_MSG" ;;
esac

reset_scenario; SCEN_DD_FAIL=flash; run_installer
assert_abort "aborts when dd fails"

banner "installer: hash consistency between installer and packager"
# ----------------------------------------------------------------------------
# customize.sh verifies the images it unzips; build_zip.py verifies the images
# it bundles. If one copy of a hash is edited without the other, the installer
# ships a zip that aborts on device. Both V6 hashes and the patched lib must
# therefore appear in both files, byte for byte.
for pair in "V6_DTBO_CN:$V6_CN" "V6_DTBO_OVS:$V6_OVS" "PATCHED_LIB:$PATCHED_LIB"; do
    name=${pair%%:*}
    hash=${pair#*:}
    in_install=$(grep -c "$hash" "$CUSTOMIZE" || true)
    in_pack=$(grep -c "$hash" "$MODULE_SRC/build_zip.py" || true)
    check "$name hash identical in customize.sh and build_zip.py" \
          "$([ "$in_install" -ge 1 ] && [ "$in_pack" -ge 1 ] && echo 1 || echo 0)" \
          "customize=$in_install build_zip=$in_pack"
done
for pair in "STOCK_DTBO_CN:$STOCK_CN" "STOCK_DTBO_OVS:$STOCK_OVS"; do
    name=${pair%%:*}
    hash=${pair#*:}
    check "$name hash bundled by build_zip.py" \
          "$([ "$(grep -c "$hash" "$MODULE_SRC/build_zip.py" || true)" -ge 1 ] && echo 1 || echo 0)"
done
check "PREV_LIB_SHA256 declared in customize.sh" \
      "$([ "$(grep -c "$PREV_LIB" "$CUSTOMIZE" || true)" -ge 1 ] && echo 1 || echo 0)"
# The stock baselines are only ever compared against, never bundled, so they
# belong in customize.sh. All supported variants must be present for the gate.
for pair in "STOCK_DTBO_CN:$STOCK_CN" "STOCK_DTBO_OVS:$STOCK_OVS" "STOCK_DTBO_INTL:$STOCK_INTL"; do
    name=${pair%%:*}
    hash=${pair#*:}
    check "$name declared once in customize.sh" \
          "$([ "$(grep -c "$hash" "$CUSTOMIZE" || true)" -ge 1 ] && echo 1 || echo 0)"
done
check "no stale single-variant V6 hash left in customize.sh" \
      "$([ "$(grep -c 'V6_DTBO_SHA256' "$CUSTOMIZE" || true)" = 0 ] && echo 1 || echo 0)"

banner "service.sh: one-shot resync behaviour"
# ----------------------------------------------------------------------------
# The installer arms $MODPATH/screen_fix_once only when it actually writes the
# partition, and service.sh consumes it. These cases are the whole point of that
# marker: cycle the screen exactly once after a flash, never on a healthy boot.
reset_scenario
MODDIR=$(mktemp -d)
run_service "$MODDIR"
check "healthy boot does not cycle the screen" \
      "$([ "$(svc_events)" = 0 ] && echo 1 || echo 0)" "events=$(svc_events)"
check "healthy boot sets persist.pvr.display.type" \
      "$([ "$(svc_prop persist.pvr.display.type)" -ge 1 ] && echo 1 || echo 0)"
check "healthy boot sets sys.pvr.display.type=120" \
      "$([ "$(svc_prop sys.pvr.display.type)" -ge 1 ] && echo 1 || echo 0)"
check "healthy boot pushes sdk_refreshRate=120 to the config service" \
      "$(grep -q 'sdk_refreshRate,120' "$SPOOL/calls" 2>/dev/null && echo 1 || echo 0)"

: > "$MODDIR/screen_fix_once"
run_service "$MODDIR"
check "first boot after flash cycles the screen twice (off+on)" \
      "$([ "$(svc_events)" = 2 ] && echo 1 || echo 0)" "events=$(svc_events)"
check "the marker is consumed, not left behind" \
      "$([ ! -f "$MODDIR/screen_fix_once" ] && echo 1 || echo 0)"
run_service "$MODDIR"
check "the boot after that does not cycle again" \
      "$([ "$(svc_events)" = 0 ] && echo 1 || echo 0)" "events=$(svc_events)"

: > "$MODDIR/screen_fix_once"
NOSCREENFIX=$(mktemp)
run_service "$MODDIR"
check "the opt-out file suppresses the resync" \
      "$([ "$(svc_events)" = 0 ] && echo 1 || echo 0)" "events=$(svc_events)"
check "the opt-out still consumes the marker" \
      "$([ ! -f "$MODDIR/screen_fix_once" ] && echo 1 || echo 0)"
rm -f "$NOSCREENFIX"
unset NOSCREENFIX
rm -rf "$MODDIR"

banner "service.sh: config service unavailable"
# ----------------------------------------------------------------------------
reset_scenario
MODDIR=$(mktemp -d)
SCEN_CONFIG_SERVICE_OK=0
run_service "$MODDIR"
check "still sets the display props when the config call fails" \
      "$([ "$(svc_prop sys.pvr.display.type)" -ge 1 ] && echo 1 || echo 0)"
check "does not cycle the screen when nothing was flashed" \
      "$([ "$(svc_events)" = 0 ] && echo 1 || echo 0)"
reset_scenario
rm -rf "$MODDIR"

printf '\n\033[1m结果: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    printf '失败用例:\n'
    for n in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$n"; done
    rm -rf "$FAKE_ROOT" "$SPOOL"
    exit 1
fi
rm -rf "$FAKE_ROOT" "$SPOOL"
exit 0
