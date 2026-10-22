# PICO 4 120Hz Display Unlock

[中文](#中文) · [English](#english) · [Русский](#русский)

---

## 中文

> **当前发布：v1.2.1（2026-10-20）**
> 我把 PICO 4（PICOA8110 / Phoenix）的 Sharp LS026B3SA 面板（`ro.pvr.hmd.type=SHARP5K`，单眼 2160×2160）锁定在 120Hz，并配套改了 HMD 服务、SDK 校准、眼缓冲和底部锁存时序。
> 支持 **CN（Phoenix）与 Phoenix_ovs（国际版 b9666）**、固件 **5.13.7**、Magisk。
> 其他国际基线（bee2b067）不在本发布内。
>
> 新手直接看 **[QUICKSTART.md](QUICKSTART.md)**；我的完整实验记录在 **[pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md)**。
>
> **v1.2.1 更新：** `service.sh` 增加 Pico3dResolution 兼容——每 30s 把 `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` 压回 2160，V-Sleep 生效或恢复期间让位。另加模块目录外的开机回滚守卫：用 Magisk 的 remove（或直接删模块目录）卸载时，首次开机自动恢复原厂 DTBO + 90Hz 配置。**不要用 disable**——禁用不会重刷 DTBO，重新启用请重刷 zip。
>
> **⚠️ 面板供应商/规格不统一（社区反馈，不是我的实测）。** 有人的 P4 是 Sharp 面板、规格可到 120Hz；有人的 P4 Pro 是 Innolux 面板、只能 90Hz；还有人说见过 P4 的三种面板。**本项目的机型是 PICO 4（PICOA8110 / Phoenix），面板 Sharp LS026B3SA（`ro.pvr.hmd.type=SHARP5K`），驱动 IC 是 Novatek NT57900**——机型、面板标识、原厂 DTBO 与 lib 哈希都由安装器逐项校验。两点与我的实测有出入：① “Sharp 可到 120”说的是面板硬件能扫更快，但原厂 DTBO 里这块面板只有一个 90Hz timing 节点，它的 `post-120-nt57900-on-command` 只是 53 字节的补充命令、不是完整的 120Hz 配置；本项目的 120Hz 属超频，所以蓝紫描边/发雾在 DTBO 层消不掉。② 同一份原厂 DTBO 里的 `innolux_nt57900_90_video` 节点（同样 2160×2160/眼、同 DSC 拓扑、同 NT57900）**反而带完整的 72/90/120 三档 on-command 查表**（`ff` 页；与 Sharp 的 `b9` 页地址空间不同，值不可互搬），所以“Innolux 只能 90Hz”我无法确认。安装器对 `ro.pvr.hmd.type != SHARP5K` 一律 abort，非 Sharp 面板机型不在支持范围——请只回帖这几项，不要刷本模块：`ro.product.device`、`ro.build.id`、`ro.pvr.hmd.type`、`sys.pvr.display.type`、`persist.pvr.display.type`、`androidboot.dtbo_idx`（在 `/proc/cmdline` 里）、`sha256sum /dev/block/by-name/dtbo`、`cat /sys/class/drm/card0-DSI-1/modes`。我这台已知 Sharp 的原厂机实测是：`PICOA8110` / `5.13.7` / `SHARP5K` / `72.000000` / `jdi49390` / `dtbo_idx=5` / `307e7021…` / `4320x2160x90 + 4320x2160x72`。**注意：运行时的 Android 读不出面板厂商**（16 个 `qcom,mdss_dsi_*` 节点在 live tree 里全都在、都没有 `status` 属性，dmesg 里没有厂商名），所以只能靠上面这组指纹做差分；main 分支的安装器已会在日志开头自动打印它（尚未随 zip 发布）。

### 我做了什么

| 项目 | 我的改动 |
| --- | --- |
| 面板 | 把原厂 90Hz DTBO 改成 120Hz 时序（locked 120，不做实时多档切换） |
| HMD 服务 | 补丁 `libpxrhmdservice.so`：所有速率请求落到 120 配置，并把 SDK 的 `displayRefreshRate` 固定为 120 |
| SDK 校准 | 使用 120Hz 的 TimeWarp wait bias 0/0、曝光 6.5/2.3ms，而不是 72Hz 的 20.13/6.78ms |
| 眼缓冲 | 把 PICO 默认的每眼 2816×2816 超采样降到面板原生 2160×2160，给 ATW 留 GPU 余量 |
| 锁存时序 | `xrMiniVsyncBackStep=4`，消除面板最底边的晚锁存/扫描撕裂线条 |
| 首次刷入 | 安装器备份原厂 DTBO、写入 120 DTBO、读回校验，并在首次开机做一次面板时序重同步 |
| 升级 | 支持从 v1.0.0 / v1.1.0 直接覆盖安装 |
| 卸载 | `uninstall.sh` 恢复对应变体的原厂 DTBO、清理 canary 配置、恢复 ConfigurationService 与 props |

**我的实测（v1.2.0，摘下头显的桌面场景）**：`FrmGpu` 中位约 **13–15ms**，引擎约 **65–73fps**，`VsyncDelay` 2–3；v1.0.0 同场景约 27–30ms / 30fps。

### 支持范围

- **设备**：PICO 4 `PICOA8110`（Phoenix），面板 `ro.pvr.hmd.type=SHARP5K`。
- **固件**：`ro.build.id` 为 `5.13.7*`（安装器会校验）。
- **Root**：Magisk（模块安装、DTBO 写入、props 设置都需要 root）。
- **区域**：CN（Phoenix）与 Phoenix_ovs（国际版 b9666）。安装器按当前 stock DTBO 哈希自动选择对应的 120/stock 镜像；其他国际基线（bee2b067）请勿安装。
- **刷新率架构**：锁定 120Hz。任何实时 DFPS 切换（离开 120）仍会黑屏，我的模块刻意禁止。

### 安装 / 升级 / 卸载

**全新安装（出厂状态）**

1. 下载 Release 里的 `pico4-120hz-v1.2.1.zip`。
2. Magisk App → **模块** → **从本地安装** → 选择 zip。
3. 重启。首次开机后屏幕可能闪一下——这是我安排的一次性面板时序重同步，正常。
4. 进入系统后确认面板 120Hz（见下方“验证”）。

我的安装器会自动：
- 校验固件/面板/lib/DTBO 基线；
- 识别 **CN / Phoenix_ovs** 并选择对应的 120 镜像与 stock 回滚镜像；
- 把原厂 DTBO 备份到 `/sdcard/Download/pico4-dtbo-stock-backup.img`；
- 写入 120 DTBO 并读回校验；
- 安装补丁 lib、120 配置、眼缓冲/锁存修复和卸载脚本。

**从 v1.0.0 / v1.1.0 升级**

直接把 v1.2.1 zip 覆盖安装即可，不需要先卸载：

- 安装器接受旧 lib（`32427922…`）和旧 DTBO（`f0c10d1d…`），不会重刷分区；
- 新补丁 lib、`xrMiniVsyncBackStep=4`、眼缓冲 2160 和 120 校准会在重启后生效；
- 原厂 DTBO 备份保留，卸载仍可回官方。

**卸载 / 回官方**

1. Magisk App → **模块** → 移除 `Pico4 120Hz Display Unlock`。
2. 重启。
3. 卸载脚本会用模块内置的对应变体 stock 镜像（CN `307e7021…` / OVS `f4d6073c…`，或安装时的备份）恢复 DTBO，重置 `sdk_refreshRate` / `sdk_Recommand_refreshRate` / `displayRefreshRate` / 眼缓冲 / `persist.pvr.display.type`，删除 canary 配置，并在 `/data/adb/service.d/` 放一个一次性清理脚本。
4. 重启后应回到官方 72Hz（系统设置里仍可选 90Hz）。

> 如果 `/sdcard/Download/pico4-dtbo-stock-backup.img` 丢失，模块目录里的 `/data/adb/modules/pico4_120hz/dtbo-stock.img`（安装器按变体从 zip 内 `dtbo-stock-cn.img` / `dtbo-stock-ovs.img` 复制而来）仍是可校验的原厂镜像；两者都缺失时用 EDL 读 `dtbobak` 或官方固件回滚（见下）。

### 验证 120Hz

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
- 确认固件是 5.13.7、面板 SHARP5K；
- 查看 Magisk 安装日志/`logcat` 里是否有 `pico4_120hz` 的 abort；
- 确认没有其他模块同时修改 `dtbo` 或 `libpxrhmdservice.so`。
- 把开头那份指纹整段贴出来（`pico4_120hz fingerprint …`）；`dtbo` 哈希已是 `f0c10d1d…` 却仍 72/90Hz，就不是"没刷上"，而是面板批次/硬件差异——见上方说明。

### 已知限制（重要）

1. **2D 应用边缘的蓝紫描边仍在**。这是面板在 120Hz 下的模拟/充电标定极限，`screencap` 抓图是干净的；我试过的所有 DTBO 候选（`b0both`、`panel-b0`、`vfp14`、`e5d5`）和色差校正开关都改变不了它。
2. **整体画面有轻微发白/发雾**。这是 90Hz gamma/VCOM 标定被推到 120Hz 的基线代价；比早期 `e5d5` 候选的严重白滤镜轻得多（那个是错误写入 E5/D5 导致的，已排除）。
3. **不保证所有应用都跑满 120fps**。面板扫描是 120Hz，应用渲染由 GPU 决定；我通过把眼缓冲降到 2160 大幅改善了帧时序，但重负载场景仍可能低于 72fps。
4. **其他 global 基线（bee2b067）不支持**。CN 与 Phoenix_ovs（b9666）已打包；未知基线会安全 abort，不写分区。
5. **Phoenix_ovs 尚未物理机回归**。OVS 120 镜像由官方 b9666 包构建，entry 6 补丁与面板子树已离线校验（与 CN v6 逐字节一致），但本发布只在 CN 真机上完成了刷机/升级/卸载回归；首次 OVS 安装请保留 stock 备份。
6. **不要实时切换刷新率**。离开 120 的 DFPS 切换会黑屏；我的模块锁定 120。

如果蓝紫描边/发雾无法接受，建议回官方 90Hz；继续盲写面板寄存器收益很低。

### 故障排查 / 恢复

- **开机黑屏、卡 bootloader**：先强制重启或电源键熄屏再亮；能进系统就用 Magisk 安全模式/App 移除模块。卡 bootloader 时进 EDL（Vol Up + Vol Down + Power），用 `edl-ng read-part dtbobak` 读本机原厂槽，确认读到的镜像是 **25,165,824 字节**且 SHA-256 = `307e7021…`（CN）/ `f4d6073c…`（Phoenix_ovs）后再 `write-part dtbo`。本仓库不附带任何 `.img`（`.gitignore` 已排除），需要现成文件就从安装包里取 `dtbo-stock-cn.img` / `dtbo-stock-ovs.img`，或用官方固件包；**别把 `dtbo-stock-cn-5.13.7.img` 当原厂**（它只有 8 MiB、`ffd65209…`，是不完整的截断副本，写进去开不了机）。详见 [RECOVERY.md](RECOVERY.md)。
- **安装器 abort: Unknown dtbo baseline**：当前 DTBO 不是已知的 stock/v6/vfp14/OVS 基线。先用 EDL/官方固件恢复 stock，再安装。
- **安装器 abort: Unsupported global**：该国际基线不在本发布内；不要强刷 CN/OVS 镜像。

### 安全红线

- 二进制分区镜像只能来自 **`edl-ng read-part`** 或 **官方 firmware 包**；**绝不要**用 `adb shell dd > hostfile` 拉分区。
- 写 `dtbo` 前必须确认镜像大小为 **25,165,824 字节（24 MiB）**，并读回校验 SHA-256。
- 回滚前先读同机 `dtbobak` 槽做真值对照；`dtbobak` 是工程 abl 建的原厂备份槽，从未被写过。
- 不要用 `fastboot flash` 写本机的 critical 分区（unlocktoken 缺失）。
- 刷机前确认已有原厂 DTBO 备份（安装器会自动存到 `/sdcard/Download/pico4-dtbo-stock-backup.img`）。

### 技术文档

| 文档 | 内容 |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | 5 分钟安装/升级/卸载 |
| [pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md) | 画质/时序分析、眼缓冲与晚锁存修复、候选对比 |
| [pico4-display-analysis/LS026B3SA_120HZ_FULL_CONFIG.md](pico4-display-analysis/LS026B3SA_120HZ_FULL_CONFIG.md) | LS026B3SA 120Hz 完整配置推导 |
| [pico4-display-analysis/EDL_120HZ_EXPERIMENT.md](pico4-display-analysis/EDL_120HZ_EXPERIMENT.md) | EDL 直写 DTBO 实验 |
| [RECOVERY.md](RECOVERY.md) | 砖机恢复、EDL、`*bak` 槽真值 |
| [HANDOVER-120HZ.md](HANDOVER-120HZ.md) | 项目交接与验证清单 |

### 版本历史

- **v1.2.1（2026-10-20）**：`service.sh` 增加 Res3D 兼容——每 30s 把 `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` 压回 2160，V-Sleep 期间让位；zip 已重建。
- **v1.2.0（2026-10-20）**：新增 Phoenix_ovs（国际版 b9666）支持；安装器按 stock DTBO 自动选择 CN/OVS 镜像与 stock 回滚镜像；CN 路径已完成真机回归。
- **v1.1.0（2026-10-20）**：眼缓冲 2816→2160（FrmGpu 约减半）、`xrMiniVsyncBackStep=4` 修复底部撕裂、120Hz SDK 校准、CN 安装器升级/卸载支持、stock CN 回滚镜像。
- **v1.0.0（2026-09-05）**：首个锁定 120Hz 发布（v6 DTBO + 速率映射 + 开机帧率修正）。

### 许可

MIT License，见 [LICENSE](LICENSE)。仅供个人设备研究与自用；刷机有风险，请先备份并确认能走 EDL 恢复。

---

## English

> **Current release: v1.2.1 (2026-10-20)**
> I lock the PICO 4 (PICOA8110 / Phoenix, panel SHARP5K = Sharp LS026B3SA, 2160×2160 per eye) at 120 Hz and fix the HMD-service mapping, 120 Hz SDK calibration, eye buffer and bottom-edge latch timing.
> Supported: **CN (Phoenix) and Phoenix_ovs (international b9666)**, firmware **5.13.7**, Magisk.
> Other international baselines (bee2b067) are not included in this release.
>
> New users: read **[QUICKSTART.md](QUICKSTART.md)**. My full experiment log: **[pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md)**.
>
> **v1.2.1 update:** `service.sh` now coordinates with Pico3dResolution — every 30 s it clamps `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` back to 2160, and yields while V-Sleep is active or restoring. A boot guard outside the module also restores the stock DTBO + 90 Hz config on the first boot after Magisk `remove` (or manual deletion). **Do not disable** — disabling does not re-flash the DTBO; reinstall the zip after re-enabling.
>
> **⚠️ Panel suppliers/specs are not uniform (community reports, not my measurements).** Some P4 units have a Sharp panel whose spec reaches 120 Hz; some P4 Pro units have an Innolux panel limited to 90 Hz; one person claims three different panels across P4. **This project's unit is a PICO 4 (PICOA8110 / Phoenix) with a Sharp LS026B3SA panel (`ro.pvr.hmd.type=SHARP5K`) and a Novatek NT57900 driver IC** — device, panel id, stock DTBO and lib hashes are all verified by the installer. Two points differ from my measurements: (1) "Sharp can do 120" means the panel hardware can scan faster, but in the stock DTBO this panel has only a single 90 Hz timing node and its `post-120-nt57900-on-command` is a 53-byte supplemental command, not a complete 120 Hz configuration — my 120 Hz is an overclock, which is why the blue/purple fringing and haze cannot be removed at DTBO level. (2) The `innolux_nt57900_90_video` node in the *same* stock DTBO (also 2160×2160 per eye, same DSC topology, same NT57900) actually ships a **complete 72/90/120 three-tier on-command table** (`ff` page; different address space from Sharp's `b9` page, values are not transplantable), so I cannot confirm that Innolux units are limited to 90 Hz. The installer aborts on `ro.pvr.hmd.type != SHARP5K`; non-Sharp panels are unsupported — please just post `ro.product.device`, `ro.build.id`, `ro.pvr.hmd.type`, `sys.pvr.display.type`, `persist.pvr.display.type`, `androidboot.dtbo_idx` (from `/proc/cmdline`), `sha256sum /dev/block/by-name/dtbo` and `cat /sys/class/drm/card0-DSI-1/modes` instead of flashing. My known-Sharp stock unit measures: `PICOA8110` / `5.13.7` / `SHARP5K` / `72.000000` / `jdi49390` / `dtbo_idx=5` / `307e7021…` / `4320x2160x90 + 4320x2160x72`. **Note: Android cannot reveal the panel supplier at runtime** (all 16 `qcom,mdss_dsi_*` nodes are present in the merged live tree, none carries a `status` property, and the kernel log names no vendor), so this fingerprint set is the strongest differential available; the installer on `main` already prints it at the top of the install log (not yet in the shipped zip).

