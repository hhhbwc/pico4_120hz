# PICO 4 GPU 频率表提取与超频指南

## 关键发现

### 1. GPU 频率表位置
- **不在 dtbo 镜像里** - Stock dtbo (5.13.7) 不含 GPU OPP 节点
- **在 boot.img 的 DTB 段里** - 使用 `qcom,gpu-pwrlevel` 节点格式
- 7 个频率级别: 670, 587, 525, 490, 441.6, 400, 305 MHz

### 2. DTB 格式
- **Magisk 修补过的 boot 镜像里 DTB 段被加密/压缩**
- 无法用标准 FDT 解析器解析
- 需要原版 boot.img 才能提取干净的 DTB

### 3. 频率值验证
在 `boot-current-magisk.img` 中找到所有 7 个频率值（大端存储）:
- `27 ef 63 80` = 670 MHz
- `22 fc e8 c0` = 587 MHz
- `1f 4a d4 40` = 525 MHz
- `1d 34 ce 80` = 490 MHz
- `1a 52 48 00` = 441.6 MHz
- `17 d7 84 00` = 400 MHz
- `12 2d ee 40` = 305 MHz

### 4. 电压值 (opp-microvolt)
- 670 MHz: 0x140 = 320 mV
- 587 MHz: 0x100 = 256 mV
- 525 MHz: 0xe0 = 224 mV
- 490 MHz: 0xc0 = 192 mV
- 441.6 MHz: 0x90 = 144 mV
- 400 MHz: 0x80 = 128 mV
- 305 MHz: 0x40 = 64 mV

## 超频方案

### 方法 1: 直接修改 boot.img 里的 DTB（推荐）
需要：
1. 从原厂固件镜像获取未加密的 boot.img
2. 用 `dtc -I dtb -O dts` 反编译 DTB
3. 修改 `gpu-opp-table` 或 `qcom,gpu-pwrlevel` 节点里的频率值
4. 重新编译 DTB，重新打包 boot.img
5. 刷入设备

### 方法 2: Magisk 模块运行时修改（风险高）
通过 kernel module 或 init.d 脚本在运行时修改：
- `/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq` (CPU，不是 GPU)
- `/sys/devices/system/gpu/gpu0/devfreq/...` (GPU devfreq)

### 方法 3: 编译自定义 kernel（最稳定）
1. 提取原版 kernel 源码
2. 修改 `arch/arm64/boot/dts/qcom/sm8250.dtsi` 里的 GPU OPP 表
3. 编译 kernel
4. 打包到 boot.img

## 注意事项

1. **GPU 超频会增加功耗和发热** - PICO 4 的散热设计有限
2. **电压必须同步提升** - 单纯提高频率会导致不稳定
3. **测试方法**: 用 `adb shell cat /sys/devices/system/gpu/gpu0/devfreq/.../cur_freq` 检查
4. **恢复**: 刷回原厂 boot.img 即可

## 工具链
- `edl.py` - 9008 模式刷写
- `magiskboot` - boot 镜像解包/打包
- `dtc` - Device Tree 编译/反编译
- `zstd` - DTB 解压（如果压缩）

## 下一步
1. 从原厂固件镜像提取未加密的 boot.img
2. 解包 boot.img，提取 DTB
3. 用 `dtc` 反编译 DTB
4. 修改 GPU 频率表
5. 重新编译并打包
