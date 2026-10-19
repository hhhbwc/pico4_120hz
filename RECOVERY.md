# PICO 4 救砖 / 快刷恢复手册

> 来源：研究 `D:\more-picohaxx-tool-1.3.10` 的 fastboot / EDL 流程，
> 叠加本项目（`pico4_120hz`）的「分层安全」实践。
> 触发条件：快刷 dtbo / 改 abl / 任何可能变砖的操作之前，先读这一篇。

---

## 0. 本机设备快照（写于 2026-10-19）

| 项目 | 值 |
|------|-----|
| 型号 | A8110 / PICOA8110 (Phoenix) |
| 序列号 (qchip_id, 十进制) | `1669527880` |
| fastboot unlock 码 | `picoF93DMXJ3` |
| 当前 bootloader 状态 | **已解锁** `vbmeta.device_state=unlocked` / `verifiedbootstate=orange` |
| 固件 | `Pico/Phoenix/PICOA8110:10/5.13.7/smartcm.1761755159:user/dev-keys`（工程构建，2025-10-30） |
| 面板 | SHARP5K (LS026B3SA) |
| 区域 | zh-Hans-CN（国行） |

### 分区布局（`/dev/block/by-name`）
| 分区 | 设备节点 | 大小 |
|------|---------|------|
| abl | sde8 | 1 MB |
| ablbak | sde31 | 1 MB |
| boot | sde11 | 96 MB |
| bootbak | sde34 | 96 MB |
| dtbo | sde17 | 24 MB |
| dtbobak | sde40 | 24 MB |
| vbmeta | sde9 | 64 KB |

> **关键安全事实**：`dtbo` 与 `dtbobak` 是**两个独立分区**。快刷只写 `dtbo`，
> `dtbobak` 始终保留上一份镜像，是硬件级回滚槽。本机两者当前内容一致
> （均为 `df09ffa4…`，见下）。

### 当前 dtbo 现状（已从设备拉取存档）
- 设备当前 dtbo 哈希：`df09ffa40c90c3807c622b35ca2eea5b1b7def5da8f66e2b036fb4256fd863a7`
- 本地存档：`pico4-display-analysis/dtbo-device-pulled.img`（24,173,602 字节，与分区一致）
- **重要**：此镜像内部 DTBO 表的 `dt_offset` 字段滞后于真实 FDT 位置（16 个真实 FDT
  魔数偏移比表声明偏移大几百~上千字节），即**表是坏的**（dev-keys 工程镜像特征）。
  设备靠连续布局/其它机制仍能启动，但第三方工具按表解析会失败。**切勿用此镜像做
  「按表偏移」的工具往返读写**——应始终以整分区 `dd` 方式备份/恢复。

---

## 1. 进入各模式（按键 / 命令）

| 模式 | 按键组合 | 屏显 |
|------|---------|------|
| 系统 | 长按 Power 至 Pico logo | — |
| Recovery | Vol Up + Power 至机器人 | 死机器人 |
| Fastboot | Vol Down + Power 至菜单 | 左眼菜单 |
| EDL | **Vol Up + Vol Down + Power** | 黑屏 |

- 进入 Fastboot 后可用 `fastboot reboot edl` 转 EDL（需 abl 支持）。
- EDL 不稳时换 USB 2.0 口；用高质量线。

---

## 2. Fastboot 路径（本机已解锁 → 直接可用）

本机 `device_state=unlocked`，**不需要工程 abl、不需要 unlock 码**即可
`fastboot flash`。下面流程仅「若将来锁回 / 换机」时参考。

### 2.1 unlock 码生成算法（more-picohaxx）
```
key = "0XD9J6FB3ATQIHNM46XYZZZOPQRSTUVWXYZ"
val = serial & 0xF7F3F37F          # serial 取自 /sys/devices/soc0/serial_number
if val == 0: enc = key[0]
else:
    while val > 0:
        enc_chars.append(key[val & 0xF]); val >>= 4
    enc = "".join(reversed(enc_chars))
命令 = f"fastboot oem pico{enc} unlock"
```
本机：serial=`1669527880` → **`picoF93DMXJ3`**。

