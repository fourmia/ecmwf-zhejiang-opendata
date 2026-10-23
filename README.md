# ecmwf-zhejiang-opendata

ECMWF IFS 0.1°（≈9 km）开放数据下载工具 — 浙江省区域

从 ECMWF 免费开放数据中下载最新高分辨率数值预报，自动裁剪至浙江省，转为压缩 NetCDF4 输出，辐射量自动完成累计→通量转换。

---

## 背景

ECMWF 自 2026-10-20 起将 IFS 高分辨率预报（原内部约 9 km）以 **0.1° 分辨率**对外免费开放，与原有 0.25° 数据并行发布。文件采用 **GRIB2 + CCSDS（AEC）压缩**，按参数调整每值比特数（Bits per value）。数据授权协议为 **CC BY 4.0**（署名即可免费使用）。

| 项目 | 值 |
|------|----|
| 分辨率 | 0.1°（≈9 km），3600 × 1801 全球格点 |
| 起报时次 | 00z / 06z / 12z / 18z UTC |
| 预报时效 | 00z/12z：0–144h（3h步）＋ 150–360h（6h步） |
| 延迟 | 比 0.25° 晚约 2 小时发布 |
| 并发限制 | ECMWF 官方 500–2000 连接；云镜像无限制 |
| 授权 | CC BY 4.0 |

---

## 安装

```bash
# Python 3.9+
pip install ecmwf-opendata cfgrib xarray numpy netCDF4
```

eccodes 需支持 CCSDS/AEC 解码器（`eccodes >= 2.25`，cfgrib `>= 0.9.10`）：

```bash
# macOS
brew install eccodes

# Ubuntu/Debian
apt-get install libeccodes-dev
```

---

## 快速开始

```bash
# 下载最新起报，短期（0–72h），仅地面层
python src/download_ecmwf.py --no-pl

# 指定起报时间，中期预报（0–120h）
python src/download_ecmwf.py --date 2026-10-22 --time 0 --steps medium

# 完整 10 天，包含压力层
python src/download_ecmwf.py --steps full

# 下载全部 45 个 SFC 参数（含陆面/海洋等）
python src/download_ecmwf.py --extra --no-pl
```

输出文件：

```
ecmwf_data/
├── ecmwf_zj_sfc_20261022_00z.nc   # 地面层（50×54格点，压缩）
└── ecmwf_zj_pl_20261022_00z.nc    # 压力层（可选）
```

---

## 全部参数说明

```
usage: download_ecmwf.py [-h]
  [--date DATE]         起报日期 YYYYMMDD 或 YYYY-MM-DD（默认：最新）
  [--time {0,6,12,18}]  起报时次 UTC（默认：最新）
  [--steps {short,medium,full}]
                        short=0~72h | medium=0~120h | full=0~240h（默认：short）
  [--source {aws,google,azure,ecmwf}]
                        数据源（默认：google）
  [--no-rad]            跳过辐射变量
  [--no-pl]             跳过压力层
  [--extra]             下载扩展 SFC 参数（100m风/陆面/海洋等共24个）
  [--proxy PROXY]       HTTP代理，如 http://127.0.0.1:1082（macOS自动检测）
  [--outdir OUTDIR]     输出目录（默认：./ecmwf_data）
  [--keep-grib]         保留原始 GRIB2（默认转NetCDF后删除）
  [--grib-only]         仅下载 GRIB2，不转 NetCDF
```

### 数据源选择

| source | 地址 | 速度限制 | 适用场景 |
|--------|------|---------|---------|
| `google` | GCS `ecmwf-open-data` | 无 | **推荐**，国内代理稳定 |
| `aws` | S3 `eu-central-1` | 无 | 部署在 AWS 时首选 |
| `azure` | Azure Blob | 无（需 SAS token） | 部署在 Azure 时 |
| `ecmwf` | data.ecmwf.int | 500–2000 并发 | 调试/备用 |

---

## 输出变量说明

### 地面层（SFC）— 核心 21 个变量（默认下载）

