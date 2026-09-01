#!/usr/bin/env bash
# Report the refresh rate the PICO 4 panel is really running.
#
# Neither "dumpsys SurfaceFlinger" nor PICO's own PxrCompositor log can be
# trusted for this: SurfaceFlinger derives its VSYNC period from whatever timing
# the mode was registered with, and a DTBO that produces an impossible timing
# still yields a mode that reports a high rate. This script instead reads the
# programmed DSI timing and the pixel clock straight out of the hardware and
# divides one by the other.
#
# Usage: ./verify_refresh_rate.sh [adb-serial]

set -u

ADB=${ADB:-adb}
SERIAL=${1:-}
if [ -n "$SERIAL" ]; then
    ADB="$ADB -s $SERIAL"
fi

PANEL=qcom,mdss_dsi_sharp_ls026b3sa_90_video
CTRL=/sys/kernel/debug/$PANEL/dsi-ctrl-0/reg_dump

sh_su() {
    # shellcheck disable=SC2086
    $ADB shell su -c "$1" 2>/dev/null
}

echo "== hardware timing (authoritative) =="
total=$(sh_su "grep DSI_VIDEO_MODE_TOTAL $CTRL" | grep -o '0x[0-9a-fA-F]*' | head -n1)
pclk=$(sh_su "grep -w dsi0pll_pclk_src /sys/kernel/debug/clk/clk_summary" | awk 'NR==1{print $5}')

if [ -z "$total" ] || [ -z "$pclk" ]; then
    echo "  could not read the DSI controller or the clock tree; is the device rooted and awake?"
else
    printf '  DSI_VIDEO_MODE_TOTAL = %s\n' "$total"
    printf '  pixel clock          = %s Hz\n' "$pclk"
    awk -v t="$total" -v c="$pclk" 'BEGIN {
        v = strtonum(t); h = and(v, 65535) + 1; vt = int(v / 65536) + 1
        printf "  htotal = %d, vtotal = %d\n", h, vt
        printf "  actual refresh rate  = %.3f Hz\n", c / (h * vt)
    }'
fi

echo
echo "== rates the panel driver actually applied =="
applied=$(sh_su "dmesg | grep -oE 'entered rate:[0-9]+' | sort | uniq -c")
if [ -n "$applied" ]; then
    echo "$applied" | sed 's/^/  /'
else
    echo "  no dsi_bridge_enable records in the current kernel ring buffer"
fi

echo
echo "== modes exposed by DRM =="
sh_su "cat /sys/class/drm/card0-DSI-1/modes" | sed 's/^/  /'

echo
echo "== SurfaceFlinger view (derived, can disagree with the hardware) =="
# shellcheck disable=SC2086
$ADB shell dumpsys SurfaceFlinger 2>/dev/null \
    | grep -E 'VSYNC period|Allowed Display Configs|refresh-rate' | sed 's/^ */  /'

echo
echo "== vendor state =="
for key in persist.pvr.display.type sys.pvr.display.type; do
    # shellcheck disable=SC2086
    printf '  %s = %s\n' "$key" "$($ADB shell getprop $key 2>/dev/null | tr -d '\r')"
done
# shellcheck disable=SC2086
printf '  pico_refresh_selector_choice = %s\n' \
    "$($ADB shell settings get global pico_refresh_selector_choice 2>/dev/null | tr -d '\r')"

echo
echo "== display errors since boot =="
errors=$(sh_su "dmesg | grep -icE 'new_hfp|underrun|dsc_|pll_unlock'")
printf '  matching dmesg lines: %s\n' "${errors:-unknown}"