### 2.2 解锁流程（仅当设备锁定时）
1. 备份数据（解锁会清 userdata）。
2. 刷工程 abl：`fastboot flash abl tools/engineering/abl.elf` + `fastboot flash devinfo tools/engineering/devinfo`。
3. `fastboot oem picoF93DMXJ3 unlock` → `fastboot flashing unlock` → `fastboot flashing unlock_critical` → `fastboot oem setenforce 0`。
4. `fastboot reboot bootloader` 确认 `Device unlocked: true`；若仍 locked 就重复（RPMB 写入偶发不立即生效）。
5. 刷回原厂 abl（解锁位存 RPMB，刷回原 abl 仍保持解锁）。

### 2.3 刷 dtbo 的安全流程（本项目核心）
工具链：`D:\more-picohaxx-tool-1.3.10\tools\fastboot.exe`

```bat
adb reboot bootloader
fastboot devices                      # 确认已连
fastboot flash dtbo <要刷的 24MB 镜像>.img
fastboot reboot
```
**回滚（若黑屏/显示异常但 bootloader 仍活）：**
```bat
fastboot flash dtbo dtbo-device-pulled.img   # 本机当前可用镜像（本地存档）
# 或退回硬件槽：fastboot flash dtbo <原厂 24MB dtbo>
```
> 显示变砖（黑屏/花屏但能进 fastboot）≈ 100% 可救：只刷 dtbo，不动 boot/abl。

---

## 3. EDL 路径（最终后盾）

工具链：
- `D:\more-picohaxx-tool-1.3.10\tools\edl-ng.exe`
- `D:\more-picohaxx-tool-1.3.10\tools\firehoses\prog_firehose_ddr.elf`（官方签名 firehose）
- `D:\more-picohaxx-tool-1.3.10\tools\engineering\abl.elf` + `devinfo`（解锁用）

### 3.1 进入 EDL
用户手动：**Vol Up + Vol Down + Power**（黑屏）。或 `fastboot reboot edl`。

### 3.2 备份（EDL 下，整分区）
```bat
edl-ng.exe --loader prog_firehose_ddr.elf --mem dump --skip-storage 0 --lun 0 -o backup_lun0.bin
rem 更精细：edl-ng 的 --part 按分区名 dump，例如 dtbo / boot / abl
```
（具体子命令以 `edl-ng.exe --help` 为准；不同版本参数名可能变。）

### 3.3 恢复（EDL 下刷回）
```bat
edl-ng.exe --loader prog_firehose_ddr.elf --mem write --lun 0 backup_lun0.bin
rem 或按分区：edl-ng.exe --loader ... --part dtbo --img dtbo.bin
```

### 3.4 工程 abl 解锁（EDL 下）
more-picohaxx 的方法：EDL 拉出 stock boot → Windows 上 magiskboot patch → EDL 刷回；
解锁则先 EDL 刷早期 Pico3 工程 abl 让 unlock 命令可用（见 §2.2）。
**本机已解锁，正常情况不需要这一步。**

---

## 4. 本项目分层安全（快刷前必做）

1. **第 1 层（最快）**：`fastboot flash dtbo <回滚镜像>` —— 显示变砖但 bootloader 活。
2. **第 2 层（硬件槽）**：`dtbobak` 分区保留上一份；必要时 `fastboot flash dtbo <从 dtbobak 读出的镜像>`。
3. **第 3 层（EDL）**：用户进 EDL 后，`edl-ng + firehose` 整片或按分区恢复
   （`abl`/`boot`/`dtbo`/`vbmeta`）。

### 刷前 checklist（每次快刷前逐项确认）
- [ ] 已 `dd` 整分区备份当前 dtbo 到本地，sha256 记录。
- [ ] 目标镜像尺寸 = 24,173,602 字节（与分区一致），且 sha256 已知。
- [ ] 确认设备 `device_state=unlocked`（否则先走 §2.2）。
- [ ] 目标镜像与设备**固件版本/region** 匹配（见下方「禁忌」）。
- [ ] 已把回滚镜像（当前可用 dtbo）放在手边，且能 `fastboot flash dtbo` 成功。
- [ ] 用户已知晓：变砖后自己进 EDL（Vol Up+Vol Down+Power），我再 EDL 恢复。

---

## 5. 禁忌 / 已知坑

