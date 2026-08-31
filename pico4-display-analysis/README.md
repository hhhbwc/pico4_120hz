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

## 文件说明 / Files / Файлы

| 文件 | 说明 |
| --- | --- |
| `build_candidate_dtbo.py` | 结构化解析并重组 DTBO，只改目标节点 |
| `dtbo-120hz-candidate-audit.txt` | 候选镜像审计记录（偏移、尺寸、改动范围、校验值） |
| `edl-readonly-lun4-gpt-dtbo.xml` | Firehose **只读**回读配置，LUN4 上的 `gpt_header` 与 `dtbo` |

`edl-readonly-lun4-gpt-dtbo.xml` 只用于回读验证，不含任何写入操作。EDL 必须使用物理 USB 连接。
