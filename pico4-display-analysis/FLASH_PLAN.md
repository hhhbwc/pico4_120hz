# 120 Hz DTBO 刷入计划（EDL 路径）

> ⚠️ **2026-10-19 修订**：本文件原先写的 fastboot 流程**实测走不通**
> （`fastboot flash` 被 unlocktoken 拒绝），且把 `adb dd` 污染的
> `dtbo-device-pulled.img` 当成回滚资产。现已全部更正为 EDL 直写路径。
>
> **最终结果**：120 Hz 确实跑通了（VSYNC 8.33 ms、bitclk≈1325 MHz、内核零报错），
> 但主观画质代价（蓝紫描边/发雾/细线花屏）**无法通过 DTBO 调优消除**——
> LS026B3SA 面板没有原生 120 Hz 时序，120 Hz 是纯超频。
> 设备已于同日回滚到原厂 dtbo。完整实验记录见 `EDL_120HZ_EXPERIMENT.md`。

---

## 1. 前提与工具

| 项 | 值 |
|---|---|
| loader | `D:\more-picohaxx-tool-1.3.10\tools\firehoses\prog_firehose_ddr.elf` |
| 工具 | `D:\more-picohaxx-tool-1.3.10\tools\edl-ng.exe` |
| 进 EDL | 手动 **Vol Up + Vol Down + Power**（黑屏） |
| 分区大小 | `dtbo` = **25,165,824 字节（24 MiB 整）**，必须精确匹配 |

**为什么必须用 EDL**：本机 bootloader 虽显示 `unlocked: yes`，但未取得 critical
partition 的 unlocktoken 授权，实测以下命令全部被拒：

```
fastboot flash dtbo <img>     -> CmdFlash is not allowed without unlocktoken authority
fastboot oem <cmd>            -> oem command is not allowed without unlocktoken authority
fastboot flashing get_unlock_ability -> Critical partition: 1, Normal partition: (空)
```

## 2. 候选镜像

| 文件 | SHA-256 | 说明 |
|---|---|---|
| `dtbo-120-validated.img` | `6077b6e1…` | **实刷版本**：120 Hz + 厂商验证 PHY |
| `dtbo-120-scale.img` | `27d968df…` | 120 Hz + 线性放大 PHY（有缺陷，不建议） |
| `dtbo-120-keep.img` | `a57573ae…` | 120 Hz + 保留 993 MHz 旧 PHY |
| `dtbo-120-nop.img` | `9c79d713…` | 120 Hz + PHY 属性删除（内核重算） |
| `dtbo-stock-cn-24mb.img` | `307e7021…` | **真原厂，回滚用**（= `dtbobak` 硬件槽内容） |

> ⚠️ **不可使用**：`dtbo-device-pulled.img`（`df09ffa4…`）、
> `dtbo-stock-90hz-24m.img`（`970da2f5…`）——均为 `adb dd` 污染副本，
> 写进去会导致设备**无法开机**。

## 3. 写入前检查（逐项确认）

- [ ] 镜像字节数 `stat -c%s <img>` **== 25,165,824**
- [ ] 头部 magic = `0xD7B7AB1E`，且能数出 16 个 FDT 块（`d00dfeed`）
- [ ] 记录镜像 sha256
- [ ] **回滚真值已就位**：`dtbo-stock-cn-24mb.img`（`307e7021…`）
- [ ] 已手动进入 EDL（9008），`edl-ng printgpt` 能读出分区表

## 4. 执行步骤

```bat
set TOOLS=D:\more-picohaxx-tool-1.3.10\tools
set FH=%TOOLS%\firehoses\prog_firehose_ddr.elf
set IMG=D:\pico\pico4_120hz\pico4-display-analysis\dtbo-120-validated.img

:: 1) 确认 EDL 连通
%TOOLS%\edl-ng.exe -l %FH% printgpt

:: 2) 写入
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo %IMG%

:: 3) 读回校验（sha 必须与镜像完全一致）
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo verify.img
certutil -hashfile verify.img SHA256

:: 4) 重启
%TOOLS%\edl-ng.exe -l %FH% reset
```

5. 开机后启用模块（若要 120 Hz）：删除 `/data/adb/modules/pico4_120hz/disable`
6. 验证：
   - `dumpsys SurfaceFlinger | grep VSYNC` → 8.33 ms（120 Hz）
   - `dumpsys display | grep fps=` → `120.00001`
   - 设备内 `dd if=/dev/block/by-name/dtbo | sha256sum` → 与镜像一致
   - 目测画质（**已知代价**：蓝紫描边 / 发雾 / 细线花屏）

## 5. 失败回退

> 回退一律走 EDL + 真原厂镜像。**不要用 `fastboot flash`（被拒），
> 不要用 `dtbo-device-pulled.img`（污染副本，会变砖）。**

```bat
set TOOLS=D:\more-picohaxx-tool-1.3.10\tools
set FH=%TOOLS%\firehoses\prog_firehose_ddr.elf
set STOCK=D:\pico\pico4_120hz\pico4-display-analysis\dtbo-stock-cn-24mb.img

%TOOLS%\edl-ng.exe -l %FH% write-part dtbo %STOCK%
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo verify.img    :: 期望 307e7021...
%TOOLS%\edl-ng.exe -l %FH% reset
```

并禁用模块：`touch /data/adb/modules/pico4_120hz/disable`（当前已是此状态）。

**若设备连 EDL 都进不去 / 更深层问题** → 见 `../RECOVERY.md` 的分层恢复流程。

## 6. 注意事项

- 只写 `dtbo` 单分区，不动 `boot` / `vbmeta` / `abl`，影响范围最小。
- 写入前务必 `printgpt` 核对 `dtbo` 分区大小，防写溢出损坏相邻分区。
- 若引导失败（停在 bootloader、`fastboot continue` 报
  `Failed to load image from partition: Load Error`），
  **不要用 `fastboot reboot` 反复拉起**（会死循环），直接回 EDL 读 `dtbobak` 取真值。