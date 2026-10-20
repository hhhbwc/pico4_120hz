# 120 Hz 画质退化分析（边缘发虚 / 移动拖影）

**记录日期**：2026-10-19（2026-10-20 修正）
**症状**：刷入 v6 DTBO 锁定 120 Hz 后，画面边缘出现虚化，头部/画面移动时有拖影，主观"屏幕素质下降"。
**状态**：**未定位到单一根因**。PHY 路线已被真机 A/B 证伪；kprobe 确认驱动会自动下发 `post-120-nt57900` 属性，但 2026-10-20 真机 A/B 证明 v6 的 on-command 早发副本**不能删**（删除后整屏发白）——它写到了错误的页（F1:08），却承担了必需的初始化作用。当前在保留注入的前提下修正页选/结构。
**警告**：本文是分析，不是修复方案。文中所有"待验证"项未经过真机 A/B，不得写进 README 的已确认结论。

---

## 0. 先排除的因素

| 因素 | 结论 | 依据 |
|---|---|---|
| DSC 压缩比 | **不是元凶** | 压缩比固定在 24bpp → 8bpp（3:1），`COMPRESSED_HTOTAL = 720 + 54 + 33 + 20 = 827`，`H_ACTIVE_COMPRESSED = 2160/3 = 720`。DSC 参数与刷新率无关，`FINAL_120HZ_ANALYSIS.md` §2 已确认"不用动"。 |
| 面板物理分辨率 | 未变 | `mdss-dsi-panel-width/height` 仍为 2160×2160。 |
| 几何时序（porch） | 未变 | v6 保持 htotal=827、vtotal=2225、vfp=57 与 90 Hz 完全一致，只改了 `panel-framerate`。 |

**所以**：90 Hz → 120 Hz 真正变化的物理量只有两个 —— **时钟变快 33%**、**帧周期变短 25%**。下面三层原因都由这两个量派生。

---

## 1. 层一：渲染分辨率被动态下调（GPU 侧）

**成本最低，必须先排除。**

120 Hz 把每帧预算从 11.11 ms 压到 8.33 ms，GPU 合成负载上升 33%。若 PICO 的动态分辨率 / 固定注视点渲染在 120 Hz 下压低 eye buffer，画面会整体变虚 —— 而 VR 透镜边缘本来就是采样率最低的区域，**边缘最先被肉眼察觉**。

这与"边缘发虚"的描述高度吻合，且不需要任何面板物理异常就能解释。

### 判据

在 90 Hz 与 120 Hz 两档下分别采集并对比：

```bash
adb shell dumpsys SurfaceFlinger | grep -iE "refresh|display [0-9]|active"
adb shell getprop persist.sys.pvr.display.type
adb shell getprop sys.pvr.display.type
# PICO 侧渲染分辨率相关属性（按需补充）
adb shell dumpsys media.metrics | grep -i res
```

**若 120 Hz 下的渲染分辨率明显低于 90 Hz，本层即为首要原因**，应先解决 GPU 侧（降分辨率档位 / 关闭动态分辨率），再谈面板。

---

## 2. 层二：面板模拟参数仍停在 90 Hz 标定（TCON / NT57900 侧）

这是本项目方案的结构性缺陷。

### 2.1 厂商 DT 里确实有 120 Hz 配置

`sharp_ls026b3sa_90_video` 节点自带三个按刷新率分发的命令槽：

| 属性 | 长度 | 包数 |
|---|---|---|
| `qcom,mdss-dsi-post-72-nt57900-on-command` | 90 B | 6 |
| `qcom,mdss-dsi-post-90-nt57900-on-command` | 90 B | 6 |
| `qcom,mdss-dsi-post-120-nt57900-on-command` | **53 B** | **4** |

