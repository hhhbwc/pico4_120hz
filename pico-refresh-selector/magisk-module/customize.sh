#!/system/bin/sh
# Pico4 120Hz Display Unlock - installer
SKIPUNZIP=1
SKIPMOUNT=false
PROPFILE=false
POSTFSDATA=false
LATESTARTSERVICE=true

ui_print "======================================"
ui_print "  Pico4 120Hz Display Unlock v1.0.1"
ui_print "======================================"

# Firmware gate, component-wise. 5.13.7 ships under several device-tree
# variants (Phoenix, Phoenix_ovs) and build incrementals (smartcm.*); the
# v1.0.0 whole-fingerprint match rejected all of those (issue #2). The OS
# version lives in ro.build.id — ro.build.version.incremental is a
# smartcm.<timestamp> build number on every 5.13.7 unit (CN and global alike),
# so matching 5.13.7* against it aborts on 100% of devices. The incremental
# match stays only as a fallback for builds that do not populate ro.build.id.
if [ "$(getprop ro.product.device)" != "PICOA8110" ]; then
    abort "Unsupported device: $(getprop ro.product.device)"
fi
case "$(getprop ro.build.id)" in
    5.13.7*) ;;
    *)
        case "$(getprop ro.build.version.incremental)" in
            5.13.7*) ;;
            *) abort "Unsupported firmware: id=$(getprop ro.build.id) incremental=$(getprop ro.build.version.incremental) (need 5.13.7; post these props to github.com/hhhbwc/pico4_120hz issue #2)" ;;
        esac ;;
esac
if [ "$(getprop ro.pvr.hmd.type)" != "SHARP5K" ]; then
    abort "Unsupported panel: $(getprop ro.pvr.hmd.type)"
fi

# The overlay lib was patched from the 5.13.7 stock lib. Refuse to bind-mount
# it over anything else, or hmdservice may crash at boot. On upgrade/reinstall
# the running module's overlay is active in this namespace, so the mounted lib
# hashes to the patched value — the base was verified at first install, accept
# both.
BASE_LIB_SHA256="c290a9f51214ff37b415c309c5facf80542024d40c22e5ae3cdeff9825a31fef"
PATCHED_LIB_SHA256="32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea"
BASE_LIB="/system/lib64/libpxrhmdservice.so"
STOCK_DTBO_SHA256="307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
V6_DTBO_SHA256="f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"
DTBO_PART="/dev/block/by-name/dtbo"

sha256_file() {
    local output digest
    output=$(/system/bin/toybox sha256sum -b "$1" 2>/dev/null) || return 1
    set -- $output
    digest="$1"
    [ "${#digest}" -eq 64 ] || return 1
    case "$digest" in *[!0123456789abcdefABCDEF]*) return 1 ;; esac
    echo "$digest"
}

if [ ! -b "$DTBO_PART" ]; then
    abort "dtbo partition not found"
fi

base_lib_hash=$(sha256_file "$BASE_LIB") || abort "Cannot hash $BASE_LIB"
if [ "$base_lib_hash" != "$BASE_LIB_SHA256" ] && [ "$base_lib_hash" != "$PATCHED_LIB_SHA256" ]; then
    abort "Stock libpxrhmdservice.so mismatch: $base_lib_hash (post this hash to github.com/hhhbwc/pico4_120hz issue #2)"
fi

# Extract module files manually: Magisk's built-in extractor skips zip
# entries without Unix permission bits.
unzip -o "$ZIPFILE" "module.prop" "service.sh" "system/*" -d "$MODPATH" >/dev/null 2>&1     || abort "Failed to extract module files"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/service.sh" 0 0 0755
[ -f "$MODPATH/system/lib64/libpxrhmdservice.so" ] || abort "libpxrhmdservice.so missing after extraction"
[ -f "$MODPATH/service.sh" ] || abort "service.sh missing after extraction"

current_dtbo=$(sha256_file "$DTBO_PART") || abort "Unable to hash dtbo partition"

case "$current_dtbo" in
    "$STOCK_DTBO_SHA256")
        ui_print "- Stock dtbo detected, backing up"
        BACKUP="/sdcard/Download/pico4-dtbo-stock-backup.img"
        dd if="$DTBO_PART" of="$BACKUP" bs=4096 >/dev/null 2>&1 || abort "dtbo backup failed"
        chmod 644 "$BACKUP" 2>/dev/null
        backup_check=$(sha256_file "$BACKUP")
        [ "$backup_check" = "$STOCK_DTBO_SHA256" ] || abort "dtbo backup verification failed"
        ui_print "- Backup: $BACKUP"
        NEED_FLASH=1
        ;;
    "$V6_DTBO_SHA256")
        ui_print "- 120Hz dtbo already flashed, skipping partition write"
        NEED_FLASH=0
        ;;
    *)
        abort "Unknown dtbo baseline: $current_dtbo (wrong firmware or already modified; post this hash to issue #2)"
        ;;
esac

if [ "$NEED_FLASH" = "1" ]; then
    ui_print "- Extracting 120Hz dtbo image"
    unzip -o "$ZIPFILE" "dtbo.img" -d "$TMPDIR" >/dev/null 2>&1 || abort "Failed to extract dtbo.img"
    dtbo_img=$(sha256_file "$TMPDIR/dtbo.img")
    [ "$dtbo_img" = "$V6_DTBO_SHA256" ] || abort "Bundled dtbo.img is corrupt"
    ui_print "- Flashing dtbo (panel 120Hz init)"
    dd if="$TMPDIR/dtbo.img" of="$DTBO_PART" bs=4096 >/dev/null 2>&1 || abort "dtbo flash failed"
    sync
    written=$(sha256_file "$DTBO_PART")
    [ "$written" = "$V6_DTBO_SHA256" ] || abort "dtbo write verification failed"
    ui_print "- dtbo flashed and verified"
    # Arm the one-shot boot-time panel resync for the first boot after
    # flashing (consumed by service.sh). Healthy boots must not resync —
    # a forced panel re-init on them tears the bottom scanout.
    touch "$MODPATH/screen_fix_once"
fi

ui_print "- Installing vendor config-map patch"
ui_print "- Installing boot-time rate fix + panel resync"
ui_print "======================================"
ui_print " Reboot to apply. Panel runs 120Hz."
ui_print " A screen blink seconds after boot is"
ui_print " the automatic panel resync - expected."
ui_print " Restore stock: flash your dtbo"
ui_print " backup + disable this module."
ui_print "======================================"
