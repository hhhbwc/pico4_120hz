# PICO 4 120Hz Display Unlock

PICO 4（PICOA8110 / Phoenix，SHARP5K 4.93" 面板）的 **锁定 120Hz** Magisk 模块。它把面板时序、HMD 服务速率映射、120Hz SDK 校准、眼缓冲和底部锁存时序一起改到位，避免只改 DTBO 带来的花屏、卡顿和错误线条。

> **当前发布：v1.1.0（2026-10-20）**
> 仅支持 **CN 5.13.7 + SHARP5K + Magisk**。INTL/OVS 镜像不在本发布内。
>
> 新手请直接看 **[QUICKSTART.md](QUICKSTART.md)**。深度原理与实验记录在 **[pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md)**。

---

## 这个模块做什么

| 项目 | 内容 |
| --- | --- |
| 面板 | 把原厂 90Hz DTBO 改成 120Hz 时序（locked 120，不做实时多档切换） |
| HMD 服务 | 补丁 `libpxrhmdservice.so`：所有速率请求落到 120 配置，并把 SDK 的 `displayRefreshRate` 固定为 120 |
| SDK 校准 | 使用 120Hz 的 TimeWarp wait bias 0/0、曝光 6.5/2.3ms（而不是 72Hz 的 20.13/6.78ms） |
| 眼缓冲 | 把 PICO 默认的每眼 2816×2816 超采样降到面板原生 2160×2160，给 ATW 留 GPU 余量 |
| 锁存时序 | `xrMiniVsyncBackStep=4`，消除面板最底边的晚锁存/扫描撕裂线条 |
| 首次刷入 | 安装器备份原厂 DTBO、写入 120 DTBO、读回校验，并在首次开机做一次面板时序重同步 |
| 升级 | 支持从 v1.0.0 直接覆盖安装 |
| 卸载 | `uninstall.sh` 恢复原厂 DTBO、清理 canary 配置、恢复 ConfigurationService 与 props |

**实测（v1.1.0，离头/桌面场景）**：`FrmGpu` 中位约 **13–15ms**，引擎约 **65–73fps**，`VsyncDelay` 2–3；v1.0.0 同场景约 27–30ms / 30fps。

---

## 支持范围

- **设备**：PICO 4 `PICOA8110`（Phoenix），面板 `ro.pvr.hmd.type=SHARP5K`。
- **固件**：`ro.build.id` 为 `5.13.7*`（安装器会校验）。
- **Root**：Magisk（模块安装、DTBO 写入、props 设置都需要 root）。
- **区域**：本发布仅内置 **CN（Phoenix）** 的 120 DTBO 和 stock CN 回滚镜像；INTL/OVS 请勿安装。
- **刷新率架构**：锁定 120Hz。任何实时 DFPS 切换（离开 120）仍会黑屏，本模块刻意禁止。

---

## 安装 / 升级 / 卸载

### 安装（官方状态）

1. 下载 Release 里的 `pico4-120hz-v1.1.0.zip`。
2. Magisk App → **模块** → **从本地安装** → 选择 zip。
3. 重启。首次开机后屏幕可能闪一下——这是安装器安排的一次性面板时序重同步，正常。
4. 进入系统后确认面板 120Hz（见下方“验证”）。

安装器会自动：
- 校验固件/面板/lib/DTBO 基线；
- 把原厂 DTBO 备份到 `/sdcard/Download/pico4-dtbo-stock-backup.img`；
- 写入 120 DTBO 并读回校验；
- 安装补丁 lib、120 配置、眼缓冲/锁存修复和卸载脚本。

### 从 v1.0.0 升级

直接把 v1.1.0 zip 覆盖安装即可，不需要先卸载：

- 安装器接受 v1.0.0 的旧 lib（`32427922…`）和旧 DTBO（`f0c10d1d…`），不会重刷分区；
- 新补丁 lib、`xrMiniVsyncBackStep=4`、眼缓冲 2160 和 120 校准会在重启后生效；
- 原厂 DTBO 备份保留，卸载仍可回官方。

### 卸载 / 回官方

1. Magisk App → **模块** → 移除 `Pico4 120Hz Display Unlock`。
2. 重启。
3. 卸载脚本会：
   - 用模块内置的 stock CN 镜像（或安装时的备份）恢复 DTBO；
   - 重置 `sdk_refreshRate` / `sdk_Recommand_refreshRate` / `displayRefreshRate` / 眼缓冲 / `persist.pvr.display.type`；
   - 删除 `/data/misc/pxr/canary/config/pxr_config.txt` 和 `/sdcard/psmart/canary/pxr_config.txt`；
   - 在 `/data/adb/service.d/` 放一个一次性清理脚本，确保重启后配置也恢复。

重启后应回到官方 72Hz（系统设置里仍可选 90Hz）。

> 如果 `/sdcard/Download/pico4-dtbo-stock-backup.img` 丢失，模块内的 `dtbo-stock.img` 仍是可验证的 CN 原厂镜像；两者都缺失时用 EDL 读 `dtbobak` 或官方固件回滚（见下）。

---

## 验证 120Hz

