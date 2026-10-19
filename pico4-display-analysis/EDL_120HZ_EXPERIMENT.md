# 2026-10-19：EDL 直写 DTBO 实现 120 Hz，以及面板超频的画质代价

本轮我把 120 Hz 从"刷机包 + Magisk 模块"改成了**直接用 EDL 写 DTBO 分区**，在真机上跑通了 120 Hz，完整验证了链路时钟，也拿到了宝贵的画质代价一手数据。收尾时我把 dtbo 回滚到原厂（`307e7021…`），设备状态已复原（实测运行在 PICO 出厂默认档 **72 Hz**，`defaultModeId=2`，90 Hz 档需在系统设置里选）。以下是全过程与结论。

> 说明：本文以项目作者的第一人称记录，所有命令、哈希、结论均来自我自己的实机操作与离线取证。

---

## 1. 出发点：fastboot 写不了分区，改走 EDL

项目早期一直用 Magisk 一键包走 fastboot 刷 dtbo。本轮想直接落 DTBO 时撞上硬墙：

```
fastboot flash dtbo dtbo-120-scale.img
# CmdFlash is not allowed without unlocktoken authority
```

**关键认知**：PICO 4 的 bootloader 即使报告 `unlocked: yes`，也**不等于**取得了写分区所需的 unlocktoken 授权——这台机器实测 `oem` 命令全被拒、`get_unlock_ability` 显示 critical partition 未授权、`fastboot flash` 直接被拒。所以本轮全部走 EDL 直写。

> 更正：本轮早期我曾把原因记为"fastboot 必须先刷工程 abl"。实测更准确的表述是
> **本机当前 abl 是原厂 `af6992ba…`，工程 abl 早已被恢复**；写分区被拒是
> unlocktoken 授权缺失，与 abl 版本无关。详见 `RECOVERY.md` §2。

EDL 直写路径（每次都读回校验，全程不动 abl、不清数据）：

```bash
# loader 取自 more-picohaxx-tool
LOADER=tools/firehoses/prog_firehose_ddr.elf
edl-ng.exe -l "$LOADER" write-part dtbo dtbo-120-scale.img
edl-ng.exe -l "$LOADER" read-part  dtbo dtbo-edl-readback.img   # 读回逐字节比对
edl-ng.exe -l "$LOADER" reset                                     # 重启
```

> 主机侧 `adb shell dd ... > 文件` 把 24 MiB 二进制流传出来会多截/污染字节，**分区 sha 必须以设备内 `sha256sum` 或 EDL `read-part` 为准**，否则会看到"假不一致"。

---

## 2. 120 Hz 链路时钟实跑验证

EDL 写入 `dtbo-120-scale.img` 并读回校验一致（SHA-256 `27d968df…`）后，重启进系统实测：

| 判据 | 结果 |
| --- | --- |
| SurfaceFlinger VSYNC | `period = 8333333 ns` → **120 Hz** |
| `dumpsys display` | `mActiveModeId=1, fps=120.00001` |
| 亮屏链路时钟 | `pclk0 = 220,809,000 Hz`、`byte0 = 165,606,750 Hz` |
| 推导 bitclk | `165,606,750 × 8 / 10 ≈ 1325 MHz`，与 827×2225×120 的理论值精确吻合 |
| 内核日志 | `hactive=4320,vactive=2160,fps=120`，无 CRC/ECC/underflow/overflow |

结论：**120 Hz 是真的在跑，主机侧时钟与帧率全部对上**，不是假刷新。

---

## 3. 画质代价：120 Hz 下偏色 + 发雾 + 细线花屏

120 Hz 跑起来之后，我观察到三个画质问题：

- 2D 应用边缘出现**蓝/紫色描边**（某色通道数据错位的典型症状）
- 整体**发灰发雾**，像屏幕素质被拉低
- 手柄**瞄准射线**等细线**花屏/断裂**（高频内容对信号误码最敏感）

我先排查了 GPU 动态分辨率（GPU busy 0%、频率 305/587 MHz 有余量）和 dmesg（无任何 DSI/MIPI 报错）——**都不是**。真正的根因是**面板本身**：

### 3.1 这块面板原生没有 120 Hz