### What I changed

| Item | My change |
| --- | --- |
| Panel | Rebuild the stock 90 Hz DTBO as a 120 Hz timing (locked 120, no live multi-rate switching) |
| HMD service | Patch `libpxrhmdservice.so`: every rate request maps to the 120 config; the SDK `displayRefreshRate` is pinned to 120 |
| SDK calibration | Use the 120 Hz TimeWarp wait bias 0/0 and exposure 6.5/2.3 ms, not the 72 Hz 20.13/6.78 ms values |
| Eye buffer | Clamp PICO's 2816×2816 per-eye supersampling to the panel-native 2160×2160 to give the ATW pass GPU headroom |
| Latch timing | `xrMiniVsyncBackStep=4` removes the bottom-edge late-latch tear |
| First flash | The installer backs up the stock DTBO, writes the 120 DTBO, verifies the read-back, and arms a one-shot panel resync on the first boot |
| Upgrade | Directly install over v1.0.0 / v1.1.0 |
| Uninstall | `uninstall.sh` restores the matching stock DTBO, clears the canary config, resets ConfigurationService and props |

**My measurements (v1.2.0, off-head/desktop):** median `FrmGpu` **13–15 ms**, engine **~65–73 fps**, `VsyncDelay` 2–3; v1.0.0 was ~27–30 ms / 30 fps in the same scene.

