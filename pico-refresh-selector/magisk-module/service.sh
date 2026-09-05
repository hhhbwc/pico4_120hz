#!/system/bin/sh
# Pico4 120Hz Display Unlock - boot-time fix
#
# The zero-switch design keeps the panel locked to the 120 Hz config, so the
# vendor's fps-change confirmation never fires and sys.pvr.display.type stays
# at the boot default (72). Also write the authoritative configuration-service
# keys (fresh installs carry sdk_refreshRate=90) and the persistent panel type.

(
    until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 2; done
    sleep 20

    # ConfigurationService AIDL transaction 4 = setConfigProperty
    # (IConfigServiceInterface, first arg = package, then type 0 = string,
    #  configJson "name,value", two empty strings, final int 1).
    ok=0
    for i in 1 2 3 4 5 6 7 8 9 10; do
        r=$(service call ConfigurationService 4 s16 com.picovr.settings i32 0 s16 sdk_refreshRate,120 s16 "" s16 "" i32 1 2>/dev/null)
        case "$r" in
            *Result:*"00000001"*) ok=1; break ;;
        esac
        sleep 5
    done
    service call ConfigurationService 4 s16 com.picovr.settings i32 0 s16 sdk_Recommand_refreshRate,120 s16 "" s16 "" i32 1 >/dev/null 2>&1

    setprop persist.pvr.display.type jdi493120
    setprop sys.pvr.display.type 120.000000
    log -t pico4_120hz "applied: config=$ok persist=jdi493120 sys=120.000000"
) &
