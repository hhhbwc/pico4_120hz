# DTBO 分析 / DTBO analysis / Анализ DTBO

## 关于固件镜像 / About firmware images / О образах прошивки

**中文** —— 本目录**不包含**任何 PICO 固件镜像（`dtbo`、`vbmeta`、`boot`、系统 APK）。这些文件属于 PICO 的专有固件，不适合再分发。请自行从**你自己的设备**导出，再用下面的校验值确认与本项目验证过的固件一致。

**English** — This directory contains **no** PICO firmware images (`dtbo`, `vbmeta`, `boot`, system APKs). They are PICO proprietary firmware and are not redistributable. Dump them from **your own device** and use the checksums below to confirm you are on the same firmware this project was verified against.

**Русский** — В этом каталоге **нет** образов прошивки PICO (`dtbo`, `vbmeta`, `boot`, системные APK). Это проприетарная прошивка PICO, её распространение недопустимо. Снимите образы **со своего устройства** и сверьте контрольные суммы ниже.

## 导出 / Dump / Снятие

```bash
adb shell su -c "dd if=/dev/block/by-name/dtbo    of=/sdcard/dtbo-current.img"
adb shell su -c "dd if=/dev/block/by-name/dtbobak of=/sdcard/dtbobak-current.img"
adb shell su -c "dd if=/dev/block/by-name/vbmeta  of=/sdcard/vbmeta-current.img"
adb pull /sdcard/dtbo-current.img
adb pull /sdcard/dtbobak-current.img
adb pull /sdcard/vbmeta-current.img
```

## 校验值 / Checksums / Контрольные суммы

固件：`c000_rf01_bv1.0.1_sv5.13.7_202510300008_phoenix_b9650_user`

| 文件 / File / Файл | 大小 / Size | SHA-256 |
| --- | --- | --- |
| `dtbo-current.img` | 24 MiB | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| `dtbobak-current.img` | 24 MiB | `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac` |
| `dtbo-120hz-candidate.img` | 24 MiB | `df4e7b25d437464291ebbef0230e28ad3b6eaf6303866dc6ace7e1a52fa1bdf4` |
| `vbmeta-current.img` | 64 KiB | `2bce6e1cccf657c0237b3e8a35f0cfa52b663cec1d922b27a561c5ea97c4b4d3` |
| `vbmetabak-current.img` | 64 KiB | `2bce6e1cccf657c0237b3e8a35f0cfa52b663cec1d922b27a561c5ea97c4b4d3` |
| `devinfo-current.bin` | 4 KiB | `0fc9f5f864195a5ec61f18a005b4b2f0e1e59ace1bc707569612f3a97ff3e9fd` |

活动 `dtbo` 与备份 `dtbobak` 内容完全相同，EDL 只读回读结果也与 ADB 基线逐字节一致。

## 生成候选镜像 / Build the candidate / Сборка кандидата

```bash
python build_candidate_dtbo.py dtbo-current.img dtbo-120hz-candidate.img
sha256sum dtbo-120hz-candidate.img   # 必须等于上表中的候选校验值
```

脚本只改目标面板节点的两个属性，并强制候选镜像与原镜像**完全同尺寸**：

```python
TARGET_NODE       = "qcom,mdss_dsi_sharp_ls026b3sa_90_video"
DFPS_PROPERTY     = "qcom,dsi-supported-dfps-list"      # <90 72>  -> <120 90 72>
MAX_FPS_PROPERTY  = "qcom,mdss-dsi-max-refresh-rate"    # <90>     -> <120>

if len(candidate) != len(baseline):
    raise ValueError("Candidate must remain exactly partition-sized")
```

`dtbo-120hz-candidate-audit.txt` 是本项目实际使用的那份候选镜像的审计记录，可用于比对。

## 生成 120 Hz 基准候选 / Build the 120 Hz base candidate / Сборка кандидата с базой 120 Гц