### Support

- **Device:** PICO 4 `PICOA8110` (Phoenix), panel `ro.pvr.hmd.type=SHARP5K`.
- **Firmware:** `ro.build.id` = `5.13.7*`.
- **Root:** Magisk.
- **Region:** CN (Phoenix) and Phoenix_ovs (international b9666). The installer picks the 120/stock pair from the current stock DTBO hash. Other international baselines (bee2b067) are not supported.
- **Architecture:** locked 120 Hz. Any live DFPS switch away from 120 still black-screens, so I deliberately prohibit it.

### Install / upgrade / uninstall

**Fresh install**

1. Download `pico4-120hz-v1.2.1.zip` from the Release.
2. Magisk → **Modules** → **Install from storage** → select the zip.
3. Reboot. The screen may blink once on the first boot — that is my one-shot panel resync.
4. Verify 120 Hz (below).

My installer will:
- verify firmware/panel/lib/DTBO;
- detect **CN / Phoenix_ovs** and select the matching 120 and stock images;
- back up the stock DTBO to `/sdcard/Download/pico4-dtbo-stock-backup.img`;
- write the 120 DTBO and verify the read-back;
- install the patched lib, 120 config, eye-buffer/latch fixes and uninstall script.

**Upgrade from v1.0.0 / v1.1.0**

