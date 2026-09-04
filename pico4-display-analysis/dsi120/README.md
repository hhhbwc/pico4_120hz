# dsi120 — force the PICO 4 DSI pixel clock at 120 Hz

## What it is

A loadable Linux kernel module for the SM8250 PICO 4 (kernel
`4.19.81-perf+`) that hooks `dsi_display_set_mode()` via kprobe and
manually invokes `dsi_clk_set_pixel_clk_rate()` to move the DSI PLL
off the 993 MHz (90 Hz) value the driver currently leaves it on.

## Why

See `../FINAL_120HZ_ANALYSIS.md`.  The short version: the PICO display
driver registers the 120 Hz mode and updates the DRM state machine
(`entered rate:120`), but never actually reprograms the DSI PLL.  The
panel therefore receives a 90 Hz signal while the stack believes it is
at 120 — a black screen with a corrupted band at the bottom.

This module closes that gap from outside the driver, without touching
the DTBO and without patching the kernel.

## Build (this Windows machine, WSL Ubuntu)

Prerequisites on the WSL side (already installed):
  - `gcc-aarch64-linux-gnu`
  - `linux-source` 4.19 (cloned to `/home/hhhbwc/linux-build/linux-4.19`)
  - `bison`, `flex`, `m4`

```bash
# One-time setup of the buildroot (generates autoconf.h for arm64,
# forces UTS_RELEASE to "4.19.81-perf+" so the built module's
# vermagic exactly matches the running kernel):
bash setup_buildroot.sh

# IMPORTANT: sync the buildroot .config from the device kernel so that
# CONFIG_KPROBES and other feature flags match.  Without this step the
# module builds with CONFIG_KPROBES=n and register_kprobe() becomes a
# stub that always returns 0 — probes are never actually registered.
adb shell 'su -c "zcat /proc/config.gz"' > device-kernel.config
cp device-kernel.config /home/hhhbwc/linux-build/linux-4.19/.config
cd /home/hhhbwc/linux-build/linux-4.19
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- HOSTCFLAGS=-fcommon \
     prepare modules_prepare
# Note: the SELinux genheaders step may fail on modern GCC; the critical
# generated headers (autoconf.h, utsrelease.h, kernel.release) are already
# correct before that point.

# Compile:
bash build.sh

# Artifact:
/home/hhhbwc/linux-build/dsi120/dsi120.ko
```

Expected vermagic in the built module (must match the running kernel
byte-for-byte for `insmod` to accept it):

```
vermagic=4.19.81-perf+ SMP preempt mod_unload modversions aarch64
```

The Windows-side copy is at `out/dsi120.ko`.

## Load (device, via Magisk root, **no reboot required**)

```bash
adb push dsi120.ko /data/local/tmp/
# Cross-compile load_module.c for the device first, or use insmod directly
adb shell su -Z u:r:magisk:s0 -c 'insmod /data/local/tmp/dsi120.ko target_rate=120'
```

The module takes five parameters (all visible at runtime under
`/sys/module/dsi120/parameters/`):

  - `target_rate` — refresh rate (Hz) that triggers the forced switch
    (default `120`).
  - `verbose`   — set `1` to get detailed printk output.
  - `armed`     — set `0` to disarm the kprobe hook without unloading
    (e.g. `echo 0 > /sys/module/dsi120/parameters/armed`).
  - `setmode_hits` — read-only counter of `dsi_display_set_mode` probe hits.
  - `pixel_hits`  — read-only counter of `dsi_clk_set_pixel_clk_rate` probe hits.

## How it works (high level)

  1. Kprobe on `dsi_display_set_mode` fires on every mode set.  When
     `armed=1` and the clock handle has been captured, it queues a
     work item.
  2. Kprobe on `dsi_clk_set_pixel_clk_rate` runs on the first
     legitimate 72<->90 Hz switch and captures the `client` argument —
     that IS `display->dsi_clk_handle`, which we need for the API.
  3. The work item calls, in order:
       - `dsi_clk_prepare_enable(&src_clks)`
       - `dsi_clk_update_parent(&mux_clks, &shadow_clks)`
       - `dsi_clk_set_pixel_clk_rate(handle, 216541680, 0)`   # 120 Hz pclk
       - `dsi_clk_set_byte_clk_rate(handle, 162406260, 0)`    # 120 Hz byteclk
       - `dsi_clk_update_parent(&src_clks, &mux_clks)`
       - `dsi_clk_disable_unprepare(&src_clks)`

   The work is deliberately deferred to a kernel thread so we never
   hold a driver lock while calling into the clock stack.

## Unload

```bash
adb shell su -Z u:r:magisk:s0 -c 'rmmod dsi120'
```

## Signature bypass

`CONFIG_MODULE_SIG_FORCE=y` on the device.  The `patch_sig_enforce.py`
script zeroes the `sig_enforce` boolean variable and patches
`is_module_sig_enforced()` to return false in the boot image.  Flash
the resulting image, then unsigned modules load without the
`Required key not available` error.

## Safety notes

  - No reboot is required.  `rmmod` restores the original behaviour
    immediately (the kernel just stops calling the extra clock switch).
  - The clock switch is throttled to once per second and is not
    re-entrant.
  - Every clock function's return code is logged; a failure is logged
    but does not corrupt state.
  - If the module panics (should not, but kernel modules always carry
    that risk), hold the power button.  The device will reboot to the
    stock DTBO, which is still in place.

## Files

```
dsi120.c                  module source
build.sh                  compile the module
setup_buildroot.sh        one-time buildroot preparation
patch_sig_enforce.py      offline boot-image sig_enforce patcher
hexpatch_boot.py          legacy branch-patch script (analysis only, do not flash)
load_module.c             minimal finit_module() wrapper for Magisk shell
README.md                 this file
```