```bash
python build_candidate_dtbo.py  dtbo-current.img          dtbo-120hz-candidate.img
python build_120hz_base_dtbo.py dtbo-120hz-candidate.img  dtbo-120hz-base.img
sha256sum dtbo-120hz-base.img
# 1c6c6cbc5e3014e70d46bddd7ad2b3d63ca92f2fabfe0153c9d0d84e43424237
```

第二步把默认时序挪到 120 Hz，使 90 与 72 可以由 DFPS 推导；理由见根目录 README 的 2.2 与 2.6 节。全部改动都在原地完成，镜像尺寸不变，整个分区仅 20 字节差异。

The second step moves the default timing to 120 Hz so that 90 and 72 can be derived by DFPS; see sections 2.2 and 2.6 of the top-level README. Every edit is in place, the image keeps its exact size, and only 20 bytes differ across the whole partition.

Второй шаг переносит тайминг по умолчанию на 120 Гц, чтобы 90 и 72 выводились через DFPS; см. разделы 2.2 и 2.6 в README верхнего уровня. Все правки выполняются на месте, размер образа не меняется, во всём разделе отличаются лишь 20 байт.

## 验证真实刷新率 / Verify the real rate / Проверка реальной частоты

```bash
./verify_refresh_rate.sh [adb-serial]
```

`dumpsys SurfaceFlinger` 与 PICO 自己的 `PxrCompositor` 日志都**不能**用来判断刷新率：前者按模式登记的时序反推，后者只是回读属性。脚本改为读取 DSI 控制器实际编程的时序和时钟树里的像素时钟，相除得到真值。一份典型输出暴露了三者的分歧：

```
DSI_VIDEO_MODE_TOTAL = 0x0adc033a
pixel clock          = 165591864 Hz
htotal = 827, vtotal = 2781
actual refresh rate  = 72.000 Hz      <- 硬件真值
    101 entered rate:72               <- 驱动只应用过 72
VSYNC period: 8333333 ns              <- SurfaceFlinger 声称 120
```

Neither `dumpsys SurfaceFlinger` nor PICO's `PxrCompositor` log can be used to judge the refresh rate: the former derives it from whatever timing the mode was registered with, the latter merely echoes a property. The script reads the timing actually programmed into the DSI controller together with the pixel clock from the clock tree and divides one by the other. A typical run exposes the disagreement, as shown above.

Ни `dumpsys SurfaceFlinger`, ни журнал `PxrCompositor` от PICO не годятся для оценки частоты обновления: первый выводит её из тайминга, с которым зарегистрирован режим, второй просто повторяет свойство. Скрипт читает тайминг, фактически запрограммированный в контроллере DSI, вместе с пиксельной частотой из дерева тактирования и делит одно на другое. Типичный запуск показывает расхождение, приведённое выше.

## 刷写与回滚 / Flashing and rollback / Прошивка и откат

```bash
# 写入（需要 root，dtbobak 保持原样）
adb push dtbo-120hz-base.img /data/local/tmp/
adb shell su -c "dd if=/data/local/tmp/dtbo-120hz-base.img of=/dev/block/by-name/dtbo bs=4096 && sync"

# 回读校验，必须与上面的 SHA-256 一致
adb shell su -c "dd if=/dev/block/by-name/dtbo bs=4096 count=6144 | sha256sum"

# 回滚：写回任一已知良品镜像
adb shell su -c "dd if=/data/local/tmp/dtbo-current.img of=/dev/block/by-name/dtbo bs=4096 && sync"
```

刷写后必须重启才生效。**校验不一致时不要重启。**

关于恢复手段：虽然 `ro.boot.flash.locked=0`，但**这台设备的 fastboot 禁用了 `flash` 命令**——能进 fastboot，却刷不了任何分区。实测可用的离线刷写途径只有 **EDL(9008)**，需要物理 USB 连接与 WinUSB 驱动。所以只要 ADB 还在，就优先用上面的 `dd` 回滚；ADB 也没了才走 9008。

A reboot is required for the new DTBO to take effect. **Do not reboot if the checksum does not match.**

