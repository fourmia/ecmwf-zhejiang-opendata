# ecmwf-zhejiang-opendata

ECMWF 数据下载工具集 — 浙江省区域。两条独立数据线：

| 数据线 | 脚本 | 类型 | 分辨率 | 时效 | 时延 | 格式 |
|--------|------|------|--------|------|------|------|
| **IFS 0.1° 实时预报** | `src/download_ecmwf.py`<br>`src/cron_fetch_ecmwf.py` | 数值预报 | 0.1°（≈9 km） | 0–360h | ~9h | GRIB2 |
| **ARCO-ERA5 再分析** | `src/cron_fetch_era5.py` | 历史再分析 | 0.25° | 1940 至今 | ~6 天 | NetCDF4 |

实时预报取未来，再分析补历史。两者分辨率不同（0.1° 仅实时预报提供），不可互相替代。

---

## 目录结构

```
ecmwf-zhejiang-opendata/
├── README.md
├── docs/
│   ├── ecmwf_parameters.md        # 参数核对报告（45 SFC + 10 PL × 14 层，三重来源验证）
│   ├── DATA_CHANNEL_SPEC.md       # 数据通道规范（步长、文件大小、存储规划）
│   ├── VERIFICATION_360H.md       # 360h 时效验证（修正早期 240h 错误）
│   └── TEST_FOUR_CYCLES_FINAL.md  # 四时次完整实测报告
├── src/
│   ├── ecmwf_common.py            # 单一来源：参数、压力层、步长、代理检测
│   ├── download_ecmwf.py          # 单次下载：GRIB2 → 裁剪浙江 → NetCDF4
│   ├── download_gcs_batch.py      # GCS 原始整文件：仅代理、断点续传、MD5、配套索引
│   ├── cron_fetch_ecmwf.py        # 业务化：自动起报时次 + 全时长 + 重试
│   ├── cron_fetch_era5.py         # ERA5：GCS 公开桶直取
│   └── requirements.txt
└── tests/
    ├── test_common_consistency.py # 定义一致性检查（离线）
    ├── test_grib_to_netcdf.py     # 后处理回归（离线，用 samples/ 基准）
    ├── test_retry_call.py         # 重试原语行为测试（离线）
    ├── test_all_cycles.py         # 四时次并发测试（00z/12z 85步，06z/18z 31步）
    ├── test_06z_18z_3h.py         # 3h 步长实测（真实存在）
    └── test_06z_18z_latest.py     # 1h 步长验证（确认不存在）
```

---

## 安装

```bash
# Python 3.9+
pip install -r src/requirements.txt
```

所有参数清单、压力层列表、步长预设、代理检测与重试原语**只在 `src/ecmwf_common.py` 定义一次**，
三个脚本共享，避免多处硬编码漂移。

`eccodes` 是系统库，不能用 pip 装（必须 ≥ 2.25，支持 CCSDS/AEC 解码）：

```bash
brew install eccodes          # macOS
apt-get install libeccodes-dev # Debian/Ubuntu
```

---

## 一、IFS 0.1° 实时预报

ECMWF 自 2026-10-20 起将 IFS 高分辨率预报（约 9 km）以 0.1° 免费开放，与 0.25° 并行发布。GRIB2 + CCSDS（AEC）压缩，按参数调整每值比特数。授权 **CC BY 4.0**。

### 起报时次与时效（实测，已修正官方错误）

| 时次 | 批次 | 时效 | 步长 | 步数 | 单变量大小 |
|------|------|------|------|------|-----------|
| 00z / 12z | 主批次 | 0–360h | 0–144h/3h + 150–360h/6h | **85** | ~117 MB |
| 06z / 18z | 辅助批次 | 0–90h | **3h** | **31** | ~42 MB |

> ⚠️ 官方文档称 06z/18z 为 1h/91 步，实测 GCS 无 1h 文件（404），实际仅 **3h/31 步**。
> 地面层（`-sfc`）与压力层（`-pl`）**分文件发布**，均 0.1°，比 0.25° 晚约 2 小时。