v6 插入的 `POST_120_STREAM` 是第三个属性的副本（去掉开头的 `b0 00`）。2026-10-20 的 kprobe 证明：驱动在亮屏时会自己把这个属性完整发出去（`pe120` → `tx type=0x5`，见 §4 C），所以 v6 的插入确实是**第二份、且在 sleep-out 之前**的副本。

但**不能因此删掉它**。2026-10-20 真机 A/B：删除注入的 `noinject-control` 能正常建立 120 Hz 链路（`entered rate:120`、clocks 正确、无 DSI 错误），但整屏异常发白、无法使用；刷回保留注入的 `post120-control` 后立即恢复正常。结论：这份早发副本参与了面板上电初期的模拟状态，驱动的晚发 post-120 **不能替代**它。

页选仍然是问题：逐包解码 on-command 后，偏移 298（注入点）处的当前页是 `F1:08` —— 最后一个页选是偏移 108 的 `F1 08`，之后只有 `B6 60` 和 DSC PPS。v6 剥掉 `B0 00` 后，`B9 10 2c 01 cb` / `EC 05 46` 等写入的是 **F1:08 页的 0xB9/0xEC 寄存器**，而不是门极参数所在的 0 页。也就是说，这份"必需"的注入目前写错了页。修正候选（保留注入 + 补 `B0 00`）见 §4 C 的 `panel-b0`。

### 2.2 post-120 序列不是残缺，是另一套命令方言

**修正（2026-10-20）**：`post-120` 不是"表被截断"，但它和 72/90 的结构差异不只是 B9/EC 数值。逐包解码后：

| 包 | 72 / 90 | 120 |
|---|---|---|
| `B0 00` 页选 | 有 | 有 |
| `E5 07` | 有 | **无** |
| `B9 …` / `EC …` | 各两组 | 各两组 |
| `D5 00 00 00 00 00 00` | 每组 `EC` 后都有 | **无** |

v6 为了把插入流凑成 4 字节对齐，把副本里的 `B0 00` 剥掉了（44 B），但那只影响那份冗余副本；驱动真正发送的仍是厂商 53 B 属性（含 `B0 00`，无 E5/D5）。E5/D5 的语义没有 datasheet，不能断言是画质根因；要验证只能直接改 post-120 属性本身，候选与真机状态见 §4 C。

同一份 DTBO 里的 `innolux_nt57900_90_video` 用 `ff` 页选寄存器，LS026B3SA 用 `b9` 页 —— 两者地址空间不同，**没有可移植的查表**。

### 2.3 主 `on-command` 的其余部分仍全部是 90 Hz 标定

v6 只把 `B9/EC`（门极扫描）覆盖成 120 值。主 `on-command`（314 B）中以下寄存器**没有任何 120 Hz 版本**：

| 命令 | 90 Hz 取值 | 作用（待确认） |
|---|---|---|
| `b9 13 5f 02 64` | 门极参数设置 | 被 post-120 的 `b9 10 2c 01 cb` 覆盖 |
| `ec 06 48` / `ec 05 d8` | 与门极/时序配对 | 被 `ec 05 46` / `ec 04 e6` 覆盖 |
| `e6 …`（129 B 大块） | DSC PPS（128 B），前 4 字节是 `11 00 00 89` | **不是 gamma/过驱表**，与刷新率无关，不需要改 |
| `d1 09 30 03 09` | 未识别（F1 18 页） | **未覆盖** |
| `d2 0e`、`d6 00` | 未识别 | **未覆盖** |
| `c2 07`、`b6 60` | 未识别（F1 1a / F1 08 页） | **未覆盖** |
| `be 00 0d` | 未识别 | **未覆盖** |

**结论**：面板在 120 Hz 下运行时，门极扫描（B9/EC）是 120 的；`d1/d2/d6/c2/b6/be` 是否包含必须随刷新率变化的模拟参数，目前没有 datasheet 或厂商 120 参考，**不能下结论**。像素充电不足仍是候选机制，但需要真机 A/B 才能验证。此前把 `e6` 认作 gamma/过驱表是**错误的**：它就是 DSC PPS，修改它只会破坏画质。

