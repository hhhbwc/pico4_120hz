#!/system/bin/sh
# Restore the stock state before Magisk removes the module directory.
#
# 1. Write the verified stock CN dtbo back (bundled image, then the installer
#    backup as fallback).
# 2. Reset the ConfigurationService keys the module changed.
# 3. Remove the runtime canary config so the stock /system/etc/pvr/pxr_config.txt
#    is used again.
# 4. Leave a one-shot /data/adb/service.d script for the first boot: the
#    ConfigurationService is usually not reachable from the uninstall context.

MODDIR=${MODDIR:-${0%/*}}
DTBO_PART=/dev/block/by-name/dtbo
STOCK_DTBO_CN="307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
BUNDLED_STOCK="$MODDIR/dtbo-stock.img"
BACKUP_STOCK="/sdcard/Download/pico4-dtbo-stock-backup.img"
CLEANUP="/data/adb/service.d/pico4_120hz_cleanup.sh"

sha256_file() {
    /system/bin/toybox sha256sum -b "$1" 2>/dev/null | awk '{print $1}'
}

log -t pico4_120hz "uninstall: restoring stock dtbo"

current=""
[ -b "$DTBO_PART" ] && current=$(sha256_file "$DTBO_PART")

restore_from=""
if [ "$current" != "$STOCK_DTBO_CN" ]; then
    for candidate in "$BUNDLED_STOCK" "$BACKUP_STOCK"; do
        [ -f "$candidate" ] || continue
        [ "$(sha256_file "$candidate")" = "$STOCK_DTBO_CN" ] || continue
        restore_from="$candidate"
        break
    done
    if [ -n "$restore_from" ]; then
        dd if="$restore_from" of="$DTBO_PART" bs=4096 >/dev/null 2>&1
        sync
        written=$(sha256_file "$DTBO_PART")
        if [ "$written" = "$STOCK_DTBO_CN" ]; then
            log -t pico4_120hz "uninstall: stock dtbo restored from $restore_from"
        else
            log -t pico4_120hz "uninstall: dtbo write verification failed ($written)"
        fi
    else
        log -t pico4_120hz "uninstall: no verified stock dtbo; use EDL read-part dtbobak"
    fi
fi

# Best-effort immediate reset when the framework is still up.
setcfg() {
    service call ConfigurationService 4 s16 "$1" i32 0 s16 "$2" s16 "" s16 "" i32 1 >/dev/null 2>&1
}
setcfg com.picovr.settings sdk_refreshRate,90
setcfg com.picovr.settings sdk_Recommand_refreshRate,90
setcfg pxr_config_package displayRefreshRate,72
setcfg pxr_config_package sdk_eyebufferX,2816
setcfg pxr_config_package sdk_eyebufferY,2816
setcfg android os_eyebuffer_width,0
setcfg android os_eyebuffer_height,0
setprop persist.pvr.display.type jdi49390
setprop sys.pvr.display.type 72.000000

rm -f /data/misc/pxr/canary/config/pxr_config.txt
rm -f /sdcard/psmart/canary/pxr_config.txt

# The ConfigurationService may be unavailable here (Magisk app/recovery). A
# one-shot late-start script finishes the reset on the next Android boot.
mkdir -p /data/adb/service.d
cat > "$CLEANUP" <<'EOF'
#!/system/bin/sh
(
    until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 1; done
    sleep 5
    setcfg() {
        service call ConfigurationService 4 s16 "$1" i32 0 s16 "$2" s16 "" s16 "" i32 1 >/dev/null 2>&1
    }
    setcfg com.picovr.settings sdk_refreshRate,90
    setcfg com.picovr.settings sdk_Recommand_refreshRate,90
    setcfg pxr_config_package displayRefreshRate,72
    setcfg pxr_config_package sdk_eyebufferX,2816
    setcfg pxr_config_package sdk_eyebufferY,2816
    setcfg android os_eyebuffer_width,0
    setcfg android os_eyebuffer_height,0
    setprop persist.pvr.display.type jdi49390
    setprop sys.pvr.display.type 72.000000
    rm -f /data/misc/pxr/canary/config/pxr_config.txt
    rm -f /sdcard/psmart/canary/pxr_config.txt
    log -t pico4_120hz "uninstall cleanup: stock config restored"
    rm -f "$0"
) &
EOF
chmod 755 "$CLEANUP"
log -t pico4_120hz "uninstall: reboot to finish stock restore"
