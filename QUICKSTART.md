# PICO 4 120Hz 快速上手

> 适用于 **PICO 4 CN（PICOA8110 / Phoenix）** 与 **Phoenix_ovs（国际版 b9666）**、固件 **5.13.7**、面板 **SHARP5K**、已装 **Magisk**。
> 其他国际基线（bee2b067）不在本发布内。刷机有风险，先读完“回滚”再动手。

---

## 1. 先确认三件事

在头显里或通过 adb 确认：

```bash
adb shell getprop ro.product.device     # PICOA8110
adb shell getprop ro.build.id           # 5.13.7...
adb shell getprop ro.pvr.hmd.type       # SHARP5K
```

三条都匹配再继续。另外确认：

- Magisk 已安装且模块功能正常；
- 电量 > 50%；
- 已保存重要数据；
- 能进入 **EDL(9008)**（Vol Up + Vol Down + Power），或会用 `fastboot reboot edl`。

---

## 2. 安装

1. 从 Releases 下载 **`pico4-120hz-v1.1.0.zip`**。
2. 打开 Magisk App → **模块** → **从本地安装**。
3. 选择 zip，等待安装完成。
4. 重启头显。

安装器会自动：

- 校验固件/面板/lib/DTBO；
- 识别 **CN / Phoenix_ovs**，选择对应的 120 镜像和 stock 回滚镜像；
- 备份原厂 DTBO 到 `/sdcard/Download/pico4-dtbo-stock-backup.img`；
- 写入 120Hz DTBO 并读回校验；
- 安装 120Hz 校准、眼缓冲 2160、底部锁存修复和卸载脚本。

---

## 3. 第一次开机

- 首次开机会安排一次面板时序重同步，屏幕可能**闪一下/黑一下**，随后恢复，这是正常的。
- 如果一直黑屏：先电源键熄屏再亮；仍不行按“回滚”处理。

---

## 4. 验证 120Hz

```bash
adb shell dumpsys SurfaceFlinger | grep -m1 refresh-rate
# refresh-rate : 120.000005 fps

adb shell dumpsys pxrhmdservice | head -8
# refreshRate=120.000000

adb shell getprop sys.pvr.display.type
# 120.000000
```

系统设置里也应显示 120Hz。

---

## 5. 从 v1.0.0 升级

**不需要先卸载。** 直接把 v1.2.0 zip 在 Magisk 里覆盖安装，然后重启：

- 安装器识别 v1.0.0/v1.1.0 的旧 lib/DTBO，不会重刷分区；
- 新的 120Hz 校准、眼缓冲 2160、`xrMiniVsyncBackStep=4` 会生效；
- 原厂 DTBO 备份保留，之后仍可卸载回官方。

---

## 6. 卸载 / 回官方

1. Magisk App → **模块** → 移除 `Pico4 120Hz Display Unlock`。
2. 重启。
3. 卸载脚本会按安装时选择的变体恢复原厂 DTBO（CN / Phoenix_ovs）、配置和 props，并清理 canary 配置。
4. 重启后应回到官方 72Hz（设置里仍可选 90Hz）。

如果卸载后仍停在 120Hz，检查模块是否真的移除、是否重启过；必要时用 EDL 刷回 stock。

---

## 7. 出问题了怎么办

### 黑屏 / 花屏 / 卡 bootloader

1. 先强制重启或电源键熄屏再亮。
2. 能进系统：用 Magisk 安全模式/App 移除模块。
3. 卡 bootloader：
   - 不要用 `fastboot flash`（没有 critical partition 的 unlocktoken 权限）；
   - 进 EDL（Vol Up + Vol Down + Power）；
   - 用 `edl-ng read-part dtbobak` 读出本机原厂槽，确认镜像 `307e7021…`、大小 24 MiB；
   - `edl-ng write-part dtbo dtbo-stock-5.13.7.img`，读回校验，`reset`。
   - 详见 [RECOVERY.md](RECOVERY.md)。

### 安装器 abort

- **Unknown dtbo baseline**：当前 DTBO 不在已知列表。先用 EDL/官方固件恢复 stock，再安装。
- **CN-only / INTL**：本发布只支持 CN，不要强刷。
- **lib mismatch**：系统库不是 5.13.7 原版或旧版补丁库，先恢复官方固件。

### 仍是 72Hz

- 确认模块启用并重启过；
- 确认固件/面板匹配；
- 确认没有其他模块同时改 `dtbo`/`libpxrhmdservice.so`；
- 看 Magisk 安装日志和 `logcat | grep pico4_120hz`。

---

## 8. 已知限制

- 2D 应用边缘的**蓝紫描边**仍在：面板 120Hz 模拟标定极限，截图看不出来，DTBO/CA 都改不掉。
- **轻微整体发白**：120Hz 下 90Hz gamma/VCOM 的基线代价，比早期错误 E5/D5 的白滤镜轻很多。
- 不保证所有应用跑满 120fps；重负载场景由 GPU 决定。
- 锁定 120Hz，不做实时刷新率切换。
- 其他国际基线（bee2b067）不支持；CN 与 Phoenix_ovs（b9666）已打包。
- Phoenix_ovs 镜像已完成离线校验（entry 6 + 面板子树），但尚未在物理 OVS 机上做刷机回归；首次 OVS 安装请保留 stock 备份。

如果蓝边/发雾无法接受，建议回官方 90Hz。

---

## 9. 安全红线

- 分区镜像只能来自 `edl-ng read-part` 或官方固件，**绝不要** `adb shell dd > hostfile`。
- 写 `dtbo` 前核对 24 MiB 大小和 SHA-256；写完读回校验。
- 回滚前先读 `dtbobak` 槽做真值对照。
- 保留 `/sdcard/Download/pico4-dtbo-stock-backup.img`。

更多原理与实验：[README.md](README.md) · [QUALITY_120HZ_ANALYSIS.md](pico4-display-analysis/QUALITY_120HZ_ANALYSIS.md) · [RECOVERY.md](RECOVERY.md)。
