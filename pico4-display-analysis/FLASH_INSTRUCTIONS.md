# PICO 4 120Hz — 签名校验绕过 + dsi120 模块刷写指南

## 文件清单

| 文件 | 位置 | 说明 |
|------|------|------|
| `boot-sig-bypass-patched.img` | `D:\picoooooooooooooo\05-Magisk-root\` | hexpatch 后的 boot 镜像（禁用模块签名强制） |
| `boot未修补pico4.img` | `D:\picoooooooooooooo\05-Magisk-root\` | 原版 boot（恢复用） |
| `dsi120.ko` | `D:\picoooooooooooooo\05-Magisk-root\` | DSI 120Hz 时钟强制切换内核模块 |

## Patch 说明

在 kernel 偏移 `0xfb02d4` 处，把 `cbnz w0, #0xfaf318`（`0x35000220`）
替换为 `nop`（`0xd503201f`）。

这条 `cbnz` 是 `CONFIG_MODULE_SIG_FORCE=y` 的签名校验分支：
- 原始逻辑：`verify_module_sig()` 返回非零 → 跳错误路径 → 拒绝加载
- patch 后：NOP 掉分支 → 签名校验返回值被忽略 → 模块直接加载

## 刷写步骤

### 方案 1：fastboot（推荐，如果设备支持 fastbootd）

```bash
# 1. 进入 fastboot 模式（关机后按住音量减+电源，或 adb reboot bootloader）
# 2. 刷入 patched boot
fastboot flash boot D:\picoooooooooooooo\05-Magisk-root\boot-sig-bypass-patched.img
# 3. 重启
fastboot reboot
```

### 方案 2：QFIL / 9008 EDL（如果 fastboot 不可用）

1. 关机，按住音量减+电源进入 9008 模式
2. 打开 QFIL（`D:\pico4\helper\Flasher\QFIL.exe`）
3. 选择 firehose 程序：`prog_firehose_ddr.elf`
4. 在 rawprogram XML 中添加 boot 分区刷写：
   ```xml
   <program physical_partition_number="0" start_sector="SECTOR_NUM" filename="boot-sig-bypass-patched.img" />
   ```
   （boot 分区的扇区号需要从 GPT 表获取）
5. 点击 Download

### 刷完后验证

重启设备后，通过 adb 推送并加载模块：

```bash
# 推送模块
adb push D:\picoooooooooooooo\05-Magisk-root\dsi120.ko /data/local/tmp/

# 进入 shell
adb shell

# 加载模块（现在应该不再报签名错误）
su
insmod /data/local/tmp/dsi120.ko

# 检查 dmesg
dmesg | grep dsi120

# 切换到 120Hz 模式（通过 sysfs 或 display 配置）
echo 120 > /sys/class/graphics/fb0/refresh_rate 2>/dev/null
# 或通过 setprop
setprop debug.display.refreshrate 120
```

## 恢复原版

如果出问题，刷回原版 boot：

```bash
# fastboot
fastboot flash boot D:\picoooooooooooooo\05-Magisk-root\boot未修补pico4.img

# 或 QFIL 刷回原版
```

## 注意事项

1. **原版 boot 是 Magisk 未修补版本**（`boot未修补pico4.img`）
   - 当前设备上跑的是 Magisk 修补版（`boot-device.img`）
   - 如果你要保留 Magisk root，需要用 Magisk 重新 patch `boot-sig-bypass-patched.img`
   - 或者：先刷 patched boot，再在 Magisk Manager 里重新安装 Magisk

2. **KASLR**：kernel 使用了 KASLR，但 hexpatch 是在 boot 镜像里直接改的，
   不受 KASLR 影响（patch 的是静态文件，不是运行时内存）

3. **SELinux**：kernel 命令行里有 `androidboot.selinux=permissive`，已经是 permissive 模式，
   不需要额外处理
