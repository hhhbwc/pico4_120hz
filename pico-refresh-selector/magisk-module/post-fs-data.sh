#!/system/bin/sh
# Stage the runtime config before XRRuntime starts.  The loader checks
# /sdcard/psmart/canary first (not mounted yet) and then this path, so the
# system overlay alone can be shadowed by a stale canary file.
MODDIR=${0%/*}
CONF="$MODDIR/system/etc/pvr/pxr_config.txt"
[ -f "$CONF" ] || exit 0
mkdir -p /data/misc/pxr/canary/config
cp "$CONF" /data/misc/pxr/canary/config/pxr_config.txt
chmod 644 /data/misc/pxr/canary/config/pxr_config.txt
chown system:system /data/misc/pxr/canary/config/pxr_config.txt
chcon u:object_r:data_misc_pxr_file:s0 /data/misc/pxr/canary/config/pxr_config.txt 2>/dev/null
