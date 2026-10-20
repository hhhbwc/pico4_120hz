# PICO 4 120Hz 项目交接文档

**用途**：本文件是 `pico4_120hz` 项目的权威交接入口。内容只覆盖 PICO 4 物理 120Hz 解锁、验证、回滚和发布状态。

**最后整理**：2026-10-20

> **2026-10-20 v1.1.0 发布更新**：v1.1.0 是当前发布版本，替代未单独发布的 v1.0.1。
> 真机回归已完成：stock → v1.0.0 → v1.1.0 升级、stock 全新安装、uninstall → stock 恢复；
> 当前设备已恢复官方 72Hz。本发布为 **CN / Phoenix 专用**，INTL/OVS 不在包内。
> 安装、升级、卸载和回滚见 [README.md](README.md) 与 [QUICKSTART.md](QUICKSTART.md)。

## 1. 当前结论

当前已经确认可工作的方案是**锁定物理 120Hz**，不是稳定的 72/90/120Hz 实时三档切换。

- v1.0.0：已发布，并完成过 Magisk 真机端到端验证。
- v1.0.1：未单独发布；固件门、Phoenix_ovs、一次性 resync 等修复已并入 v1.1.0。
- v1.1.0：当前发布版本。眼缓冲 2816→2160、`xrMiniVsyncBackStep=4`、120Hz SDK 校准、
  CN 升级/卸载支持和 stock 回滚镜像已通过真机回归。
- 发布前最后一步：提交/推送并打 tag（见 §11）。
- PICO OS 5.13.8 及后续 OTA 存在 root 和恢复能力风险，**不要点系统更新**。

> 任何文档或历史脚本若与本文件冲突，以本文件的“当前结论”和“安全红线”为准；历史分析只用于理解问题，不代表可以直接执行。

## 2. 项目边界

