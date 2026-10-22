#!/system/bin/sh
# Pico4 120Hz Display Unlock - installer
SKIPUNZIP=1
SKIPMOUNT=false
PROPFILE=false
POSTFSDATA=true
LATESTARTSERVICE=true

ui_print "======================================"
ui_print "  Pico4 120Hz Display Unlock v1.2.1"
ui_print "======================================"

# Display fingerprint, printed before any gate can abort so a failed install log
# is self-explanatory. The panel supplier is NOT derivable at runtime (all 16
# qcom,mdss_dsi_* nodes live in the merged tree, none carries a status property,
# and the kernel log names no vendor), so this is the strongest identity set
# available. Every read is failure-tolerant: a missing file just prints empty.
tb() { /system/bin/toybox "$@" 2>/dev/null; }
pico_fp() { ui_print "pico4_120hz fingerprint $1=$2"; }
pico_fp "ro.product.device" "$(getprop ro.product.device)"
pico_fp "ro.build.id" "$(getprop ro.build.id)"
pico_fp "ro.pvr.hmd.type" "$(getprop ro.pvr.hmd.type)"
pico_fp "sys.pvr.display.type" "$(getprop sys.pvr.display.type)"
pico_fp "persist.pvr.display.type" "$(getprop persist.pvr.display.type)"
pico_fp "dtbo_idx" "$([ -r /proc/cmdline ] && tb tr ' ' '\n' < /proc/cmdline | tb grep -m1 dtbo_idx)"
pico_fp "dtbo_sha16" "$(tb sha256sum -b /dev/block/by-name/dtbo | tb cut -c1-16)"
pico_fp "modes" "$([ -r /sys/class/drm/card0-DSI-1/modes ] && tb tr '\n' ';' < /sys/class/drm/card0-DSI-1/modes)"
pico_fp "lib_sha16" "$(tb sha256sum -b /system/lib64/libpxrhmdservice.so | tb cut -c1-16)"

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
PATCHED_LIB_SHA256="8b4431d4c8f7ebec4bdead981800780347f376e10da10bdb90d6f2977187c829"
# v1.0.0 module: upgrading from it must pass the mounted-lib gate.
PREV_LIB_SHA256="32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea"
BASE_LIB="/system/lib64/libpxrhmdservice.so"
DTBO_PART="/dev/block/by-name/dtbo"

# Two stock baselines and their matching 120Hz images. CN (Phoenix) and global
# (INTL) firmware ship the same sixteen dtbo entries in different
# orders and hash differently, so the patched image must be built from the
# matching stock one — flashing a CN-ordered image onto a global unit would
# move every entry and the bootloader would select the wrong board tree.
# Both images patch every entry, so the module never needs to know which
# entry a given unit actually boots.
STOCK_DTBO_CN="307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac"
STOCK_DTBO_OVS="f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992"
STOCK_DTBO_INTL="bee2b0676e04d93135c660f1c80157afd06e52678432ea2db9f9c90b47007d9e"
# v1.1.0 CN bundle: the v6 init120 image from the v1.0.0 release.
V6_DTBO_CN="f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea"
# International Phoenix_ovs image: entry 6 patched in place from the b9666
# stock dtbo (f4d6073c). Panel subtree is byte-identical to the CN v6.
V6_DTBO_OVS="d138d5d68e64be3209b8d5024c7f10fd120dc3d2d83fd703a31fe09b3a6b5123"
# Pre-1.1 universal / vfp14 images, accepted on upgrade/reinstall without
# rewriting the partition.
V6_DTBO_UNIVERSAL_CN="a57573ae89a26bc37db10d8b258a25f2cf343b042246519144ff3213508ff385"
V6_DTBO_INTL="0ab8b85ed85203bd0096f4a89f12d18a0746d7bd461a7d7c0e355ace727936e9"
V6_DTBO_VFP14="806951abf48af261a3dac002aca79c7df321fa9d24564e593ecbc6b7b69d5c4c"

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
if [ "$base_lib_hash" != "$BASE_LIB_SHA256" ] && [ "$base_lib_hash" != "$PATCHED_LIB_SHA256" ] && [ "$base_lib_hash" != "$PREV_LIB_SHA256" ]; then
    abort "Stock libpxrhmdservice.so mismatch: $base_lib_hash (post this hash to github.com/hhhbwc/pico4_120hz issue #2)"
fi