### 快速开始

```bash
# 最新起报，短期（0–72h），仅地面层
python src/download_ecmwf.py --no-pl

# 指定起报，中期（0–120h）
python src/download_ecmwf.py --date 2026-10-22 --time 0 --steps medium

# 完整 360h（85 步），含压力层
python src/download_ecmwf.py --steps full

# 全部 45 个 SFC 参数（陆面/海洋/海浪等）
python src/download_ecmwf.py --extra --no-pl

# 业务化：自动推算最新可用起报时次
python src/cron_fetch_ecmwf.py --params 2t,10u,10v,tp,msl --outdir /data/ecmwf
```

> 起报时次为 06z/18z 时，`--steps full` 会自动裁剪为 0–90h（31 步），不会去请求不存在的 150–360h 时效。

输出：

```
ecmwf_data/
├── ecmwf_zj_sfc_20261022_00z.nc   # 地面层（浙江裁剪，zlib 压缩）
└── ecmwf_zj_pl_20261022_00z.nc    # 压力层（可选）
```

### 原始整文件归档（断点续传与 MD5 校验）

`src/download_gcs_batch.py` 保存 GCS 发布的逐时效原始 GRIB2 和配套 `.index`，
默认先地面层（含土壤层）、再压力层；不裁剪、不转 NetCDF。仅使用标准库及项目共享步长定义。
必须配置代理；可用 `--proxy` 显式指定，也可读取系统/环境 HTTPS 代理。

```bash
python src/download_gcs_batch.py \
  --date 20261125 --time 12 \
  --outdir "/Volumes/T7 Shield/EC_IFS_0P01" \
  --require-mount "/Volumes/T7 Shield" \
  --proxy http://127.0.0.1:1082

# 仅补齐地面层和压力层的索引
python src/download_gcs_batch.py \
  --date 20261125 --time 12 \
  --outdir "/Volumes/T7 Shield/EC_IFS_0P01" \
  --require-mount "/Volumes/T7 Shield" \
  --proxy http://127.0.0.1:1082 --index-only
```

输出位于 `{outdir}/{date}/{time:02d}z/`；GRIB2 在该目录下，索引分别在
`index/sfc/` 和 `index/pl/`。重复运行相同命令会校验并跳过已完成文件，
从 `.part` 字节位置继续下载；MD5 与 GCS 元数据匹配后才改为正式文件名。
已有正式文件校验失败时停止并保留文件。传输超时/SSL 错误会自动重试，
连续 8 次无进展后退出，需重新运行命令；不会切换为直连。

该脚本要求共享步长定义中的文件全部已发布；批次过旧已被源端清除或文件缺失时会停止。
20261125 12z 的完整实测结果见 [下载记录](docs/GCS_BATCH_20261125_12Z.md)。

### 命令行参数

```
usage: download_ecmwf.py [-h]
  [--date DATE]         起报日期 YYYYMMDD 或 YYYY-MM-DD（默认：最新）
  [--time {0,6,12,18}]  起报时次 UTC（默认：最新）
  [--steps {short,medium,full}]
                        short=0~72h | medium=0~120h | full=0~360h（85步）
  [--source {aws,google,azure,ecmwf}]
                        数据源（默认：google）
  [--no-rad]            跳过辐射变量
  [--no-pl]             跳过压力层
  [--extra]             下载扩展 SFC 参数（100m风/陆面/海洋等共24个）
  [--proxy PROXY]       HTTP代理，如 http://127.0.0.1:1082（macOS自动检测）
  [--outdir OUTDIR]     输出目录（默认：./ecmwf_data）
  [--keep-grib]         保留原始 GRIB2（默认转NetCDF后删除）
  [--grib-only]         仅下载 GRIB2，不转 NetCDF
  [--retry N]           下载失败重试次数（含首次，默认 3）
  [--retry-delay SEC]   两次尝试之间的等待秒数（默认 60）
```

