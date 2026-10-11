# pico4_120hz 大检查报告（2026-10-11）

检查范围：仓库 HEAD（d5e3d48，37 commits）、Release v1.0.0 zip 实物、在线设备 PA8110MGGB070328G。
结论先行：**项目核心成果（锁 120 架构）是扎实的，但 v1.0.0 的固件门把所有非本机增量固件挡在门外（Issue #2 根因），且仓库 HEAD 的打包脚本会产出比出厂包更危险的 zip。**

---

## 一、设备现状（在线，adb 实测）

| 项 | 状态 |
|---|---|
| 指纹 | `Pico/Phoenix/PICOA8110:10/5.13.7/smartcm.1761755159:user/dev-keys`（= 包内期望值） |
| 面板 | SHARP5K ✅ |
| dtbo | **原厂**（`307e…d46ac`，v6 已回滚） |
| 120hz 模块 | **未安装**（模块目录里只有移植项目的 15 个模块 + zygisk_vector） |
| 当前刷新率 | 72Hz 待机，模式表 [90, 72] |

设备处于干净基线，随时可以重新走一遍 v1.0.0 安装流程做回归验证。

## 二、Issue 排查结论

### Issue #2「Unsupported firmware v5.13.7.S」— 根因已定位
`pico-refresh-selector/magisk-module/customize.sh:13` 用**整串指纹精确匹配**。报错用户的指纹是
`Pico/Phoenix_ovs/PICOA8110:10/5.13.7/smartcm.1761817909:user/dev-keys` —— 设备树变体（`Phoenix_ovs`）和增量号（`1761817909`）都不同，直接被拒。ngeraks 问的 global `v5.13.7S` 同理必被拒。

**v1.0.1 修复设计（两处必须一起改）：**
1. 指纹改解析式校验：device=`PICOA8110` + release=`10` + incremental 以 `5.13.7` 开头，不再比对整个字符串。
2. **新增基线库哈希门**：`sha256(/system/lib64/libpxrhmdservice.so)` 必须等于 `c290a9f51214ff37b415c309c5facf80542024d40c22e5ae3cdeff9825a31fef`（本机 5.13.7 增量的原版库，已实测），否则 abort。没有这道门就放宽指纹 = 补丁库盲覆盖不同版本的库，hmdservice 可能崩溃循环——这比安装被拒严重得多。
3. dtbo 白名单（stock/v6 两个哈希）保持不变：Phoenix_ovs 的 stock dtbo 若哈希不同会安全 abort，届时让用户上传 dtbo（EDL/dd 备份）来做 v6 变体。

### Issue #1「还是90帧+底部花屏」— 大概率是刷了早期变体
「90fps + 底部花屏」正是 README 2.6 节早期 DTBO 失败的特征（NT57900 门极扫描停在 90 档，120fps 数据按 90 扫描速率接收）。推测该用户刷了早期候选 dtbo 或 zip 里 dtbo 写入未成功。Issue 无正文无日志，需要回帖索要：
- `su -c sha256sum -b /dev/block/by-name/dtbo`（判断刷没刷 v6）
- `su -c dmesg | grep -oE 'entered rate:[0-9]+' | sort | uniq -c`
- Magisk 安装日志（判断 customize.sh 走到哪一步）

## 三、出厂 v1.0.0 映射解码（本次实测）

Release zip 里补丁库与本机原版库**逐字节对比只差 2 字节**（0x17B18、0x17C20），三处映射全解出来了：

| 偏移 | 速率档 | 原版库（stock） | 出厂 v1.0.0 补丁库 |
|---|---|---|---|
| 0x17B18 | 120 Hz | (2, 3) | (0, 3) |
| 0x17B80 | 90 Hz | (0, 3) | (0, 3) |
| 0x17C20 | 72 Hz | (1, 3) | (0, 3) |

即**出厂方案 = 所有速率请求统统改写到 cfg0（内核模式序 [120,90,72] 中的 120 配置）**，面板物理上永不降档——这就是"锁 120"能绕开 vfp 增大黑屏的机制。