### 2.4 可借鉴的对照

同一份 DTBO 里有 `qcom,mdss_dsi_sharp_493_120_new_video`（fragment@46），是厂商为另一块 Sharp 面板准备的**完整 120 Hz 节点**（960×3664，`dfps <120 90 72>`，max-refresh-rate=120）。它的 `on-command` 与 72/90 的差异是：

- 120 在开头多出 `F1 00 / EE 04 / F1 12 / C6 40` 四包；
- `B9` 从 `11 6c 01 89 … 05 b3 01 89` 改为 `0c f4 01 18 … 05 b4 01 18`；
- `C0` 从 `46 86 0f 00 0e 50 00 09` 改为 `47 86 0d 00 0e 50 00 09`；
- `D6` 与 `e6` DSC PPS **不变**（再次证明 e6 与刷新率无关）。

两者规格不同（2160×2160 vs 960×3664），命令方言也不同（493 用 `B9/C0`，LS026 用 `B9/EC/D5`），**不能照搬**。它只能证明"一个完整的 Sharp 120 初始化确实会改页选和额外的模拟寄存器"，不能给出 LS026 的具体值。

---

## 3. 层三：DSI 链路超频 33%（物理层）

### 3.1 实测时钟

| 档位 | pixel clock | bit clock | 行扫描时间 | vfp=57 的实际消隐 |
|---|---|---|---|---|
| 90 Hz | 165,606,750 Hz | 993.6 MHz | 4.993 µs | 284 µs |
| 120 Hz | 220,809,000 Hz | **1324.9 MHz** | **3.745 µs** | 213 µs |

（pclk = 827 × 2225 × fps；bitclk = pclk × 6，该比例在本面板实测为定值）

### 3.2 两个派生后果

1. **行扫描时间缩短 25%**。LCD 每个亚像素必须在行时间内充到目标电压；行时间从 4.99 µs 压到 3.75 µs，源极驱动的 RC 充电率下降 → 亮度/灰阶误差。面板边缘的 TFT 走线最长、RC 最大，**边缘最先劣化** —— 与"边缘发虚"吻合。
2. **PHY 表没有跟着时钟更新。** 实测 v6 的
   `qcom,mdss-dsi-panel-phy-timings` 与 stock **逐字节相同**：
   `00 22 08 08 19 23 09 08 09 02 04 00 1c 0d`。这张表是为 993 MHz 算的，
   而链路跑在 1325 MHz —— 每个 HS 时序段的绝对时长被压缩了四分之一。

   这条路线**已经被真机 A/B 部分证伪**：盲放大版（`×1.334`）和厂商在 1325 MHz
   验证过的 `sharp_493_120` 表都刷过，主观画质**零改善**，dmesg 也没有链路错误。
   详见 `PHY_120HZ_FIX.md`。唯一没试的是 v6 形态下 NOP 掉属性、让内核 v4.0
   计算器重算（早期 NOP 变体早于 post-120 注入，黑屏不能归因于 PHY）。

### 3.3 判据

```bash
# DSI 错误计数与 underrun
adb shell dmesg | grep -iE "dsi|underrun|pll|fifo" | tail -50
# 实测 PLL（verify_refresh_rate.sh 已封装）
bash pico4-display-analysis/verify_refresh_rate.sh
```

若 120 Hz 下出现 DSI error / underrun 计数增长，本层为主因。

---

## 4. 排查与修复路线（按成本排序）

### A. 先验证层一（零风险）
采 90/120 两档渲染分辨率。若被下调，问题在 GPU 侧而非面板 —— 这是"便宜的胜利"。

### B. 修 PHY 表（已部分证伪）

`build_120_universal.py` 可产出三个变体：