### 数据源

| source | 地址 | 限速 | 适用场景 |
|--------|------|------|---------|
| `google` | GCS `ecmwf-open-data` | 无 | **推荐**，国内代理稳定 |
| `aws` | S3 `eu-central-1` | 无 | 部署在 AWS 时首选 |
| `azure` | Azure Blob | 无（需 SAS token） | 部署在 Azure 时 |
| `ecmwf` | data.ecmwf.int | 500–2000 并发 | 调试/备用 |

### 输出变量

**地面层（SFC）** — 默认 21 个核心变量，`--extra` 补足 45 个

| NetCDF 变量 | shortName | 含义 | 单位 |
|------------|-----------|------|------|
| `t2m` | `2t` | 2米气温 | K |
| `d2m` | `2d` | 2米露点温度 | K |
| `mn2t3` | `mn2t3` | 过去3h最低2米气温 | K |
| `mx2t3` | `mx2t3` | 过去3h最高2米气温 | K |
| `skt` | `skt` | 地皮温度 | K |
| `u10` / `v10` | `10u` / `10v` | 10米风分量 | m s⁻¹ |
| `p49` | `10fg` | 过去3h最大10米阵风 | m s⁻¹ |
| `msl` / `sp` | `msl` / `sp` | 海平面气压 / 地面气压 | Pa |
| `tp` | `tp` | 累计总降水 | m |
| `tcc` / `lcc` / `mcc` / `hcc` | — | 总/低/中/高云量 | 0–1 |
| `mucape` | `mucape` | 最不稳定CAPE | J kg⁻¹ |
| `ssrd` | `ssrd` | 地面向下短波辐射**通量** | **W m⁻²** |
| `ssrd_accum` | `ssrd` | 同上，原始累计量 | J m⁻² |
| `ssr` / `strd` / `str` / `ttr` | — | 净短波/向下长波/净长波/OLR **通量** | **W m⁻²** |

> **辐射变量**：GRIB 原始为累计量（J m⁻²），脚本自动差分转换为各步长平均通量（W m⁻²），同时保留累计量（`<var>_accum`）。向下辐射已 clip 至 ≥0（消除差分舍入误差）；`str`/`ttr` 为净辐射，保留负值。

**压力层（PL）** — 10 变量 × 14 层（10–1000 hPa）

`z`（位势）、`gh`（位势高度）、`t`（温度）、`u`/`v`（风）、`w`（垂直速度）、`q`（比湿）、`r`（相对湿度）、`d`（散度）、`vo`（相对涡度）

压力层：10, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000 hPa

### 读取示例

```python
import xarray as xr, numpy as np

ds = xr.open_dataset("ecmwf_data/ecmwf_zj_sfc_20261022_00z.nc")

t2m_c   = ds["t2m"] - 273.15                                    # K → °C
ssrd_24 = ds["ssrd"].sel(step=np.timedelta64(24, "h"))           # W/m²
tp_72   = ds["tp"].sel(step=np.timedelta64(72, "h")) * 1000      # m → mm
ws10    = np.sqrt(ds["u10"]**2 + ds["v10"]**2)                   # 风速
```

---

## 二、ARCO-ERA5 再分析

从 GCS 公开桶 `gs://gcp-public-data-arco-era5` 直取，无需认证。0.25°（721×1440），1h 分辨率，1940 年至今，滞后约 6 天。

### 快速开始

```bash
# 查看要素预设
python src/cron_fetch_era5.py --list-presets

# 最新可用日期的标准要素集
python src/cron_fetch_era5.py --outdir ./era5_data

# 指定日期 + 要素
python src/cron_fetch_era5.py --date 2026-11-17 --params 2t,2d,10u,10v,tp,msl

# 压力层（指定变量与层次）
python src/cron_fetch_era5.py --date 2026-11-17 --no-sfc --pl \
    --pl-vars z,t,u,v,q --pl-levels 1000,925,850,700,500,300,200
```

