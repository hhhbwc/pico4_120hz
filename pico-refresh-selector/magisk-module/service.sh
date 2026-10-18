#!/system/bin/sh
# Pico4 120Hz Display Unlock - boot-time fix
#
# The zero-switch design keeps the panel locked to the 120 Hz config, so the
# vendor's fps-change confirmation never fires and sys.pvr.display.type stays
# at the boot default (72). Also write the authoritative configuration-service
# keys (fresh installs carry sdk_refreshRate=90) and the persistent panel type.

(
    until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 1; done

    # ConfigurationService AIDL transaction 4 = setConfigProperty
    # (IConfigServiceInterface, first arg = package, then type 0 = string,
    #  configJson "name,value", two empty strings, final int 1).
    # Poll every second — the service is usually up within a few seconds of
    # boot_completed, and the resync below must run as early as possible.
    ok=0
    tries=0
    while [ "$tries" -lt 30 ]; do
        tries=$((tries+1))
        r=$(service call ConfigurationService 4 s16 com.picovr.settings i32 0 s16 sdk_refreshRate,120 s16 "" s16 "" i32 1 2>/dev/null)
        case "$r" in
            *Result:*"00000001"*) ok=1; break ;;
        esac
        sleep 1
    done
    service call ConfigurationService 4 s16 com.picovr.settings i32 0 s16 sdk_Recommand_refreshRate,120 s16 "" s16 "" i32 1 >/dev/null 2>&1

    setprop persist.pvr.display.type jdi493120
    setprop sys.pvr.display.type 120.000000
    log -t pico4_120hz "applied: config=$ok persist=jdi493120 sys=120.000000"

    # Panel/host timing resync — ONE-SHOT, first boot after flashing only.
    # The v6 panel-init bakes the 120 Hz gate-scan into the panel on-command;
    # on the very first boot the config service still carries 90, so panel
    # and host can mismatch (horizontal split + corrupted rows). A screen
    # off/on cycle re-runs the panel init once the host is locked at 120
    # (the manual power-button fix, automated). Healthy boots do NOT need
    # it — config service keeps sdk_refreshRate=120 and panel/host match —
    # and forcing the cycle on them tears the bottom scanout while the
    # desktop starts (flickering rows + invisible dock), so the installer
    # drops screen_fix_once only when it actually flashes the dtbo, and
    # this script consumes it. The DRM dpms sysfs node would be cleaner
    # than power-key events but is 0444, unwritable even for root.
    if [ -f "$MODDIR/screen_fix_once" ]; then
        rm -f "$MODDIR/screen_fix_once"
        sleep 2
        input keyevent KEYCODE_POWER
        sleep 2
        input keyevent KEYCODE_POWER
        log -t pico4_120hz "panel resync: one-shot after flash, screen cycled off/on"
    fi
) &
