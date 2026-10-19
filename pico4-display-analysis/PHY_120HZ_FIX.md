# 120Hz 画质问题（偏色/发雾/细线花屏）诊断与 PHY 修复

> 2026-10-19 第二轮：刷入 `dtbo-120-scale.img`（盲放大 PHY）后，主观观察到
> 2D 边缘蓝紫描边、整体发雾、细线（瞄准射线）花屏。
>
> **本文档的最终结论已更新（第三轮）：换用厂商验证 PHY 后画质零改善，
> PHY 不是根因，根因是面板无原生 120Hz。详见文末「最终定性」。**

## 现象
- 2D 应用边缘出现蓝/紫色彩边（系统性色偏，非随机噪点）
- 整体发灰发雾（haze）
- 手柄瞄准射线等高频细线花屏/断裂

## 排除项（已用设备实机验证）
- **GPU 动态分辨率**：`/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage = 0%`，频率仅 305MHz（上限 587MHz）→ 不是渲染降分辨率。
- **DSI 链路裸误码**：dmesg 无 CRC/ECC/underflow/overflow/bit-err → 不是裸比特误码。

## 根因（两层）
1. **面板原生不支持 120Hz**：DTBO 内 `fragment@48/..._ls026b3sa_90_video` 是设备面板
   `ls026b3sa`（SHARP5K）**唯一**节点，**只有 90Hz 时序**（无 120Hz timing/on-command）。
   所谓 120Hz 是项目把 90Hz 时钟/帧率硬改成 120Hz 的超频。厂商自带的
   `fragment@46/..._sharp_493_120_new_video` 是**另一种更高规格面板**的验证过 120Hz 节点。
2. **盲放大 PHY 有缺陷**：`build_120_universal.py --phy scale` 的 `×1.334` 线性放大，
   把第 9/10 字节从全 OEM 标准的 `02 04` 改成了 `03 06`，且整体放过头
   （如 byte5：盲给 `0x2f=47`，原厂 120Hz 才 `0x25=37`）。

## 金标准数据（DTBO 内各面板 timing@0 的 phy-timings，14 字节）
```
493_72 : 00 2e 0d 0c 15 12 0d 0d 09 02 04 00 25 11   (sharp_493, 厂商支持120)
493_90 : 00 1d 08 08 0d 0c 08 08 05 02 04 00 18 0d
493_120: 00 25 0a 0a 1b 25 0a 0a 0a 02 04 00 1f 0f   <-- 经验证的 1325MHz
ls026_90:00 22 08 08 19 23 09 08 09 02 04 00 1c 0d   (我们的面板, 仅90Hz)
SCALE  : 00 2e 0b 0b 22 2f 0c 0b 0c 03 06 00 26 12   (盲放大, 之前刷的, 缺陷)
```
→ 493 由 90→120 的逐字节增量（delta）为：`[0,8,2,2,14,25,2,2,5,0,0,0,7,2]`。
  该 delta 加到任意面板 90Hz PHY 即可得该面板时钟正确的 120Hz PHY（对 493 自身可精确还原 493_120）。

## 修复
采用**厂商验证过的 1325MHz PHY（493_120）= `00250a0a1b250a0a0a0204001f0f`**，
经 EDL 全局替换 `dtbo-120-scale.img` 中的 SCALE_PHY（16 处），生成
`dtbo-120-validated.img`（sha `6077b6e1…`）。保留原 120Hz 时序/on-command，仅换 PHY。

## 结果（设备实测）
- EDL `write-part dtbo` 成功，读回 sha `6077b6e1…` 逐字节一致；`reset` 重启正常。
- 设备内 `dtbo` sha = `6077b6e1…`（持久化）；120Hz 实跑（VSYNC 8.33ms / fps=120.00001）。
- dmesg 无 CRC/ECC/underflow/overflow 等链路报错。
- **主观验证结果：无任何改善。** 蓝紫边、发雾、细线花屏三项全部依旧。

## 最终定性（2026-10-19 第三轮，PHY 路线证伪）

| 原假设 | 验证方式 | 结果 |
|---|---|---|
| 盲放大 PHY 参数错误导致偏色 | 换成厂商在 1325 MHz 上验证过的 `493_120` PHY | ❌ **证伪**——主观画质零改善 |
| DSI 链路误码 | dmesg 全程监测 CRC/ECC/underflow/overflow | ❌ **排除**——内核从未报链路错误 |
| GPU 动态分辨率下调 | `gpu_busy_percentage = 0%`、`cur_freq = 305 MHz`（上限 587） | ❌ **排除**——GPU 空闲，不存在降分辨率 |
| **面板无原生 120Hz（EQ/gamma 按 90Hz 标定）** | 解析全部 16 个 DTBO entry，确认 `ls026b3sa` **只有 90Hz 一个 timing 节点** | ✅ **根因确认** |

**结论**：120Hz 是纯超频。面板内部均衡/gamma/overdrive 仍按 90Hz 工作，
偏色（蓝紫描边）、发雾、细线花屏是**硬件层面的超频代价**，
DTBO 时序/PHY 层面**改不掉**。设备已于同日回滚到原厂 dtbo（`307e7021…`）。

若将来要「120Hz + 干净画质」，需要的是 LS026B3SA 真实的 120Hz TCON 初始化序列
（目前无厂商参考），而不是继续调 PHY。

## 回滚
- **真原厂 dtbo**：`dtbo-stock-cn-24mb.img`（sha `307e7021…`，24 MiB 整），
  或现场 `edl-ng read-part dtbobak` 读出的同一份文件。
  注：原厂 dtbo 内含 **72 Hz 与 90 Hz 两档** timing，模块禁用后设备按系统默认跑 72 Hz。
- ⚠️ **不要用** `dtbo-device-pulled.img` / `dtbo-stock-90hz-24m.img`
  （`df09ffa4…` / `970da2f5…`）—— 那是 `adb dd` 污染副本，刷进去会变砖。
- 用 `edl-ng write-part dtbo <回滚镜像>` + `read-part` 校验 sha 即可。

## 坑
- **不要**用 `adb shell dd ... > hostfile` 校验 24MB dtbo：adb 流式传二进制会损坏/追加
  （多 ~7777 字节，sha 变 `0905c460` 之类假值）。一律用**设备内 `dd ... | sha256sum`** 校验。
- 解析 24MB DTBO：文件头有 544 字节 DTBO header，其后 16 个 FDT 块（magic `d00dfeed`）；
  FDT 的 `size_dt_strings` 字段为 0，需以 `total-off_strings` 兜底；BEGIN_NODE 名对齐用
  `(null_pos+1+3)&~3`。见 `fdt_phy_parse.py` / `fdt_phy_compare.py`。