本目录是独立 Git 仓库，路径以 `git rev-parse --show-toplevel` 为准（作者原工作机为 `D:\pico\pico4_120hz\`）。

它只负责显示刷新率研究和 120Hz 模块。以下内容不属于 120Hz 发布物：

- `D:\pico\vd-mod\`：Virtual Desktop 头显端汉化和字体实验。
- `D:\pico\vd-localizer\`：Stride/Xenko 通用本地化工具链。
- `D:\pico\gallery-patch\`：PICO Ultra 系统应用移植/PMS 实验。
- `D:\pico\vd-backup\`：VD 认证和应用数据备份。
- `D:\pico\pre-reset-backup\`：设备恢复出厂、Magisk、APK 和原厂镜像备份。

VD 的 PMS 修复、转区、dock 恢复和汉化都只是设备环境背景，不能写入 120Hz 的功能列表，也不能作为 120Hz 发布条件的替代品。

## 3. Git 与发布状态

2026-10-20 更新（基于远端最新状态审查；修复在工作树，未提交）：

```text
基线：origin/main = 2136057
工作分支：fix/repo-review-20261020
状态：工作树含审查修复，尚未提交/推送
```

本地 `main` 另有 2 个仅本地提交（`5ab2040` GPU 源码包、`731f776` GPU 监控脚本），
未合入本分支，也不属于 120Hz 发布物。

`ca45115` 的固件门判据错误（用 `ro.build.version.incremental` 匹配 `5.13.7*`，
而该属性在所有 5.13.7 设备上都是 `smartcm.<时间戳>`，导致 100% abort），
已由 `1cdb06f` 改为检查 `ro.build.id` 并保留 incremental 兜底。
`1cdb06f` 同时合并了 a55uka 的 Phoenix_ovs（global）支持。

### 版本矩阵

| 版本 | 状态 | 说明 |
|---|---|---|
| v1.0.0 | 已发布、已验证 | 锁定 120Hz 的稳定基线；对应提交 `eedfc30` |
| v1.0.1 | 未发布、未真机回归 | 源码含 `ca45115` + `1cdb06f` + `3ddbdbd`；固件门修正、CN/INTL 通用 dtbo、Phoenix_ovs 支持、一次性 resync、CRLF 归一化 |

当前 checkout 没有已打包的 v1.0.1 ZIP：

```text
pico4-display-analysis/pico4-120hz-v1.0.1.zip   # 不存在，需用 build_zip.py 重新生成
```

旧记录中的 `ce38dc23…` 对应 v6 单条目镜像的旧打包，已随 `3ddbdbd` 改为 CN/INTL 通用镜像而作废。
该包不能在未完成真机回归前上传 GitHub。发布前必须先形成干净、可追溯的提交，并重新计算产物 SHA-256。

## 4. 生产方案原理

稳定方案由三部分组成：

1. v6 DTBO 以 120Hz 为基准时序，并把厂商 post-120 NT57900 面板初始化序列烘焙进主 `on-command`。
2. 补丁后的 `libpxrhmdservice.so` 将 72、90、120 请求统一映射到 120 所在的配置 `cfg0`。
3. Magisk `service.sh` 写入 120Hz 相关属性和配置，必要时做一次开机面板重同步。

配置顺序实际为 `[120, 90, 72]`，因此 `cfg0` 是 120Hz。该设计规避了从 120Hz 实时切换到更大 VFP 的黑屏问题，但代价是不能提供可靠的真实三档切换。

### 已确认的物理证据

- VSYNC 周期：`8333333 ns`。
- `BYTE_CLK = 165,606,750`。
- `PIXEL_CLK = 220,809,000`。
- 上述时钟与 `827 × 2225 × 120` 精确对应。
- 关键测试中未发现 underrun、PLL 或 `new_hfp` 错误。
- 游戏场景曾达到 100+ fps。

SurfaceFlinger 的模式列表、PICO 属性或官方帧率显示都不能单独证明物理刷新率；验证必须优先看 DSI 实际时序和 pixel clock。

## 5. 关键基线哈希

| 组件 | SHA-256 |
|---|---|
| 原厂 DTBO（CN / Phoenix） | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| 原厂 DTBO（global 通用基线） | `bee2b0676e04d93135c660f1c80157afd06e52678432ea2db9f9c90b47007d9e` |
| 120Hz 通用 DTBO（CN 构建） | `a57573ae89a26bc37db10d8b258a25f2cf343b042246519144ff3213508ff385` |
| 120Hz 通用 DTBO（global 构建） | `0ab8b85ed85203bd0096f4a89f12d18a0746d7bd461a7d7c0e355ace727936e9` |
| 原厂 DTBO（Phoenix_ovs） | `f4d6073c669d81aa0a811ea4476f7a89d01bf8975a931d2b2548f237a2cda992` |
| 120Hz DTBO（Phoenix_ovs，entry 6 in-place） | `d138d5d68e64be3209b8d5024c7f10fd120dc3d2d83fd703a31fe09b3a6b5123` |
| 原厂 `libpxrhmdservice.so` | `c290a9f51214ff37b415c309c5facf80542024d40c22e5ae3cdeff9825a31fef` |
| 补丁 `libpxrhmdservice.so`（v1.0.0） | `32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea` |
| 补丁 `libpxrhmdservice.so`（v1.1.0，含 config-rate 120） | `8b4431d4c8f7ebec4bdead981800780347f376e10da10bdb90d6f2977187c829` |
| v1.1.0 runtime `pxr_config.txt`（backstep 4） | `95937d0b24c83335d5d79bf782f67f2be8e760c789a40cd116b9fafc40f59125` |
| v1.1.0 ZIP（CN） | `3a7590ddcf12f1c03fed10a077dad206e23826073298c2888a431ad48836c9be` |
| 已验证 v1.0.0 ZIP | `af0ce5db6496a416d8fb74b7c2d4c685f3364a185ee86252163f6ba669804b6a` |
| v6 init120 DTBO（= v1.0.0 / v1.1.0 内置 120 镜像） | `f0c10d1dd04dd9a7c46b319758dbdd5f7540fe06aaf807377d23392c71aa20ea` |
| 旧本地 v1.0.1 ZIP（历史，文件已不存在） | `ce38dc233fa1ccb9a10d545a37ad475dcc7005a9f4eac0ae38c9d357c870e401` |

任何发布前重打包都要重新记录哈希，并确认产物对应干净提交。
v1.1.0 为 **CN-only** 发布；INTL/Phoenix_ovs 构建不包含在本发布内。需要时从历史提交恢复
`build_zip_ovs.py`，并补齐对应机型的 stock DTBO 转储后再生成 entry-6 镜像。

## 6. 设备与固件范围

已验证目标基线：

```text
型号：PICO 4 / PICOA8110 / Phoenix
系统：PICO OS 5.13.7 / Android 10
面板：Sharp LS026B3SA
面板标识：SHARP5K
SoC：Snapdragon 865
```

v1.0.1 的固件门允许 `5.13.7*` 的多个增量，但这不等于支持所有变体。DTBO、面板和原版 vendor library 仍必须命中严格的白名单哈希；哈希不匹配应安全中止。

## 7. 安全红线

- 永不刷系统分区。
- 永不点系统更新，尤其不要升级到 5.13.8 或更高版本。
- 不修改 `boot`、`vbmeta`、`dtbobak`、`GPT`、`super` 或其他无关分区。
- 设备侧只使用已核对的 APK 安装/卸载和 systemless 模块；所有动作必须可逆。
- 刷写 DTBO 前必须保留原厂 DTBO、`dtbobak` 和可用的 EDL/恢复路径。
- 任何出现黑屏、花屏、持续重启、DSI/PLL/underrun 错误或异常温升时，立即回滚原厂 DTBO。
- 不使用 `fastboot flash` 作为默认恢复路径；按现有设备条件使用已验证的 root/ADB/EDL 流程。
- 不把 VD 汉化 APK、PMS 修复或 Ultra 移植模块混入 120Hz ZIP。

## 8. 已知问题

### 8.1 实时降档黑屏

120→90/72 的实时切换会黑屏；90→120 的方向曾可工作。根因是面板的 immediate-porch DFPS 路径不能可靠处理增大 VFP 的切换。不要把实验性的真实多档选择器当成生产方案。

### 8.2 窗口叠加细线伪影

120Hz 下多层窗口叠加场景曾出现细线，单 Surface 桌面或游戏相对稳定。后续复现时应同时采集：

- `dmesg` underrun 计数。
- DDR/总线 devfreq 状态。
- GPU busy 和合成器丢帧统计。

在没有新证据前，应把它视为已知限制，而不是宣称已解决。

### 8.3 首次刷入后的画面分裂/花屏

早期版本可能在面板和主机时序尚未同步时出现黑屏、水平分界线或下半屏花屏；电源键熄屏再亮会重跑面板初始化。v1.0.1 已改为一次性自动处理：安装器只在真正写入 dtbo 时放置 `screen_fix_once`，`service.sh` 在随后那次开机消费；该版本尚未完成新的真机回归，因此不能把自动修复写成已验证事实。

## 9. 文件与脚本分类

### 生产/打包

```text
pico-refresh-selector/magisk-module/
pico-refresh-selector/magisk-module/build_zip.py
# 产物 pico4-display-analysis/pico4-120hz-v1.1.0.zip 不入库，按需构建
```

### 物理验证

```text
pico4-display-analysis/verify_refresh_rate.sh
```

验证重点是 DSI state、BYTE_CLK、PIXEL_CLK、VSYNC、内核错误和实际画面；不能只看 Android API 的模式名。

### 构建和分析

```text
pico4-display-analysis/build_*.py
pico4-display-analysis/patch_hmdservice_cfgmap.py
pico4-display-analysis/extract_panel_config.py
pico4-display-analysis/dsi120/
```

其中部分脚本依赖历史工具、外部输入或旧路径。现有 v6 二进制可以校验和重新包装，但当前 checkout 不保证能从 stock DTBO 完整重建全部 v6 产物。

### 历史/实验，禁止直接刷写

```text
pico4-display-analysis/FINAL_120HZ_ANALYSIS.md
pico4-display-analysis/FLASH_INSTRUCTIONS.md
pico4-display-analysis/LS026B3SA_120HZ_FULL_CONFIG.md
pico4-display-analysis/*candidate*
pico4-display-analysis/*probe*
```

这些文件包含被后续 v6 结果推翻的分析或诊断候选。执行前必须以本文件和脚本内的哈希校验为准。

## 10. 标准验证流程

1. 记录设备型号、PICO OS、面板标识、当前 DTBO 哈希和 vendor library 哈希。
2. 确认原厂 DTBO 备份和回滚路径可用。
3. 只使用哈希匹配的生产包，安装前保存日志。
4. 重启后检查 DTBO 是否实际生效、`service.sh` 是否成功运行。
5. 使用 `verify_refresh_rate.sh` 采集 DSI timing、BYTE_CLK、PIXEL_CLK、VSYNC 和 dmesg。
6. 检查桌面、窗口叠加、视频、游戏等场景，并记录黑屏、花屏、细线和温升。
7. 连续重启验证状态是否稳定；确认卸载模块后能恢复原厂行为。
8. 测试失败时立即恢复干净状态，再分析日志；不要在故障状态继续叠加 VD、PMS 或其他模块。

## 11. v1.0.1 发布前清单

- [x] 审核并提交 v1.0.1 改动，形成干净、可追溯提交（含固件门改用 `ro.build.id`）。
- [x] 统一 README、中文/英文/俄文和脚本中“一次性重同步”的描述。
- [ ] 重新生成 ZIP（CN/INTL 通用镜像布局）、校验权限和哈希，并记录构建输入（旧 `ce38dc23…` 已作废）。
- [x] 打包脚本对所有文本条目做 CRLF 归一化（原来只处理 `.sh` 与 `module.prop`）。
- [x] `service.sh` 对 `$MODDIR` 增加固定路径兜底；安装器只在写入 dtbo 时放置 `screen_fix_once`（dry-run 已验证）。
- [x] 从原厂状态完成 fresh install（2026-10-20，v1.1.0 zip）。
- [x] 在已安装 v1.0.0 状态下完成 v1.1.0 覆盖升级（旧 lib/DTBO 白名单通过）。
- [x] 卸载 v1.1.0 后恢复 stock DTBO/lib/配置/72Hz（2026-10-20）。
- [x] 连续重启多次，120Hz/眼缓冲/backstep 均稳定生效。
- [ ] 提交、推送并创建 v1.1.0 Release（当前步骤）。
- [ ] 采集 DSI、VSYNC、pixel clock、dmesg 和目视结果。
- [ ] 验证模块卸载、原厂 DTBO 回滚和恢复后再次启动。
- [ ] 重新生成 ZIP、校验权限和哈希，并记录构建输入。
- [ ] 由本人确认真实设备测试通过后，才允许 push、tag、创建 Release 或回复 issue。

## 11b. 画质退化：已定性（2026-10-19 实测结论，此前三层推测作废）

120 Hz 下报告的**画面边缘发虚 / 移动拖影 / 2D 边缘蓝紫描边 / 细线（瞄准射线）花屏**，
原以为是三层原因，逐层实测后已全部排除，结论如下：

| 原推测 | 实测结果 |
|---|---|
| ① 渲染分辨率被动态下调 | **排除**：`gpu_busy_percentage = 0%`、`cur_freq = 305 MHz`（上限 587 MHz），GPU 完全空闲，不存在降分辨率 |
| ② 面板模拟参数停在 90 Hz 标定 | **确认为根因**：解析全部 16 个 DTBO entry 后确认，LS026B3SA(SHARP5K) **只有 90 Hz 一个 timing 节点**，没有 120 Hz 的 on-command / TCON 序列 |
| ③ DSI 链路超频 33% | **实测无害**：PHY 由「线性放大 1.334×」换成厂商在 1325 MHz 上验证过的值（`00250a0a1b250a0a0a0204001f0f`）后，**主观画质零改善**；dmesg 全程无 CRC/ECC/underflow/overflow |

**结论**：120 Hz 是纯超频，面板内部均衡/gamma/overdrive 仍按 90 Hz 标定，
偏色/发雾/细线花屏是**硬件层面的超频代价，DTBO 层面改不掉**。
设备已于 2026-10-19 回滚到原厂 dtbo（`307e7021…`），Magisk 模块禁用。
**实测当前运行在 PICO 出厂默认档 72 Hz**（`supportedModes` = 90/72，
`defaultModeId=2`；dmesg `dsi_bridge_enable entered rate:72`）——
原厂并非默认 90 Hz，90 Hz 是系统设置里的可选档。

若将来要「既要 120 Hz 又要干净画质」，需要的是面板级 120 Hz 初始化序列
（LS026B3SA 真实 TCON 序列，目前无厂商参考），而不是继续改 DTBO 时序或 PHY。

详见 `pico4-display-analysis/EDL_120HZ_EXPERIMENT.md`。

## 12. 交接时的第一步

接手者先阅读本文件，再阅读：

```text
README.md
PROJECT_CHECK_2026-10-11.md
pico4-display-analysis/README.md
pico4-display-analysis/verify_refresh_rate.sh
```

然后检查 Git 状态和本地构建产物。不要直接执行历史 `FLASH_INSTRUCTIONS.md`，不要把 VD 汉化交接文档当作 120Hz 的技术依据，也不要在没有真机证据的情况下发布 GitHub。
