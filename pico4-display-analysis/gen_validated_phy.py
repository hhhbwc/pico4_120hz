#!/usr/bin/env python3
# 从 dtbo-120-scale.img 生成 dtbo-120-validated.img：仅把盲放大的 SCALE_PHY
# 全局替换为厂商验证过的 1325MHz PHY(493_120)，其余(120Hz时序/on-command)不动。
import sys
SCALE = bytes.fromhex('002e0b0b222f0c0b0c0306002612')   # 当前盲放大(过头的)
VALID = bytes.fromhex('00250a0a1b250a0a0a0204001f0f')   # 厂商验证 1325MHz
src='dtbo-120-scale.img'; dst='dtbo-120-validated.img'
d=open(src,'rb').read()
n=d.count(SCALE)
assert n>0, "SCALE_PHY 未找到"
d2=d.replace(SCALE, VALID)
# 同时清掉可能残留的旧 90Hz/993 PHY 也一起替换(若某 entry 未被 scale 覆盖)
OLD=bytes.fromhex('0022080819230908090204001c0d')
nold=d2.count(OLD)
d2=d2.replace(OLD, VALID)
open(dst,'wb').write(d2)
print("SCALE_PHY 替换次数:", n)
print("残留 OLD_PHY 二次替换:", nold)
print("结果 VALID 出现:", d2.count(VALID))
print("结果 SCALE 残留:", d2.count(SCALE))
print("结果 OLD 残留:", d2.count(OLD))
import hashlib
print("dst sha256:", hashlib.sha256(d2).hexdigest())
print("written ->", dst)