我把 DTBO 逐 entry 解析后发现：`ls026b3sa`（SHARP5K，4320×2160）**只有一个 `timing@0`（90 Hz）节点，根本没有 120 Hz 的 timing，也没有独立 `qcom,mdss-dsi-panel-clockrate`**。所谓 120 Hz 是把 90 Hz 的主机时序硬改成 120 Hz 的**超频**。同一份 DTBO 里的 `sharp_493_120_new_video` 是**另一块 960×3664 面板**的验证过 120 Hz 节点，不能直接照搬到 LS026B3SA。

### 3.2 PHY 时序必须随 bitclk 放大，而线性盲放大是错的

DSI PHY 时序（`qcom,mdss-dsi-panel-phy-timings`，14 字节表）跟 bitclk 走。90 Hz 是 993 MHz，120 Hz 是 1325 MHz（+33%），HS 时序必须同步放大，否则链路裕量不足。我最初用"线性 ×1.334 放大每个非零字节"盲改，结果：

- 把第 9/10 字节从全 OEM 标准的 `02 04` 改成了 `03 06`（所有原厂 PHY 这两字节都是 `02 04`）
- 整体放过头（关键字节我给到 `0x2f`，原厂 120 Hz 实测才 `0x25`）

我随后从 DTBO 里挖出**厂商在真正跑通 120 Hz 的面板（`sharp_493_120`）上验证过的 1325 MHz PHY**，作为跨面板参考基准，替换掉盲放大的值，重建镜像再刷：

```
sharp_493_72  : 00 2e 0d 0c 15 12 0d 0d 09 02 04 00 25 11
sharp_493_90  : 00 1d 08 08 0d 0c 08 08 05 02 04 00 18 0d
sharp_493_120 : 00 25 0a 0a 1b 25 0a 0a 0a 02 04 00 1f 0f   ← 验证过的 1325 MHz
ls026_90      : 00 22 08 08 19 23 09 08 09 02 04 00 1c 0d   ← 本机原厂
```

替换后 EDL 读回逐字节一致、120 Hz 仍在、dmesg 依旧零报错。**但主观画质（蓝紫边/发雾/细线花屏）没有任何改善。**

### 3.3 定性结论

> **LS026B3SA 是 90 Hz 面板，DTBO 里没有它的 120 Hz 初始化/on-command 指令集。120 Hz 是纯超频，面板内部的均衡/gamma/overdrive 仍按 90 Hz 标定，在 1325 MHz 上偏色发雾是硬件层面的超频代价，靠改 DTBO 时序/PHY 解决不了。**

换用验证 PHY 无效这一点，把根因从"时序写错"钉死到了"面板无 120 Hz 支持"。这是本轮最有价值的结论。

---

## 4. 回滚：钉死"90 Hz 才是干净基线"

为了 100% 确认"120 Hz 画质有损 = 超频硬代价"而非"我们改错了"，我把 dtbo 通过 EDL 写回所谓"原厂状态"（当时取自 `adb shell dd` 拉取的副本，sha `970da2f5…`）。

同时用 EDL 对启动链做了一轮**纯只读取证**，结论是设备系统层面完全健康、不存在砖化：

| 分区 | 取证结论 |
| --- | --- |
| `boot`（96 MiB） | 标准 boot header v2 / 小端 / page 4096；kernel 35.19 MB + ramdisk 1.70 MB(gzip)；ramdisk 解压 3.03 MB 含 `init`/`first_stage`/`magisk`/`.backup` → **被 Magisk 正常 patch，无损坏**；kernel 段含 Magisk `shim` |
| `vbmeta` / `vbmeta_system` | `AVB0` magic + `avbtool 1.1.0` 签名 + 属性表完整（security_patch 2021-04-05），**AVB 校验链完好** |
| `devinfo` | `ANDROID-BOOT!` + `01 01 01` 解锁标志 + 完整 unlock token |
| `abl`（1 MiB） | 原厂 `af6992ba…`，与 `more-picohaxx-tool/backup/abl/abl.elf` 逐字节一致 → **工程 abl 早已被恢复** |
| A/B 槽位 | **该机不存在** A/B（`slot-count` 等全 `Not found`），排除槽位标记问题 |

### 4.1 这次回滚其实是坏的，并且因此让设备无法开机

上面那份"回滚基线"是从 `adb shell dd > hostfile` 拉的。**adb 流式传输会污染二进制**，那份副本比分区大 7778 字节；我截断到 24 MiB 就写回去了，等于往 `dtbo` 里塞了一份**字节错位**的镜像：

