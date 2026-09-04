#!/bin/bash
set -euo pipefail
SRC=/mnt/c/Users/wzy/ALCOM/Projects/sj/pico4_120hz/pico4-display-analysis/dsi120/dsi120.c
KDIR=/home/hhhbwc/linux-build/linux-4.19
M=/home/hhhbwc/linux-build/dsi120
mkdir -p "$M"
cp "$SRC" "$M/dsi120.c"
cd "$M"
# SKIP_STACK_VALIDATION=1 tells scripts/Makefile.build to bypass the
# objtool invocation entirely (it never needs to be built).
# -Wno-error: the upstream 4.19 tree has strict warning flags that
# modern GCC 13 trips over (missing-attributes, unused-function).  We
# only care about real errors, so downgrade the rest.
make -C "$KDIR" M="$M" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     LOCALVERSION= SKIP_STACK_VALIDATION=1 EXTRA_CFLAGS="-Wno-error" modules 2>&1 | tail -40
echo "=== result ==="
ls -la "$M"