Install the v1.2.1 zip over the existing module, then reboot. My installer accepts the old lib (`32427922…`) and old DTBO (`f0c10d1d…`), skips the partition write, and keeps the stock backup for a later uninstall.

**Uninstall / restore stock**

1. Magisk → **Modules** → remove `Pico4 120Hz Display Unlock`.
2. Reboot.
3. The uninstall script restores the matching stock image (CN `307e7021…` / OVS `f4d6073c…`, or the install-time backup), resets the ConfigurationService keys and props, removes the canary config, and leaves a one-shot cleanup script.
4. The device returns to stock 72 Hz (90 Hz remains selectable).

### Verify 120 Hz

```bash
adb shell dumpsys SurfaceFlinger | grep -m1 refresh-rate
# expect: refresh-rate : 120.000005 fps

adb shell dumpsys pxrhmdservice | head -8
# expect: getRefreshRate ... refreshRate=120.000000

adb shell getprop sys.pvr.display.type
# expect: 120.000000
```

### Known limitations

1. **Blue/purple fringing at 2D app edges remains.** It is the panel's 120 Hz analog/charge-calibration limit; `screencap` is clean. None of my DTBO candidates (`b0both`, `panel-b0`, `vfp14`, `e5d5`) or CA toggles changed it.
2. **A slight overall washed-out haze remains.** It is the baseline cost of running the 90 Hz gamma/VCOM calibration at 120 Hz, much milder than the early `e5d5` white filter (that was a wrong E5/D5 write and was rolled back).
3. **Not every app reaches 120 fps.** The scanout is 120 Hz; the app rate is GPU-bound. My 2160 eye-buffer clamp greatly improves frame pacing, but heavy scenes can still fall below 72 fps.
4. **Other global baselines (bee2b067) are not supported.** CN and Phoenix_ovs (b9666) are bundled; unknown baselines abort safely without touching the partition.
5. **Phoenix_ovs is not yet physically regression-tested.** I built the OVS 120 image from the official b9666 package and validated entry 6 + the panel subtree (byte-identical to CN v6) offline; this release was flash/upgrade/uninstall-tested on a CN unit only. Keep the stock backup for the first OVS install.
6. **Do not switch refresh rates live.** Any DFPS switch away from 120 black-screens; my module locks 120.