# Extract module files manually: Magisk's built-in extractor skips zip
# entries without Unix permission bits.
unzip -o "$ZIPFILE" "module.prop" "service.sh" "post-fs-data.sh" "uninstall.sh" "system/*" -d "$MODPATH" >/dev/null 2>&1     || abort "Failed to extract module files"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/uninstall.sh" 0 0 0755
[ -f "$MODPATH/system/lib64/libpxrhmdservice.so" ] || abort "libpxrhmdservice.so missing after extraction"
[ -f "$MODPATH/service.sh" ] || abort "service.sh missing after extraction"
[ -f "$MODPATH/uninstall.sh" ] || abort "uninstall.sh missing after extraction"
module_lib_hash=$(sha256_file "$MODPATH/system/lib64/libpxrhmdservice.so") || abort "Unable to hash extracted libpxrhmdservice.so"
[ "$module_lib_hash" = "$PATCHED_LIB_SHA256" ] || abort "Bundled libpxrhmdservice.so is corrupt (expected $PATCHED_LIB_SHA256, got $module_lib_hash)"

current_dtbo=$(sha256_file "$DTBO_PART") || abort "Unable to hash dtbo partition"

# Pick the image for this unit, and decide in the same step whether the
# partition has to be written. NEED_FLASH must be set by the matching branch:
# an earlier revision initialised it to 0 and only ever set it to 1 inside the
# block guarded by `[ "$NEED_FLASH" != "0" ]`, so the guard was false on the
# stock path and the module installed the overlay lib without ever writing the
# dtbo. Found by pico-refresh-selector/tools/dryrun_installer.sh.
NEED_FLASH=0
STOCK_ENTRY=""
STOCK_TARGET=""
case "$current_dtbo" in
    "$STOCK_DTBO_CN")
        DTBO_ENTRY="dtbo-cn.img"; DTBO_TARGET="$V6_DTBO_CN"
        STOCK_ENTRY="dtbo-stock-cn.img"; STOCK_TARGET="$STOCK_DTBO_CN"
        VARIANT="CN / Phoenix"; NEED_FLASH=1
        ;;
    "$STOCK_DTBO_OVS")
        DTBO_ENTRY="dtbo-ovs.img"; DTBO_TARGET="$V6_DTBO_OVS"
        STOCK_ENTRY="dtbo-stock-ovs.img"; STOCK_TARGET="$STOCK_DTBO_OVS"
        VARIANT="global / Phoenix_ovs"; NEED_FLASH=1
        ;;
    "$V6_DTBO_CN"|"$V6_DTBO_UNIVERSAL_CN"|"$V6_DTBO_VFP14")
        STOCK_ENTRY="dtbo-stock-cn.img"; STOCK_TARGET="$STOCK_DTBO_CN"
        VARIANT="CN / Phoenix"; NEED_FLASH=0
        ;;
    "$V6_DTBO_OVS")
        STOCK_ENTRY="dtbo-stock-ovs.img"; STOCK_TARGET="$STOCK_DTBO_OVS"
        VARIANT="global / Phoenix_ovs"; NEED_FLASH=0
        ;;
    "$STOCK_DTBO_INTL"|"$V6_DTBO_INTL")
        abort "Unsupported global dtbo baseline ($current_dtbo). This release bundles CN and Phoenix_ovs (b9666) images only."
        ;;
    *)
        abort "Unknown dtbo baseline: $current_dtbo (wrong firmware or already modified; post this hash to issue #2)"
        ;;
esac

ui_print "- Detected: $VARIANT"
ui_print "- Staging stock image ($STOCK_ENTRY)"
unzip -o "$ZIPFILE" "$STOCK_ENTRY" -d "$TMPDIR" >/dev/null 2>&1 || abort "Failed to extract $STOCK_ENTRY"
stock_src="$TMPDIR/$STOCK_ENTRY"
stock_img_hash=$(sha256_file "$stock_src") || abort "Unable to hash bundled $STOCK_ENTRY"
[ "$stock_img_hash" = "$STOCK_TARGET" ] || abort "Bundled $STOCK_ENTRY is corrupt (expected $STOCK_TARGET, got $stock_img_hash)"
cp "$stock_src" "$MODPATH/dtbo-stock.img" || abort "Failed to stage the stock dtbo"
chmod 644 "$MODPATH/dtbo-stock.img"