| 镜像 | PHY 处理 | 真机结果 |
|---|---|---|
| `--phy keep` | 保留原厂 993 MHz 表 | 当前 v6 行为，画质有损 |
| `--phy scale` | 每字节 ×1.3334 | **已刷，零改善**（`PHY_120HZ_FIX.md`） |
| 厂商 493_120 表 | 全局替换为 1325 MHz 验证表 | **已刷，零改善**（同上） |
| `--phy nop` | NOP 掉属性，内核重算 | **v6 形态下未测** |

`FINAL_120HZ_ANALYSIS.md` §6 的 "v2a（NOP PHY）黑屏" **早于 v6 的 post-120 修复**，不能用来预判今天的结果。若要彻底排除 PHY，只需在 v6 形态下再刷一次 `--phy nop`；但前两个 PHY 变体已经零改善，PHY 不太可能是主因。

### B2. 中间刷新率：**旧实验无效，结论未定**

初稿说"没有中间档位"，这个结论**没有实验依据**。旧的 95/100/110/116 Hz 镜像只改了 `panel-framerate`，**从未重写 B9/EC**，面板仍在 90 Hz 的门极时序下跑，所以它们失败不能证明中间档不可行。

现在能确定的是：LS026 的 B9 最后两字节严格等于 `55080 / fps`：

```
72 Hz : 0x02fd = 765, 765 × 72 = 55080
90 Hz : 0x0264 = 612, 612 × 90 = 55080
120 Hz: 0x01cb = 459, 459 × 120 = 55080
```

这更像"按帧率算出的计数值"，而不是 72/90/120 三张固定表。但 B9 首字节在 120 档从 `0x13` 切到 `0x10/0x0f`，说明桥内部仍有一个离散的页组切换。因此中间档是否可行**仍未验证**；若要试，必须同时写 B9/EC（按公式算最后一档，首字节选最接近的页组），而不是只改 framerate。

### C. 补 120 Hz 面板参数（中风险，需要多轮真机 A/B）

**2026-10-20 关键发现（kprobe 真机追踪）**：亮屏时驱动的实际调用顺序是

```text
pon → tx type=0x0（pre-on） → tx type=0x1（on-command） → dsi_bridge_enable("entered rate:120")
    → pe120（dsi_panel_post_enable_120_nt57900） → tx type=0x5（= DT 的 post-120 属性）
    → pe（dsi_panel_post_enable） → tx type=0x2（generic post-on）
```

驱动自己会在 bridge 进入 120 状态后完整发送
`qcom,mdss-dsi-post-120-nt57900-on-command`。v6 插入 on-command 的 44 B 副本发生在
`tx type=0x1`，比真正的 post-120 早，而且剥掉了页选 `B0 00` —— 它写入的是 on-command
上下文当时选中的页，未必是 B9 页。早期的五个 on-command 候选只改这份早发副本、没有改
驱动真正下发的 post-120 属性；但 2026-10-20 的真机 A/B 又证明**早发副本本身不能删**（见下）。

逐包解码给出了页号证据：on-command 在偏移 298（注入点）处的当前页是 `F1:08`
（最后一次页选是偏移 108 的 `F1 08`，之后只有 `B6 60` 和 DSC PPS）。因此 v6 注入的
`B9/EC` 实际写进了 **F1:08 页的 0xB9/0xEC**，而不是门极参数所在的 0 页。
`post120-*` 四个候选都保留了这份注入，只能回答"post-120 属性里的 E5/D5 是否有用"。

### 候选与真机结果

