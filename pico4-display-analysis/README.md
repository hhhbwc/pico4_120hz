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

刷写后必须重启才生效。校验不一致时不要重启。设备 `ro.boot.flash.locked=0`，因此 `fastboot flash dtbo` 与 EDL(9008) 都可作为后备恢复手段，两者都需要物理 USB 连接。

A reboot is required for the new DTBO to take effect. Do not reboot if the checksum does not match. The device reports `ro.boot.flash.locked=0`, so both `fastboot flash dtbo` and EDL (9008) remain available as recovery paths; both need a physical USB connection.

Для применения нового DTBO нужна перезагрузка. Не перезагружайтесь, если контрольная сумма не совпала. Устройство сообщает `ro.boot.flash.locked=0`, поэтому в качестве путей восстановления доступны и `fastboot flash dtbo`, и EDL (9008); для обоих нужен физический USB-кабель.

## 文件说明 / Files / Файлы

| 文件 | 说明 |
| --- | --- |
| `build_candidate_dtbo.py` | 结构化解析并重组 DTBO，只改目标节点 |
| `dtbo-120hz-candidate-audit.txt` | 候选镜像审计记录（偏移、尺寸、改动范围、校验值） |
| `build_120hz_base_dtbo.py` | 把默认时序挪到 120 Hz，让 DFPS 能推导出 90 与 72 |
| `edl-readonly-lun4-gpt-dtbo.xml` | Firehose **只读**回读配置，LUN4 上的 `gpt_header` 与 `dtbo` |

`edl-readonly-lun4-gpt-dtbo.xml` 只用于回读验证，不含任何写入操作。EDL 必须使用物理 USB 连接。