| 变量名（NetCDF） | shortName | 含义 | 单位 |
|-----------------|-----------|------|------|
| `t2m` | `2t` | 2米气温 | K |
| `d2m` | `2d` | 2米露点温度 | K |
| `mn2t3` | `mn2t3` | 过去3h最低2米气温 | K |
| `mx2t3` | `mx2t3` | 过去3h最高2米气温 | K |
| `skt` | `skt` | 地皮温度 | K |
| `u10` | `10u` | 10米纬向风 | m s⁻¹ |
| `v10` | `10v` | 10米经向风 | m s⁻¹ |
| `p49` | `10fg` | 10米最大阵风（过去3h） | m s⁻¹ |
| `msl` | `msl` | 海平面气压 | Pa |
| `sp` | `sp` | 地面气压 | Pa |
| `tp` | `tp` | 累计总降水 | m |
| `tcc` | `tcc` | 总云量 | 0–1 |
| `lcc` / `mcc` / `hcc` | — | 低/中/高云量 | 0–1 |
| `mucape` | `mucape` | 最不稳定CAPE | J kg⁻¹ |
| `ssrd` | `ssrd` | 地面向下短波辐射通量（GHI基础） | **W m⁻²** |
| `ssrd_accum` | `ssrd` | 同上，原始累计量 | J m⁻² |
| `ssr` / `strd` / `str` / `ttr` | — | 净短波/向下长波/净长波/OLR 通量 | **W m⁻²** |

> **辐射变量**：原始 GRIB 为累计量（J m⁻²），脚本自动差分转换为各步长平均通量（W m⁻²），同时保留原始累计量（`<var>_accum`）。向下辐射已 clip 至 ≥0（消除差分舍入误差）。

### 压力层（PL）— 10 变量 × 14 层（10–1000 hPa）

`z`（位势）、`gh`（位势高度）、`t`（温度）、`u`/`v`（风场）、`w`（垂直速度）、`q`（比湿）、`r`（相对湿度）、`d`（散度）、`vo`（相对涡度）

---

## 读取输出文件示例

```python
import xarray as xr
import numpy as np

# 打开地面层文件
ds = xr.open_dataset("ecmwf_data/ecmwf_zj_sfc_20261022_00z.nc")

# 2米气温（K → °C）
t2m = ds["t2m"] - 273.15

# 24h预报的地面向下短波辐射通量（W/m²）
ssrd_24h = ds["ssrd"].sel(step=np.timedelta64(24, "h"))

# 累计总降水（m → mm）
tp_72h = ds["tp"].sel(step=np.timedelta64(72, "h")) * 1000

# 10米风速合成
ws10 = np.sqrt(ds["u10"]**2 + ds["v10"]**2)
```

---

## 网络与代理

脚本在 macOS 上自动读取系统代理（通过 `scutil --proxy`）并注入 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量，无需手动配置。Linux/Windows 服务器直连或设置环境变量：

```bash
# Linux 服务器
export HTTPS_PROXY=http://proxy.example.com:1082
python src/download_ecmwf.py

# 手动指定
python src/download_ecmwf.py --proxy http://127.0.0.1:1082
```

---

## 已知问题

| 问题 | 原因 | 处理方式 |
|------|------|---------|
| `10fg` 读为 `p49` | cfgrib 无标准 CF 名 | 已知，使用时按 `p49` 访问 |
| `mn2t3`/`mx2t3` 合并冲突 | cfgrib 均读为 `t2m` | 已按 paramId 重命名，透明处理 |
| `ssrd` 出现极小负值 | 差分舍入误差 | 已 clip≥0，`str`/`ttr` 保留负值 |
| `vsw`/`sot` 默认不在输出 | typeOfLevel=sol | 加 `--extra` 下载 |
| 0.1° 无晴空辐射 | 官方暂未发布 | `tisr`/`ssrdc`/`strdc`/`fdir` 待 ECMWF 公告 |

---

## 参考

- [ECMWF Open Data 主页](https://confluence.ecmwf.int/display/DAC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS)
- [0.1° 新特性说明](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/)
- [ecmwf-opendata PyPI](https://pypi.org/project/ecmwf-opendata/)
- [ECMWF 参数数据库](https://codes.ecmwf.int/grib/param-db/)
- [参数核对报告](docs/ecmwf_parameters.md)