If the fringing/haze is unacceptable, go back to stock 90 Hz; further blind panel-register writes have low expected value.

### Recovery

- **Black screen / bootloader:** force a reboot or power-cycle; if Android boots, remove the module via Magisk safe mode/App. If stuck in the bootloader, enter EDL (Vol Up + Vol Down + Power), read the unit's `dtbobak` slot with `edl-ng read-part`, and confirm the image is **25,165,824 bytes** with SHA-256 `307e7021…` (CN) / `f4d6073c…` (Phoenix_ovs) before `write-part dtbo`. This repo ships no `.img` files (gitignored) — take `dtbo-stock-cn.img` / `dtbo-stock-ovs.img` out of the installer zip or use the official firmware package; **do not use `dtbo-stock-cn-5.13.7.img`** (8 MiB, `ffd65209…`, an incomplete truncated dump — writing it will not boot). See [RECOVERY.md](RECOVERY.md).
- **Installer abort — unknown DTBO baseline:** restore the official stock DTBO first.
- **Installer abort — unsupported global:** that baseline is not bundled; do not force a CN/OVS image.

### Safety rules

- Partition images must come from **`edl-ng read-part`** or the **official firmware package**; never use `adb shell dd > hostfile`.
- Verify the image is **25,165,824 bytes (24 MiB)** and read back the SHA-256 before/after writing `dtbo`.
- Read the unit's `dtbobak` slot as ground truth before rolling back.
- Do not use `fastboot flash` on this unit's critical partitions (no unlocktoken authority).
- Keep `/sdcard/Download/pico4-dtbo-stock-backup.img`.