### 要素预设

| 预设 | 变量 |
|------|------|
| `minimal` | 2t, 2d, 10u, 10v, tp, msl |
| `standard` | 2t, 2d, 10u, 10v, 10fg, tp, msl, sp, tcc, cape, ssrd, strd |
| `full_met` | 全部 27 个已映射地面变量 |

支持 27 个地面变量与 7 个压力层变量（`z`/`t`/`u`/`v`/`w`/`q`/`r`）× 37 个标准层。

### 实测参考（2026-10-28，经代理）

- 单变量 `2t`：34 MB，24 时次 × 721 × 1440 格点
- 温度范围 −59.5 ~ +43.9 °C（全球）
- `minimal` 六变量：215 MB，全部成功，约 5 分钟

### 与实时预报的分工

- **补历史 / 训练样本** → ERA5
- **未来 0–15 天预报** → IFS 0.1°

ERA5 无 0.1° 版本；若业务要求 0.1°，只能用 IFS 实时预报。

---

## 测试

```bash
python3 tests/test_common_consistency.py   # 定义一致性（离线）
python3 tests/test_retry_call.py           # 重试行为（离线）
python3 tests/test_grib_to_netcdf.py       # 后处理回归（离线，需 cfgrib + samples/ 基准）
```

联网测试脚本（四时次、1h 步长验证）在 `tests/` 下，需代理与 `eccodes`。

## 网络与代理

macOS 自动读取系统代理（`scutil --proxy`）并注入 `HTTP_PROXY`/`HTTPS_PROXY`，无需手动配置。Linux/Windows 用环境变量或 `--proxy`：

```bash
export HTTPS_PROXY=http://proxy.example.com:1082
python src/download_ecmwf.py --proxy http://127.0.0.1:1082
```

---

## 已知问题

| 问题 | 原因 | 处理 |
|------|------|------|
| `10fg` 读为 `p49` | cfgrib 无标准 CF 名 | 已知，按 `p49` 访问 |
| `mn2t3`/`mx2t3` 覆盖 `t2m` | cfgrib 三者同读为 `t2m` | 已按 paramId 重命名，透明处理 |
| `ssrd` 极小负值 | 差分舍入误差 | 已 clip≥0；`str`/`ttr` 保留负值 |
| `vsw`/`sot` 默认不在输出 | typeOfLevel=sol | 加 `--extra` |
| 0.1° 无晴空辐射 | 官方暂未发布 | `tisr`/`ssrdc`/`strdc`/`fdir` 待公告 |
| 06z/18z 无 1h 步长 | 官方文档有误 | 实际 3h/31 步，见 `docs/DATA_CHANNEL_SPEC.md` |
| 单步 GRIB 无法算通量 | 累计量需前一步差分 | 该变量保留累计量、跳过通量转换并告警 |
| 大请求仍偶发截断 | 传输层不稳定 | 两个脚本均带重试（`--retry`），重试前自动删除半文件 |

---

## 文档

- [参数核对报告](docs/ecmwf_parameters.md) — 45 SFC + 10 PL × 14 层，GRIB index / eccodes / NetCDF 三重验证
- [数据通道规范](docs/DATA_CHANNEL_SPEC.md) — 步长规律、文件大小、存储规划
- [360h 时效验证](docs/VERIFICATION_360H.md) — 修正早期 240h 错误
- [四时次实测报告](docs/TEST_FOUR_CYCLES_FINAL.md) — 00z/06z/12z/18z 完整测试

## 参考

- [ECMWF Open Data 主页](https://confluence.ecmwf.int/display/DAC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS)
- [0.1° 新特性说明](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/)
- [ecmwf-opendata PyPI](https://pypi.org/project/ecmwf-opendata/)
- [ECMWF 参数数据库](https://codes.ecmwf.int/grib/param-db/)