| 镜像 | on-command 注入 | post-120 属性 | sha256 | 真机 |
|---|---|---|---|---|
| `post120-control` | v6 的 44 B 副本（无 B0） | 厂商原样 53 B | `3204935c727ffa760ae5fbd99e5eac9b7a8e9f699c19931514513b86eeaba846` | ✅ 回滚基线，正常 |
| `noinject-control` | **无** | 厂商原样 53 B | `d222bd701a7921187510635807395640eb868262c355dc59a1c57ff1de8dd14b` | ❌ 整屏异常发白，已回滚 |
| `panel-b0` | 44 B + `B0 00`（53 B） | 厂商原样 53 B | `c5fb0b52aa8e181970caf7832b1cb8121490d116fb2683bce813a8c7f26dfbcb` | 待测：修正页选 |
| `b0both` | v6 44 B + `B0/B9/EC` 53 B + `F1 08`（106 B） | 厂商原样 53 B | `dded2ac3f06ca4eb9ee8b0a569d56692ebe6247639d69fddbadcaa5cb2a06161` | 当前，待目视 |
| `post120-e5` | v6 的 44 B 副本 | 加 `E5 07`（62 B） | `c61a89012c92baaf36aaede2ae6e36743b5e207ab0756c8193866848ccdaf091` | 待测 |
| `post120-d5` | v6 的 44 B 副本 | 每组 `EC` 后加 `D5`（81 B） | `f6aa0583f6e9e6421a06f804a08ce87b1ee9a93b9bf5344e35da4cf063f85916` | 待测 |
| `post120-e5d5` | v6 的 44 B 副本 | 加 `E5 07` + `D5`（90 B） | `808f3c396a5449d22d9a52ef4205de945072218de53fc469e10c56690b1dbef3` | ❌ 整屏白滤镜（面板侧，截图不可见），已回滚 |
| `panel-e5d5` | `B0` + `E5/D5`（90 B） | 厂商原样 53 B | `cf2a61afddb564bdf81d80d8ea391f295b79962805656abdf37aa8bfe19d2896` | 待测 |
| `noinject-e5d5` | **无** | 加 `E5 07` + `D5`（90 B） | `40d4c7511b1fd7855e09cef80b290df781d9f92cb657de88d462e2b46ee048ef` | 不再测试（无注入已证伪） |

所有变体都保持原厂 PHY、DSC PPS、几何时序不变；除 entry 5 外 15 个 FDT entry 逐字节不变，
on-command / post-120 包流均可完整解析。

**真机时间线（2026-10-20）**：

1. `post120-e5d5`（`808f3c39…`）刷入后 120 Hz 链路正常，画质未判定。
2. `noinject-control`（`d222bd70…`）刷入后：离线 diff 只有 framerate / max-refresh / DFPS
   三个属性变化，on-command 与 post-120 与厂商逐字节相同；开机 120 Hz（modeId 1，
   `fps=120.00001`，`PIXEL_CLK=220809000`，`BYTE_CLK=165606750`），`entered rate:120`，
   dmesg 无 DSI 错误，kprobe 序列 `pon → tx 0x0 → tx 0x1 → br → pe120 → tx 0x5 → tx 0x2`
   完整。但头显内**整屏异常发白，无法使用**。
3. 刷回 `post120-control`（= v6 基线）后恢复正常。
4. `b0both`（`dded2ac3…`）刷入：保留 v6 的 44 B 注入不动，追加 `B0 00` + 120 B9/EC 写 0 页，
   再用 `F1 08` 恢复 stock 在 sleep-out 前的页状态。开机 120 Hz、`VIDEO_ENGINE=ON`、
   `entered rate:120`、无 DSI 错误。**目视结果：蓝紫描边与运动线条仍在，b0both 未解决。**
   同时做了运行期实验：把 HMD 服务写配置库的 `displayRefreshRate` 强制为 120（bind mount，
   不改分区），让 SDK 使用 120 档 TimeWarp/曝光（6.5/2.3 ms）。我主观感觉运动线条
   “似乎变少了”，但蓝紫描边不变。