### Docs / history / license

- [QUICKSTART.md](QUICKSTART.md) — install/upgrade/uninstall
- [QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md) — my full quality/timing analysis
- [RECOVERY.md](RECOVERY.md) — brick recovery and EDL
- [HANDOVER-120HZ.md](HANDOVER-120HZ.md) — project handover and test checklist
- v1.2.1: `service.sh` clamps `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` to 2160 every 30 s, yields to V-Sleep; zip rebuilt.
- v1.2.0: Phoenix_ovs (b9666) support, CN/OVS auto-selection.
- v1.1.0: eye buffer 2160, `xrMiniVsyncBackStep=4`, 120 Hz calibration, upgrade/uninstall.
- v1.0.0: first locked-120 Hz release.

MIT License — see [LICENSE](LICENSE). For personal research only; back up and confirm EDL recovery before flashing.

---

## Русский

> **Текущий релиз: v1.2.1 (2026-10-20)**
> Я зафиксировал на 120 Гц панель PICO 4 (PICOA8110 / Phoenix) — Sharp LS026B3SA (`ro.pvr.hmd.type=SHARP5K`), 2160×2160 на глаз — и исправил отображение частот в HMD-сервисе, калибровку SDK для 120 Гц, буфер глаза и задержку защёлкивания нижней строки.
> Поддержка: **CN (Phoenix) и Phoenix_ovs (международная b9666)**, прошивка **5.13.7**, Magisk.
> Другие международные базовые прошивки (bee2b067) в релиз не входят.
>
> Для быстрого старта: **[QUICKSTART.md](QUICKSTART.md)**. Мой полный журнал экспериментов: **[pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md)**.
>
> **Обновление v1.2.1:** `service.sh` теперь согласуется с Pico3dResolution — каждые 30 с возвращает `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` к 2160 и уступает, пока V-Sleep активен или восстанавливается. Сторож в `service.d` вне модуля также возвращает стоковый DTBO и конфиг 90 Гц при первом запуске после Magisk `remove` (или ручного удаления). **Не отключайте модуль** — disable не перезаписывает DTBO; после включения прошейте zip заново.
>
> **⚠️ Поставщики и характеристики панелей неодинаковы (сообщения сообщества, не мои замеры).** У некоторых P4 стоит Sharp-панель со спецификацией до 120 Гц; у некоторых P4 Pro — панель Innolux, ограниченная 90 Гц; есть утверждение, что в P4 встречается три вида панелей. **В этом проекте используется PICO 4 (PICOA8110 / Phoenix) с панелью Sharp LS026B3SA (`ro.pvr.hmd.type=SHARP5K`) и контроллером Novatek NT57900** — модель устройства, id панели, хеши стокового DTBO и библиотеки проверяются установщиком. Два пункта расходятся с моими замерами: (1) «Sharp умеет 120» описывает лишь способность панели сканировать быстрее, но в стоковом DTBO у неё только один тайминг 90 Гц, а `post-120-nt57900-on-command` — это 53-байтная дополнительная команда, а не полная конфигурация 120 Гц; мои 120 Гц — это разгон, поэтому сине-фиолетовая кайма и дымка на уровне DTBO не убираются. (2) Узел `innolux_nt57900_90_video` в *том же* стоковом DTBO (также 2160×2160 на глаз, та же топология DSC, тот же NT57900) содержит **полную таблицу on-command для 72/90/120** (страница `ff`; адресное пространство отличается от Sharp-страницы `b9`, значения перенести нельзя) — поэтому подтвердить ограничение Innolux на 90 Гц я не могу. Установщик прерывает установку при `ro.pvr.hmd.type != SHARP5K`; панели не-Sharp не поддерживаются — вместо прошивки пришлите `ro.product.device`, `ro.build.id`, `ro.pvr.hmd.type`, `sys.pvr.display.type`, `persist.pvr.display.type`, `androidboot.dtbo_idx` (из `/proc/cmdline`), `sha256sum /dev/block/by-name/dtbo` и `cat /sys/class/drm/card0-DSI-1/modes`. Измеренный эталон моей заведомо Sharp-прошивки: `PICOA8110` / `5.13.7` / `SHARP5K` / `72.000000` / `jdi49390` / `dtbo_idx=5` / `307e7021…` / `4320x2160x90 + 4320x2160x72`. **Важно: Android во время работы не показывает поставщика панели** (все 16 узлов `qcom,mdss_dsi_*` присутствуют в объединённом live-дереве, у них нет свойства `status`, а dmesg не содержит имени вендора), поэтому этот набор отпечатков — сильнейший доступный дифференциатор; установщик в ветке `main` уже печатает его в начале лога установки (в выложенном zip этого пока нет).

