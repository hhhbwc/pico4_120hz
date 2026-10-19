# FLASH_PLAN — PICO4 120Hz dtbo 刷入（2026-10-19）

## 目标
把设备从「被 disable 的 120Hz 模块 + 90Hz stock dtbo（df09ffa4，表偏移滞后）」
升级为「120Hz dtbo（PHY 已修到 1325MHz）+ 重新启用模块」，使 120Hz 生效且消除边缘虚化。

## 当前设备状态（已核实）
- 型号 PICOA8110 / SHARP5K 面板 / 固件 5.13.7 smartcm.1761755159 (dev-keys)
- bootloader 已解锁 (device_state=unlocked / verifiedbootstate=orange) → fastboot 可刷
- 已装模块 `pico4_120hz` v1.0.1，但被 `disable` 文件禁用 → 当前无 120Hz 请求
- 当前 dtbo 分区 = df09ffa4（**stock 90Hz 内容**，非 120Hz；坏表仅偏移滞后，可启动）
- SurfaceFlinger 实测 72Hz，DRM 暴露 90/72，无 120 模式

## 镜像（均经 verify() 校验，合法 16 条目 DTBO）
- `dtbo-120-scale.img`  sha 27d968df…  **← 本次主刷（120Hz + PHY 放大到 1325MHz）**
- `dtbo-120-keep.img`   sha a57573ae…  ← 兜底（=v6，120Hz 但保留 993MHz 旧 PHY，边缘虚化）
- `dtbo-120-nop.img`    sha 9c79d713…  ← 备选（PHY 属性删除，内核重算）
- `dtbo-stock-cn-24mb.img` sha 307e7021… ← 干净的 90Hz 基线（不刷，仅参考）

## 回滚资产（刷前确认就位）
- 当前设备 dtbo 备份：`dtbo-device-pulled.img` (df09ffa4, 24MB) — fastboot 可刷回
- 硬件槽：`dtbobak` 分区（/dev/block/by-name/dtbobak，与 dtbo 同尺寸）
- 终极：EDL（Vol↑+Vol↓+Power 进 EDL）→ edl-ng + firehose（见 RECOVERY.md）

## 执行步骤
1. （已做）adb 在线，re-pull 当前 dtbo 确认回滚文件 = df09ffa4。
2. `adb shell rm /data/adb/modules/pico4_120hz/disable`  ← 重新启用模块（开机发 config=120）
3. `adb reboot bootloader`
4. `fastboot flashing get_unlock_ability` 确认可刷（应为 yes）
5. `fastboot flash dtbo dtbo-120-scale.img`
6. `fastboot reboot`
7. 等待开机，adb 重连，验证：
   - `dumpsys SurfaceFlinger --display-configs` 应出现 120Hz 配置且 VSYNC period ≈ 8.33ms
   - `service.sh` 日志：`logcat -d | grep pico4_120hz` 应见 "applied: config=1 ..."
   - 目测边缘虚化是否改善

## 失败回退
- 黑屏/花屏：`fastboot flash dtbo dtbo-120-keep.img`（v6，至少出 120Hz）→ 再不行
  `fastboot flash dtbo dtbo-device-pulled.img`（回原厂 90Hz）→ `touch /data/adb/modules/pico4_120hz/disable` 重新禁用模块。
- 仍异常：进 EDL 用 firehose 恢复（RECOVERY.md）。

## 注意
- 模块 v1.0.1 的 system/lib64/libpxrhmdservice.so 是 August 固件补丁版，覆盖到 Nov 固件上；
  若导致显示服务异常，可在恢复后仅保留 service.sh（删 system/lib64）再用 config 调用方式。
- 不刷 boot/vbmeta，仅刷 dtbo 单分区，影响范围最小。
