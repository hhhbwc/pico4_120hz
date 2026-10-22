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
| abl | sde8 | 1 MiB = 1,048,576 B |
| ablbak | sde31 | 1 MiB = 1,048,576 B |
| boot | sde11 | 96 MiB = 100,663,296 B |
| bootbak | sde34 | 96 MiB = 100,663,296 B |
| dtbo | sde17 | **24 MiB = 25,165,824 B** |
| dtbobak | sde40 | **24 MiB = 25,165,824 B** |
| vbmeta | sde9 | 64 KB |

> ⚠️ **尺寸必须是精确字节数**。历史上我因为「分区大小」这个数字本身搞错，
> 写出过一份比分区大 7778 字节的镜像还往里刷（见 §5 血泪教训）。EDL 写入前
> 一律先核对 `stat -c%s <img>` == 分区字节数。

> **关键安全事实**：`dtbo` 与 `dtbobak` 是**两个独立分区**。写 `dtbo` 不会动
> `dtbobak`，后者是工程 abl 建的原厂备份槽，是本机唯一可信的「真原厂」真值源。
> 本机当前两者均为真原厂 `307e7021…`（2026-10-19 已恢复）。

### 当前 dtbo 现状（2026-10-19 恢复后）
- 设备 `dtbo` = **原厂 `307e702182e731b7…`**，逐字节等于 `dtbobak`。
- 设备 `abl` = **原厂 `af6992ba…`**，逐字节等于
  `more-picohaxx-tool/backup/abl/abl.elf`；工程 abl 早已恢复，本机不在工程 abl 状态。
- 权威镜像：`pico4-display-analysis/dtbo-stock-cn-24mb.img`（24 MiB，`307e7021…`），
  以及 `forensics/dtbobak-now.img`（EDL 现场读出的同一份真值）。
- **不再使用** `dtbo-device-pulled.img` / `dtbo-stock-90hz-24m.img`
  （`970da2f5…`）—— 那是 `adb dd` 污染副本，刷进去会变砖（§5）。

> 关于「DTBO 表 `dt_offset` 滞后」：那是我早期用**污染副本**做表-偏移解析得出的
> 结论，**不成立**。用真原厂 `307e7021…` 解析，16 个 FDT 块偏移与表声明一致。
> 教训是：任何对 DTBO 的结论都必须先确认所用镜像的来源可信。

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

## 2. Fastboot 路径（本机实测：**写分区被拒**，只能用于只读查询）

本机 fastboot 层面显示 `unlocked: yes`，但 **2026-10-19 实测所有写分区命令被拒**：

```
oem command is not allowed without unlocktoken authority
CmdFlash is not allowed without unlocktoken authority
flashing get_unlock_ability -> Critical partition: 1, Normal partition: (空)
```

即：`unlocked` 标志在，但 **critical partition 的 unlocktoken 授权并未取得**。
因此本机 **fastboot 只能做只读查询**（`devices` / `getvar` / `continue`），
**任何 `fastboot flash` 都不能用**。写分区走 §3 的 EDL 路径。

> 若将来需要恢复 fastboot 写权限，more-picohaxx 的做法是先 EDL 刷早期工程 abl
> 再解锁（见 §2.2 / §3.4）。本机当前 abl 是原厂 `af6992ba…`，不在该状态。

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

### 2.2 解锁流程（仅当设备锁定时；本机已解锁，**本节仅存档参考**）

> ⚠️ 本节含 `fastboot flash abl` —— 这是**破坏性极大**的操作（改 bootloader）。
> 本机当前 **abl 是原厂 `af6992ba…`，已解锁，模块正常**，**不要执行本节**。
> 只有在设备确实锁死、且已完整备份的前提下才考虑。

