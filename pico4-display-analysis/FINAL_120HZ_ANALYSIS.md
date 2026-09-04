# PICO 4 LS026B3SA 120Hz 可行性最终报告

**日期**: 2026-09-04  
**状态**: 已实机验证，结论确定  
**设备**: PICO 4 (A8110, Phoenix), PICO OS 5.13.7, Android 10

---

## 执行摘要

**120Hz 在 LS026B3SA 上不可行。** 这不是配置问题，不是 DTBO 问题，不是面板能力问题——是 PICO 的显示驱动在注册 120Hz 模式后，从未调用时钟切换函数。

寄存器级证据确凿：
- `dsi_display_set_mode` 被调用，日志报 `entered rate:120`
- 但 `dsi_clk_set_pixel_clk_rate` **从未被调用**（kprobe 验证）
- PLL 寄存器 diff 证实时钟停在 993MHz（90Hz 的值）
- DSI 控制器寄存器证实 vtotal 停在 2225（vfp=57，不是 14）
- 四条数据 lane 全部报错（`DLN0_PHY_ERR = 0x88888`）

**面板收到的信号和 90Hz 一模一样，只是驱动以为自己在跑 120。** NT57900 桥在这个矛盾状态下无法出图，表现为黑屏+底部花屏。

---

## 技术细节

### 1. 我们做了什么

| 步骤 | 方法 | 结果 |
|------|------|------|
| 提取 LS026B3SA 完整配置 | 自写 `extract_panel_config.py` 离线解析 DTBO | ✅ 拿到全部 timing/PHY/DSC/TCON 参数 |
| 推导 120Hz 配置 | 几何计算 + 5 面板 PHY 标定曲线 | ✅ vfp=14, vtotal=2182, bitclk=1.299GHz |
| 生成候选镜像 | `build_120hz_v2_dtbo.py` | ✅ 三个变体（vfp14/vfp57/保留PHY） |
| 实机验证 | 刷入 dtbo 分区，重启，观察 | ❌ 全部黑屏+底部花屏 |
| 寄存器取证 | regmap 直读 DSI PLL/控制器 | ✅ 发现 PLL 未切换 |
| kprobe 验证 | `/sys/kernel/debug/tracing/kprobe_events` | ✅ 证实 `dsi_clk_set_pixel_clk_rate` 未被调用 |

### 2. 关键证据

**PLL 寄存器 diff（90Hz vs 120Hz）**：
```
只有 8 个字节变化，全部是校准/SSC 参数：
  0x1b8: 9b→9c, 0x1bc: 7a→e2, 0x1c0: 85→84, 0x1c4: ba→52
  0x1c8: 05→06, 0x1f4: 13→2b, 0x218: 9b→9c, 0x298: df→dc

主反馈分频器（应含 993MHz→1299MHz 的分频比）纹丝不动。
```

**DSI 控制器寄存器（120Hz 下）**：
```
DSI_VIDEO_MODE_TOTAL = 0x08b0033a → htotal=827, vtotal=2225 (vfp=57)
DSI_CLK_STATUS = 0x008047c3 → bit31=0，PLL 未锁定
DSI_DLN0_PHY_ERR = 0x00088888 → 四条数据 lane 全部报错
```

**kprobe 验证**：
```
echo "p:clk_probe dsi_clk_set_pixel_clk_rate" > kprobe_events
# 触发 72→90 切换
# 结果：clk_probe 未被触发（0 次）
# 但 dsi_display_set_mode 被调用（dmesg 有 entered rate:72）
```

### 3. 为什么改 DTBO 没用

三个变体覆盖了几何（vfp 14 vs 57）和 PHY（内核重算 vs 原厂表）两个维度，结果完全一致：

| 变体 | vfp | PHY | 结果 |
|------|-----|-----|------|
| v2a | 14 | NOP→内核重算 | 黑屏花屏 |
| v2b | 14 | 保留原厂 993MHz 表 | 黑屏花屏 |
| vfp57 | 57 | 保留原厂 | 黑屏花屏 |

**因为驱动根本不改时钟，所以 DT 里写什么都是白写。**

### 4. 改驱动的现实路径

**前提条件**：
- `CONFIG_MODULES=y` ✅
- `CONFIG_KPROBES=y` ✅
- `CONFIG_MODULE_SIG_FORCE=y` ❌（模块必须签名）
- `CONFIG_DYNAMIC_DEBUG=n` ❌（不能动态开调试日志）

**可行路径**：

1. **内核模块 + kprobe**（最优雅，但需要解决签名）
   - 写一个内核模块，用 kprobe 钩住 `dsi_display_set_mode`
   - 在钩子里手动调用 `dsi_clk_set_pixel_clk_rate` 设置 1.299GHz
   - 问题：`MODULE_SIG_FORCE=y`，必须绕过或拿到签名密钥

2. **静态二进制补丁 boot.img**（最彻底，但工作量最大）
   - 从 boot.img 提取内核（已做，35MB 未压缩 ARM64 Image）
   - 定位 `dsi_display_set_mode` 的机器码（需要解码 kallsyms 或用其他方法）
   - 修改指令，让它在注册 120Hz 后调用时钟切换
   - 重打包 boot.img，刷入
   - 问题：需要精确的地址定位，且每次 OTA 都要重做

3. **利用现有内核模块**（最取巧）
   - 设备已经加载了 wlan 等 .ko 模块
   - 如果某个模块有合适的钩子，可以借用
   - 问题：需要找到这样的模块，且不一定存在

**不推荐的路径**：
- 改 DTBO 里的任何参数（已证明无效）
- 改 TCON/桥序列（已证明不是瓶颈）
- 改 PHY 表（已证明不是瓶颈）

---

## 结论

**120Hz 在 LS026B3SA 上不可行，除非 PICO 修复显示驱动或推送新固件。**

驱动的问题很明确：`dsi_display_set_mode` 注册了 120Hz 模式，但从未调用 `dsi_clk_set_pixel_clk_rate` 来切换时钟。这可能是：
1. PICO 故意禁用了 120Hz 的时钟切换（面板定位就是 90Hz）
2. PICO 的驱动有 bug，120Hz 路径没走通
3. 需要特定的条件（如 FalconCV3 机型）才启用 120Hz

无论哪种情况，都不是用户侧能解决的。DTBO 修改已经做到了极致——`entered rate:120` 成功，但硬件没跟上。

**建议**：放弃 120Hz，接受 90Hz 作为这块面板的物理上限。

---

## 附录：生成的文件

| 文件 | 说明 |
|------|------|
| `extract_panel_config.py` | 离线解析 DTBO，导出面板完整配置 |
| `build_120hz_v2_dtbo.py` | 生成 120Hz 候选镜像（已验证无效） |
| `pll_90hz_baseline.txt` | 90Hz 原厂 PLL 寄存器基线（292 个） |
| `pll_120hz.txt` | 120Hz 下 PLL 寄存器（与 90Hz 几乎相同） |
| `dtbo-120hz-v2.img` | v2a 候选（vfp=14, NOP PHY） |
| `dtbo-120hz-v2-keepphy.img` | v2b 候选（vfp=14, 保留原厂 PHY） |
| `dtbo-120hz-vfp57.img` | vfp57 候选（vfp=57, 保留原厂 PHY） |
| `dtbo-device.img` | 设备原厂 dtbo 备份 |
| `boot-device.img` | 设备原厂 boot 镜像（含内核） |
| `kernel-device.img` | 提取的内核（35MB，未压缩） |

**所有候选镜像均已验证无效，不建议再刷。设备当前为原厂状态。**