On recovery: although `ro.boot.flash.locked=0`, **this device's fastboot has the `flash` command disabled** — fastboot can be entered but cannot write any partition. The only offline path proven to work is **EDL (9008)**, which needs a physical USB connection and the WinUSB driver. So prefer the `dd` rollback above while ADB is alive, and fall back to 9008 only if ADB is gone too.

Для применения нового DTBO нужна перезагрузка. **Не перезагружайтесь, если контрольная сумма не совпала.**

О восстановлении: хотя `ro.boot.flash.locked=0`, **у этого устройства в fastboot отключена команда `flash`** — войти в fastboot можно, но записать раздел нельзя. Единственный проверенный офлайн-путь — **EDL (9008)**, для которого нужны физический USB-кабель и драйвер WinUSB. Поэтому пока ADB работает, используйте откат через `dd` выше, а 9008 — только если ADB тоже недоступен.

## 文件说明 / Files / Файлы

| 文件 | 说明 |
| --- | --- |
| `build_candidate_dtbo.py` | 结构化解析并重组 DTBO，只改目标节点 |
| `dtbo-120hz-candidate-audit.txt` | 候选镜像审计记录（偏移、尺寸、改动范围、校验值） |
| `build_120hz_base_dtbo.py` | 把默认时序挪到 120 Hz，让 DFPS 能推导出 90 与 72 |
| `build_120hz_v2_dtbo.py` | 修正版 120 Hz 候选：vfp=14 几何 + 可选 NOP PHY（内核 v4.0 重算），不加 clockrate、不动 NT57900 |
| `extract_panel_config.py` | 离线解析任意 DTBO，导出指定面板节点的全部显示参数（timing/PHY/DSC/TCON） |
| `LS026B3SA_120HZ_FULL_CONFIG.md` | 120 Hz 完整配置推导：timing/clock/PHY 已定，NT57900 120 序列可从同 DTBO 的 Innolux 节点移植 |
| `verify_refresh_rate.sh` | 从 DSI 寄存器与时钟树算出真实刷新率，不依赖 dumpsys |
| `edl-readonly-lun4-gpt-dtbo.xml` | Firehose **只读**回读配置，LUN4 上的 `gpt_header` 与 `dtbo` |

`edl-readonly-lun4-gpt-dtbo.xml` 只用于回读验证，不含任何写入操作。EDL 必须使用物理 USB 连接。

## 当前结论 / Current conclusion / Текущий вывод

The stock active DTBO has been restored after the 120 Hz timing experiments. The read-back hash is `307e702182e731b76e8bc0a4aec131a53e1ddf82e96f2f416e2f49129e6d46ac`, and `dtbobak` remains unchanged. The Sharp LS026B3SA node exposes its genuine 90/72 Hz modes again.

The node has one `timing@0`, no independent 120 Hz `timing@1`, and no `qcom,mdss-dsi-panel-clockrate`. Its `post-120-nt57900-on-command` is only a rate-named 53-byte supplemental command. It is not a complete 120 Hz panel configuration. The `sharp_493_120_new_video` node in the same DTBO belongs to a different 960x3664 panel with different GPIO, PWM, DSC topology and timings, so it cannot be copied to LS026B3SA.

A real 120 Hz attempt therefore requires a panel-specific timing, clock, PHY and TCON initialization set. **This set has been derived and tested**; see `LS026B3SA_120HZ_FULL_CONFIG.md`. The short version: all six layers (timing, clock, PHY, DSC, TCON, bridge) were worked out and three candidate DTBOs were flashed and tested on-device. All three produced `entered rate:120` in the kernel log but the panel stayed black with a corrupted band at the bottom. Register-level evidence (PLL register diff + DSI controller dump) proves the driver never actually switched the clock — the PLL stayed at 993 MHz and the hardware timing stayed at vfp=57 regardless of what the DTBO said. The panel's NT57900 bridge cannot render in this contradictory state. **120 Hz on this panel is not achievable by DTBO modification alone; it requires PICO to fix the display driver or release firmware that actually programs the PLL for 120 Hz.**
