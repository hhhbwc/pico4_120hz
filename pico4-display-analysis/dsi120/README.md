# dsi120 — PICO 4 DSI 120 Hz 时钟强制切换内核模块

适用于 SM8250 PICO 4（内核 `4.19.81-perf+`）的诊断型可加载内核模块。
当前版本通过 kprobe 观察 `dsi_display_set_mode()`、
`dsi_clk_set_pixel_clk_rate()` 和 `dsi_clk_set_byte_clk_rate()`，记录调用次数、
client 指针及 byte-clock 参数；它不会排队 workqueue，也不会改变任何 DSI 时钟。

## 背景

详见 `../FINAL_120HZ_ANALYSIS.md`。简要版：PICO 显示驱动注册了
120 Hz 模式（`entered rate:120`），更新了 DRM 状态机，但**从未调用
`dsi_clk_set_pixel_clk_rate()`**。PLL 停在 993 MHz，vtotal 停在 2225，
面板收到的信号和 90 Hz 完全一样——黑屏+底部花屏。

本模块从驱动外部补上这一步，不修改 DTBO。

## 前置条件：签名绕过

设备内核 `CONFIG_MODULE_SIG_FORCE=y`，未签名模块会被拒绝加载。
使用 `patch_sig_enforce.py` 离线补丁 boot 镜像，将 `sig_enforce`
数据变量清零并让 `is_module_sig_enforced()` 始终返回 false。
补丁已刷入并验证通过。

注意：`hexpatch_boot.py` 是早期的错误猜测（偏移 `0xfb02d4`），
仅保留用于分析，**不要刷入**。正确的补丁脚本是 `patch_sig_enforce.py`。

## 构建（WSL Ubuntu）

```bash
# 1. 同步设备内核配置（关键！否则 CONFIG_KPROBES=n，探针永远不注册）
adb shell 'su -c "zcat /proc/config.gz"' > device-kernel.config
cp device-kernel.config /home/hhhbwc/linux-build/linux-4.19/.config
cd /home/hhhbwc/linux-build/linux-4.19
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- HOSTCFLAGS=-fcommon \
     prepare modules_prepare
# SELinux genheaders 在新版 GCC 上会报错，但关键头文件已生成，可忽略

# 2. 编译模块
bash build.sh

# 3. 产物
/home/hhhbwc/linux-build/dsi120/dsi120.ko
```

构建产物 vermagic 必须与运行内核完全一致：
```
vermagic=4.19.81-perf+ SMP preempt mod_unload modversions aarch64
```

注意：`setup_buildroot.sh` 是早期的一次性脚本，功能已被上述
设备配置同步取代，保留仅供参考。

## 加载（设备端，Magisk root）

需要先交叉编译 `load_module.c` 并推送到设备：

```bash
adb push dsi120.ko /data/local/tmp/
adb push load_module /data/local/tmp/
adb shell su -Z u:r:magisk:s0 -c '/data/local/tmp/load_module /data/local/tmp/dsi120.ko 0'
```

`load_module` 使用 `finit_module(fd, "", flags=0)` 加载模块。
**flags 必须是 `0`**，其他值（`0x2`、`0x6`）会导致 `EINVAL`。

## 卸载

```bash
adb shell su -Z u:r:magisk:s0 -c 'rmmod dsi120'
```

## 模块参数

加载后可通过 `/sys/module/dsi120/parameters/` 查看：

| 参数 | 类型 | 说明 |
|------|------|------|
| `target_rate` | uint | 触发强制切换的目标刷新率（默认 `120`） |
| `verbose` | uint | `1` 输出详细日志（默认 `0`） |
| `armed` | uint | `0` 解除武装但不卸载（默认 `1`） |
| `setmode_hits` | uint, 只读 | `dsi_display_set_mode` 探针命中次数 |
| `pixel_hits` | uint, 只读 | `dsi_clk_set_pixel_clk_rate` 探针命中次数 |
| `byte_hits` | uint, 只读 | `dsi_clk_set_byte_clk_rate` 探针命中次数 |

## 当前状态：probe-only 诊断版

当前构建是**纯观察模式**——kprobe 回调只记录指针和计数，
不排队 workqueue、不调用任何时钟 API。这用于验证探针注册
和设备稳定性。

时钟切换逻辑（`dsi120_clock_work()`）存在但不可达。后续版本
会在确认探针命中和时钟句柄捕获后，受控恢复 workqueue 调度
和时钟调用。

## 验证探针注册

```bash
# 确认探针已注册
adb shell su -Z u:r:magisk:s0 -c 'cat /sys/kernel/debug/kprobes/list | grep dsi'

# 确认模块加载
adb shell 'cat /sys/module/dsi120/initstate'

# 读取命中计数
adb shell 'cat /sys/module/dsi120/parameters/setmode_hits /sys/module/dsi120/parameters/pixel_hits /sys/module/dsi120/parameters/byte_hits'

# 读取内核日志
adb shell su -Z u:r:magisk:s0 -c 'dmesg | grep dsi120'
```

日志级别为 `KERN_EMERG`，确保在所有控制台上可见。

## 已知限制

- `src_clks`/`mux_clks`/`shadow_clks` 目前未赋值；worker 中的 prepare、
  parent 和 disable 路径不可达，且 worker 不会被任何 probe 调度
- `dsi_clk_handle` 只在驱动实际进入 pixel/byte setter 时从 x0 捕获；
  正常冷启动 90→72 曾观察到 `dsi_display_set_mode`，但未观察到两个
  setter，因此不能依赖每次模式切换都获得 handle
- 目标 BSP 的 byte setter 按四个参数观察：`client, byte_clk,
  byte_intf_clk, index`；D-PHY 参考计算为 `byte_intf_clk = byte_clk / 2`
- 旧 CAF 参考文件中的三参数声明不代表 PICO Phoenix 运行时 ABI；
  在没有设备端反汇编或真实命中参数验证前，不恢复时钟调用

## 文件

```
dsi120.c                  模块源码
build.sh                  编译脚本（含 LOCALVERSION= 修正）
patch_sig_enforce.py      离线 boot 镜像签名绕过补丁（正确版本）
hexpatch_boot.py          早期分支补丁脚本（分析用，不要刷入）
load_module.c             finit_module() 包装器（Magisk shell 用）
setup_buildroot.sh        早期构建环境准备（已被设备配置同步取代）
README.md                 本文件
```