1. 备份数据（解锁会清 userdata）。
2. 刷工程 abl：`fastboot flash abl tools/engineering/abl.elf` + `fastboot flash devinfo tools/engineering/devinfo`。
3. `fastboot oem picoF93DMXJ3 unlock` → `fastboot flashing unlock` → `fastboot flashing unlock_critical` → `fastboot oem setenforce 0`。
4. `fastboot reboot bootloader` 确认 `Device unlocked: true`；若仍 locked 就重复（RPMB 写入偶发不立即生效）。
5. 刷回原厂 abl（解锁位存 RPMB，刷回原 abl 仍保持解锁）——
   more-picohaxx README 称此步用于 *restore boot capability*。

> 补充：工程 abl 的代价是官方文档明说的 *unstable boot*。
> 本机 2026-10-19 实测 abl 为**原厂**、引导正常，可作为「工程 abl 已恢复」的判据。

### 2.3 只读查询（本机 fastboot 仅支持这些）
工具链：`D:\more-picohaxx-tool-1.3.10\tools\fastboot.exe`

```bat
fastboot devices                :: 确认设备在 fastboot
fastboot getvar all             :: 只读变量（分区表、unlocked/secure 等）
fastboot continue               :: 尝试继续启动（不写任何分区）
```

> ⚠️ **本机不要用 `fastboot flash`**（见本节开头，会被 unlocktoken 拒绝）。
> 刷 dtbo 一律走 §3 EDL 路径。

---

## 3. EDL 路径（最终后盾）

工具链：
- `D:\more-picohaxx-tool-1.3.10\tools\edl-ng.exe`
- `D:\more-picohaxx-tool-1.3.10\tools\firehoses\prog_firehose_ddr.elf`（官方签名 firehose）
- `D:\more-picohaxx-tool-1.3.10\tools\engineering\abl.elf` + `devinfo`（解锁用）

### 3.1 进入 EDL
手动进 EDL：**Vol Up + Vol Down + Power**（黑屏）。或 `fastboot reboot edl`。

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

## 4. 本项目分层安全（写入前必做）

1. **第 1 层（EDL 直写 + 读回校验）**：`edl-ng write-part dtbo` → 立刻
   `read-part` 回来比 sha256。这是本机唯一可用且已验证的写入路径。
2. **第 2 层（硬件槽真值）**：`dtbobak` 分区保留原厂内容，**从未被写过**。
   任何回滚前先 `read-part dtbobak` 读出真值，比对后再决定写什么。
3. **第 3 层（其他分区）**：EDL 下按分区恢复 `abl` / `boot` / `dtbo` / `vbmeta`。
   镜像必须来自 `edl-ng read-part` 或官方 firmware 包。

### 写入前 checklist（每次写 dtbo 前逐项确认）
- [ ] 目标镜像大小 **== 25,165,824 字节（24 MiB 整）**，且 sha256 已记录。
- [ ] 目标镜像来源可信：`edl-ng read-part` 或官方 firmware 包。
      **绝不能用 `adb shell dd > hostfile`**（会污染，见 §5）。
- [ ] 只读取证例外：`adb exec-out` 不挂 pty、不做行转换，可以安全读分区——
      `adb exec-out "su -c 'dd if=/dev/block/by-name/dtbo bs=1M'" > dtbo.img`。
      2026-10-22 实测：得到 25,165,824 字节、sha256 与设备端 `sha256sum /dev/block/by-name/dtbo` 完全一致（`307e7021…`）。
      仅用于**取回别人的原厂图做比对**；写回分区仍只走 EDL 或官方包。
- [ ] 镜像头部 magic = `0xD7B7AB1E`，且能数出 16 个 FDT 块（`d00dfeed`）。
- [ ] 目标镜像与设备**固件版本/region** 匹配（见下方「禁忌」）。
- [ ] 回滚真值已就位：本地 `dtbo-stock-cn-24mb.img`（`307e7021…`），
      或现场 `read-part dtbobak` 读出的文件。
- [ ] 已知晓变砖后的自救路径：手动进 EDL（Vol Up + Vol Down + Power）。

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
- **不要再相信「本机 DTBO 表是坏的」这个旧结论**。它源于污染副本。真原厂
  `307e7021…` 的 `dt_offset` 与实际 FDT 位置一致，16 个 entry 全部可按表解析。
