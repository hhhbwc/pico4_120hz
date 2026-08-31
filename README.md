# pico4_120hz

**PICO 4 显示刷新率解锁：DTBO 枚举 120 Hz + PICO Settings 原生刷新率下拉菜单**

**PICO 4 display refresh-rate unlock: 120 Hz DTBO enumeration + a native refresh-rate dropdown in PICO Settings**

**Разблокировка частоты обновления PICO 4: перечисление 120 Гц через DTBO + нативное выпадающее меню в настройках PICO**

[中文](#中文) · [English](#english) · [Русский](#русский)

> **当前状态 / Current status / Текущий статус**
>
> 120 Hz 已经被 DRM 和 Android 枚举，但面板**尚未真正运行在 120 Hz**。请先读[已知阻塞点](#5-已知阻塞点)。
>
> 120 Hz is enumerated by DRM and Android, but the panel is **not actually running at 120 Hz yet**. See [known blocker](#5-known-blocker).
>
> 120 Гц перечисляется DRM и Android, но панель **пока не работает на 120 Гц**. См. [известную блокировку](#5-известная-блокировка).

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

### 2.2 为什么 90 Hz 消失了

原始 DFPS 列表是 `<90 72>`，改成 `<120 90 72>` 之后 DRM 只公开了 120 与 72，中间的 90 没有成为独立 mode。启动日志中可见：

```
Invalid new_hfp calcluated-499
```

说明 Qualcomm DSI 的 DFPS 路径在为中间刷新率计算 horizontal front porch 时失败，因此该档位没有被注册。结论：

- `qcom,dsi-supported-dfps-list` 里写了 90，**不等于** `/sys/class/drm/.../modes` 会公开 90。
- 在修好中间时序之前，90 Hz 不可用，vendor 路径请求 90 会回落到 72。

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
// s1() == true 表示该机型支持 120
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

1. 本机 `Utils.s1()` 返回 `true`，所以原生开关打开时走的是 **120**，不是 90。这也解释了“原来的 90 Hz 开关其实是 120”。
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

## 3. 模块做了什么

模块包名 `com.picoxr.refreshselector`，作用域**仅** `com.picovr.settings`。

| Hook 点 | 作用 |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | 移除原刷新率 `SwitchView`，在同一行插入 `DropdownOptionView`，沿用同一个 id |
| `PicolabFragment.onCheckedChanged(...)` | 拦截旧开关，避免二态语义与三档冲突 |
| `PopupMenuHelper.c(...)` | 以锚点 id 识别刷新率弹窗，把菜单项替换为 `72 Hz / 90 Hz / 120 Hz`，并改写 `checkedPosition` |
| `PicolabFragment$3.onItemClick(...)` | 拦截电源模式逻辑，改为按刷新率处理：写厂商状态 → 更新行文本 → 关闭弹窗 → 调用 `K0()` 重启 |

三档请求路径：

```
72  Hz  -> Utils.v1(false)
120 Hz  -> Utils.v1(true)
90  Hz  -> 显式 vendor 路径（不能用 v1(true)，否则会被映射成 120）
             persist.pvr.display.type = jdi49390
             sdk_refreshRate = 90 / sdk_Recommand_refreshRate = 90
             Utils.P0 / Utils.B0 / Utils.w1(30)
```

模块不修改 PICO Settings 的 APK，不改资源，不动任何分区。禁用模块或移除作用域即可完全恢复原生界面。

## 4. 已验证的结果

- 候选 DTBO 刷入后设备正常启动，ADB 稳定，无显示异常。
- 120 Hz 出现在 DRM `modes` 与 Android `supportedModes` 中。
- EDL(9008) 只读回读的 `dtbo` 与 `dtbobak` 均与 ADB 基线**逐字节一致**，回滚路径可用。
- 下拉菜单在头显中正常显示，三档均可点击，弹窗点击后自动关闭，行文本随选择更新。
- Vector 日志确认 Hook 加载与请求下发：

```
PicoRefreshSelector: installed native PICO refresh popup hooks
PicoRefreshSelector: injected native popup rates=[72, 90, 120]
PicoRefreshSelector: requested 120 Hz
PicoRefreshSelector: dismissed refresh popup
```

## 5. 已知阻塞点

**面板目前仍运行在 72 Hz。**不要根据日志里的 `requested 120 Hz` 判断成功，那只表示请求已下发。

判定依据只有硬件 vsync 周期：

```
$ adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
    present offset: 0 ns     VSYNC period: 13888888 ns      # = 72 Hz
Allowed Display Configs: 72Hz, (config override by backdoor: no)
```

已排除的路径：

| 尝试 | 结果 |
| --- | --- |
| `Display.setUserPreferredDisplayMode(...)` | Android 10 上不存在该方法 |
| `Settings.Global` 的 `peak_refresh_rate` / `min_refresh_rate` | 写入成功但无效，SurfaceFlinger 仍只允许 72 Hz |
| `service call SurfaceFlinger 1035 i32 0`（配置后门） | 返回 `BAD_VALUE (-22)`，PICO 关闭了 Android 层刷新率切换 |
| `service call SurfaceFlinger 1036` | 返回 `PERMISSION_DENIED` |
| 只 `setprop persist.pvr.display.type` + 重启 | 开机后被改回，无效 |
| `Settings.Global["persist.pvr.display.type"]=120` + 重启 | 开机后仍被改回 `jdi49390` |

根因：真正的持久化来源是 **PICO 配置服务** `com.pvr.configuration` 的 `sdk_refreshRate`，通过 `ConfigurationClientService` 读写；开机时由它覆盖 `persist.pvr.display.type`。今天两次重启都被改回 `jdi49390`，而 90 Hz 又没有对应的 DRM mode，于是 vendor 回落到 72 Hz。

下一步：在模块里通过 `ConfigurationClientService` 正确写入 `sdk_refreshRate = 120`，再重启验证 vsync 周期是否变为 `8333333 ns`。

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
adb shell dumpsys SurfaceFlinger | grep "VSYNC period"
#   13888888 ns = 72 Hz
#   11111111 ns = 90 Hz
#    8333333 ns = 120 Hz

# 内核显示日志
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. 回滚

**软件层**：在 Vector/LSPosed 中禁用 `com.picoxr.refreshselector` 或移除其作用域，PICO Settings 立即恢复原生二态开关。不涉及系统 APK、boot、vbmeta、AVB。

**DTBO 层**：把 `dtbo-current.img` 写回活动 `dtbo` 分区。

EDL 注意事项：

- EDL(9008) 操作**必须使用物理 USB 连接**，无线 ADB 阶段不要尝试。
- 驱动需要切换为 WinUSB，Firehose 通过 LUN4 访问 `dtbo`。
- 只写活动 `dtbo`，保持 `dtbobak` 原样，作为二次保险。
- `reset` 时出现 `USBError(32, 'Pipe error')` 属正常现象，设备约 20 秒后恢复 ADB。

## 10. 仓库结构

```
pico4-display-analysis/
  README.md                      固件校验值、导出方法、候选镜像生成步骤
  build_candidate_dtbo.py        结构化解析并重组 DTBO，只改目标面板节点
  dtbo-120hz-candidate-audit.txt 候选镜像审计记录
  edl-readonly-lun4-gpt-dtbo.xml Firehose 只读回读配置（LUN4）
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
- [x] 复用 PICO 原生下拉菜单实现三档选择
- [x] 定位原生流程依赖重启的事实
- [ ] 通过 `ConfigurationClientService` 写入 `sdk_refreshRate`，让 120 Hz 真正生效
- [ ] 修正中间时序，使 90 Hz 成为独立 DRM mode
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

### 2.2 Why 90 Hz disappeared

The stock DFPS list is `<90 72>`. After changing it to `<120 90 72>`, DRM exposes only 120 and 72 — the middle 90 never becomes its own mode. The boot log shows:

```
Invalid new_hfp calcluated-499
```

The Qualcomm DSI DFPS path fails to compute the horizontal front porch for the intermediate rate, so that entry is never registered. Consequences:

- Listing 90 in `qcom,dsi-supported-dfps-list` does **not** mean `/sys/class/drm/.../modes` will expose 90.
- Until the intermediate timing is fixed, 90 Hz is unusable and the vendor path falls back to 72 Hz.

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
// s1() == true means this unit is 120-capable
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

1. `Utils.s1()` returns `true` on this unit, so the stock switch actually selects **120**, not 90. That is why "the old 90 Hz toggle is really 120".
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

## 3. What the module does

Package `com.picoxr.refreshselector`, scoped to `com.picovr.settings` **only**.

| Hook | Purpose |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | Removes the stock refresh `SwitchView` and inserts a `DropdownOptionView` in the same row, reusing the same id |
| `PicolabFragment.onCheckedChanged(...)` | Blocks the old switch so two-state semantics cannot fight the three-way choice |
| `PopupMenuHelper.c(...)` | Recognises the refresh popup by anchor id, replaces the items with `72 Hz / 90 Hz / 120 Hz` and rewrites `checkedPosition` |
| `PicolabFragment$3.onItemClick(...)` | Replaces power-mode handling with rate handling: write vendor state, update the row label, dismiss the popup, call `K0()` to reboot |

Request paths:

```
72  Hz  -> Utils.v1(false)
120 Hz  -> Utils.v1(true)
90  Hz  -> explicit vendor path (v1(true) would be mapped to 120)
             persist.pvr.display.type = jdi49390
             sdk_refreshRate = 90 / sdk_Recommand_refreshRate = 90
             Utils.P0 / Utils.B0 / Utils.w1(30)
```

The module never patches the PICO Settings APK, never touches resources and never writes a partition. Disabling the module or removing its scope fully restores the stock UI.

## 4. Verified results

- The device boots normally with the candidate DTBO; ADB is stable and no display artefacts appear.
- 120 Hz shows up both in DRM `modes` and Android `supportedModes`.
- EDL (9008) read-back of `dtbo` and `dtbobak` is **byte-for-byte identical** to the ADB baseline, so rollback works.
- The dropdown renders in the headset, all three entries are clickable, the popup dismisses on selection and the row label follows the choice.
- Vector logs confirm hook load and request dispatch:

```
PicoRefreshSelector: installed native PICO refresh popup hooks
PicoRefreshSelector: injected native popup rates=[72, 90, 120]
PicoRefreshSelector: requested 120 Hz
PicoRefreshSelector: dismissed refresh popup
```

## 5. Known blocker

**The panel still runs at 72 Hz.** Do not treat `requested 120 Hz` in the log as success — it only means the request was dispatched.

The only trustworthy evidence is the hardware vsync period:

```
$ adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
    present offset: 0 ns     VSYNC period: 13888888 ns      # = 72 Hz
Allowed Display Configs: 72Hz, (config override by backdoor: no)
```

Ruled out so far:

| Attempt | Result |
| --- | --- |
| `Display.setUserPreferredDisplayMode(...)` | Method does not exist on Android 10 |
| `Settings.Global` `peak_refresh_rate` / `min_refresh_rate` | Written successfully but inert; SurfaceFlinger still allows 72 Hz only |
| `service call SurfaceFlinger 1035 i32 0` (config backdoor) | Returns `BAD_VALUE (-22)`; PICO disabled Android-level refresh-rate switching |
| `service call SurfaceFlinger 1036` | Returns `PERMISSION_DENIED` |
| `setprop persist.pvr.display.type` + reboot | Overwritten during boot |
| `Settings.Global["persist.pvr.display.type"]=120` + reboot | Still reverted to `jdi49390` after boot |

Root cause: the authoritative store is `sdk_refreshRate` in the **PICO configuration service** `com.pvr.configuration`, accessed through `ConfigurationClientService`. It overwrites `persist.pvr.display.type` at boot. Both reboots reverted to `jdi49390`, and since 90 Hz has no DRM mode, the vendor path falls back to 72 Hz.

Next step: write `sdk_refreshRate = 120` through `ConfigurationClientService` from the module, reboot, and check whether the vsync period becomes `8333333 ns`.

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
adb shell dumpsys SurfaceFlinger | grep "VSYNC period"
#   13888888 ns = 72 Hz
#   11111111 ns = 90 Hz
#    8333333 ns = 120 Hz

# kernel display log
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. Rollback

**Software**: disable `com.picoxr.refreshselector` in Vector/LSPosed or remove its scope; PICO Settings returns to the stock two-state switch immediately. Nothing touches system APKs, boot, vbmeta or AVB.

**DTBO**: write `dtbo-current.img` back to the active `dtbo` partition.

EDL notes:

- EDL (9008) work **requires a physical USB connection**; never attempt it over wireless ADB.
- Switch the driver to WinUSB; Firehose reaches `dtbo` through LUN4.
- Write the active `dtbo` only and leave `dtbobak` untouched as a second safety net.
- `USBError(32, 'Pipe error')` on `reset` is expected; ADB returns after roughly 20 seconds.

## 10. Repository layout

```
pico4-display-analysis/
  README.md                      checksums, dump instructions, candidate build steps
  build_candidate_dtbo.py        structured DTBO parse and rebuild, target node only
  dtbo-120hz-candidate-audit.txt audit record of the candidate image
  edl-readonly-lun4-gpt-dtbo.xml Firehose read-only configuration (LUN4)
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
- [x] Reuse PICO's native dropdown for a three-way choice
- [x] Establish that the stock flow depends on a reboot
- [ ] Write `sdk_refreshRate` through `ConfigurationClientService` so 120 Hz truly applies
- [ ] Fix intermediate timings so 90 Hz becomes its own DRM mode
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

### 2.2 Почему пропали 90 Гц

Заводской список DFPS — `<90 72>`. После замены на `<120 90 72>` DRM публикует только 120 и 72: промежуточные 90 не становятся отдельным режимом. В журнале загрузки видно:

```
Invalid new_hfp calcluated-499
```

Путь DFPS в драйвере Qualcomm DSI не может рассчитать horizontal front porch для промежуточной частоты, поэтому запись не регистрируется. Следствия:

- Наличие 90 в `qcom,dsi-supported-dfps-list` **не означает**, что `/sys/class/drm/.../modes` покажет 90.
- Пока промежуточные тайминги не исправлены, 90 Гц недоступны, а вендорный путь откатывается на 72 Гц.

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
// s1() == true означает, что экземпляр поддерживает 120
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

1. На этом устройстве `Utils.s1()` возвращает `true`, поэтому заводской переключатель выбирает **120**, а не 90. Именно поэтому «старый переключатель 90 Гц» фактически даёт 120.
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

## 3. Что делает модуль

Пакет `com.picoxr.refreshselector`, область действия — **только** `com.picovr.settings`.

| Хук | Назначение |
| --- | --- |
| `PicolabFragment.onCreateView(...)` | Удаляет заводской `SwitchView` и вставляет `DropdownOptionView` в ту же строку с тем же id |
| `PicolabFragment.onCheckedChanged(...)` | Блокирует старый переключатель, чтобы двоичная логика не конфликтовала с тремя вариантами |
| `PopupMenuHelper.c(...)` | Определяет попап частоты по id якоря, заменяет элементы на `72 Hz / 90 Hz / 120 Hz` и переписывает `checkedPosition` |
| `PicolabFragment$3.onItemClick(...)` | Вместо логики режимов питания обрабатывает частоту: запись состояния, обновление подписи, закрытие попапа, вызов `K0()` |

Пути запроса:

```
72  Гц  -> Utils.v1(false)
120 Гц  -> Utils.v1(true)
90  Гц  -> явный вендорный путь (v1(true) был бы отражён в 120)
             persist.pvr.display.type = jdi49390
             sdk_refreshRate = 90 / sdk_Recommand_refreshRate = 90
             Utils.P0 / Utils.B0 / Utils.w1(30)
```

Модуль не патчит APK настроек PICO, не меняет ресурсы и не пишет в разделы. Отключение модуля или снятие области действия полностью восстанавливает штатный интерфейс.

## 4. Подтверждённые результаты

- С кандидатом DTBO устройство загружается нормально, ADB стабилен, артефактов нет.
- 120 Гц присутствуют и в DRM `modes`, и в `supportedModes` Android.
- Считывание `dtbo` и `dtbobak` через EDL (9008) **побайтово совпадает** с эталоном из ADB, откат работает.
- Меню отображается в шлеме, все три пункта нажимаются, попап закрывается после выбора, подпись строки обновляется.
- Журнал Vector подтверждает загрузку хуков и отправку запросов:

```
PicoRefreshSelector: installed native PICO refresh popup hooks
PicoRefreshSelector: injected native popup rates=[72, 90, 120]
PicoRefreshSelector: requested 120 Hz
PicoRefreshSelector: dismissed refresh popup
```

## 5. Известная блокировка

**Панель по-прежнему работает на 72 Гц.** Строка `requested 120 Hz` в журнале не означает успех — она подтверждает лишь отправку запроса.

Единственное надёжное доказательство — аппаратный период vsync:

```
$ adb shell dumpsys SurfaceFlinger | grep -E "VSYNC period|Allowed Display"
    present offset: 0 ns     VSYNC period: 13888888 ns      # = 72 Гц
Allowed Display Configs: 72Hz, (config override by backdoor: no)
```

Проверено и исключено:

| Попытка | Результат |
| --- | --- |
| `Display.setUserPreferredDisplayMode(...)` | Метода нет в Android 10 |
| `Settings.Global` `peak_refresh_rate` / `min_refresh_rate` | Запись успешна, но не действует: SurfaceFlinger разрешает только 72 Гц |
| `service call SurfaceFlinger 1035 i32 0` (бэкдор конфигурации) | Возвращает `BAD_VALUE (-22)`; PICO отключила переключение частоты на уровне Android |
| `service call SurfaceFlinger 1036` | Возвращает `PERMISSION_DENIED` |
| `setprop persist.pvr.display.type` + перезагрузка | Перезаписывается при загрузке |
| `Settings.Global["persist.pvr.display.type"]=120` + перезагрузка | После загрузки снова `jdi49390` |

Первопричина: авторитетное хранилище — `sdk_refreshRate` в **службе конфигурации PICO** `com.pvr.configuration`, доступной через `ConfigurationClientService`. При загрузке она перезаписывает `persist.pvr.display.type`. Обе перезагрузки вернули `jdi49390`, а поскольку для 90 Гц нет режима DRM, вендорный путь откатился на 72 Гц.

Следующий шаг: записать `sdk_refreshRate = 120` через `ConfigurationClientService` из модуля, перезагрузиться и проверить, стал ли период vsync равен `8333333 ns`.

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
adb shell dumpsys SurfaceFlinger | grep "VSYNC period"
#   13888888 ns = 72 Гц
#   11111111 ns = 90 Гц
#    8333333 ns = 120 Гц

# журнал дисплея в ядре
adb shell su -c "dmesg | grep -iE 'dfps|dsi|underrun|hfp|pll'"
```

## 9. Откат

**Программный уровень**: отключите `com.picoxr.refreshselector` в Vector/LSPosed или снимите область действия — настройки PICO сразу вернутся к штатному переключателю. Системные APK, boot, vbmeta и AVB не затрагиваются.

**Уровень DTBO**: запишите `dtbo-current.img` обратно в активный раздел `dtbo`.

Замечания по EDL:

- Работа с EDL (9008) **требует физического USB-подключения**; не пытайтесь делать это по беспроводному ADB.
- Драйвер нужно переключить на WinUSB; Firehose обращается к `dtbo` через LUN4.
- Записывайте только активный `dtbo`, оставляя `dtbobak` нетронутым как вторую страховку.
- `USBError(32, 'Pipe error')` при `reset` — нормальное явление, ADB возвращается примерно через 20 секунд.

## 10. Структура репозитория

```
pico4-display-analysis/
  README.md                      контрольные суммы, снятие образов, сборка кандидата
  build_candidate_dtbo.py        разбор и пересборка DTBO, только целевой узел
  dtbo-120hz-candidate-audit.txt журнал аудита образа-кандидата
  edl-readonly-lun4-gpt-dtbo.xml конфигурация Firehose только для чтения (LUN4)
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
- [x] Переиспользовать нативное меню PICO для выбора из трёх значений
- [x] Установить, что штатный сценарий требует перезагрузки
- [ ] Записывать `sdk_refreshRate` через `ConfigurationClientService`, чтобы 120 Гц действительно применялись
- [ ] Исправить промежуточные тайминги, чтобы 90 Гц стали отдельным режимом DRM
- [ ] Выпустить модуль Magisk для установки в один шаг

## 12. Благодарности

- [CreoleVR/quest-pro-display-overclock](https://github.com/CreoleVR/quest-pro-display-overclock) — источник идеи патча DFPS в памяти для Qualcomm DSI. Он опирается на модуль ядра для Quest Pro и приватные свойства Oculus, поэтому **не может** быть прошит на PICO 4.
- [hhhbwc/pico4-power-mode](https://github.com/hhhbwc/pico4-power-mode) — ориентир по взаимодействию с выпадающим меню настроек PICO.

## 13. Лицензия

MIT