5. `post120-e5d5`（`808f3c39…`）刷入：EDL 读回一致，开机 120 Hz 正常，但头显内出现
   **整屏白滤镜/发白**，而 `screencap` 抓图完全正常——再次证明面板侧发白/偏色不会进入
   帧缓冲截图。已回滚到 `b0both`。结论：**晚发 post-120 补 `E5 07`+`D5` 的方向错误**，
   E5/D5 是 72/90 序列的模拟参数，不适用于 120。`panel-e5d5`（早发 E5/D5）因此也降低优先级。

结论：驱动晚发的 post-120 53 B **不足以**完成面板上电初期的模拟初始化；v6 的早发副本
虽然写错页，却承担了某个必需作用。下一步不能再删注入，只能在保留注入的前提下修正它：

1. `panel-b0`（`c5fb0b52…`，**下一个**）—— 早发只写 0 页（`B0 00` + 120 B9/EC），
   完全去掉 v6 误写的 `F1:08`。验证"错页写入 F1:08 导致蓝紫描边/细线"的假设。
   若白屏，说明 F1:08 写入仍属必需，退回 `post120-control`/`b0both`。
2. `post120-e5` / `post120-d5` / `post120-e5d5` —— **晚发 E5/D5 方向已证伪**（`e5d5`
   实测整屏白滤镜，截图不可见）。不再测试。
3. `panel-e5d5`（`cf2a61af…`）—— 低优先级：早发 E5/D5 很可能同样触发白滤镜。

已知限制：

- 没有 LS026B3SA datasheet，`E5 / D5` 的语义只能靠与 72/90 序列的结构类比；
- 从 `sharp_493_120` 反推 `d1 / d2 / d6 / c2 / b6 / be` 的 120 取值（目前无参考，风险最高）；
- 每改一次要重新打包 dtbo 并重启，迭代成本高（内核模块路线见 D）。

### D. 内核模块路线（高投入，高控制力）
`dsi120/` 已有雏形，且 `kernel-symbols/kallsyms-5.13.7.txt` 有 149884 个符号的真实地址。走这条路可以：
- 运行时下发完整 init code，**不刷 dtbo 就能 A/B 测试寄存器组合**，把 C 的迭代成本从"刷一次机"降到"改一次参数"；
- 直接读写 DSI PHY 寄存器调 drive strength / pre-emphasis / slew，改善 1.3 GHz 下的信号完整性；
- 绕开 DFPS 的 vfp-grow 黑屏问题（驱动层可控切换），从而允许放宽时序、给面板更多充电时间。

**这是唯一能同时解决层二和层三的路线。** 面板 init code 本身是厂商数据、无 datasheet 时只能逆向，但至少迭代闭环会快一个数量级。

---

## 5. 构建链已可复现（2026-10-19）

此前 v6 只存在于 Release 资产里，无法从源码重建。现已打通：

```text
官方固件 5.13.7_CN_b9650.zip  → firmware-update/dtbo.img (8 MB)
  补零到分区大小 24 MB        → sha256 307e7021… = 设备上的 stock 基线 ✅
  build_120_init120_inplace.py <stock24> 5 <out>
                              → sha256 f0c10d1d… = 已发布的 v6，逐字节一致 ✅
```

CN 与 INTL 固件的 16 个 entry **内容完全相同**（只是排列顺序不同），
`build_120_universal.py` 因此一次性 patch 全部 entry，产出两份镜像；
安装器按 stock 哈希选择对应的一份。

## 6. 运行期修复：底部晚锁存撕裂（2026-10-20）

我补充的关键症状：**平视时面板最底边一直有线条，抬头后更严重**。这不是面板初始化问题，
而是扫描/锁存时序：屏幕最后扫描的底部行在 GPU 饱和时拿到的是上一帧。头显内 30 s 实测：

```text
GPU 99% @ 587MHz, engine ~31fps
FrmGpu median 27.2ms, FrmTime ~30ms
VsyncDelay 3–5, FrmLate >0 in 34/35 samples
ATWGPU ~4.2ms, no DSI/underrun errors
```