### Что я изменил

| Компонент | Моё изменение |
| --- | --- |
| Панель | Пересобрал штатный DTBO 90 Гц в тайминг 120 Гц (locked 120, без живого переключения) |
| HMD-сервис | Патч `libpxrhmdservice.so`: все запросы частоты ведут в конфиг 120; `displayRefreshRate` SDK зафиксирован на 120 |
| Калибровка SDK | Использую TimeWarp wait bias 0/0 и экспозицию 6.5/2.3 мс для 120 Гц вместо 20.13/6.78 мс для 72 Гц |
| Буфер глаза | Ограничил суперсэмплинг PICO 2816×2816 на глаз до родных 2160×2160, чтобы дать GPU запас для ATW |
| Защёлкивание | `xrMiniVsyncBackStep=4` убирает разрыв/линию у нижней кромки панели |
| Первая прошивка | Установщик сохраняет штатный DTBO, пишет 120 DTBO, проверяет чтением и делает одну пересинхронизацию панели при первой загрузке |
| Обновление | Прямая установка поверх v1.0.0 / v1.1.0 |
| Удаление | `uninstall.sh` восстанавливает штатный DTBO нужного варианта, чистит canary-конфиг, сбрасывает ConfigurationService и props |

**Мои замеры (v1.2.0, гарнитура снята, сцена на рабочем столе):** медиана `FrmGpu` **13–15 мс**, движок **~65–73 fps**, `VsyncDelay` 2–3; в v1.0.0 та же сцена давала ~27–30 мс / 30 fps.

### Поддержка

- **Устройство:** PICO 4 `PICOA8110` (Phoenix), панель `ro.pvr.hmd.type=SHARP5K`.
- **Прошивка:** `ro.build.id` = `5.13.7*`.
- **Root:** Magisk.
- **Регион:** CN (Phoenix) и Phoenix_ovs (международная b9666). Установщик выбирает пару 120/stock по хешу текущего stock DTBO. Другие международные базы (bee2b067) не поддерживаются.
- **Архитектура:** фиксированные 120 Гц. Любое живое переключение DFPS с 120 по-прежнему даёт чёрный экран, поэтому я его намеренно запрещаю.

### Установка / обновление / удаление

**Чистая установка**

1. Скачайте `pico4-120hz-v1.2.1.zip` из Release.
2. Magisk → **Модули** → **Установить из хранилища** → выберите zip.
3. Перезагрузитесь. При первой загрузке экран может моргнуть — это моя одноразовая пересинхронизация панели.
4. Проверьте 120 Гц (ниже).

Мой установщик:
- проверяет прошивку/панель/lib/DTBO;
- определяет **CN / Phoenix_ovs** и выбирает соответствующие образы 120 и stock;
- сохраняет штатный DTBO в `/sdcard/Download/pico4-dtbo-stock-backup.img`;
- пишет 120 DTBO и проверяет чтением;
- устанавливает пропатченный lib, конфиг 120, исправления буфера глаза и защёлкивания, а также скрипт удаления.

**Обновление с v1.0.0 / v1.1.0**

Установите zip v1.2.1 поверх модуля и перезагрузитесь. Мой установщик принимает старый lib (`32427922…`) и старый DTBO (`f0c10d1d…`), не перезаписывает раздел и сохраняет штатный бэкап для удаления.

**Удаление / возврат к stock**

1. Magisk → **Модули** → удалить `Pico4 120Hz Display Unlock`.
2. Перезагрузитесь.
3. Скрипт удаления восстановит штатный образ нужного варианта (CN `307e7021…` / OVS `f4d6073c…` или бэкап установки), сбросит ключи ConfigurationService и props, удалит canary-конфиг и оставит одноразовый скрипт очистки.
4. Устройство вернётся к штатным 72 Гц (90 Гц останется доступным).

### Проверка 120 Гц