| | 真原厂（`dtbobak` 硬件槽） | 我写进去的"回滚基线" |
| --- | --- | --- |
| SHA-256 | `307e7021…` | `970da2f5…` |
| 第 1 个 FDT 偏移 | `0x44495` | `0x44649` ❌ |
| 差异 | — | **13.58%（3,418,346 字节）** |

设备树解析失败 → bootloader 报 `Failed to load image from partition: Load Error` → 设备彻底卡在 bootloader，**在菜单里选 Start 也会弹回**（那是引导失败，不是解锁警告屏）。工程 abl 与 Magisk 模块都曾是清白嫌疑。

修复：EDL 读出**硬件备份槽 `dtbobak`**（工程 abl 建的原厂槽，从未被写过）作为真值参照，确认真原厂 = `307e7021…`（与本地 `dtbo-stock-cn-24mb.img` 一致），写回后 30 秒正常开机。

> **由此确立的铁律**：① 二进制分区镜像只能来自 `edl-ng read-part` 或官方 firmware 包，**绝不能用 `adb dd`**；② 回滚前必须先读同机 `*bak` 槽做 SHA-256 真值对照。详见 [`../RECOVERY.md`](../RECOVERY.md)。

最终设备状态：**`dtbo` = `dtbobak` = 原厂 `307e7021…`，`boot`/`vbmeta`/`abl` 全未动，Magisk 模块已禁用，系统正常开机**。

---

## 5. 本轮产出文件

| 文件 | 说明 |
| --- | --- |
| `build_120_universal.py` | 通用 DTBO 构建器：patch 全部面板 entry（CN/INTL 通吃），`--phy keep\|nop\|scale` 三变体，自带 `verify()` 断言 |
| `gen_validated_phy.py` | 生成"厂商验证 PHY 版"120 Hz 镜像（`dtbo-120-validated.img`） |
| `dtbo-120-scale.img` | 线性放大 PHY 版 120 Hz（`27d968df…`） |
| `dtbo-120-validated.img` | 厂商验证 PHY 版 120 Hz（`6077b6e1…`） |
| `dtbo-stock-cn-24mb.img` | **真·原厂 CN dtbo（`307e7021…`）——唯一正确的回滚源** |
| `dtbo-stock-90hz-24m.img` | ⚠️ **已损坏**（`970da2f5…`，源自 `adb dd` 污染副本），**不可用于回滚** |
| `fdt_phy_parse.py` | 离线解析任意 DTBO，导出各面板 fragment 的完整 PHY 与关键词节点 |
| `forensics/` | EDL 只读取证：`boot`/`bootbak`/`abl`/`ablbak`/`dtbo`/`dtbobak` 原始分区镜像 |
| `../RECOVERY.md` | 分层恢复手册 + 本次事故的教训与本机分区大小实测表 |

---

## 6. 结论与后续

1. **EDL 直写 DTBO 是 PICO 4 落 120 Hz 的可行路径**，绕开 unlocktoken，全程可读回校验。
2. **120 Hz 链路时钟真实可达 1325 MHz**，主机侧无报错；但
3. **LS026B3SA 面板无原生 120 Hz 支持，画质代价（偏色/发雾/细线花屏）是超频的硬件代价，DTBO 层面无法消除**。若要"既要 120 Hz 又要干净画质"，需要的是面板级 120 Hz 初始化/on-command（目前无厂商参考），而不是继续盲改时序。
4. **默认保持原厂 dtbo**（模块禁用，实测运行在出厂默认 72 Hz）。后续若再尝试 120 Hz，建议方向：拿到 LS026B3SA 真实 120 Hz TCON 初始化序列，或从驱动层（dsi120 内核模块）强制切时钟并配合面板重初始化。
5. **但更重要的教训是操作纪律**：本轮真正让设备停摆的不是 120 Hz，而是用不可信的镜像做回滚。任何分区写入前，先证明镜像是对的（`*bak` 槽对照 / 官方 firmware / `edl-ng read-part` 拉取），再动手。

---

## 附：PICO 4 分区写入速查

```bat
set TOOLS=D:\more-picohaxx-tool-1.3.10\tools
set FH=%TOOLS%\firehoses\prog_firehose_ddr.elf

:: 拉干净副本（唯一可信的拉取方式）
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo stock.img

:: 写入 + 读回校验 + 重启
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo stock.img
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo verify.img
%TOOLS%\edl-ng.exe -l %FH% reset
```

*记录于 2026-10-19。所有哈希与日志均为实机取证，可复现。*