# Magisk's `remove` flag (and deleting the module dir by hand) removes the
# module WITHOUT running uninstall.sh. That would leave the 120Hz DTBO on a
# 90Hz config after a reboot. Keep a stock image and a service.d guard outside
# the module so the first boot after removal restores the stock DTBO itself.
cp "$stock_src" /data/adb/pico4_120hz_stock.img || abort "Failed to stage the rollback guard image"
chmod 600 /data/adb/pico4_120hz_stock.img
mkdir -p /data/adb/service.d
cat > /data/adb/service.d/pico4_120hz_rollback.sh <<'EOS'
#!/system/bin/sh
(
    until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 1; done
    sleep 5
    MOD=/data/adb/modules/pico4_120hz
    if [ -d "$MOD" ] && [ ! -e "$MOD/remove" ] && [ ! -e "$MOD/disable" ]; then
        exit 0
    fi
    STOCK=/data/adb/pico4_120hz_stock.img
    [ -f "$STOCK" ] || exit 1
    hash=$(/system/bin/toybox sha256sum -b "$STOCK" 2>/dev/null | cut -d' ' -f1)
    case "$hash" in
        307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac|\
        f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992) ;;
        *) exit 1 ;;
    esac
    /system/bin/dd if="$STOCK" of=/dev/block/by-name/dtbo bs=4096 >/dev/null 2>&1
    sync
    now=$(/system/bin/toybox sha256sum -b /dev/block/by-name/dtbo 2>/dev/null | cut -d' ' -f1)
    case "$now" in
        307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac|\
        f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992) ;;
        *) exit 1 ;;
    esac
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
    [ "$(getprop persist.pvr.config.eyebuffer_width)" = "2160" ] && setprop persist.pvr.config.eyebuffer_width ""
    [ "$(getprop persist.pvr.config.eyebuffer_height)" = "2160" ] && setprop persist.pvr.config.eyebuffer_height ""
    rm -f /data/misc/pxr/canary/config/pxr_config.txt /sdcard/psmart/canary/pxr_config.txt
    log -t pico4_120hz "rollback guard: stock dtbo + 90Hz config restored"
    if [ ! -d "$MOD" ]; then rm -f "$0"; fi
) &
EOS
chmod 755 /data/adb/service.d/pico4_120hz_rollback.sh

if [ "$NEED_FLASH" = "1" ]; then
    ui_print "- Stock dtbo detected, backing up"
    BACKUP="/sdcard/Download/pico4-dtbo-stock-backup.img"
    dd if="$DTBO_PART" of="$BACKUP" bs=4096 >/dev/null 2>&1 || abort "dtbo backup failed"
    # Best effort: the backup's readability matters, but a chmod failure must not
    # abort an otherwise good install on a recovery shell running with errexit.
    chmod 644 "$BACKUP" 2>/dev/null || true
    backup_check=$(sha256_file "$BACKUP")
    [ "$backup_check" = "$current_dtbo" ] || abort "dtbo backup verification failed"
    ui_print "- Backup: $BACKUP"
fi

if [ "$NEED_FLASH" = "1" ]; then
    ui_print "- Extracting 120Hz dtbo image ($DTBO_ENTRY)"
    unzip -o "$ZIPFILE" "$DTBO_ENTRY" -d "$TMPDIR" >/dev/null 2>&1 || abort "Failed to extract $DTBO_ENTRY"
    dtbo_img=$(sha256_file "$TMPDIR/$DTBO_ENTRY")
    [ "$dtbo_img" = "$DTBO_TARGET" ] || abort "Bundled $DTBO_ENTRY is corrupt"
    ui_print "- Flashing dtbo (panel 120Hz init)"
    dd if="$TMPDIR/$DTBO_ENTRY" of="$DTBO_PART" bs=4096 >/dev/null 2>&1 || abort "dtbo flash failed"
    sync
    written=$(sha256_file "$DTBO_PART")
    [ "$written" = "$DTBO_TARGET" ] || abort "dtbo write verification failed"
    ui_print "- dtbo flashed and verified"
    # Arm the one-shot boot-time panel resync for the first boot after
    # flashing (consumed by service.sh). Healthy boots must not resync —
    # a forced panel re-init on them tears the bottom scanout.
    touch "$MODPATH/screen_fix_once"
fi

ui_print "- Installing vendor config-map patch"
ui_print "- Installing boot-time rate fix + panel resync"
ui_print " Supported: CN (Phoenix) + Phoenix_ovs"
ui_print "======================================"
ui_print " Reboot to apply. Panel runs 120Hz."
ui_print " A screen blink seconds after boot is"
ui_print " the automatic panel resync - expected."
ui_print " Upgrade: install this zip over v1.0.0."
ui_print " Uninstall: safe even via Magisk remove;"
ui_print " a boot guard restores the stock dtbo."
ui_print " Do not disable; uninstall or reinstall."
ui_print "======================================"