**代价（Issue #2 楼主自曝的 98% 占用/10fps）**：桌面/Shell 的合法 72Hz 空闲请求也被改写到 120，桌面的帧率监测发现要 72 得 120，无限重试。两个映射各有缺陷：
- 出厂 all→cfg0：无黑屏，但有重试风暴（CPU 烧在桌面场景）。
- 仓库 HEAD `patch_hmdservice_cfgmap.py` 的 v7 真实三档映射：杀死重试风暴，但降档请求会真实落档 → vfp 增大 → 黑屏。

⚠️ **重要**：`build_zip.py` 引用 HEAD 的 `patch_hmdservice_cfgmap.py` 产物。现在用仓库脚本重打包，会打出一个标着 v1.0.0、实际内置 v7 映射的 zip——**比出厂包危险**（桌面一降档就黑屏）。发 v1.0.1 前必须把脚本改成默认产出厂映射（v7 作为显式选项），或在校验注释里写死出厂库哈希 `32427922a3c695453ec85a1c3c454bd984db95b55f0de095689cdd2f8af36eea`。

## 四、仓库卫生问题清单

1. **`tools/audit_selector.py` 已失效**：对着旧"仅 72/90 档"版本写的——把 `jdi493120`、`pico_refresh_selector_choice` 列为禁止项（现在正是核心实现），要求 `RATES = {72, 90}`（现在是 `{72, 90, 120}`），还钉死旧 APK 哈希。实测直接 `FAIL`。需要重写成与 v1.0.0 语义一致的审计（或归档）。
2. **`FINAL_120HZ_ANALYSIS.md`（2026-09-04）没有"已被推翻"横幅**：通篇仍以"状态：已实机验证，结论确定"陈述"120Hz 不可行"，而 09-06 v6 已推翻该结论。README 里加了删除线标记，但这份文档本身会误导新读者（issue 里来的人很可能先读它）。
3. **`build_zip.py` 从新克隆跑不起来**：依赖仓库外 `.release-repo/META-INF/`、gitignored 的 `dtbo-120hz-v6-init120.img` 和 `libpxrhmdservice.patched.so`。v6 dtbo 目前只活在 Release 资产里。建议把 META-INF 两个小文件提交进仓库，dtbo/lib 从 Release zip 反解（哈希校验后）或至少写清获取路径。
4. 7 个 DTBO 构建脚本里 README 只背书 3 个（`build_120_base_dtbo.py`/`build_120_init_dtbo.py`/`patch_hmdservice_cfgmap.py`），其余 5 个是历史候选。建议移入 `archive/` 子目录，避免误用。

## 五、整理后的思路：下一步优先级

1. **v1.0.1：修固件门**（解析式指纹 + lib 哈希白名单 + 默认出厂映射固化）→ 回 Issue #2；global 支持需要样本（让 ngeraks/chaixshot 提供 dtbo + libpxrhmdservice.so 的 sha256），有样本才能做变体，没有就明确说"仅 CN 5.13.7"。
2. **回 Issue #1**：按上面清单要三组信息。
3. **桌面争抢问题**（楼主自己在 #2 报告的 98%/10fps）：这是锁 120 架构的固有矛盾，短期靠文档（说明症状与成因），中期两条真路——dsi120 内核模块路线（roadmap 未勾选项：workqueue 里调 `dsi_clk_set_pixel_clk_rate`）或 hook `system_server` 修正 DisplayModeDirector。别用 v7 映射当"修复"。
4. **窗口叠加细线伪影**（README 问题 2）：取证清单已列好（underrun 计数、devfreq、GPU busy），下次复现时跑。
5. 仓库卫生四项（见上）。

## 六、本次检查留档的产物

- 仓库克隆：`D:\pico\pico4_120hz\`
- Release v1.0.0 实物：`D:\pico\release-v1.0.0.zip`（dtbo.img 哈希 = customize.sh 的 V6 值 ✅，customize.sh 与仓库版本一致 ✅）
- 设备原版库样本：`D:\pico\device-libpxrhmdservice.so`（sha256 `c290a9f5…31fef`）
