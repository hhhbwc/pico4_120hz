#!/system/bin/sh
# Pico4 120Hz Display Unlock - installer
SKIPMOUNT=false
PROPFILE=false
POSTFSDATA=false
LATESTARTSERVICE=true

ui_print "======================================"
ui_print "  Pico4 120Hz Display Unlock v1.0.0"
ui_print "======================================"

EXPECTED_FINGERPRINT="Pico/Phoenix/PICOA8110:10/5.13.7/smartcm.1761755159:user/dev-keys"
STOCK_DTBO_SHA256="307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
V6_DTBO_SHA256="f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"
DTBO_PART="/dev/block/by-name/dtbo"

if [ "$(getprop ro.build.fingerprint)" != "$EXPECTED_FINGERPRINT" ]; then
    abort "Unsupported firmware: $(getprop ro.build.fingerprint)"
fi
if [ "$(getprop ro.pvr.hmd.type)" != "SHARP5K" ]; then
    abort "Unsupported panel: $(getprop ro.pvr.hmd.type)"
fi

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
        abort "Unknown dtbo baseline: $current_dtbo (wrong firmware or already modified)"
        ;;
esac

if [ "$NEED_FLASH" = "1" ]; then
    ui_print "- Extracting 120Hz dtbo image"
    rm -rf "$TMPDIR/dtbo.img"
    unzip -o "$ZIPFILE" "dtbo.img" -d "$TMPDIR" >/dev/null 2>&1 || abort "Failed to extract dtbo.img"
    dtbo_img=$(sha256_file "$TMPDIR/dtbo.img")
    [ "$dtbo_img" = "$V6_DTBO_SHA256" ] || abort "Bundled dtbo.img is corrupt"
    ui_print "- Flashing dtbo (panel 120Hz init)"
    dd if="$TMPDIR/dtbo.img" of="$DTBO_PART" bs=4096 >/dev/null 2>&1 || abort "dtbo flash failed"
    sync
    written=$(sha256_file "$DTBO_PART")
    [ "$written" = "$V6_DTBO_SHA256" ] || abort "dtbo write verification failed"
    ui_print "- dtbo flashed and verified"
fi

ui_print "- Installing vendor config-map patch"
ui_print "- Installing boot-time rate fix"
ui_print "======================================"
ui_print " Reboot to apply. Panel runs 120Hz."
ui_print " Restore stock: flash your dtbo"
ui_print " backup + disable this module."
ui_print "======================================"