```bash
adb shell dumpsys SurfaceFlinger | grep -m1 refresh-rate
# 期望：refresh-rate : 120.000005 fps

adb shell dumpsys pxrhmdservice | head -8
# 期望：getRefreshRate ... refreshRate=120.000000

adb shell getprop sys.pvr.display.type
# 期望：120.000000
```

如果仍是 72Hz：

- 确认模块已启用并重启过；
- 确认固件是 5.13.7 CN、面板 SHARP5K；
- 查看 Magisk 安装日志/`logcat` 里是否有 `pico4_120hz` 的 abort；
- 确认没有其他模块同时修改 `dtbo` 或 `libpxrhmdservice.so`。

---

## 已知限制（重要）

1. **2D 应用边缘的蓝紫描边仍在**。这是面板在 120Hz 下的模拟/充电标定极限，`screencap` 抓图是干净的；所有 DTBO 候选（`b0both`、`panel-b0`、`vfp14`、`e5d5`）和色差校正开关都改变不了它。
2. **整体画面有轻微发白/发雾**。这是 90Hz gamma/VCOM 标定被推到 120Hz 的基线代价；比早期 `e5d5` 候选的严重白滤镜轻得多（那个是错误写入 E5/D5 导致的，已排除）。
3. **不保证所有应用都跑满 120fps**。面板扫描是 120Hz，应用渲染由 GPU 决定；本模块通过把眼缓冲降到 2160 大幅改善了帧时序，但重负载场景仍可能低于 72fps。
4. **INTL/OVS 不支持**。本发布只打包 CN 镜像；INTL 设备安装会安全 abort，不会写分区。
5. **不要实时切换刷新率**。离开 120 的 DFPS 切换会黑屏；本模块锁定 120。

如果蓝边/发雾无法接受，建议回官方 90Hz；继续盲写面板寄存器收益很低。

---

## 故障排查 / 恢复

### 开机黑屏、卡 bootloader、模块导致无法开机

1. 先尝试强制重启/电源键；如果能进系统，用 Magisk 安全模式或 Magisk App 移除模块。
2. 如果卡在 bootloader：
   - PICO 4 的 fastboot **没有** critical partition 的 unlocktoken 权限，`fastboot flash` 会被拒；
   - 写分区只能走 **EDL(9008)**：Vol Up + Vol Down + Power 进入 EDL，或 `fastboot reboot edl`；
   - 用 `edl-ng read-part dtbobak` 读取本机原厂备份槽做 sha 真值，确认 `dtbo-stock-5.13.7.img`（`307e7021…`）后 `write-part dtbo`；
   - 详细步骤：[RECOVERY.md](RECOVERY.md)。

### 安装器 abort：Unknown dtbo baseline

说明当前 DTBO 不是已知的 stock/v6/vfp14 基线（或已被其他工具改过）。先 EDL/官方固件恢复 stock `307e7021…`，再安装。

### 安装器 abort：INTL / CN-only

本发布只支持 CN。INTL 设备请不要强行刷 CN 镜像，否则 bootloader 可能选错设备树。

---

## 安全红线

- 二进制分区镜像只能来自 **`edl-ng read-part`** 或 **官方 firmware 包**；**绝不要**用 `adb shell dd > hostfile` 拉分区（会污染/错位，曾导致设备卡 bootloader）。
- 写 `dtbo` 前必须确认镜像大小为 **25,165,824 字节（24 MiB）**，并读回校验 SHA-256。
- 回滚前先读同机 `dtbobak` 槽做真值对照；`dtbobak` 是工程 abl 建的原厂备份槽，从未被写过。
- 不要用 `fastboot flash` 写本机的 critical 分区（unlocktoken 缺失）。
- 刷机前备份 `/sdcard/Download/pico4-dtbo-stock-backup.img`。

---

## 技术文档

| 文档 | 内容 |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | 5 分钟安装/升级/卸载 |
| [pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md) | v1.1.0 的画质/时序分析、眼缓冲与晚锁存修复、候选对比 |
| [pico4-display-analysis/LS026B3SA_120HZ_FULL_CONFIG.md](pico4-display-analysis/LS026B3SA_120HZ_FULL_CONFIG.md) | LS026B3SA 120Hz 完整配置推导 |
| [pico4-display-analysis/EDL_120HZ_EXPERIMENT.md](pico4-display-analysis/EDL_120HZ_EXPERIMENT.md) | EDL 直写 DTBO 实验 |
| [RECOVERY.md](RECOVERY.md) | 砖机恢复、EDL、`*bak` 槽真值 |
| [HANDOVER-120HZ.md](HANDOVER-120HZ.md) | 项目交接与验证清单 |

---

## 版本历史

- **v1.1.0（2026-10-20）**：眼缓冲 2816→2160（FrmGpu 约减半）、`xrMiniVsyncBackStep=4` 修复底部撕裂、120Hz SDK 校准、CN 安装器升级/卸载支持、stock CN 回滚镜像。
- **v1.0.1（本地开发版，未单独发布）**：固件门组件化、Phoenix_ovs 支持、一次性面板重同步、打包可复现。
- **v1.0.0（2026-09-05）**：首个锁定 120Hz 发布（v6 DTBO + 速率映射 + 开机帧率修正）。

---

## 许可

MIT License，见 [LICENSE](LICENSE)。仅供个人设备研究与自用；刷机有风险，请先备份并确认能走 EDL 恢复。