修复：把 `/system/etc/pvr/pxr_config.txt` 的 `xrMiniVsyncBackStep` 从 2 改为 4
（bind mount + canary 同步 + kill `com.pico.xr.openxr_runtime` 重新加载）。
生效证据：ATWGPU 升到 ~5.2ms、VsyncDelay 到 5；我目视确认
**“正常了，没有画面错误了”**。代价是约多 2 个 vsync（120Hz 下 ≈16.7ms）的延迟，
下一步可试 3 找平衡。

剩余问题：2D 应用蓝紫描边仍在，整体画面有轻微偏白（远轻于 `post120-e5d5` 的面板白滤镜）。
两者都属于面板侧静态问题，运行期时序修复不影响。`sdk_chromaticStaus` 受 powerlevel 规则控制
（默认 0），改 `xrEnableChromatic` 无效；实测 CA 开/关都不改变蓝边，确认是面板侧。

### 6.1 GPU 占用：真正的原因是眼缓冲超采样（2026-10-20）

`pxr_config.txt` 的 `xrRenderTextureWidth/Height`（1656×1822）**被配置库覆盖**。
实际每眼渲染尺寸来自：

```text
sdk_eyebufferX/Y = 2816        (pxr_config_package, powerlevel 规则也是 2816)
os_eyebuffer_width/height = 2816 (android 包)
```

面板每眼原生只有 2160×2160。把两对键都设为 2160 后，compositor 日志出现
`onOSEyebufferChanged = 2160,2160`，离头实测：

| 指标 | 2816² | 2160² |
|---|---|---|
| FrmGpu 中位 | 27–30 ms | **15.5 ms** |
| 引擎 FPS | ~30 | **~65** |
| ATWGPU | 4.2 ms | **2.6 ms** |
| VsyncDelay | 4–5 | **3** |

GPU 仍显示 99%，但这是因为引擎终于能提交更多帧，不再卡在 30fps；温度 55–60°C。
`powerlevel` 规则可能在开机/功率档切换时把 2816 写回，因此 `service.sh` 在开机后
重新设置并持续 60 秒。

### 6.2 持久化（模块已更新，待重启验证）

已把运行期修复写进 Magisk 模块：

- 补丁 lib `8b4431d4…`：速率映射 + 把 `displayRefreshRate` 配置写入强制为 120；
- `system/etc/pvr/pxr_config.txt`：`xrMiniVsyncBackStep = 4`；
- `post-fs-data.sh`：开机早期把配置复制到 `/data/misc/pxr/canary/config/`；
- `service.sh`：开机后设置 `os_eyebuffer_width/height=2160`、`sdk_eyebufferX/Y=2160`。

文件已推到 `/data/adb/modules/pico4_120hz/` 并**重启验证通过**：

```text
/system/lib64/libpxrhmdservice.so = 8b4431d4… (模块挂载)
/system/etc/pvr/pxr_config.txt     = xrMiniVsyncBackStep = 4
sys.pvr.display.type               = 120.000000
getRefreshRate                     = 120.000000
displayRefreshRate / sdk_refreshRate = 120
os_eyebuffer / sdk_eyebuffer       = 2160
离头 FrmGpu 中位 13.2 ms，引擎 ~73 fps，VsyncDelay 2
```

注意：直接推到 `/data/adb/modules` 的 `service.sh` 必须是 **LF 换行**。第一次推送保留了 CRLF，
Android 的 sh 静默失败，表现为 `sys.pvr.display.type` 仍为 72、眼缓冲未设置；转 LF 后正常。

## 7. 关联

- 时序/时钟数据：`FINAL_120HZ_ANALYSIS.md`（注意：该文"120 Hz 永远不会亮"的结论已被 v6 推翻，仅寄存器级证据仍有效）
- 面板配置提取：`extract_panel_config.py <dtbo.img>`，可打印每个面板节点的全部属性与 `post-*-on-command`
- 物理验证：`verify_refresh_rate.sh`
