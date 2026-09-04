#!/bin/bash
# Make the buildroot produce a .ko whose vermagic matches the running kernel
# on the PICO 4 exactly:
#   vermagic=4.19.81-perf+ SMP preempt mod_unload modversions aarch64
set -e
cd /home/hhhbwc/linux-build/linux-4.19

# 1) Fresh config from defconfig
cp arch/arm64/configs/defconfig .config
make olddefconfig 2>&1 | tail -2

# 2) Flip MODVERSIONS on (so 'modversions' is in vermagic)
scripts/config --enable CONFIG_MODVERSIONS
scripts/config --disable CONFIG_STACK_VALIDATION       # avoid objtool
make olddefconfig 2>&1 | tail -2

# 3) Set the version to 4.19.81-perf+ (SUBLEVEL = 0 -> 81; note the spaces)
sed -i 's/^SUBLEVEL = 0/SUBLEVEL = 81/' Makefile
grep -E "^VERSION =|^PATCHLEVEL =|^SUBLEVEL =" Makefile | head -3

# localversion: bare suffix, no LOCALVERSION= prefix
printf -- '-perf+' > localversion

# 4) Stub out asm/tlbbatch.h for arm64.  Upstream linux-4.19 selects
# CONFIG_ARCH_WANT_BATCHED_UNMAP_TLB_FLUSH on arm64 but only provides the
# real header on x86.  The struct is unused by any arm64 code, so an
# empty stub (the struct is defined inline in mm_types_task.h anyway) is
# enough.  Guarded by CONFIG_ARCH_WANT_BATCHED_UNMAP_TLB_FLUSH so it only
# activates for arm64 where the real one is missing.
mkdir -p arch/arm64/include/generated/asm
cat > arch/arm64/include/generated/asm/tlbbatch.h <<'EOF'
/* Stub: upstream 4.19 selects CONFIG_ARCH_WANT_BATCHED_UNMAP_TLB_FLUSH on
 * arm64 but only ships asm/tlbbatch.h for x86.  The actual struct used by
 * mm_types_task.h is declared there, not here, so an empty file is enough
 * to satisfy the #include.  See include/linux/mm_types_task.h.
 */
EOF

# 5) archprepare for arm64
make -j$(nproc) archprepare ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     SKIP_STACK_VALIDATION=1 2>&1 | tail -3

# 6) Force auto.conf regen
touch .config
make include/config/auto.conf 2>&1 | tail -2 || true

# 7) Sanity check
echo "=== UTS_RELEASE ==="
cat include/generated/utsrelease.h
echo "=== MODVERSIONS in autoconf ==="
grep -E "CONFIG_MODVERSIONS" include/generated/autoconf.h | head

# 8) Clean old object files
rm -f /home/hhhbwc/linux-build/dsi120/dsi120.mod.o \
      /home/hhhbwc/linux-build/dsi120/dsi120.mod.c \
      /home/hhhbwc/linux-build/dsi120/dsi120.ko \
      /home/hhhbwc/linux-build/dsi120/dsi120.o