- **【血泪教训】回滚镜像绝不能来自 `adb shell dd > hostfile`。**
  2026-10-19 我用这个方式拉 dtbo 做"回滚基线"，结果那份副本比分区大 7778 字节
  （adb 流式传二进制会污染）。我截断到 24MiB 后写回设备 —— **写进去的是一份字节
  错位的 dtbo**，与真原厂差 13.58%（3,418,346 字节），第 1 个 FDT 偏移就错位
  （`0x44495` vs `0x44649`）。结果设备**彻底开不了机**，停在 bootloader，
  `fastboot continue` 报 `Failed to load image from partition: Load Error`。

  正确做法：二进制大文件一律用 `edl-ng read-part` 拉，或直接用官方 firmware 包里的镜像。
- **【回滚前必做】拿同机 `*bak` 备份槽做真值对照。**
  工程 abl 建了一整套 `*bak` 分区（`dtbobak`/`bootbak`/`ablbak`/`vbmetabak`…），
  这些是**原厂内容、从未被碰过**。回滚前先 `read-part dtbobak` 读出来比对 sha，
  确认"真原厂"到底长什么样，再决定写什么。
  本机实测：`dtbobak` = `dtbo-stock-cn-24mb.img` = `307e7021…`（这才是真原厂）。
- **不要拿 8 月参考固件（b9650/b9665）构建的 v6 直刷本机**。本机跑的是
  2025-10 的 dev-keys 工程固件，dtbo/lib 哈希均不匹配，`v1.0.1` 模块会直接
  abort（lib 不匹配 + dtbo 白名单未知）。必须基于**本机实际 dtbo** 就地 patch。
- **不要按 DTBO 表偏移解析本机 dtbo**（表是坏的）。始终整分区 `dd`。
- **校验 24MB dtbo 用设备内 `dd … | sha256sum`**，不要用主机侧文件 sha（adb 传输会改字节）。
- 解锁会清 userdata；EDL 全片 dump/restore 是破坏性的，只在该走 EDL 时才做。
- 工程 abl 开机可能变慢或偶发进 EDL；解锁位在 RPMB，刷回原 abl 不影响解锁状态。
- **设备引导失败时不要用 `fastboot reboot` 反复拉起**——那只是重启回 bootloader，
  会形成死循环。正确做法是回 EDL 读分区做二进制取证。

---

## 5.1 本机分区布局（LUN 4，EDL printgpt 实测）

刷任何分区前，**必须先核对镜像大小 == 分区大小**，防止写溢出损坏相邻分区。

| 分区 | 大小 | 备注 |
|---|---|---|
| `abl` | 1.00 MiB | 本机 = `af6992ba…`（= 原厂 abl，工程 abl 早已恢复） |
| `boot` | 96.00 MiB | Magisk patched（ramdisk 1.70MB，含 magisk） |
| `bootbak` | 96.00 MiB | 原厂 boot（ramdisk 0.79MB，**不含** magisk） |
| `vbmeta` | 0.06 MiB | |
| `dtbo` | **24.00 MiB** | 本机真原厂 = `307e7021…` |
| `dtbobak` | 24.00 MiB | 原厂 dtbo 备份槽，**真值参照物** |

LBA（512B/扇区，LUN 4）：`dtbo` = 155466-161609，`uefisecapp` 紧接 161610。


---

## 6. 一键参考

```bat
set TOOLS=D:\more-picohaxx-tool-1.3.10\tools
set FH=%TOOLS%\firehoses\prog_firehose_ddr.elf

:: 快刷 dtbo（fastboot 需先刷工程 abl 才有权限）
%TOOLS%\fastboot.exe flash dtbo <img>.img
%TOOLS%\fastboot.exe reboot

:: EDL 直写 dtbo（本项目实际走的路径，绕开 unlocktoken）
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo <img>.img
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo verify.img   :: 读回校验 sha
%TOOLS%\edl-ng.exe -l %FH% reset

:: 回滚到真原厂（务必用这个，不要用 dtbo-device-pulled.img —— 那份是坏的）
set STOCK=D:\pico\pico4_120hz\pico4-display-analysis\dtbo-stock-cn-24mb.img
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo %STOCK%
:: 或现场从硬件备份槽取真值：
%TOOLS%\edl-ng.exe -l %FH% read-part dtbobak stock.img
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo stock.img
```

> ⚠️ `dtbo-device-pulled.img` / `dtbo-stock-90hz-24m.img`（sha `970da2f5…`）是
> **损坏镜像**，写进去会导致设备无法开机。正确原厂是 `dtbo-stock-cn-24mb.img`
> （sha `307e7021…`）或现场 `read-part dtbobak`。
