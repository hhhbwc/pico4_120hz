# pico4_120hz

**PICO 4 显示刷新率研究：原生 72/90 Hz + 120 Hz DTBO 超频实验 + dsi120 内核模块**

**PICO 4 display refresh-rate research: stock 72/90 Hz + 120 Hz DTBO overclock experiments + dsi120 kernel module**

**Исследование частоты обновления PICO 4: штатные 72/90 Гц + эксперименты с разгоном DTBO до 120 Гц + модуль ядра dsi120**

[中文](#中文) · [English](#english) · [Русский](#русский)

> **当前状态 / Current status / Текущий статус**
>
> **DTBO 层面的 120 Hz 已确认不可行**（三个变体均黑屏+花屏，寄存器级证据证实驱动从不调用时钟切换）。但内核模块路径已突破：`sig_enforce` 签名绕过成功，当前 probe-only 模块已加载并注册到 `dsi_display_set_mode`、`dsi_clk_set_pixel_clk_rate` 和 `dsi_clk_set_byte_clk_rate`；时钟调用仍未启用，正在确认 Phoenix BSP 的 handle 生命周期与完整切换序列。详见 [dsi120 内核模块](pico4-display-analysis/dsi120/README.md) 和[寄存器级失败分析](#52-失败分析)。
>
> **DTBO-level 120 Hz is confirmed infeasible** (all three variants black-screened; register-level evidence proves the driver never calls the clock-switch function). However, the kernel-module path has broken through: the `sig_enforce` signature bypass works, and the current probe-only module registers probes on `dsi_display_set_mode`, `dsi_clk_set_pixel_clk_rate`, and `dsi_clk_set_byte_clk_rate`. Clock calls remain disabled while the Phoenix BSP handle lifetime and complete switch sequence are verified. See the [dsi120 kernel module](pico4-display-analysis/dsi120/README.md) and [register-level failure analysis](#52-failure-analysis).
>
> **DTBO-уровень 120 Гц подтверждённо недостижим** (все три варианта дали чёрный экран; регистровые доказательства показывают, что драйвер не вызывает функцию переключения часов). Однако путь через модуль ядра прорван: обход подписи `sig_enforce` работает; текущий probe-only модуль зарегистрирован на `dsi_display_set_mode`, `dsi_clk_set_pixel_clk_rate` и `dsi_clk_set_byte_clk_rate`. Вызовы часов пока отключены, пока проверяются lifetime handle и полный порядок переключения в Phoenix BSP. См. [модуль ядра dsi120](pico4-display-analysis/dsi120/README.md) и [анализ на уровне регистров](#52-анализ-неудачи).

---

# 中文

## 0. 免责声明

本项目会修改 `dtbo` 分区并向系统应用注入代码，属于高风险改机操作。

- 刷入前必须先完整备份 `dtbo`、`dtbobak`、`vbmeta`，并确认 EDL(9008) 回写路径可用。
- 本项目**不关闭 AVB**，**不修改** `vbmeta`、`boot`、`dtbobak`、`GPT`、`super`、`ABL` 或任何其他分区。
- 出现黑屏、花屏、持续重启、DSI/DSC/PLL/underrun 报错或异常温升，立刻回滚原始 DTBO。
- 一切后果自负。作者不对变砖、保修失效或硬件损伤负责。

## 1. 目标设备

本项目仅在下述固件上验证过。

| 项目 | 值 |
| --- | --- |
| 型号 | PICO 4 (A8110) |
| 代号 | Phoenix |
| 系统 | PICO OS 5.13.7 / Android 10 |
| 内部版本 | `c000_rf01_bv1.0.1_sv5.13.7_202510300008_phoenix_b9650_user` |
| SoC | Snapdragon 865 (Kona) |
| 面板 | Sharp LS026B3SA (`ro.pvr.hmd.type=SHARP5K`) |
| 分辨率 | 4320 × 2160 |
| 出厂刷新率 | 72 Hz / 90 Hz |
| 前置条件 | 已 root（Magisk/KSU）+ Zygisk Vector 或 LSPosed |

## 2. 原理

### 2.1 DTBO 与 DFPS

PICO 4 的面板时序由 DTBO 中的面板节点描述。目标节点与属性：

```
节点: qcom,mdss_dsi_sharp_ls026b3sa_90_video
属性: qcom,dsi-supported-dfps-list   <90 72>  ->  <120 90 72>
属性: qcom,mdss-dsi-max-refresh-rate <90>     ->  <120>
```

DTBO 结构信息：

```
Android DT table magic : 0xD7B7AB1E
分区大小               : 24 MiB（候选镜像必须保持完全一致的大小）
当前生效条目           : dtbo_idx = 5
```

镜像校验值：

| 文件 | SHA-256 |
| --- | --- |
| `dtbo-current.img`（原始） | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| `dtbo-120hz-candidate.img`（候选） | `df4e7b25d437464291ebbef0230e28ad3b6eaf6303866dc6ace7e1a52fa1bdf4` |
| `vbmeta-current.img`（基线，不修改） | `2bce6e1cccf657c0237b3e8a35f0cfa52b663cec1d922b27a561c5ea97c4b4d3` |

刷入候选 DTBO 后，DRM 公开的模式变为：

```
4320x2160x120x331212vid
4320x2160x72x331212vid
```

Android 侧同步可见：

```
supportedModes [{id=1, 4320x2160, fps=120.00001},
                {id=2, 4320x2160, fps=72.00001}]
```

### 2.2 DFPS 只能降频不能升频

这块面板走的是 DFPS（动态帧率），关键属性是：

```
qcom,mdss-dsi-pan-fps-update = dfps_immediate_porch_mode_vfp
```

含义是**像素时钟固定不变，只调整垂直前肩（VFP）**。基准时序取自 DT 里的默认时序：

```
每 DSI 2160x2160（双 DSI 合成 4320x2160）
h: hfp 54, hbp 33, hpw 20  -> htotal 2267（压缩后 827）
v: vbp 4, vfp 57, vpw 4    -> vtotal 2225
qcom,mdss-dsi-panel-framerate = 90
```

由此可推算每档所需的 VFP：

```
vtotal(fps) = vtotal_base × 90 / fps
vfp(fps)    = 57 + (vtotal(fps) - 2225)

72  Hz -> vtotal 2781 -> vfp  +613   可行
90  Hz -> vtotal 2225 -> vfp    57   基准
120 Hz -> vtotal 1669 -> vfp  -499   不可能
```

`-499` 正是内核那条报错的来源，它属于 **120 Hz**，不是 90 Hz：

```
Invalid new_hfp calcluated-499
```

vtotal 1669 甚至小于 vactive 2160，物理上无法扫出 2160 行。**要往上加帧率必须提高像素时钟，而 immediate-porch 模式的 DFPS 不会动时钟。**

这套推算可以用 PICO 自己的面板节点交叉验证。`sharp_493_120_new_video` 以 120 Hz 为基准（vtotal 3686、htotal 1072），按同一公式推导：

| 目标 | 推算 vfp | PICO 专用节点实测 vfp |
| --- | --- | --- |
| 90 Hz | 1242 | `sharp_493_90_new_video` = 1231 |
| 72 Hz | 2471 | `sharp_493_72_new_video` = 2459 |

误差都在 1% 以内，说明模型正确：**基准时序必须是最高帧率那一档**，其余档位靠加长 VFP 得到。我们这块面板的基准是 90 Hz，所以原厂只能给出 72/90。

### 2.3 PICO 的厂商刷新率链路

刷新率不是通过 Android 标准 API 切换的，而是走 PICO 私有链路。核心属性：

```
persist.pvr.display.type   jdi49372 / jdi49390 / jdi493120   持久化请求值
sys.pvr.display.type       72.000000 / 90.000000 / 120.000000  运行时生效值
```

`pxrhmdservice` 只读取 `sys.pvr.display.type` 并向应用报告：

```
Call <getRefreshRate> - sys.pvr.display.type=[72.000000] done.
Call <getRefreshRate> - refreshRate=[72.000000 72.000000 72.000000].
```

PICO Settings 中的实现（`com.picovr.settings`）：

```
PicolabFragment.onCheckedChanged(...)         刷新率开关 id = 0x7f0902c6
  -> b1(boolean)                              弹出确认对话框
    -> PicolabFragment$6.onClick(View)         用户点“确定”
      -> N(...) -> O(boolean)
        -> Utils.v1(boolean)                  写入厂商状态
      -> K0()                                 restartDevice，postDelayed 1200 ms 后重启
```

`Utils.v1(boolean)` 的实际行为：

```java
// s1() == Constant.i() && Constant.c()
// Constant.i() 只在 ro.pvr.product.name == "FalconCV3" 时为真
// PICO 4 是 Phoenix，所以 s1() == false，这一行选到的是 jdi49390
String type = s1() ? "jdi493120" : "jdi49390";
if (!enable) type = "jdi49372";

CommonUtils.setSystemProperties("persist.pvr.display.type", type);
ConfigServiceManager.i("sdk_refreshRate", s1() ? "120" : "90");
ConfigServiceManager.i("sdk_Recommand_refreshRate", ...);
Utils.P0("persist.pvr.display.type", rate);   // Settings.Global.putInt
Utils.B0("com.pvr.display.type", rate);       // PxrNotificationService.sendPxrMessage
Utils.x1(enable);                             // 更新录屏帧率
```

两个关键结论：

1. 本机 `Utils.s1()` 实测返回 **`false`**（`ro.pvr.product.name` 是 `Phoenix`，不是 `FalconCV3`），所以原生开关只能在 72 与 **90** 之间切换，`Utils.v1(true)` 写入的是 `jdi49390`。**不能**用 `v1(true)` 来请求 120，否则实际写下去的是 90。120 相关路径仅用于实验，当前未启用。本项目早期曾对三档都走显式 vendor 写入并把 `s1()` hook 成 `true`，但后续实测确认 120 Hz 候选会黑屏/花屏；当前原厂 DTBO 下只保留真实 72/90 两档，120 相关逻辑不应视为可用。
2. **原生流程本身就要重启设备**。`K0()` 就是 `restartDevice`，不重启不会生效。


### 2.4 原生下拉菜单

“电源管理方案”那一行用的是 PICO 自己的控件与弹窗，本项目复用同一套实现，因此外观与交互和系统原生完全一致。

```
控件      com.picovr.customviews.DropdownOptionView      (电源行 id = 0x7f0902d0)
入口      PicolabFragment.T0(View)
弹窗      PopupMenuHelper.c(Activity, View, BaseAdapter,
                            SimpleOnItemClickListener, int checkedPosition)
适配器    com.bytedance.osui.popupmenu.OSUIMenuAdapter
条目      new MenuItemData(MenuItemType.TYPE_TITLE_CHECK).l("120 Hz")
点击      PicolabFragment$3.onItemClick(AdapterView, View, int, long)
```

勾选状态由传入的 `checkedPosition` 决定，不保存在 `MenuItemData` 内部。

### 2.5 SurfaceFlinger 的私有校验

即使 DTBO 已经让 120 Hz 成为 DRM 与 Android 的合法模式，Android 框架仍然会把面板钉在 72 Hz：

```
E DisplayModeDirector: Asked about unknown display, returning empty allowed set! (id=0)
F DEBUG: #08 libsurfaceflinger.so (SurfaceFlinger::setAllowedDisplayConfigs(...))
```

`DisplayModeDirector` 不认识 display 0，返回空的允许集合；这个空集合传给 SurfaceFlinger 后触发越界，开机时把它崩掉两次，SF 恢复后退回默认配置。

而标准接口全部被静默拒绝：

```
setAllowedDisplayConfigs({0})   -> 返回成功，状态不变
setActiveConfig(0)              -> 返回成功，状态不变
service call SurfaceFlinger 1035 i32 0 -> BAD_VALUE (-22)
```

反汇编 `/system/lib64/libsurfaceflinger.so` 找到了原因，PICO 在这个函数里加了一道私有校验：

```asm
0xfad78  ldr  w10, [x9]        ; 遍历 allowedConfigs
0xfad7c  cmp  w10, #3          ; 是否存在等于 3 的元素
0xfad80  b.eq #0xfadac         ; 存在 → has pico parameter，放行
0xfadb8  b.eq #0xfae5c         ; 不存在 → no pico parameter
0xfae6c  mov  w19, #-0x16      ;          返回 -22 (BAD_VALUE)
0xfadd4  sub  x8, x8, #4       ; 放行后把末尾的标记弹出
```

数组里必须携带魔数 `3`，且因为它会被从末尾弹出，标记必须放在最后：

```java
SurfaceControl.setAllowedDisplayConfigs(token, new int[] {configIndex, 3});
```

日志里那句 `no pico parameter so allow to change display config through surfaceflinger` 措辞有误，实际含义是**不放行**。

### 2.6 120 Hz 基准时序候选（已测试并回滚）

既然 DFPS 只能降频，唯一的出路就是让默认时序本身变成 120 Hz，再让 90 与 72 从它推导出来。这份候选已经实际刷入并重启测试过，结果是黑屏和底部花屏，随后已通过有线 ADB 回滚到原厂 DTBO。`build_120hz_base_dtbo.py` 只做三处原地改动，镜像尺寸不变，全镜像仅 20 字节差异；该脚本用于复现实验，不代表候选可用：

```
qcom,mdss-dsi-panel-framerate    90 -> 120
qcom,mdss-dsi-v-front-porch      57 -> 14
qcom,mdss-dsi-panel-phy-timings  用 FDT_NOP 覆盖（合法 FDT，解析器跳过）
```

PHY 时序是删掉而不是手算的。DT 里那 14 字节属于旧的 993 MHz 位时钟，新时钟下必然不对；这块 SoC 用的是 DSI PHY v4.0，14 字节正是它的时序表长度。删掉之后驱动会自己算，`/proc/kallsyms` 证实这个内核带着计算器和对应的 v4.0 算子：

```
dsi_phy_hw_calculate_timing_params
dsi_phy_hw_v4_0_calc_clk_zero / calc_clk_trail_rec_min / calc_hs_zero / calc_hs_trail
```

算术依据不是猜的，压缩后 htotal 取自运行中的 DSI 控制器寄存器 `DSI_VIDEO_MODE_TOTAL = 0x0adc033a`，即 htotal−1 = 0x033a、vtotal−1 = 0x0adc：

| 档位 | vtotal | vfp | 来源 |
| --- | --- | --- | --- |
| 120 Hz | 2182 | 14 | 基准 |
| 90 Hz | 2909 | 741 | DFPS 推导 |
| 72 Hz | 3636 | 1468 | DFPS 推导 |

三档都落在正的前肩上。像素时钟 216,541,680 Hz（现为 165,591,864，+30.8%），位时钟约 1.30 GHz（现为 993.5 MHz），在 SM8250 D-PHY 的范围内。

安全性检查：该节点的 `__local_fixups__` 只引用 `io-channels` 与 `qcom,panel-supply-entries` 两个 phandle 属性，都没被碰到，因此覆盖 PHY 时序不会破坏 overlay 的 phandle 修正。

**实测结果：黑屏并伴随底部花屏。**该候选已经实际写入活动 `dtbo` 并重启测试，随后已通过有线 ADB 回滚到原厂 DTBO。失败时内核出现 `DSI_0: LLENGTH = 3400`，说明 DSI 传输长度与 LS026B3SA 的面板配置不匹配。

刷入前请确保 USB 线可用。注意这台设备虽然 `ro.boot.flash.locked=0`，但**fastboot 的 `flash` 命令被禁用**——能进 fastboot 却刷不了分区，唯一可用的离线刷写途径是 **EDL(9008)**。所以只要 ADB 还在就用 `dd` 回滚，`dtbobak` 全程保持原样作为第二道保险。刷入后用 `pico4-display-analysis/verify_refresh_rate.sh` 判断真实刷新率，不要看 dumpsys。

### 2.7 公开面板资料与可信度

公开资料能确认 `LS026B3SA` 系列的基础硬件信息，但没有找到 Sharp 官方 datasheet、DSC PPS、PHY 时序或 TCON 初始化表。

- [Panelook LS026B3SA01X](https://www.panelook.com/LS026B3SA01X_Sharp_2.6_LCM_overview_64156.html)：搜索摘要显示 Sharp、2.6 英寸、2160×2160、MIPI、2 channels、4 data lanes，并标注 120 Hz。
- [Panelook LS026B3SA01Y](https://www.panelook.com/LS026B3SA01Y_Sharp_2.6_LCM_overview_64157.html)：同系列的 Y 子型号，摘要也显示 2160×2160、MIPI、2 channels、4 data lanes、120 Hz。
- [MyDoPoint LS026B3SA01X](https://www.mydopoint.com/lcd_LS026B3SA01X.html)：列出 Sharp、2.6 英寸、2160×2160、520 cd/m²、650:1、MIPI、WLED。
- [JianXiang LS026B3SA 系列](https://www.jxg.tw/en/product_1569517.html)：将 LS026B3SA01/A/B/X 列为面向 PICO、Meta/Oculus 等 VR 设备的 Sharp 面板系列。
- [PICO 4 官方规格](https://www.picoxr.com/global/products/pico4/specs)：确认 PICO 4 使用两块 2.56 英寸 Fast-LCD，每眼 2160×2160，官方刷新率为 72/90 Hz。
- [PICO 4 官方产品页](https://www.picoxr.com/global/products/pico4)：同样把 PICO 4 的最高刷新率列为 90 Hz。
- [52audio PICO 4 拆解](https://www.52audio.com/archives/150653.html)：确认两块 2.56 英寸、4320×2160、90 Hz Fast-LCD，但没有给出面板型号或 TCON。
- [NT57900 经销商页面](https://www.displayamoled.com/sale-53602352-2-56-inch-vr-lcd-display-2160x2160-45-pins-mipi-interface-driving-ic-nt57900.html)：页面对应的是 ESHX026C4T-NH0，不是明确的 LS026B3SA01X，因此只能证明 NT57900 出现在相似 VR 面板中，不能证明它就是本机的 TCON 配置来源。

Panelook 页面本身会触发滑块验证，上述 Panelook 参数来自搜索摘要，可靠性低于可直接访问的原始 datasheet。当前实机 DTBO 和内核证据优先级更高：本机原厂节点明确是 `sharp ls026b3sa 90hz video mode dsi panel`，真实模式为 72/90。

## 3. 模块做了什么

模块包名 `com.picoxr.refreshselector`，作用域**仅** `com.picovr.settings`。

| Hook 点 | 作用 |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | 移除原刷新率 `SwitchView`，在同一行插入 `DropdownOptionView`，沿用同一个 id |
| `PicolabFragment.onCheckedChanged(...)` | 拦截旧开关，避免二态语义与三档冲突 |
| `PopupMenuHelper.c(...)` | 以锚点 id 识别刷新率弹窗，把菜单项替换为当前真实存在的 display config；原厂 DTBO 下为 `72 Hz / 90 Hz` |
| `PicolabFragment$3.onItemClick(...)` | 拦截电源模式逻辑，按真实 display config 处理刷新率；live 切换失败时才提示重启 |
| `Utils.s1()` | 强制返回 `true`，抵消 `Constant.i()` 只认 `FalconCV3` 的机型门 |
| `SurfaceControl.setAllowedDisplayConfigs` | 带上 PICO 魔数 `3` 调用，实现运行时即时切换，无需重启 |
| `SettingApplication.onCreate(...)` | 只读诊断探针，打印 `sdk_refreshRate`、`sdk_Recommand_refreshRate` 与两个属性的当前值 |

刷新率请求路径，全部显式写入，不依赖 `Utils.v1()` 的 `s1()` 判定；原厂 DTBO 当前只提供真实的 72/90 两档：

```
72  Hz  -> persist.pvr.display.type = jdi49372  + sdk_refreshRate = 72
90  Hz  -> persist.pvr.display.type = jdi49390  + sdk_refreshRate = 90
120 Hz  -> 仅用于失败的 DTBO 实验，当前菜单已移除
共同部分  sdk_Recommand_refreshRate 同步为同一值
          Utils.P0 / Utils.B0 / Utils.w1(72 档 24，其余 30)
          setAllowedDisplayConfigs(token, {configIndex, 3})  ← 立即生效
```

菜单只列出真实存在的 display config。当前原厂 DTBO 下是 72 与 90；120 选项已移除，因为对应候选会导致黑屏或花屏。

模块不修改 PICO Settings 的 APK，不改资源，不动任何分区。禁用模块或移除作用域即可完全恢复原生界面。

## 4. 已验证的结果

- 候选 DTBO 刷入后设备正常启动，ADB 稳定，无显示异常；EDL 只读回读的 `dtbo` 与 `dtbobak` 与基线**逐字节一致**，回滚路径可用。
- **逆向出 PICO 在 SurfaceFlinger 上的私有校验（魔数 `3`）确实有效**，这是本项目唯一被完整验证的运行时突破：

```
before  activeConfig=1  allowedConfigs=[1]
setAllowedDisplayConfigs({0, 3})  -> accepted
after   activeConfig=1  allowedConfigs=[0]      # 不带魔数时这里不会变
```

- 厂商状态可以跨重启保持，配置服务里存的就是 120：

```
config sdk_refreshRate=120 / sdk_Recommand_refreshRate=120
prop persist.pvr.display.type=jdi493120
prop sys.pvr.display.type=120.000000
```

- 下拉菜单在头显中正常显示，点击后弹窗自动关闭，行文本随选择更新。

### 但 120 Hz 并没有真正生效

必须说清楚：上面这些都不等于面板在以 120 Hz 扫描。内核里 PICO 自己的日志给出了唯一可信的答案：

```
$ dmesg | grep -oE "entered rate:[0-9]+" | sort | uniq -c
    102 entered rate:72
```

`entered rate:120` 出现 **0 次**。开机后除了 `t=6.5 s` 那一瞬间，`dsi_display_set_mode` 报告的一直是 `fps=72`。

SurfaceFlinger 的 `VSYNC period: 8333333 ns` 是按那个模式登记的时序算出来的，而该模式的 vtotal 约为 1669——比 vactive 2160 还小，本身就是无效时序。换句话说，**Android 侧的 120 Hz 是一个被登记下来的假模式**，`refresh-rate: 120.000005 fps` 同样只是它的算术结果。

同理，PICO 合成器那行日志也不能当证据，它只是回读属性：

```
PxrCompositor: setRefreshRate:120.000000, current rate: 120.000000
```

## 5. 已知限制

**候选 DTBO 已全部回滚，当前使用原始 DTBO。**原始 DTBO 的列表是 `<90 72>`，`max-refresh-rate = 90`，两档都是真实有效时序；所有 120 Hz 候选都已通过有线 ADB 回滚，不建议继续在设备上盲写。

**90 Hz 是这块面板的原生档位。**面板名就叫 `sharp ls026b3sa 90hz video mode dsi panel`，`panel-framerate = 90`，DFPS 基准也是 90。它不需要时序改动。魔数 `3` 可以让 SurfaceFlinger 接受 90 Hz 配置，但实测 PICO 的系统服务随后会重新投票回 72 Hz，因此 72↔90 的稳定免重启切换尚未完成。

**120 Hz 完整时序候选已经写过并测试失败。**按 2.2 的推算，120 Hz 要求：

```
vtotal ≥ 2160 + 4 + 4 + 1 = 2169
压缩后 htotal 827
像素时钟 ≥ 827 × 2169 × 120 ≈ 215 MHz（当前 165.6 MHz，需 +30%）
DSI 位时钟   ≈ 1291 MHz（当前 993.6 MHz）
```

SM8250 的 D-PHY 有这个余量，所以并非不可能。有利的线索是面板节点里本来就带着 120 Hz 的 TCON 命令，且与 72/90 明显不同：

```
qcom,mdss-dsi-post-72-nt57900-on-command  = ... b9 13 5f
qcom,mdss-dsi-post-90-nt57900-on-command  = ... b9 13 5f      # 与 72 完全相同
qcom,mdss-dsi-post-120-nt57900-on-command = ... b9 10 2c 01 cb # 明显不同
```

说明 PICO/Sharp 曾准备过一段 120 Hz TCON 补充命令，但实际测试证明它不足以让 LS026B3SA 稳定运行 120 Hz。完整候选已经补过 timing、panel-clockrate 和 PHY，仍然黑屏花屏；继续写入前需要新的、经过验证的面板级配置。

**不要用日志或 dumpsys 判断成功。**唯一可信的判据是内核的 `dsi_bridge_enable entered rate`：

```bash
adb shell su -c "dmesg | grep -oE 'entered rate:[0-9]+' | sort | uniq -c"
```

**重启后需要重新应用。**SurfaceFlinger 每次启动都回到默认配置，`DisplayModeDirector` 的空集合问题依然存在。模块把选择记在 `Settings.Global`，每次 PICO Settings 启动时比对并补上；要完全无感需要把 hook 扩展到 `system_server`，还没做。

## 5.1 当前设备状态与结论

设备当前已恢复原厂活动 DTBO，回读 SHA-256 为 `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac`；`dtbobak` 同样保持原厂。原厂 Sharp LS026B3SA 节点重新公开真实的 90/72 Hz 模式。

继续对比 DTBO 后确认，Sharp LS026B3SA 节点只有一个 `timing@0`，没有独立的 120 Hz `timing@1`，也没有 `qcom,mdss-dsi-panel-clockrate`。同一节点里虽然存在 `post-120-nt57900-on-command`，但它只是按刷新率命名的 53 字节补充命令；它不能替代完整的 120 Hz timing、PHY、时钟和 TCON 初始化配置。

同一份 DTBO 中的 `sharp_493_120_new_video` 是另一块 960×3664 面板，带独立 GPIO/PWM、不同 DSC 拓扑和完整 120 Hz timing，不能直接复制到 4320×2160 的 LS026B3SA。后续若继续 120 Hz，必须针对 LS026B3SA 单独构造完整的 120 Hz timing 和 TCON 初始化序列；目前没有可靠的厂商参考，继续写分区只是在盲试。

## 5.2 失败分析

### 早期实验（DTBO 层面）

120 Hz 候选的共同结果：内核可进入 `fps=120`，但屏幕黑屏或底部花屏。最终抓到的错误是：

```text
DSI_0: LLENGTH = 3400
```

候选已全部回滚，当前活动 `dtbo` 与 `dtbobak` 都是原厂 SHA-256 `307e7021…`。原厂启动日志恢复为真实的 90/72 Hz。

### 寄存器级验证（本轮新增）

三个变体基于设备真实 5.13.7 原厂 dtbo 生成，逐一刷入重启：

| 变体 | vfp | PHY 处理 | bitclk | 结果 |
| --- | --- | --- | --- | --- |
| v2a | 14 | NOP→内核 v4.0 重算 | 1299 MHz | `entered rate:120`，黑屏+底部花屏 |
| v2b | 14 | 保留原厂 993 MHz 表 | 1299 MHz | `entered rate:120`，黑屏+底部花屏 |
| vfp57 | 57（不变） | 保留原厂 | 1325 MHz | `entered rate:120`，黑屏+底部花屏 |

通过 `/sys/kernel/debug/regmap/ae94900.qcom,mdss_dsi_pll/registers` 直接读取 DSI PLL 硬件寄存器，在 90 Hz（原厂）和 120 Hz（v2a）下各 dump 292 个寄存器并 diff：

```
只有 8 个字节变化，全部是校准/SSC 参数：
  0x1b8: 9b→9c, 0x1bc: 7a→e2, 0x1c0: 85→84, 0x1c4: ba→52
  0x1c8: 05→06, 0x1f4: 13→2b, 0x218: 9b→9c, 0x298: df→dc

主反馈分频器（应含 993→1299 MHz 的分频比变化）纹丝不动。
```

DSI 控制器寄存器（120 Hz 下）：

```
DSI_VIDEO_MODE_TOTAL = 0x08b0033a  → htotal=827, vtotal=2225 (vfp=57，不是 14)
DSI_CLK_STATUS       = 0x008047c3  → bit31=0，PLL 未锁定
DSI_DLN0_PHY_ERR     = 0x00088888  → 四条数据 lane 全部报错
```

kprobe 验证：

```bash
# 钩住 dsi_display_set_mode（确认被调用）
echo "p:dsi_probe dsi_display_set_mode" > /sys/kernel/debug/tracing/kprobe_events
echo 1 > /sys/kernel/debug/tracing/events/kprobes/dsi_probe/enable
# → dmesg 出现 entered rate:120，probe 被触发

# 钩住 dsi_clk_set_pixel_clk_rate（确认从未被调用）
echo "p:clk_probe dsi_clk_set_pixel_clk_rate" > /sys/kernel/debug/tracing/kprobe_events
echo 1 > /sys/kernel/debug/tracing/events/kprobes/clk_probe/enable
# → 0 次触发
```

### 结论

**PICO 的显示驱动接受了 120 Hz 模式（`entered rate:120`），更新了 DRM 状态机，但从未把新的时钟和时序写入硬件。** PLL 仍在 993 MHz，vtotal 仍是 2225，面板收到的信号和 90 Hz 一模一样。NT57900 桥在这个矛盾状态下无法出图，表现为黑屏+底部花屏。

无论 DTBO 怎么改——timing、clockrate、PHY、TCON——只要驱动不调用 `dsi_clk_set_pixel_clk_rate`，120 Hz 就永远不会发生。这超出了 DTBO 能做到的范围。内核模块路径（dsi120）正在尝试从驱动外部补上这一步，详见 `pico4-display-analysis/dsi120/README.md`。

### 改驱动的可行路径

内核配置确认：`CONFIG_KPROBES=y`、`CONFIG_MODULES=y`，但 `CONFIG_MODULE_SIG_FORCE=y`（模块必须签名）和 `CONFIG_DYNAMIC_DEBUG=n`（不能动态开调试日志）。

| 路径 | 可行性 | 障碍 |
| --- | --- | --- |
| 内核模块 + kprobe 观察 DSI 模式与时钟 setter | **诊断版已实现** | `sig_enforce` 已绕过；三探针加一个 handle 返回探针可注册并记录参数；时钟调用保持禁用，等待 Phoenix BSP handle 与切换序列确认 |
| 静态二进制补丁 boot.img 里的内核，修改 `dsi_display_set_mode` 指令 | 理论可行 | kallsyms 解码已完成；`hexpatch_boot.py` 存在但为分析用脚本，当前优先走内核模块路径 |
| 改 DTBO | **已证明无效** | 驱动不读这些值，三个变体覆盖 vfp×PHY 两维度结果一致 |
| 等 PICO 推送支持 120 Hz 的固件更新 | 最省事 | 不可控 |

设备已回滚原厂，`entered rate:72/90` 正常。所有候选镜像保留在 `pico4-display-analysis/` 仅供复现，标注了不建议再刷。完整分析详见 `pico4-display-analysis/FINAL_120HZ_ANALYSIS.md`、`LS026B3SA_120HZ_FULL_CONFIG.md` 和 `pico4-display-analysis/dsi120/README.md`。

## 6. 构建

```bash
cd pico-refresh-selector
./gradlew :app:assembleDebug
# 产物: app/build/outputs/apk/debug/app-debug.apk
```

环境：`compileSdk 35`、`minSdk 29`、`targetSdk 29`，依赖 `compileOnly de.robv.android.xposed:api:82`。

## 7. 安装

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
# 在 Vector / LSPosed 中启用模块，作用域只勾选 com.picovr.settings
adb shell su -c "am force-stop com.picovr.settings"
```

可选开关，都存在 `Settings.Global` 里：

```bash
# 运行时即时切换，默认开启；设为 0 则退回"改配置 + 重启"的方式
adb shell settings put global pico_refresh_selector_live_switch 1

# live 切换失败时是否沿用 PICO 原生的自动重启，默认关闭
adb shell settings put global pico_refresh_selector_auto_restart 0
```

确认 Hook 已加载：

```bash
adb shell su -c "/data/adb/modules/zygisk_vector/cli log cat" | grep PicoRefreshSelector
```

## 8. 验证命令

```bash
# 厂商状态
adb shell getprop persist.pvr.display.type      # jdi49372 / jdi49390 / jdi493120
adb shell getprop sys.pvr.display.type          # 运行时生效值

# DRM 公开的模式
adb shell su -c "cat /sys/class/drm/card0-DSI-1/modes"

# Android 侧模式与当前 modeId
adb shell dumpsys display | grep -m1 "内置屏幕"

# 唯一可信的实际刷新率判据
adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
#   13888888 ns = 72 Hz
#   11111111 ns = 90 Hz
#    8333333 ns = 120 Hz

# 模块记录的选择，重启后据此自动恢复
adb shell settings get global pico_refresh_selector_choice

# 内核显示日志
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. 回滚

**软件层**：在 Vector/LSPosed 中禁用 `com.picoxr.refreshselector` 或移除其作用域，PICO Settings 立即恢复原生二态开关。不涉及系统 APK、boot、vbmeta、AVB。

**DTBO 层**：把 `dtbo-current.img` 写回活动 `dtbo` 分区。

EDL 注意事项：

- 这台设备的 **fastboot 禁用了 `flash` 命令**——能进 fastboot 但刷不了分区，所以离线刷写只能走 EDL(9008)。
- EDL(9008) 操作**必须使用物理 USB 连接**，无线 ADB 阶段不要尝试。
- 驱动需要切换为 WinUSB，Firehose 通过 LUN4 访问 `dtbo`。
- 只写活动 `dtbo`，保持 `dtbobak` 原样，作为二次保险。
- `reset` 时出现 `USBError(32, 'Pipe error')` 属正常现象，设备约 20 秒后恢复 ADB。

## 10. 仓库结构

```
pico4-display-analysis/
  README.md                      固件校验值、导出方法、候选镜像生成步骤
  build_candidate_dtbo.py        结构化解析并重组 DTBO，只改目标面板节点
  build_120hz_base_dtbo.py       把默认时序挪到 120 Hz
  build_120hz_v2_dtbo.py         修正版 120 Hz 候选（vfp=14 + 可选 NOP PHY）
  extract_panel_config.py        离线解析任意 DTBO，导出面板完整配置
  verify_refresh_rate.sh         从 DSI 寄存器算出真实刷新率
  dtbo-120hz-candidate-audit.txt 候选镜像审计记录
  edl-readonly-lun4-gpt-dtbo.xml Firehose 只读回读配置（LUN4）
  FINAL_120HZ_ANALYSIS.md        120 Hz 可行性最终报告
  LS026B3SA_120HZ_FULL_CONFIG.md 完整配置推导与实机验证文档
  pll_90hz_baseline.txt           90 Hz 原厂 PLL 寄存器基线（292 个）
  pll_120hz.txt                   120 Hz 下 PLL 寄存器（与基线 diff 证实时钟未切换）
  dsi120/
    dsi120.c                     内核模块：kprobe + 强制 DSI 时钟切换
    build.sh                     编译脚本（WSL，需设备 .config 同步）
    patch_sig_enforce.py         离线 boot 镜像签名绕过补丁
    load_module.c                finit_module() 包装器（Magisk shell 用）
    hexpatch_boot.py             早期分支补丁脚本（分析用，不要刷入）
    setup_buildroot.sh           早期构建环境准备（已被设备配置同步取代）
    README.md                    模块构建/加载/参数文档
  FLASH_INSTRUCTIONS.md          boot 镜像补丁与刷写指南
pico-refresh-selector/
  app/src/main/java/com/picoxr/refreshselector/RefreshRateHook.java
  app/src/main/assets/xposed_init
  app/src/main/res/values/arrays.xml     作用域仅 com.picovr.settings
docs/
  settings-current.jpg           改造前的实验室页面
```

> 仓库**不包含**任何 PICO 固件镜像（`dtbo`、`vbmeta`、`boot`、系统 APK）。它们属于专有固件，请自行从本机导出，并用 `pico4-display-analysis/README.md` 中的校验值核对。


## 11. 路线图

- [x] 定位面板节点与 DFPS 属性，构建候选 DTBO
- [x] 验证 EDL 回读与回滚路径
- [x] 让 120 Hz 被 DRM 与 Android 枚举
- [x] 复用 PICO 原生下拉菜单实现 72/90 两档选择
- [x] 定位原生流程依赖重启的事实
- [x] 通过配置服务写入 `sdk_refreshRate`，让厂商状态跨重启保持
- [x] 逆向出 SurfaceFlinger 私有校验（魔数 `3`），拿到运行时改配置的能力
- [x] 用内核日志证伪「120 Hz 已生效」，定位 DFPS 只能降频的根本限制
- [x] 刷回原始 DTBO，确认真实 72/90 模式恢复
- [x] 提取 LS026B3SA 完整配置（timing/PHY/DSC/TCON），推导 120 Hz 自洽参数
- [x] 实机验证三个变体 DTBO，全部黑屏花屏
- [x] 通过 regmap 直读 PLL 寄存器 + kprobe，证实驱动从不调用时钟切换函数
- [x] **DTBO 结论：120 Hz 在 DTBO 层面不可行，根因是驱动层而非配置层**
- [x] 绕过内核模块签名强制（`sig_enforce` 数据变量补丁）
- [x] 构建并加载 dsi120 kprobe 内核模块，注册 `dsi_display_set_mode` 和 `dsi_clk_set_pixel_clk_rate` 探针
- [ ] 触发 72↔90 Hz 切换，捕获 DSI clock handle
- [ ] 在 workqueue 中调用 `dsi_clk_set_pixel_clk_rate()`，验证 120 Hz 时钟切换
- [ ] 在原始 DTBO 上完成 72↔90 运行时即时切换的稳定性验证
- [ ] 扩展到 `system_server` 修正 `DisplayModeDirector`，做到开机自动生效
- [ ] 提供 Magisk 模块形式的一键安装

## 12. 致谢

- [CreoleVR/quest-pro-display-overclock](https://github.com/CreoleVR/quest-pro-display-overclock) —— Qualcomm DSI DFPS 内存补丁思路的来源。注意它依赖 Quest Pro 专用内核模块与 Oculus 私有属性，**不能**直接刷入 PICO 4。
- [hhhbwc/pico4-power-mode](https://github.com/hhhbwc/pico4-power-mode) —— PICO Settings 下拉菜单交互的参考。

---

# English

## 0. Disclaimer

This project flashes the `dtbo` partition and injects code into a system app. That is a high-risk modification.

- Back up `dtbo`, `dtbobak` and `vbmeta` first, and confirm your EDL (9008) write-back path works.
- The project does **not** disable AVB and does **not** modify `vbmeta`, `boot`, `dtbobak`, `GPT`, `super`, `ABL` or any other partition.
- Roll back the original DTBO immediately on a black screen, corrupted image, boot loop, DSI/DSC/PLL/underrun errors or abnormal heating.
- Use at your own risk. The author is not responsible for bricked devices, voided warranties or hardware damage.

## 1. Target device

Only this firmware has been verified.

| Item | Value |
| --- | --- |
| Model | PICO 4 (A8110) |
| Codename | Phoenix |
| OS | PICO OS 5.13.7 / Android 10 |
| Internal version | `c000_rf01_bv1.0.1_sv5.13.7_202510300008_phoenix_b9650_user` |
| SoC | Snapdragon 865 (Kona) |
| Panel | Sharp LS026B3SA (`ro.pvr.hmd.type=SHARP5K`) |
| Resolution | 4320 × 2160 |
| Stock refresh rates | 72 Hz / 90 Hz |
| Prerequisites | Rooted (Magisk/KSU) + Zygisk Vector or LSPosed |

## 2. How it works

### 2.1 DTBO and DFPS

Panel timings live in a panel node inside DTBO. Target node and properties:

```
node: qcom,mdss_dsi_sharp_ls026b3sa_90_video
prop: qcom,dsi-supported-dfps-list   <90 72>  ->  <120 90 72>
prop: qcom,mdss-dsi-max-refresh-rate <90>     ->  <120>
```

DTBO layout:

```
Android DT table magic : 0xD7B7AB1E
partition size         : 24 MiB (the candidate image must keep the exact size)
active entry           : dtbo_idx = 5
```

Image checksums:

| File | SHA-256 |
| --- | --- |
| `dtbo-current.img` (stock) | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| `dtbo-120hz-candidate.img` | `df4e7b25d437464291ebbef0230e28ad3b6eaf6303866dc6ace7e1a52fa1bdf4` |
| `vbmeta-current.img` (baseline, untouched) | `2bce6e1cccf657c0237b3e8a35f0cfa52b663cec1d922b27a561c5ea97c4b4d3` |

After flashing the candidate DTBO, DRM exposes:

```
4320x2160x120x331212vid
4320x2160x72x331212vid
```

Android sees the same:

```
supportedModes [{id=1, 4320x2160, fps=120.00001},
                {id=2, 4320x2160, fps=72.00001}]
```

### 2.2 DFPS can only lower the rate

This panel uses DFPS (dynamic frame rate), and the decisive property is:

```
qcom,mdss-dsi-pan-fps-update = dfps_immediate_porch_mode_vfp
```

That means **the pixel clock stays fixed and only the vertical front porch (VFP) is adjusted**. The base timing is the default timing in the DT:

```
2160x2160 per DSI (dual DSI composes 4320x2160)
h: hfp 54, hbp 33, hpw 20  -> htotal 2267 (827 compressed)
v: vbp 4, vfp 57, vpw 4    -> vtotal 2225
qcom,mdss-dsi-panel-framerate = 90
```

The VFP each rate would need follows directly:

```
vtotal(fps) = vtotal_base × 90 / fps
vfp(fps)    = 57 + (vtotal(fps) - 2225)

72  Hz -> vtotal 2781 -> vfp  +613   fine
90  Hz -> vtotal 2225 -> vfp    57   the base
120 Hz -> vtotal 1669 -> vfp  -499   impossible
```

That `-499` is exactly the kernel error, and it belongs to **120 Hz**, not 90 Hz:

```
Invalid new_hfp calcluated-499
```

A vtotal of 1669 is smaller than vactive 2160, so 2160 lines cannot physically be scanned out. **Raising the rate requires raising the pixel clock, and immediate-porch DFPS never touches the clock.**

The model cross-checks against PICO's own panel nodes. `sharp_493_120_new_video` is based on 120 Hz (vtotal 3686, htotal 1072); applying the same formula:

| Target | Derived vfp | Dedicated PICO node |
| --- | --- | --- |
| 90 Hz | 1242 | `sharp_493_90_new_video` = 1231 |
| 72 Hz | 2471 | `sharp_493_72_new_video` = 2459 |

Both within 1%, which confirms the model: **the base timing has to be the highest rate**, and the lower rates are produced by stretching VFP. Our panel's base is 90 Hz, which is why the stock firmware only offers 72/90.

### 2.3 PICO's vendor refresh-rate chain

The rate is not switched through standard Android APIs but through PICO's private chain:

```
persist.pvr.display.type   jdi49372 / jdi49390 / jdi493120     persisted request
sys.pvr.display.type       72.000000 / 90.000000 / 120.000000  effective runtime value
```

`pxrhmdservice` only reads `sys.pvr.display.type` and reports it to apps:

```
Call <getRefreshRate> - sys.pvr.display.type=[72.000000] done.
Call <getRefreshRate> - refreshRate=[72.000000 72.000000 72.000000].
```

Implementation inside PICO Settings (`com.picovr.settings`):

```
PicolabFragment.onCheckedChanged(...)         refresh switch id = 0x7f0902c6
  -> b1(boolean)                              shows a confirmation dialog
    -> PicolabFragment$6.onClick(View)         user confirms
      -> N(...) -> O(boolean)
        -> Utils.v1(boolean)                  writes vendor state
      -> K0()                                 restartDevice, reboots 1200 ms later
```

What `Utils.v1(boolean)` actually does:

```java
// s1() == Constant.i() && Constant.c()
// Constant.i() is true only for ro.pvr.product.name == "FalconCV3"
// PICO 4 is Phoenix, so s1() == false and this line picks jdi49390
String type = s1() ? "jdi493120" : "jdi49390";
if (!enable) type = "jdi49372";

CommonUtils.setSystemProperties("persist.pvr.display.type", type);
ConfigServiceManager.i("sdk_refreshRate", s1() ? "120" : "90");
ConfigServiceManager.i("sdk_Recommand_refreshRate", ...);
Utils.P0("persist.pvr.display.type", rate);   // Settings.Global.putInt
Utils.B0("com.pvr.display.type", rate);       // PxrNotificationService.sendPxrMessage
Utils.x1(enable);                             // updates recording fps
```

Two important conclusions:

1. `Utils.s1()` was measured to return **`false`** on this unit (`ro.pvr.product.name` is `Phoenix`, not `FalconCV3`), so the stock switch only toggles between 72 and **90**, and `Utils.v1(true)` writes `jdi49390`. `v1(true)` therefore **cannot** be used to request 120 — it silently writes 90. Earlier builds wrote all three rates explicitly and hooked `s1()` to `true`, but later testing showed that every 120 Hz candidate produced a black screen or corruption. The stock DTBO now exposes only genuine 72/90 configs, and 120 is experimental and disabled.
2. **The stock flow itself reboots the device.** `K0()` is `restartDevice`; without a reboot nothing takes effect.


### 2.4 The native dropdown

The "power management" row uses PICO's own widget and popup. This project reuses the exact same implementation, so look and feel match the system UI.

```
widget    com.picovr.customviews.DropdownOptionView      (power row id = 0x7f0902d0)
entry     PicolabFragment.T0(View)
popup     PopupMenuHelper.c(Activity, View, BaseAdapter,
                            SimpleOnItemClickListener, int checkedPosition)
adapter   com.bytedance.osui.popupmenu.OSUIMenuAdapter
item      new MenuItemData(MenuItemType.TYPE_TITLE_CHECK).l("120 Hz")
click     PicolabFragment$3.onItemClick(AdapterView, View, int, long)
```

The check mark comes from the `checkedPosition` argument; it is not stored inside `MenuItemData`.

### 2.5 SurfaceFlinger's private check

Even with the DTBO exposing 120 Hz as a valid DRM and Android mode, the Android framework keeps pinning the panel to 72 Hz:

```
E DisplayModeDirector: Asked about unknown display, returning empty allowed set! (id=0)
F DEBUG: #08 libsurfaceflinger.so (SurfaceFlinger::setAllowedDisplayConfigs(...))
```

`DisplayModeDirector` does not know display 0 and returns an empty allowed set. Handing that empty set to SurfaceFlinger reads past the end of the vector and crashes it twice during boot, after which it falls back to the default config.

Every standard entry point is silently refused:

```
setAllowedDisplayConfigs({0})   -> returns success, state unchanged
setActiveConfig(0)              -> returns success, state unchanged
service call SurfaceFlinger 1035 i32 0 -> BAD_VALUE (-22)
```

Disassembling `/system/lib64/libsurfaceflinger.so` shows why: PICO added a private check to that function.

```asm
0xfad78  ldr  w10, [x9]        ; walk allowedConfigs
0xfad7c  cmp  w10, #3          ; is any element equal to 3?
0xfad80  b.eq #0xfadac         ; yes -> has pico parameter, proceed
0xfadb8  b.eq #0xfae5c         ; no  -> no pico parameter
0xfae6c  mov  w19, #-0x16      ;        return -22 (BAD_VALUE)
0xfadd4  sub  x8, x8, #4       ; on success the marker is popped off the end
```

The array has to carry the marker `3`, and because it is popped from the back the marker must come last:

```java
SurfaceControl.setAllowedDisplayConfigs(token, new int[] {configIndex, 3});
```

The log line `no pico parameter so allow to change display config through surfaceflinger` is worded backwards: that branch is the one that refuses.

### 2.6 120 Hz base-timing candidate (tested and rolled back)

Since DFPS can only lower the rate, the only way forward is to make the default timing itself 120 Hz and let 90 and 72 be derived from it. This candidate was flashed and tested, produced a black screen with a corrupted band at the bottom, and was then rolled back to the stock DTBO. `build_120hz_base_dtbo.py` is retained to reproduce the experiment and does not indicate a usable candidate; only 20 bytes differ in the whole partition:

```
qcom,mdss-dsi-panel-framerate    90 -> 120
qcom,mdss-dsi-v-front-porch      57 -> 14
qcom,mdss-dsi-panel-phy-timings  overwritten with FDT_NOP words (legal FDT, parsers skip them)
```

The PHY timings are dropped rather than recomputed by hand. The 14 bytes in the DT belong to the old 993 MHz bit clock and cannot be right at the new one; this SoC uses DSI PHY v4.0, for which 14 bytes is exactly the timing table size. With the property gone the driver computes them, and `/proc/kallsyms` confirms this kernel carries both the calculator and the matching v4.0 ops:

```
dsi_phy_hw_calculate_timing_params
dsi_phy_hw_v4_0_calc_clk_zero / calc_clk_trail_rec_min / calc_hs_zero / calc_hs_trail
```

The arithmetic is not guesswork: the compressed horizontal total comes from the live DSI controller, where `DSI_VIDEO_MODE_TOTAL = 0x0adc033a`, so htotal−1 = 0x033a and vtotal−1 = 0x0adc.

| Rate | vtotal | vfp | Source |
| --- | --- | --- | --- |
| 120 Hz | 2182 | 14 | base |
| 90 Hz | 2909 | 741 | derived by DFPS |
| 72 Hz | 3636 | 1468 | derived by DFPS |

All three land on positive front porches. The pixel clock becomes 216,541,680 Hz (currently 165,591,864, +30.8%) and the bit clock about 1.30 GHz (currently 993.5 MHz), inside the SM8250 D-PHY range.

Safety check: this node's `__local_fixups__` only references the phandle properties `io-channels` and `qcom,panel-supply-entries`, neither of which is touched, so overwriting the PHY timings cannot break the overlay's phandle fixups.

**Tested and rolled back.** This candidate was written to the active `dtbo` and tested after reboot; it produced a black screen with a corrupted band at the bottom. It was then rolled back to the stock DTBO through wired ADB. The failure included `DSI_0: LLENGTH = 3400`, indicating a mismatch between DSI transfer length and the LS026B3SA panel configuration.

Have a USB cable available before flashing. Note that although this device reports `ro.boot.flash.locked=0`, **its fastboot has the `flash` command disabled** — fastboot can be entered but cannot write a partition, so the only usable offline path is **EDL (9008)**. Roll back with `dd` while ADB is alive, and `dtbobak` stays untouched throughout as a second safety net. After flashing, judge the real rate with `pico4-display-analysis/verify_refresh_rate.sh` rather than dumpsys.

### 2.7 Public panel sources and confidence

Public sources confirm the basic hardware information for the `LS026B3SA` family, but no Sharp datasheet, DSC PPS, PHY timing table or TCON initialization table was found.

- [Panelook LS026B3SA01X](https://www.panelook.com/LS026B3SA01X_Sharp_2.6_LCM_overview_64156.html): search results identify Sharp, 2.6-inch, 2160x2160, MIPI, 2 channels, 4 data lanes and list 120 Hz.
- [Panelook LS026B3SA01Y](https://www.panelook.com/LS026B3SA01Y_Sharp_2.6_LCM_overview_64157.html): the Y variant is similarly summarized as 2160x2160, MIPI, 2 channels, 4 data lanes and 120 Hz.
- [MyDoPoint LS026B3SA01X](https://www.mydopoint.com/lcd_LS026B3SA01X.html): lists Sharp, 2.6-inch, 2160x2160, 520 cd/m2, 650:1, MIPI and WLED.
- [JianXiang LS026B3SA family](https://www.jxg.tw/en/product_1569517.html): lists LS026B3SA01/A/B/X as a Sharp VR panel family for PICO, Meta/Oculus and similar devices.
- [Official PICO 4 specifications](https://www.picoxr.com/global/products/pico4/specs): confirms two 2.56-inch Fast-LCD panels, 2160x2160 per eye and official 72/90 Hz modes.
- [Official PICO 4 product page](https://www.picoxr.com/global/products/pico4): also lists 90 Hz as the maximum refresh rate.
- [52audio PICO 4 teardown](https://www.52audio.com/archives/150653.html): confirms two 2.56-inch, 4320x2160, 90 Hz Fast-LCD panels, but not the panel model or TCON.
- [NT57900 reseller page](https://www.displayamoled.com/sale-53602352-2-56-inch-vr-lcd-display-2160x2160-45-pins-mipi-interface-driving-ic-nt57900.html): describes ESHX026C4T-NH0, not an identified LS026B3SA01X, so it only proves that NT57900 appears in a similar VR panel and does not prove the TCON configuration in this device.

The Panelook pages are protected by a slider; those parameters come from search snippets and have lower confidence than a primary datasheet. Device DTBO and kernel evidence takes priority: this unit's stock node is explicitly `sharp ls026b3sa 90hz video mode dsi panel`, with real 72/90 modes.

## 3. What the module does

Package `com.picoxr.refreshselector`, scoped to `com.picovr.settings` **only**.

| Hook | Purpose |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | Removes the stock refresh `SwitchView` and inserts a `DropdownOptionView` in the same row, reusing the same id |
| `PicolabFragment.onCheckedChanged(...)` | Blocks the old switch so two-state semantics cannot fight the rate selector |
| `PopupMenuHelper.c(...)` | Recognises the refresh popup by anchor id, replaces the items with the real `72 Hz / 90 Hz` configs and rewrites `checkedPosition` |
| `PicolabFragment$3.onItemClick(...)` | Replaces power-mode handling with real display-config rate handling; reboot is only a fallback when live switching fails |
| `Utils.s1()` | Forced to `true`, cancelling the model gate where `Constant.i()` only accepts `FalconCV3` |
| `SurfaceControl.setAllowedDisplayConfigs` | Called with PICO's marker `3` so the rate applies live, with no reboot |
| `SettingApplication.onCreate(...)` | Read-only probe that logs `sdk_refreshRate`, `sdk_Recommand_refreshRate` and both properties |

Request paths are written explicitly instead of relying on the `s1()` decision inside `Utils.v1()`; the stock DTBO currently exposes only genuine 72/90 configs:

```
72  Hz  -> persist.pvr.display.type = jdi49372  + sdk_refreshRate = 72
90  Hz  -> persist.pvr.display.type = jdi49390  + sdk_refreshRate = 90
120 Hz  -> only used by the failed DTBO experiment; removed from the current menu
shared     sdk_Recommand_refreshRate mirrors the same value
           Utils.P0 / Utils.B0 / Utils.w1(24 for 72 Hz, 30 otherwise)
           setAllowedDisplayConfigs(token, {configIndex, 3})  <- applies at once
```

The menu only lists display configs that really exist. With the stock DTBO it offers 72 and 90. The 120 entry is intentionally removed because every tested 120 Hz DTBO produced a black screen or corruption.

The module never patches the PICO Settings APK, never touches resources and never writes a partition. Disabling the module or removing its scope fully restores the stock UI.

## 4. Verified results

- The device boots normally with the candidate DTBO, ADB is stable and no display artefacts appear; EDL read-back of `dtbo` and `dtbobak` is **byte-for-byte identical** to the baseline, so rollback works.
- **PICO's private check in SurfaceFlinger (the marker `3`) was reversed successfully**, and this is the one runtime breakthrough that is fully verified:

```
before  activeConfig=1  allowedConfigs=[1]
setAllowedDisplayConfigs({0, 3})  -> accepted
after   activeConfig=1  allowedConfigs=[0]      # without the marker this never changes
```

- The vendor state survives a reboot and the configuration service really holds 120:

```
config sdk_refreshRate=120 / sdk_Recommand_refreshRate=120
prop persist.pvr.display.type=jdi493120
prop sys.pvr.display.type=120.000000
```

- The dropdown renders in the headset, the popup dismisses on selection and the row label follows the choice.

### But 120 Hz is not actually in effect

None of the above means the panel is scanning at 120 Hz. PICO's own kernel log gives the only trustworthy answer:

```
$ dmesg | grep -oE "entered rate:[0-9]+" | sort | uniq -c
    102 entered rate:72
```

`entered rate:120` appears **zero** times. Apart from one moment at `t=6.5 s` during boot, every `dsi_display_set_mode` reports `fps=72`.

SurfaceFlinger's `VSYNC period: 8333333 ns` is computed from the timing registered for that mode, and that mode's vtotal is about 1669 — smaller than vactive 2160, so the timing is invalid on its face. In other words **the 120 Hz on the Android side is a bogus mode that got registered**, and `refresh-rate: 120.000005 fps` is just arithmetic on it.

PICO's compositor log is no evidence either; it only echoes a property:

```
PxrCompositor: setRefreshRate:120.000000, current rate: 120.000000
```

## 5. Known limitations

**All candidate DTBOs have been rolled back; the stock DTBO is active.** The stock DTBO lists `<90 72>` with `max-refresh-rate = 90`, and both are genuine valid timings. Every 120 Hz candidate was rolled back through wired ADB; further blind partition writes are not recommended.

**90 Hz is this panel's native rate.** The panel is literally named `sharp ls026b3sa 90hz video mode dsi panel`, `panel-framerate = 90`, and the DFPS base is 90. It needs no timing work. The marker `3` makes SurfaceFlinger accept the 90 Hz config, but testing shows that a later PICO system-service vote returns it to 72 Hz, so stable reboot-free 72<->90 switching is not complete.

**A complete 120 Hz timing candidate was authored and tested, but failed.** Following the arithmetic in 2.2, 120 Hz requires:

```
vtotal >= 2160 + 4 + 4 + 1 = 2169
compressed htotal 827
pixel clock >= 827 x 2169 x 120 ~= 215 MHz (currently 165.6 MHz, +30%)
DSI bit clock ~= 1291 MHz (currently 993.6 MHz)
```

The SM8250 D-PHY has that headroom, so it is not impossible. An encouraging sign is that the panel node already carries a 120 Hz TCON command, clearly different from 72/90:

```
qcom,mdss-dsi-post-72-nt57900-on-command  = ... b9 13 5f
qcom,mdss-dsi-post-90-nt57900-on-command  = ... b9 13 5f      # identical to 72
qcom,mdss-dsi-post-120-nt57900-on-command = ... b9 10 2c 01 cb # clearly different
```

PICO/Sharp did prepare a 120 Hz supplemental TCON command, but testing showed that it is not sufficient for stable 120 Hz operation on LS026B3SA. A complete candidate with timing, panel-clockrate and PHY changes was tested and still produced a black screen and corruption; further writes require a new panel-specific, validated configuration.

**Do not judge success from logs or dumpsys.** The only trustworthy measure is the kernel's `dsi_bridge_enable entered rate`:

```bash
adb shell su -c "dmesg | grep -oE 'entered rate:[0-9]+' | sort | uniq -c"
```

**The choice has to be re-applied after a reboot.** SurfaceFlinger returns to its default config on every start and the empty-allowed-set problem in `DisplayModeDirector` remains. The module stores the choice in `Settings.Global` and reconciles it whenever PICO Settings starts; making it fully transparent needs the hook extended into `system_server`, which is not done.

## 5.2 Failure analysis

### Early experiments (DTBO level)

All 120 Hz candidates had the same outcome: the kernel entered `fps=120`, but the panel was black or showed a corrupted band at the bottom. The final low-level error captured was:

```text
DSI_0: LLENGTH = 3400
```

Every candidate has been rolled back. Both active `dtbo` and `dtbobak` are stock, with SHA-256 `307e7021…`. Stock boot logs again show genuine 90/72 Hz modes.

### Register-level verification (this round)

Three variants built from the device's real 5.13.7 stock dtbo, each flashed and rebooted:

| Variant | vfp | PHY handling | bitclk | Result |
| --- | --- | --- | --- | --- |
| v2a | 14 | NOP → kernel v4.0 recompute | 1299 MHz | `entered rate:120`, black screen + corrupted band |
| v2b | 14 | kept stock 993 MHz table | 1299 MHz | `entered rate:120`, black screen + corrupted band |
| vfp57 | 57 (unchanged) | kept stock | 1325 MHz | `entered rate:120`, black screen + corrupted band |

DSI PLL hardware registers were read directly via `/sys/kernel/debug/regmap/ae94900.qcom,mdss_dsi_pll/registers` — 292 registers dumped at 90 Hz (stock) and 120 Hz (v2a), then diffed:

```
Only 8 bytes changed, all calibration/SSC parameters:
  0x1b8: 9b→9c, 0x1bc: 7a→e2, 0x1c0: 85→84, 0x1c4: ba→52
  0x1c8: 05→06, 0x1f4: 13→2b, 0x218: 9b→9c, 0x298: df→dc

The main feedback divider (should reflect 993→1299 MHz ratio change) did not move at all.
```

DSI controller registers (at 120 Hz):

```
DSI_VIDEO_MODE_TOTAL = 0x08b0033a  → htotal=827, vtotal=2225 (vfp=57, not 14)
DSI_CLK_STATUS       = 0x008047c3  → bit31=0, PLL not locked
DSI_DLN0_PHY_ERR     = 0x00088888  → all four data lanes report PHY errors
```

kprobe verification:

```bash
# Probe dsi_display_set_mode (confirm it is called)
echo "p:dsi_probe dsi_display_set_mode" > /sys/kernel/debug/tracing/kprobe_events
echo 1 > /sys/kernel/debug/tracing/events/kprobes/dsi_probe/enable
# → dmesg shows entered rate:120, probe fires

# Probe dsi_clk_set_pixel_clk_rate (confirm it is NEVER called)
echo "p:clk_probe dsi_clk_set_pixel_clk_rate" > /sys/kernel/debug/tracing/kprobe_events
echo 1 > /sys/kernel/debug/tracing/events/kprobes/clk_probe/enable
# → 0 hits
```

### Conclusion

**PICO's display driver accepted the 120 Hz mode (`entered rate:120`), updated the DRM state machine, but never wrote the new clock and timing to hardware.** The PLL stayed at 993 MHz, vtotal stayed at 2225, and the panel received exactly the same signal as 90 Hz. The NT57900 bridge cannot render in this contradictory state, producing a black screen with a corrupted bottom band.

No matter what the DTBO says — timing, clockrate, PHY, TCON — as long as the driver does not call `dsi_clk_set_pixel_clk_rate`, 120 Hz will never happen. This is beyond what DTBO modification can achieve. The kernel-module path (dsi120) is attempting to close this gap from outside the driver; see `pico4-display-analysis/dsi120/README.md`.

### Paths to modify the driver

Kernel config confirmed: `CONFIG_KPROBES=y`, `CONFIG_MODULES=y`, but `CONFIG_MODULE_SIG_FORCE=y` (modules must be signed) and `CONFIG_DYNAMIC_DEBUG=n`.

| Path | Feasibility | Obstacle |
| --- | --- | --- |
| Kernel module + kprobe hook on `dsi_display_set_mode`, manually call `dsi_clk_set_pixel_clk_rate` | **Implemented** | `sig_enforce` bypassed via `patch_sig_enforce.py`; dsi120 module built and loaded, kprobes registered; clock-switch verification in progress |
| Static binary patch of kernel in boot.img, modify `dsi_display_set_mode` instructions | Theoretically viable | kallsyms decode complete; `hexpatch_boot.py` exists as an analysis-only script; kernel module path is currently preferred |
| Modify DTBO | **Proven ineffective** | Driver ignores these values; three variants covering vfp×PHY dimensions all fail identically |
| Wait for PICO firmware update with 120 Hz support | Easiest | Not user-controllable |

Device has been rolled back to stock, `entered rate:72/90` normal. All candidate images retained in `pico4-display-analysis/` for reproduction only, marked as not recommended to flash. Full analysis in `pico4-display-analysis/FINAL_120HZ_ANALYSIS.md`, `LS026B3SA_120HZ_FULL_CONFIG.md`, and `pico4-display-analysis/dsi120/README.md`.

## 6. Build

```bash
cd pico-refresh-selector
./gradlew :app:assembleDebug
# output: app/build/outputs/apk/debug/app-debug.apk
```

Toolchain: `compileSdk 35`, `minSdk 29`, `targetSdk 29`, `compileOnly de.robv.android.xposed:api:82`.

## 7. Install

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
# enable the module in Vector / LSPosed, scope = com.picovr.settings only
adb shell su -c "am force-stop com.picovr.settings"
```

Optional switches, both stored in `Settings.Global`:

```bash
# live switching, on by default; set to 0 to fall back to "write config + reboot"
adb shell settings put global pico_refresh_selector_live_switch 1

# whether to reuse PICO's automatic reboot when the live switch fails, off by default
adb shell settings put global pico_refresh_selector_auto_restart 0
```

Confirm the hook loaded:

```bash
adb shell su -c "/data/adb/modules/zygisk_vector/cli log cat" | grep PicoRefreshSelector
```

## 8. Verification commands

```bash
# vendor state
adb shell getprop persist.pvr.display.type      # jdi49372 / jdi49390 / jdi493120
adb shell getprop sys.pvr.display.type          # effective runtime value

# modes exposed by DRM
adb shell su -c "cat /sys/class/drm/card0-DSI-1/modes"

# Android modes and current modeId
adb shell dumpsys display | grep -m1 "Built-in Screen"

# the only reliable proof of the real rate
adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
#   13888888 ns = 72 Hz
#   11111111 ns = 90 Hz
#    8333333 ns = 120 Hz

# the stored choice the module restores after a reboot
adb shell settings get global pico_refresh_selector_choice

# kernel display log
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. Rollback

**Software**: disable `com.picoxr.refreshselector` in Vector/LSPosed or remove its scope; PICO Settings returns to the stock two-state switch immediately. Nothing touches system APKs, boot, vbmeta or AVB.

**DTBO**: write `dtbo-current.img` back to the active `dtbo` partition.

EDL notes:

- This device's **fastboot has the `flash` command disabled** — fastboot can be entered but cannot write a partition, so EDL (9008) is the only offline path.
- EDL (9008) work **requires a physical USB connection**; never attempt it over wireless ADB.
- Switch the driver to WinUSB; Firehose reaches `dtbo` through LUN4.
- Write the active `dtbo` only and leave `dtbobak` untouched as a second safety net.
- `USBError(32, 'Pipe error')` on `reset` is expected; ADB returns after roughly 20 seconds.

## 10. Repository layout

```
pico4-display-analysis/
  README.md                      checksums, dump instructions, candidate build steps
  build_candidate_dtbo.py        structured DTBO parse and rebuild, target node only
  build_120hz_base_dtbo.py       moves the default timing to 120 Hz
  build_120hz_v2_dtbo.py         corrected 120 Hz candidate (vfp=14 + optional NOP PHY)
  extract_panel_config.py        offline DTBO parser, exports full panel configuration
  verify_refresh_rate.sh         computes the real rate from DSI registers
  dtbo-120hz-candidate-audit.txt audit record of the candidate image
  edl-readonly-lun4-gpt-dtbo.xml Firehose read-only configuration (LUN4)
  FINAL_120HZ_ANALYSIS.md        final 120 Hz feasibility report
  LS026B3SA_120HZ_FULL_CONFIG.md full configuration derivation and on-device verification
  pll_90hz_baseline.txt           90 Hz stock PLL register baseline (292 registers)
  pll_120hz.txt                   120 Hz PLL registers (diff vs baseline proves clock never switched)
  dsi120/
    dsi120.c                     kernel module: kprobe + forced DSI clock switch
    build.sh                     build script (WSL, requires device .config sync)
    patch_sig_enforce.py         offline boot-image signature bypass patcher
    load_module.c                finit_module() wrapper for Magisk shell
    hexpatch_boot.py             legacy branch-patch script (analysis only, do not flash)
    setup_buildroot.sh           early buildroot preparation (superseded by device config sync)
    README.md                    module build/load/parameter documentation
  FLASH_INSTRUCTIONS.md          boot-image patching and flashing guide
pico-refresh-selector/
  app/src/main/java/com/picoxr/refreshselector/RefreshRateHook.java
  app/src/main/assets/xposed_init
  app/src/main/res/values/arrays.xml     scope: com.picovr.settings only
docs/
  settings-current.jpg           the lab page before modification
```

> The repository ships **no** PICO firmware images (`dtbo`, `vbmeta`, `boot`, system APKs). They are proprietary; dump them from your own unit and verify them against the checksums in `pico4-display-analysis/README.md`.


## 11. Roadmap

- [x] Locate the panel node and DFPS properties, build a candidate DTBO
- [x] Verify EDL read-back and rollback
- [x] Get 120 Hz enumerated by DRM and Android
- [x] Reuse PICO's native dropdown for the real 72/90 choices
- [x] Establish that the stock flow depends on a reboot
- [x] Write `sdk_refreshRate` through the configuration service so the vendor state survives a reboot
- [x] Reverse SurfaceFlinger's private check (marker `3`) and gain runtime config control
- [x] Disprove "120 Hz works" from the kernel log and pin down the DFPS lower-only limit
- [x] Restore the stock DTBO and confirm genuine 72/90 modes
- [x] Extract full LS026B3SA configuration (timing/PHY/DSC/TCON), derive self-consistent 120 Hz parameters
- [x] Flash and test three DTBO variants on-device — all black-screened with a corrupted band
- [x] Read PLL registers via regmap + kprobe, prove the driver never calls the clock-switch function
- [x] **DTBO verdict: 120 Hz is infeasible at the DTBO level — the root cause is in the driver layer, not the configuration**
- [x] Bypass kernel module signature enforcement (`sig_enforce` data variable patch)
- [x] Build and load the dsi120 kprobe kernel module, register probes on `dsi_display_set_mode` and `dsi_clk_set_pixel_clk_rate`
- [ ] Trigger a 72↔90 Hz switch to capture the DSI clock handle
- [ ] Call `dsi_clk_set_pixel_clk_rate()` from the workqueue and verify the 120 Hz clock switch
- [ ] Verify stable live 72<->90 switching on the stock DTBO
- [ ] Extend into `system_server` to fix `DisplayModeDirector` and apply the rate at boot
- [ ] Ship a Magisk module for one-step installation

## 12. Credits

- [CreoleVR/quest-pro-display-overclock](https://github.com/CreoleVR/quest-pro-display-overclock) — source of the Qualcomm DSI DFPS in-memory patching idea. It relies on a Quest Pro specific kernel module and Oculus private properties and **cannot** be flashed on a PICO 4.
- [hhhbwc/pico4-power-mode](https://github.com/hhhbwc/pico4-power-mode) — reference for the PICO Settings dropdown interaction.

---

# Русский

## 0. Отказ от ответственности

Проект прошивает раздел `dtbo` и внедряет код в системное приложение. Это модификация с высоким риском.

- Сначала сделайте резервные копии `dtbo`, `dtbobak` и `vbmeta` и убедитесь, что путь записи через EDL (9008) работает.
- Проект **не отключает** AVB и **не изменяет** `vbmeta`, `boot`, `dtbobak`, `GPT`, `super`, `ABL` и любые другие разделы.
- При чёрном экране, артефактах, цикле перезагрузок, ошибках DSI/DSC/PLL/underrun или аномальном нагреве немедленно верните исходный DTBO.
- Вы действуете на свой риск. Автор не отвечает за «кирпич», потерю гарантии и повреждение оборудования.

## 1. Целевое устройство

Проверено только на этой прошивке.

| Параметр | Значение |
| --- | --- |
| Модель | PICO 4 (A8110) |
| Кодовое имя | Phoenix |
| ОС | PICO OS 5.13.7 / Android 10 |
| Внутренняя версия | `c000_rf01_bv1.0.1_sv5.13.7_202510300008_phoenix_b9650_user` |
| SoC | Snapdragon 865 (Kona) |
| Панель | Sharp LS026B3SA (`ro.pvr.hmd.type=SHARP5K`) |
| Разрешение | 4320 × 2160 |
| Заводские частоты | 72 Гц / 90 Гц |
| Требования | Root (Magisk/KSU) + Zygisk Vector или LSPosed |

## 2. Принцип работы

### 2.1 DTBO и DFPS

Тайминги панели описаны в узле панели внутри DTBO. Целевой узел и свойства:

```
узел:     qcom,mdss_dsi_sharp_ls026b3sa_90_video
свойство: qcom,dsi-supported-dfps-list   <90 72>  ->  <120 90 72>
свойство: qcom,mdss-dsi-max-refresh-rate <90>     ->  <120>
```

Структура DTBO:

```
Android DT table magic : 0xD7B7AB1E
размер раздела         : 24 МиБ (образ-кандидат обязан сохранить точный размер)
активная запись        : dtbo_idx = 5
```

Контрольные суммы:

| Файл | SHA-256 |
| --- | --- |
| `dtbo-current.img` (заводской) | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| `dtbo-120hz-candidate.img` | `df4e7b25d437464291ebbef0230e28ad3b6eaf6303866dc6ace7e1a52fa1bdf4` |
| `vbmeta-current.img` (эталон, не меняется) | `2bce6e1cccf657c0237b3e8a35f0cfa52b663cec1d922b27a561c5ea97c4b4d3` |

После прошивки кандидата DRM показывает:

```
4320x2160x120x331212vid
4320x2160x72x331212vid
```

Android видит то же самое:

```
supportedModes [{id=1, 4320x2160, fps=120.00001},
                {id=2, 4320x2160, fps=72.00001}]
```

### 2.2 DFPS умеет только понижать частоту

Панель использует DFPS (динамическую частоту кадров), и решающее свойство такое:

```
qcom,mdss-dsi-pan-fps-update = dfps_immediate_porch_mode_vfp
```

Это значит, что **пиксельная частота остаётся неизменной и подстраивается только вертикальный front porch (VFP)**. Базовым является тайминг по умолчанию из DT:

```
2160x2160 на каждый DSI (два DSI дают 4320x2160)
h: hfp 54, hbp 33, hpw 20  -> htotal 2267 (827 после сжатия)
v: vbp 4, vfp 57, vpw 4    -> vtotal 2225
qcom,mdss-dsi-panel-framerate = 90
```

Требуемый VFP для каждой частоты вычисляется напрямую:

```
vtotal(fps) = vtotal_base × 90 / fps
vfp(fps)    = 57 + (vtotal(fps) - 2225)

72  Гц -> vtotal 2781 -> vfp  +613   допустимо
90  Гц -> vtotal 2225 -> vfp    57   база
120 Гц -> vtotal 1669 -> vfp  -499   невозможно
```

Эти `-499` и есть та самая ошибка ядра, и она относится к **120 Гц**, а не к 90 Гц:

```
Invalid new_hfp calcluated-499
```

vtotal 1669 меньше vactive 2160, поэтому 2160 строк физически невозможно вывести. **Повышение частоты требует повышения пиксельной частоты, а DFPS в режиме immediate-porch её не меняет.**

Модель перекрёстно проверяется на собственных узлах PICO. `sharp_493_120_new_video` построен на 120 Гц (vtotal 3686, htotal 1072); по той же формуле:

| Цель | Расчётный vfp | Отдельный узел PICO |
| --- | --- | --- |
| 90 Гц | 1242 | `sharp_493_90_new_video` = 1231 |
| 72 Гц | 2471 | `sharp_493_72_new_video` = 2459 |

Отклонение менее 1%, что подтверждает модель: **базовым таймингом должна быть самая высокая частота**, а более низкие получаются растягиванием VFP. База нашей панели — 90 Гц, поэтому заводская прошивка предлагает только 72/90.

### 2.3 Вендорная цепочка PICO

Частота переключается не стандартными API Android, а закрытой цепочкой PICO:

```
persist.pvr.display.type   jdi49372 / jdi49390 / jdi493120     сохраняемый запрос
sys.pvr.display.type       72.000000 / 90.000000 / 120.000000  фактическое значение
```

`pxrhmdservice` читает только `sys.pvr.display.type` и сообщает его приложениям:

```
Call <getRefreshRate> - sys.pvr.display.type=[72.000000] done.
Call <getRefreshRate> - refreshRate=[72.000000 72.000000 72.000000].
```

Реализация в PICO Settings (`com.picovr.settings`):

```
PicolabFragment.onCheckedChanged(...)         id переключателя = 0x7f0902c6
  -> b1(boolean)                              показывает диалог подтверждения
    -> PicolabFragment$6.onClick(View)         пользователь подтверждает
      -> N(...) -> O(boolean)
        -> Utils.v1(boolean)                  запись вендорного состояния
      -> K0()                                 restartDevice, перезагрузка через 1200 мс
```

Что делает `Utils.v1(boolean)`:

```java
// s1() == Constant.i() && Constant.c()
// Constant.i() истинно только при ro.pvr.product.name == "FalconCV3"
// PICO 4 — это Phoenix, поэтому s1() == false и здесь выбирается jdi49390
String type = s1() ? "jdi493120" : "jdi49390";
if (!enable) type = "jdi49372";

CommonUtils.setSystemProperties("persist.pvr.display.type", type);
ConfigServiceManager.i("sdk_refreshRate", s1() ? "120" : "90");
ConfigServiceManager.i("sdk_Recommand_refreshRate", ...);
Utils.P0("persist.pvr.display.type", rate);   // Settings.Global.putInt
Utils.B0("com.pvr.display.type", rate);       // PxrNotificationService.sendPxrMessage
Utils.x1(enable);                             // частота записи экрана
```

Два ключевых вывода:

1. Замер показал, что на этом устройстве `Utils.s1()` возвращает **`false`** (`ro.pvr.product.name` — `Phoenix`, а не `FalconCV3`), поэтому заводской переключатель работает только между 72 и **90**, а `Utils.v1(true)` записывает `jdi49390`. Использовать `v1(true)` для запроса 120 **нельзя** — фактически запишется 90. Проект записывает все три частоты явно и подменяет `s1()` на `true`, чтобы тексты интерфейса PICO соответствовали 120 Гц, которые теперь перечисляет DTBO.
2. **Заводской сценарий сам перезагружает устройство.** `K0()` — это `restartDevice`; без перезагрузки изменение не применяется.


### 2.4 Нативное выпадающее меню

Строка «схема управления питанием» использует собственный виджет и попап PICO. Проект переиспользует ту же реализацию, поэтому вид и поведение совпадают с системными.

```
виджет    com.picovr.customviews.DropdownOptionView      (id строки питания = 0x7f0902d0)
вход      PicolabFragment.T0(View)
попап     PopupMenuHelper.c(Activity, View, BaseAdapter,
                            SimpleOnItemClickListener, int checkedPosition)
адаптер   com.bytedance.osui.popupmenu.OSUIMenuAdapter
элемент   new MenuItemData(MenuItemType.TYPE_TITLE_CHECK).l("120 Hz")
клик      PicolabFragment$3.onItemClick(AdapterView, View, int, long)
```

Отметка выбора определяется аргументом `checkedPosition` и не хранится внутри `MenuItemData`.

### 2.5 Приватная проверка в SurfaceFlinger

Даже когда DTBO объявляет 120 Гц допустимым режимом для DRM и Android, фреймворк Android продолжает удерживать панель на 72 Гц:

```
E DisplayModeDirector: Asked about unknown display, returning empty allowed set! (id=0)
F DEBUG: #08 libsurfaceflinger.so (SurfaceFlinger::setAllowedDisplayConfigs(...))
```

`DisplayModeDirector` не знает display 0 и возвращает пустой набор допустимых режимов. Передача пустого набора в SurfaceFlinger приводит к выходу за границы вектора и дважды роняет его при загрузке, после чего он откатывается к режиму по умолчанию.

Все стандартные точки входа молча отклоняются:

```
setAllowedDisplayConfigs({0})   -> возвращает успех, состояние не меняется
setActiveConfig(0)              -> возвращает успех, состояние не меняется
service call SurfaceFlinger 1035 i32 0 -> BAD_VALUE (-22)
```

Дизассемблирование `/system/lib64/libsurfaceflinger.so` объясняет причину: PICO добавила в эту функцию приватную проверку.

```asm
0xfad78  ldr  w10, [x9]        ; обход allowedConfigs
0xfad7c  cmp  w10, #3          ; есть ли элемент, равный 3?
0xfad80  b.eq #0xfadac         ; есть -> has pico parameter, продолжаем
0xfadb8  b.eq #0xfae5c         ; нет  -> no pico parameter
0xfae6c  mov  w19, #-0x16      ;         возврат -22 (BAD_VALUE)
0xfadd4  sub  x8, x8, #4       ; при успехе маркер снимается с конца
```

Массив обязан содержать маркер `3`, и, поскольку он снимается с конца, маркер должен идти последним:

```java
SurfaceControl.setAllowedDisplayConfigs(token, new int[] {configIndex, 3});
```

Строка `no pico parameter so allow to change display config through surfaceflinger` сформулирована наоборот: именно эта ветка отклоняет запрос.

### 2.6 Кандидат с базовым таймингом 120 Гц (проверен и откатан)

Поскольку DFPS умеет только понижать частоту, единственный путь — сделать сам тайминг по умолчанию 120 Гц и выводить из него 90 и 72. Кандидат был реально прошит и проверен: получены чёрный экран и искажённая полоса снизу, после чего выполнен откат к заводскому DTBO. Скрипт сохранён для воспроизведения эксперимента и не означает, что кандидат пригоден; в разделе отличаются лишь 20 байт:

```
qcom,mdss-dsi-panel-framerate    90 -> 120
qcom,mdss-dsi-v-front-porch      57 -> 14
qcom,mdss-dsi-panel-phy-timings  перезаписано словами FDT_NOP (корректный FDT, парсеры их пропускают)
```

Тайминги PHY удалены, а не пересчитаны вручную. Эти 14 байт в DT относятся к прежней битовой частоте 993 МГц и не могут быть верны при новой; SoC использует DSI PHY v4.0, для которой 14 байт — ровно размер таблицы таймингов. Без этого свойства драйвер считает их сам, и `/proc/kallsyms` подтверждает наличие калькулятора и операций v4.0:

```
dsi_phy_hw_calculate_timing_params
dsi_phy_hw_v4_0_calc_clk_zero / calc_clk_trail_rec_min / calc_hs_zero / calc_hs_trail
```

Расчёт не умозрительный: сжатый горизонтальный total взят из работающего контроллера DSI, где `DSI_VIDEO_MODE_TOTAL = 0x0adc033a`, то есть htotal−1 = 0x033a и vtotal−1 = 0x0adc.

| Частота | vtotal | vfp | Источник |
| --- | --- | --- | --- |
| 120 Гц | 2182 | 14 | база |
| 90 Гц | 2909 | 741 | выведено DFPS |
| 72 Гц | 3636 | 1468 | выведено DFPS |

Все три дают положительный front porch. Пиксельная частота становится 216 541 680 Гц (сейчас 165 591 864, +30,8%), битовая — около 1,30 ГГц (сейчас 993,5 МГц), в пределах D-PHY SM8250.

Проверка безопасности: `__local_fixups__` этого узла ссылается только на phandle-свойства `io-channels` и `qcom,panel-supply-entries`, ни одно из которых не затронуто, поэтому перезапись таймингов PHY не может нарушить исправление phandle в overlay.

**Проверено и откатано.** Кандидат был записан в активный `dtbo` и проверен после перезагрузки: получены чёрный экран и искажённая полоса снизу. Затем через проводной ADB выполнен откат к заводскому DTBO. В журнале появилась ошибка `DSI_0: LLENGTH = 3400`, то есть длина передачи DSI не совпала с конфигурацией LS026B3SA.

Перед прошивкой держите наготове USB-кабель. Учтите: хотя устройство сообщает `ro.boot.flash.locked=0`, **в его fastboot отключена команда `flash`** — войти можно, но записать раздел нельзя, поэтому единственный рабочий офлайн-путь — **EDL (9008)**. Пока ADB работает, откатывайтесь через `dd`; `dtbobak` всё время остаётся нетронутым как вторая страховка. После прошивки определяйте реальную частоту с помощью `pico4-display-analysis/verify_refresh_rate.sh`, а не dumpsys.

### 2.7 Открытые источники по панели и степень доверия

Открытые источники подтверждают базовые характеристики семейства `LS026B3SA`, но найти официальный datasheet Sharp, DSC PPS, таблицу таймингов PHY или таблицу инициализации TCON не удалось.

- [Panelook LS026B3SA01X](https://www.panelook.com/LS026B3SA01X_Sharp_2.6_LCM_overview_64156.html): в поисковом описании указаны Sharp, 2,6 дюйма, 2160x2160, MIPI, 2 канала, 4 линии данных и 120 Гц.
- [Panelook LS026B3SA01Y](https://www.panelook.com/LS026B3SA01Y_Sharp_2.6_LCM_overview_64157.html): вариант Y с аналогичным описанием — 2160x2160, MIPI, 2 канала, 4 линии данных, 120 Гц.
- [MyDoPoint LS026B3SA01X](https://www.mydopoint.com/lcd_LS026B3SA01X.html): Sharp, 2,6 дюйма, 2160x2160, 520 кд/м², 650:1, MIPI и WLED.
- [Каталог JianXiang LS026B3SA](https://www.jxg.tw/en/product_1569517.html): перечисляет LS026B3SA01/A/B/X как семейство VR-панелей Sharp для PICO, Meta/Oculus и похожих устройств.
- [Официальные характеристики PICO 4](https://www.picoxr.com/global/products/pico4/specs): две Fast-LCD панели 2,56 дюйма, 2160x2160 на глаз и официальные режимы 72/90 Гц.
- [Официальная страница PICO 4](https://www.picoxr.com/global/products/pico4): также указывает 90 Гц как максимальную частоту.
- [Разбор PICO 4 от 52audio](https://www.52audio.com/archives/150653.html): подтверждает две Fast-LCD панели 2,56 дюйма, 4320x2160 и 90 Гц, но не сообщает модель панели или TCON.
- [Страница продавца NT57900](https://www.displayamoled.com/sale-53602352-2-56-inch-vr-lcd-display-2160x2160-45-pins-mipi-interface-driving-ic-nt57900.html): описывает ESHX026C4T-NH0, а не точно идентифицированную LS026B3SA01X; это не доказательство конфигурации TCON данного устройства.

Страницы Panelook защищены слайдером, поэтому их параметры получены из поисковых описаний и имеют меньшую надёжность, чем данные первичного datasheet. Приоритет имеют DTBO и ядро устройства: штатный узел прямо называется `sharp ls026b3sa 90hz video mode dsi panel`, а реальные режимы — 72/90 Гц.

## 3. Что делает модуль

Пакет `com.picoxr.refreshselector`, область действия — **только** `com.picovr.settings`.

| Хук | Назначение |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | Удаляет заводской `SwitchView` и вставляет `DropdownOptionView` в ту же строку с тем же id |
| `PicolabFragment.onCheckedChanged(...)` | Блокирует старый переключатель, чтобы двоичная логика не конфликтовала с тремя вариантами |
| `PopupMenuHelper.c(...)` | Определяет попап частоты по id якоря, заменяет элементы на реальные конфигурации `72 Hz / 90 Hz` и переписывает `checkedPosition` |
| `PicolabFragment$3.onItemClick(...)` | Вместо логики режимов питания обрабатывает реальные конфигурации 72/90; при неудаче live-переключения используется резервный путь |
| `Utils.s1()` | Принудительно `true`, чтобы обойти проверку модели, где `Constant.i()` принимает только `FalconCV3` |
| `SurfaceControl.setAllowedDisplayConfigs` | Вызывается с маркером PICO `3`, поэтому частота применяется на ходу без перезагрузки |
| `SettingApplication.onCreate(...)` | Диагностический зонд только для чтения: печатает `sdk_refreshRate`, `sdk_Recommand_refreshRate` и оба свойства |

Пути запроса записываются явно, без опоры на проверку `s1()` внутри `Utils.v1()`; на заводском DTBO доступны только реальные 72/90:

```
72  Гц  -> persist.pvr.display.type = jdi49372  + sdk_refreshRate = 72
90  Гц  -> persist.pvr.display.type = jdi49390  + sdk_refreshRate = 90
120 Гц  -> использовались только в неудачном эксперименте; на заводском DTBO не показываются
общее      sdk_Recommand_refreshRate получает то же значение
           Utils.P0 / Utils.B0 / Utils.w1(24 для 72 Гц, иначе 30)
           setAllowedDisplayConfigs(token, {configIndex, 3})  <- применяется сразу
```

Меню перечисляет только реально существующие конфигурации дисплея. На заводском DTBO доступны 72 и 90; вариант 120 удалён, поскольку его кандидаты давали чёрный экран и искажения.

Модуль не патчит APK настроек PICO, не меняет ресурсы и не пишет в разделы. Отключение модуля или снятие области действия полностью восстанавливает штатный интерфейс.

## 4. Подтверждённые результаты

- С кандидатом DTBO устройство загружается нормально, ADB стабилен, артефактов нет; считывание `dtbo` и `dtbobak` через EDL **побайтово совпадает** с эталоном, откат работает.
- **Приватная проверка PICO в SurfaceFlinger (маркер `3`) успешно разобрана** — это единственный полностью подтверждённый прорыв во время выполнения:

```
before  activeConfig=1  allowedConfigs=[1]
setAllowedDisplayConfigs({0, 3})  -> accepted
after   activeConfig=1  allowedConfigs=[0]      # без маркера значение не меняется
```

- Вендорное состояние переживает перезагрузку, и служба конфигурации действительно хранит 120:

```
config sdk_refreshRate=120 / sdk_Recommand_refreshRate=120
prop persist.pvr.display.type=jdi493120
prop sys.pvr.display.type=120.000000
```

- Меню отображается в шлеме, попап закрывается после выбора, подпись строки обновляется.

### Но 120 Гц фактически не работают

Ничто из перечисленного не означает, что панель сканирует на 120 Гц. Единственный достоверный ответ даёт собственный журнал ядра PICO:

```
$ dmesg | grep -oE "entered rate:[0-9]+" | sort | uniq -c
    102 entered rate:72
```

`entered rate:120` не встречается **ни разу**. Кроме единственного момента на `t=6.5 s` при загрузке, каждый `dsi_display_set_mode` сообщает `fps=72`.

`VSYNC period: 8333333 ns` в SurfaceFlinger вычислен из тайминга, зарегистрированного для этого режима, а его vtotal около 1669 — меньше vactive 2160, то есть тайминг заведомо некорректен. Иными словами, **120 Гц со стороны Android — это зарегистрированный фиктивный режим**, а `refresh-rate: 120.000005 fps` — лишь арифметика по нему.

Журнал композитора PICO тоже не доказательство: он просто повторяет свойство:

```
PxrCompositor: setRefreshRate:120.000000, current rate: 120.000000
```

## 5. Известные ограничения

**Все кандидаты DTBO откатаны; активен исходный DTBO.** В исходном DTBO список `<90 72>`, `max-refresh-rate = 90`, и оба режима являются настоящими корректными таймингами. Все кандидаты 120 Гц были откатаны через проводной ADB; дальнейшая слепая запись в раздел не рекомендуется.

**90 Гц — родная частота этой панели.** Панель так и называется: `sharp ls026b3sa 90hz video mode dsi panel`, `panel-framerate = 90`, база DFPS тоже 90. Правки таймингов не нужны. Маркер `3` заставляет SurfaceFlinger принять конфигурацию 90 Гц, но проверка показала, что последующий голос системной службы PICO возвращает 72 Гц, поэтому стабильное переключение 72↔90 без перезагрузки ещё не завершено.

**Полный кандидат тайминга 120 Гц был создан и проверен, но не сработал.** По расчёту из 2.2 для 120 Гц нужно:

```
vtotal >= 2160 + 4 + 4 + 1 = 2169
htotal после сжатия 827
пиксельная частота >= 827 x 2169 x 120 ~= 215 МГц (сейчас 165,6 МГц, +30%)
битовая частота DSI ~= 1291 МГц (сейчас 993,6 МГц)
```

У D-PHY в SM8250 такой запас есть, так что это не невозможно. Обнадёживает то, что узел панели уже содержит команду TCON для 120 Гц, явно отличную от 72/90:

```
qcom,mdss-dsi-post-72-nt57900-on-command  = ... b9 13 5f
qcom,mdss-dsi-post-90-nt57900-on-command  = ... b9 13 5f      # идентично 72
qcom,mdss-dsi-post-120-nt57900-on-command = ... b9 10 2c 01 cb # явно иное
```

PICO/Sharp действительно подготовили дополнительную команду TCON для 120 Гц, но проверка показала, что её недостаточно для стабильной работы LS026B3SA на 120 Гц. Полный кандидат с timing, panel-clockrate и PHY уже проверялся и дал чёрный экран с искажениями; дальнейшая запись требует новой проверенной конфигурации именно для этой панели.

**Не судите об успехе по журналам или dumpsys.** Единственный достоверный критерий — `dsi_bridge_enable entered rate` в ядре:

```bash
adb shell su -c "dmesg | grep -oE 'entered rate:[0-9]+' | sort | uniq -c"
```

**После перезагрузки выбор нужно применить заново.** SurfaceFlinger при каждом старте возвращается к конфигурации по умолчанию, проблема пустого набора в `DisplayModeDirector` сохраняется. Модуль хранит выбор в `Settings.Global` и сверяет его при запуске настроек PICO; для полной незаметности нужно расширить хук на `system_server`, что не сделано.

## 5.2 Анализ неудачи

### Ранние эксперименты (уровень DTBO)

Все кандидаты 120 Гц дали один результат: ядро входило в `fps=120`, но панель оставалась чёрной или показывала искажённую полосу снизу. Последняя низкоуровневая ошибка:

```text
DSI_0: LLENGTH = 3400
```

Все кандидаты откатили. И активный `dtbo`, и `dtbobak` снова заводские; SHA-256 — `307e7021…`.

### Проверка на уровне регистров (этот раунд)

Три варианта собраны из реального заводского `dtbo` версии 5.13.7 и прошиты по очереди:

| Вариант | vfp | Обработка PHY | bitclk | Результат |
| --- | --- | --- | --- | --- |
| v2a | 14 | NOP → пересчёт ядром (v4.0) | 1299 МГц | `entered rate:120`, чёрный экран + полоса снизу |
| v2b | 14 | заводская таблица 993 МГц | 1299 МГц | `entered rate:120`, чёрный экран + полоса снизу |
| vfp57 | 57 (без изменений) | заводская | 1325 МГц | `entered rate:120`, чёрный экран + полоса снизу |

Через `/sys/kernel/debug/regmap/ae94900.qcom,mdss_dsi_pll/registers` снято по 292 регистра DSI PLL на 90 Гц (завод) и на 120 Гц (v2a):

```
Изменились только 8 байт — все они калибровка/SSC:
  0x1b8: 9b→9c, 0x1bc: 7a→e2, 0x1c0: 85→84, 0x1c4: ba→52
  0x1c8: 05→06, 0x1f4: 13→2b, 0x218: 9b→9c, 0x298: df→dc

Основной делитель обратной связи (в нём должен был поменяться
коэффициент 993→1299 МГц) не изменился вообще.
```

Регистры контроллера DSI на 120 Гц:

```
DSI_VIDEO_MODE_TOTAL = 0x08b0033a  → htotal=827, vtotal=2225 (vfp=57, а не 14)
DSI_CLK_STATUS       = 0x008047c3  → bit31=0, PLL не захвачена
DSI_DLN0_PHY_ERR     = 0x00088888  → все четыре линии данных сообщают об ошибках
```

kprobe подтвердил: `dsi_display_set_mode` вызывается (`entered rate:120`), но `dsi_clk_set_pixel_clk_rate` — **ни разу**.

### Вывод

**Драйвер PICO принял режим 120 Гц (`entered rate:120`) и обновил конечный автомат DRM, но так и не записал новые часы и тайминги в железо.** PLL осталась на 993 МГц, vtotal на 2225 — панель получает ровно тот же сигнал, что и на 90 Гц. Мост NT57900 не может вывести картинку в этом противоречивом состоянии, отсюда чёрный экран с искажённой полосой снизу.

Как бы ни правился DTBO — timing, clockrate, PHY, TCON — пока драйвер не вызывает `dsi_clk_set_pixel_clk_rate`, 120 Гц не появятся. Это выходит за пределы возможностей DTBO. Путь через модуль ядра (dsi120) пытается закрыть этот пробел извне драйвера; см. `pico4-display-analysis/dsi120/README.md`.

### Возможные пути через драйвер

Конфигурация ядра: `CONFIG_KPROBES=y`, `CONFIG_MODULES=y`, но `CONFIG_MODULE_SIG_FORCE=y` (модуль обязан быть подписан) и `CONFIG_DYNAMIC_DEBUG=n`.

| Путь | Осуществимость | Препятствие |
| --- | --- | --- |
| Модуль ядра + kprobe на `dsi_display_set_mode` с ручным вызовом `dsi_clk_set_pixel_clk_rate` | **Реализовано** | `sig_enforce` обойдён через `patch_sig_enforce.py`; модуль dsi120 собран и загружен, kprobe зарегистрированы; проверка переключения часов в процессе |
| Статический патч ядра внутри boot.img (правка инструкций `dsi_display_set_mode`) | теоретически да | kallsyms декодирован; `hexpatch_boot.py` существует как скрипт только для анализа; приоритет отдан пути через модуль ядра |
| Правка DTBO | **доказано неэффективно** | драйвер не читает эти значения; три варианта по осям vfp×PHY дали одинаковый результат |
| Дождаться прошивки PICO с поддержкой 120 Гц | проще всего | не зависит от нас |

Устройство откачено на завод, `entered rate:72/90` работает. Полный анализ — в `pico4-display-analysis/FINAL_120HZ_ANALYSIS.md`, `LS026B3SA_120HZ_FULL_CONFIG.md` и `pico4-display-analysis/dsi120/README.md`.

## 6. Сборка

```bash
cd pico-refresh-selector
./gradlew :app:assembleDebug
# результат: app/build/outputs/apk/debug/app-debug.apk
```

Окружение: `compileSdk 35`, `minSdk 29`, `targetSdk 29`, `compileOnly de.robv.android.xposed:api:82`.

## 7. Установка

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
# включите модуль в Vector / LSPosed, область действия — только com.picovr.settings
adb shell su -c "am force-stop com.picovr.settings"
```

Необязательные переключатели, оба хранятся в `Settings.Global`:

```bash
# переключение на ходу, включено по умолчанию; 0 возвращает схему «запись + перезагрузка»
adb shell settings put global pico_refresh_selector_live_switch 1

# использовать ли штатную автоперезагрузку PICO при неудаче live-переключения, по умолчанию выключено
adb shell settings put global pico_refresh_selector_auto_restart 0
```

Проверка загрузки хука:

```bash
adb shell su -c "/data/adb/modules/zygisk_vector/cli log cat" | grep PicoRefreshSelector
```

## 8. Команды проверки

```bash
# вендорное состояние
adb shell getprop persist.pvr.display.type      # jdi49372 / jdi49390 / jdi493120
adb shell getprop sys.pvr.display.type          # фактическое значение

# режимы, публикуемые DRM
adb shell su -c "cat /sys/class/drm/card0-DSI-1/modes"

# режимы Android и текущий modeId
adb shell dumpsys display | grep -m1 "Screen"

# единственный надёжный критерий реальной частоты
adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
#   13888888 ns = 72 Гц
#   11111111 ns = 90 Гц
#    8333333 ns = 120 Гц

# сохранённый выбор, который модуль восстанавливает после перезагрузки
adb shell settings get global pico_refresh_selector_choice

# журнал дисплея в ядре
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. Откат

**Программный уровень**: отключите `com.picoxr.refreshselector` в Vector/LSPosed или снимите область действия — настройки PICO сразу вернутся к штатному переключателю. Системные APK, boot, vbmeta и AVB не затрагиваются.

**Уровень DTBO**: запишите `dtbo-current.img` обратно в активный раздел `dtbo`.

Замечания по EDL:

- В fastboot этого устройства **отключена команда `flash`** — войти можно, но записать раздел нельзя, поэтому EDL (9008) остаётся единственным офлайн-путём.
- Работа с EDL (9008) **требует физического USB-подключения**; не пытайтесь делать это по беспроводному ADB.
- Драйвер нужно переключить на WinUSB; Firehose обращается к `dtbo` через LUN4.
- Записывайте только активный `dtbo`, оставляя `dtbobak` нетронутым как вторую страховку.
- `USBError(32, 'Pipe error')` при `reset` — нормальное явление, ADB возвращается примерно через 20 секунд.

## 10. Структура репозитория

```
pico4-display-analysis/
  README.md                      контрольные суммы, снятие образов, сборка кандидата
  build_candidate_dtbo.py        разбор и пересборка DTBO, только целевой узел
  build_120hz_base_dtbo.py       переносит тайминг по умолчанию на 120 Гц
  build_120hz_v2_dtbo.py         исправленный кандидат 120 Гц (vfp=14 + опционально NOP PHY)
  extract_panel_config.py        офлайн-разбор любого DTBO, выгрузка полной конфигурации панели
  verify_refresh_rate.sh         вычисляет реальную частоту из регистров DSI
  dtbo-120hz-candidate-audit.txt журнал аудита образа-кандидата
  edl-readonly-lun4-gpt-dtbo.xml конфигурация Firehose только для чтения (LUN4)
  FINAL_120HZ_ANALYSIS.md        итоговый отчёт об осуществимости 120 Гц
  LS026B3SA_120HZ_FULL_CONFIG.md вывод полной конфигурации и проверка на устройстве
  pll_90hz_baseline.txt          заводская база регистров PLL на 90 Гц (292 шт.)
  pll_120hz.txt                  регистры PLL на 120 Гц (diff с базой доказывает, что часы не переключились)
  dsi120/
    dsi120.c                     модуль ядра: kprobe + принудительное переключение часов DSI
    build.sh                     скрипт сборки (WSL, требует синхронизации .config с устройством)
    patch_sig_enforce.py         офлайн-патчер обхода подписи в boot-образе
    load_module.c                обёртка finit_module() для Magisk shell
    hexpatch_boot.py             ранний скрипт патча ветки (только для анализа, не прошивать)
    setup_buildroot.sh           ранняя подготовка сборочного окружения (заменена синхронизацией .config)
    README.md                    документация по сборке, загрузке и параметрам модуля
  FLASH_INSTRUCTIONS.md          руководство по патчингу и прошивке boot-образа
pico-refresh-selector/
  app/src/main/java/com/picoxr/refreshselector/RefreshRateHook.java
  app/src/main/assets/xposed_init
  app/src/main/res/values/arrays.xml     область действия: только com.picovr.settings
docs/
  settings-current.jpg           страница «лаборатория» до модификации
```

> Репозиторий **не содержит** образов прошивки PICO (`dtbo`, `vbmeta`, `boot`, системные APK). Они проприетарные: снимите их со своего устройства и сверьте с контрольными суммами в `pico4-display-analysis/README.md`.


## 11. План работ

- [x] Найти узел панели и свойства DFPS, собрать кандидат DTBO
- [x] Проверить считывание через EDL и откат
- [x] Добиться перечисления 120 Гц в DRM и Android
- [x] Переиспользовать нативное меню PICO для реальных значений 72/90
- [x] Установить, что штатный сценарий требует перезагрузки
- [x] Записывать `sdk_refreshRate` через службу конфигурации, чтобы вендорное состояние переживало перезагрузку
- [x] Разобрать приватную проверку SurfaceFlinger (маркер `3`) и получить контроль над конфигурацией во время работы
- [x] Опровергнуть «120 Гц работают» по журналу ядра и установить, что DFPS умеет только понижать частоту
- [x] Вернуть исходный DTBO и подтвердить реальные режимы 72/90
- [x] Извлечь полную конфигурацию LS026B3SA, вывести самосогласованные параметры 120 Гц
- [x] Прошить и проверить три варианта DTBO — все дали чёрный экран с искажениями
- [x] Через regmap и kprobe доказать: драйвер не вызывает функцию переключения часов
- [x] **Итог по DTBO: 120 Гц недостижимы на уровне DTBO — корень проблемы в драйвере, а не в конфигурации**
- [x] Обойти принудительную подпись модулей ядра (патч переменной `sig_enforce`)
- [x] Собрать и загрузить kprobe-модуль dsi120, зарегистрировать пробы на `dsi_display_set_mode` и `dsi_clk_set_pixel_clk_rate`
- [ ] Вызвать переключение 72↔90 Гц для захвата дескриптора DSI clock
- [ ] Вызвать `dsi_clk_set_pixel_clk_rate()` из workqueue и проверить переключение часов на 120 Гц
- [ ] Проверить стабильное переключение 72<->90 на ходу на исходном DTBO
- [ ] Расширить хук на `system_server`, починить `DisplayModeDirector` и применять частоту при загрузке
- [ ] Выпустить модуль Magisk для установки в один шаг

## 12. Благодарности

- [CreoleVR/quest-pro-display-overclock](https://github.com/CreoleVR/quest-pro-display-overclock) — источник идеи патча DFPS в памяти для Qualcomm DSI. Он опирается на модуль ядра для Quest Pro и приватные свойства Oculus, поэтому **не может** быть прошит на PICO 4.
- [hhhbwc/pico4-power-mode](https://github.com/hhhbwc/pico4-power-mode) — ориентир по взаимодействию с выпадающим меню настроек PICO.

## 13. Лицензия

MIT