```bash
adb shell dumpsys SurfaceFlinger | grep -m1 refresh-rate
# ожидается: refresh-rate : 120.000005 fps

adb shell dumpsys pxrhmdservice | head -8
# ожидается: getRefreshRate ... refreshRate=120.000000

adb shell getprop sys.pvr.display.type
# ожидается: 120.000000
```

### Известные ограничения

1. **Сине-фиолетовая кайма по краям 2D-приложений остаётся.** Это предел аналоговой/зарядной калибровки панели на 120 Гц; `screencap` чистый. Ни один из моих DTBO-кандидатов (`b0both`, `panel-b0`, `vfp14`, `e5d5`) и ни одна настройка коррекции цвета это не исправили.
2. **Остаётся лёгкая общая бель/дымка.** Это неизбежная цена того, что профиль гаммы/VCOM, откалиброванный для 90 Гц, работает на 120 Гц; выражено намного слабее раннего белого фильтра `e5d5` (там была ошибочная запись E5/D5, образ откачен).
3. **Не все приложения достигают 120 fps.** Развёртка идёт на 120 Гц, а частота приложения ограничена GPU. Ограничение буфера глаза до 2160 сильно улучшает равномерность кадров, но тяжёлые сцены всё ещё могут быть ниже 72 fps.
4. **Другие международные базы (bee2b067) не поддерживаются.** CN и Phoenix_ovs (b9666) включены; неизвестная база безопасно прерывает установку, не трогая раздел.
5. **Phoenix_ovs ещё не прошёл физическую регрессию.** Я собрал OVS 120 из официального пакета b9666 и офлайн проверил entry 6 и поддерево панели (побайтово совпадает с CN v6); в этом релизе я прогнал прошивку/обновление/удаление только на CN-устройстве. Для первой установки на OVS сохраните stock-бэкап.
6. **Не переключайте частоту на лету.** Любое переключение DFPS с 120 даёт чёрный экран; мой модуль фиксирует 120.

Если кайма и дымка неприемлемы, вернитесь на штатные 90 Гц; дальнейшие слепые записи в регистры панели не дают заметного выигрыша.

### Восстановление

- **Чёрный экран / bootloader:** принудительная перезагрузка или выключение/включение; если Android загружается — удалите модуль через Magisk safe mode/App. Если застряли в bootloader — EDL (Vol Up + Vol Down + Power), прочитайте слот `dtbobak` через `edl-ng read-part` и убедитесь, что образ весит **25 165 824 байт** и имеет SHA-256 `307e7021…` (CN) / `f4d6073c…` (Phoenix_ovs), затем `write-part dtbo`. Репозиторий не содержит `.img` (в `.gitignore`) — берите `dtbo-stock-cn.img` / `dtbo-stock-ovs.img` из архива модуля или официальный firmware; **не используйте `dtbo-stock-cn-5.13.7.img`** (8 МиБ, `ffd65209…`, неполный обрезанный дамп — с ним устройство не загрузится). Подробно: [RECOVERY.md](RECOVERY.md).
- **Установщик abort — unknown DTBO baseline:** сначала восстановите официальный stock DTBO.
- **Установщик abort — unsupported global:** эта база не входит в релиз; не форсируйте CN/OVS-образ.

### Правила безопасности

- Образы разделов — только из **`edl-ng read-part`** или **официального firmware-пакета**; никогда не используйте `adb shell dd > hostfile`.
- Перед записью `dtbo` проверьте размер **25 165 824 байт (24 MiB)**; после записи перечитайте раздел и сверьте SHA-256.
- Перед откатом прочитайте слот `dtbobak` этого устройства как эталон.
- Не используйте `fastboot flash` для critical-разделов (нет unlocktoken).
- Сохраняйте `/sdcard/Download/pico4-dtbo-stock-backup.img`.

### Документация / история / лицензия

- [QUICKSTART.md](QUICKSTART.md) — установка/обновление/удаление
- [QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md) — мой полный анализ качества/таймингов
- [RECOVERY.md](RECOVERY.md) — восстановление и EDL
- [HANDOVER-120HZ.md](HANDOVER-120HZ.md) — передача проекта и чек-лист
- v1.2.1: `service.sh` каждые 30 с возвращает `sdk_eyebuffer` / `sdk_eyebufferX/Y` / `os_eyebuffer_*` к 2160 и уступает V-Sleep; zip пересобран.
- v1.2.0: поддержка Phoenix_ovs (b9666), авто-выбор CN/OVS.
- v1.1.0: буфер глаза 2160, `xrMiniVsyncBackStep=4`, калибровка 120 Гц, обновление/удаление.
- v1.0.0: первый релиз с фиксированными 120 Гц.

MIT License — см. [LICENSE](LICENSE). Только для личных исследований; сделайте бэкап и убедитесь в возможности восстановления через EDL.