- **校验 24 MiB dtbo 用设备内 `dd … | sha256sum` 或 EDL `read-part`**，
  不要用主机侧 `adb shell dd > file` 得到的文件 sha（会被污染）。
- 解锁会清 userdata；EDL 全片 dump/restore 是破坏性的，只在该走 EDL 时才做。
- 本机 abl 是**原厂**，不是工程 abl。解锁标志在 RPMB，与 abl 版本无关。
- **设备引导失败时不要用 `fastboot reboot` 反复拉起**——那只是重启回 bootloader，
  会形成死循环。正确做法是回 EDL 读分区做二进制取证。
- **120 Hz 画质问题不要再在 DTBO 层找解**。已定性：LS026B3SA(SHARP5K) 只有
  90 Hz 原生 timing，120 Hz 是超频，蓝紫描边/发雾/细线花屏是硬件代价。
  详见 `pico4-display-analysis/EDL_120HZ_EXPERIMENT.md`。

---

## 5.1 本机分区布局（LUN 4，EDL printgpt 实测）

刷任何分区前，**必须先核对镜像大小 == 分区大小**，防止写溢出损坏相邻分区。

| 分区 | 大小（字节） | 备注 |
|---|---|---|
| `abl` | 1,048,576 | 本机 = `af6992ba…`（= 原厂 abl，工程 abl 早已恢复） |
| `ablbak` | 1,048,576 | 与 `abl` 内容一致（原厂） |
| `boot` | 100,663,296 | Magisk patched（ramdisk 1.70 MiB，含 magisk） |
| `bootbak` | 100,663,296 | 原厂 boot（ramdisk 0.79 MiB，**不含** magisk） |
| `vbmeta` | 65,536 | `AVB0` + avbtool 1.1.0 签名 |
| `dtbo` | **25,165,824** | 本机真原厂 = `307e7021…` |
| `dtbobak` | 25,165,824 | 原厂 dtbo 备份槽，**真值参照物** |

> 这张表来自 `edl-ng printgpt`（LUN 4）实测，不是估算。
> **写任何分区前先核对镜像字节数等于上表数字。**

LBA（512B/扇区，LUN 4）：`dtbo` = 155466-161609，`uefisecapp` 紧接 161610。


---

## 6. 一键参考

```bat
set TOOLS=D:\more-picohaxx-tool-1.3.10\tools
set FH=%TOOLS%\firehoses\prog_firehose_ddr.elf
set STOCK=D:\pico\pico4_120hz\pico4-display-analysis\dtbo-stock-cn-24mb.img

:: ---- EDL 直写 dtbo（本机唯一可用的写入路径，绕开 unlocktoken）----
:: 写前必查：镜像字节数 == 25165824
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo <img>.img
%TOOLS%\edl-ng.exe -l %FH% read-part dtbo verify.img    :: 读回校验 sha256
%TOOLS%\edl-ng.exe -l %FH% reset

:: ---- 回滚到真原厂 ----
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo %STOCK%
:: 或现场从硬件备份槽取真值（最可靠）：
%TOOLS%\edl-ng.exe -l %FH% read-part dtbobak stock.img
%TOOLS%\edl-ng.exe -l %FH% write-part dtbo stock.img

:: ---- fastboot 只读（本机 flash 被拒，仅供查询）----
%TOOLS%\fastboot.exe devices
%TOOLS%\fastboot.exe getvar all
```

> ⚠️ **不可使用的镜像**：`dtbo-device-pulled.img` / `dtbo-device-dtbobak.img` /
> `dtbo-stock-90hz-24m.img`（`df09ffa4…` / `970da2f5…`）均为 `adb dd` 污染副本，
> 写进去会导致设备**无法开机**。正确原厂只有 `dtbo-stock-cn-24mb.img`
> （`307e7021…`），或现场 `read-part dtbobak` 读出的文件。
>
> ⚠️ **不要用 `fastboot flash dtbo`**：本机 unlocktoken 未授权，必被拒绝。
