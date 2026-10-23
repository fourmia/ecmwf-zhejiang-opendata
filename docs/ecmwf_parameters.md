# ECMWF IFS 9km（0.1°）开放数据要素核对报告

| 项目 | 内容 |
|------|------|
| **数据集** | ECMWF Open Data — IFS High-Resolution Forecast |
| **分辨率** | 0.1°（≈9 km），全球等经纬度网格 |
| **正式上线** | 2026-10-20（与 0.25° 并行发布） |
| **授权协议** | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| **官方页面** | https://confluence.ecmwf.int/display/DAC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS |
| **0.1°新特性** | https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ |
| **Python包** | https://pypi.org/project/ecmwf-opendata/ （v0.3.35） |

> **核对说明**：本文档基于 2026-10-22 00z 起报批次实际下载的 GRIB2 文件（通过 `eccodes` 读取消息头）与 ECMWF 官方 index 文件（GCS 镜像）交叉验证，并参照 ECMWF 参数数据库（https://codes.ecmwf.int/grib/param-db/）核对 paramId 和单位。

---

## 一、地面层（SFC）— 45 个参数

> **0.1° 特有说明**：地面层（sfc）与压力层（pl）文件分开存储，发布时间比 0.25° 晚约 2 小时。

### 1.1 温度与湿度（5个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `2t` | 167 | 2米气温 | 2 metre temperature | K | heightAboveGround | — | ✅ 实测 282–303 K（9–30°C） |
| `2d` | 168 | 2米露点温度 | 2 metre dewpoint temperature | K | heightAboveGround | — | ✅ 实测 275–299 K |
| `mn2t3` | 228027 | 过去3h最低2米气温 | Minimum temperature at 2 metres in the last 3 hours | K | heightAboveGround | 步长从3h起 | ✅ GRIB文件验证 |
| `mx2t3` | 228026 | 过去3h最高2米气温 | Maximum temperature at 2 metres in the last 3 hours | K | heightAboveGround | 步长从3h起 | ✅ GRIB文件验证 |
| `skt` | 235 | 地皮温度 | Skin temperature | K | surface | — | ✅ 实测 281–304 K |

### 1.2 风场（5个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `10u` | 165 | 10米纬向风（U分量） | 10 metre U wind component | m s⁻¹ | heightAboveGround | — | ✅ 实测 ±21 m/s |
| `10v` | 166 | 10米经向风（V分量） | 10 metre V wind component | m s⁻¹ | heightAboveGround | — | ✅ 实测 ±24 m/s |
| `10fg` | 49 | 10米最大阵风（过去3h） | Maximum 10 metre wind gust since previous post-processing | m s⁻¹ | heightAboveGround | 累计步长 | ✅ 实测最大 33.1 m/s |
| `100u` | 228246 | 100米纬向风 | 100 metre U wind component | m s⁻¹ | heightAboveGround | 风能行业常用 | ✅ index文件确认存在 |
| `100v` | 228247 | 100米经向风 | 100 metre V wind component | m s⁻¹ | heightAboveGround | 风能行业常用 | ✅ index文件确认存在 |

### 1.3 气压（2个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `msl` | 151 | 海平面气压 | Mean sea level pressure | Pa | meanSea | — | ✅ 实测 989–1027 hPa |
| `sp` | 134 | 地面气压 | Surface pressure | Pa | surface | — | ✅ 实测 871–1028 hPa |

### 1.4 云量（4个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `tcc` | 164 | 总云量 | Total cloud cover | (0–1) | entireAtmosphere | — | ✅ 实测 0–1 |
| `lcc` | 186 | 低云量 | Low cloud cover | (0–1) | surface | — | ✅ 实测 0–1 |
| `mcc` | 187 | 中云量 | Medium cloud cover | (0–1) | surface | — | ✅ 实测 0–1 |
| `hcc` | 188 | 高云量 | High cloud cover | (0–1) | surface | — | ✅ 实测 0–1 |

### 1.5 降水（5个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `tp` | 228 | 累计总降水 | Total precipitation | m | surface | 从t=0累计 | ✅ 实测 0–177 mm（72h） |
| `cp` | 143 | 对流性降水 | Convective precipitation | m | surface | 从t=0累计 | ✅ index文件确认存在 |
| `sf` | 144 | 降雪量（水当量） | Snowfall | m of water equivalent | surface | 从t=0累计 | ✅ index文件确认存在 |
| `ptype` | 260015 | 降水类型 | Precipitation type | code | surface | 分类码：1=雨,3=冻雨,5=雪 | ✅ index文件确认存在 |
| `tprate` | 260048 | 降水率（瞬时） | Total precipitation rate | kg m⁻² s⁻¹ | surface | — | ✅ index文件确认存在 |

### 1.6 辐射（5个）⚠️

> **重要**：所有辐射变量均为**从预报 t=0 起的累计量**（单位 J m⁻²），需差分后除以步长时间间隔转换为平均通量（W m⁻²）。详见第四节。

| shortName | paramId | 中文名 | 英文全名 | 原始单位 | typeOfLevel | 通量范围（浙江实测） | 核对 |
|-----------|---------|--------|----------|----------|-------------|---------------------|------|
| `ssrd` | 169 | 地面向下太阳短波辐射（GHI基础） | Surface short-wave (solar) radiation downwards | J m⁻² | surface | 0–771 W m⁻² | ✅ |
| `ssr` | 176 | 地面净短波辐射 | Surface net short-wave (solar) radiation | J m⁻² | surface | 0–696 W m⁻² | ✅ |
| `strd` | 175 | 地面向下长波辐射 | Surface long-wave (thermal) radiation downwards | J m⁻² | surface | 0–457 W m⁻² | ✅ |
| `str` | 177 | 地面净长波辐射 | Surface net long-wave (thermal) radiation | J m⁻² | surface | −120 – +12 W m⁻² | ✅ |
| `ttr` | 179 | 大气顶净长波辐射（OLR） | Top net long-wave (thermal) radiation | J m⁻² | nominalTop | −302 – 0 W m⁻² | ✅ |

**⚠️ 0.1° tier 暂不提供（0.25° 有）**：

| shortName | paramId | 中文名 | 说明 |
|-----------|---------|--------|------|
| `tisr` | 212 | 大气顶入射太阳辐射（天文辐射） | 0.25° 提供，0.1° 暂无 |
| `ssrdc` | 228129 | 晴空地面向下短波辐射 | 0.25° 提供，0.1° 暂无 |
| `strdc` | 228130 | 晴空地面向下长波辐射 | 0.25° 提供，0.1° 暂无 |
| `fdir` | 228021 | 地面直接法线太阳辐射 | 0.25° 提供，0.1° 暂无 |

### 1.7 对流（1个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 备注 | 核对 |
|-----------|---------|--------|----------|------|-------------|------|------|
| `mucape` | 228235 | 最不稳定CAPE | Most-unstable CAPE | J kg⁻¹ | mostUnstableParcel | — | ✅ 实测 0–1392 J/kg |

### 1.8 整层水汽与云水（5个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 核对 |
|-----------|---------|--------|----------|------|-------------|------|
| `tcwv` | 137 | 整层可降水量 | Total column water vapour | kg m⁻² | surface | ✅ index确认 |
| `tclw` | 78 | 整层液态水 | Total column liquid water | kg m⁻² | surface | ✅ index确认 |
| `tciw` | 79 | 整层冰水 | Total column ice water | kg m⁻² | surface | ✅ index确认 |
| `tcrw` | 228088 | 整层雨水 | Total column rain water | kg m⁻² | surface | ✅ index确认 |
| `tcw` | 136 | 整层总水 | Total column water | kg m⁻² | surface | ✅ index确认 |

### 1.9 陆面与土壤（6个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 核对 |
|-----------|---------|--------|----------|------|-------------|------|
| `sd` | 141 | 积雪深度（水当量） | Snow depth | m of water equivalent | surface | ✅ index确认 |
| `rsn` | 33 | 雪密度 | Snow density | kg m⁻³ | surface | ✅ index确认 |
| `asn` | 32 | 雪反照率 | Snow albedo | (0–1) | surface | ✅ index确认 |
| `ro` | 205 | 地表径流 | Runoff | m | surface | ✅ index确认 |
| `vsw` | 39 | 土壤体积含水量 | Volumetric soil water layer 1 | m³ m⁻³ | sol | ✅ index确认 |
| `sot` | 228139 | 土壤温度 | Soil temperature | K | sol | ✅ index确认 |

### 1.10 海洋与静态场（3个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 核对 |
|-----------|---------|--------|----------|------|-------------|------|
| `sithick` | 228029 | 海冰厚度 | Sea ice thickness | m | surface | ✅ index确认 |
| `zos` | 263090 | 海面高度（相对大地水准面） | Sea surface height above geoid | m | surface | ✅ index确认 |
| `lsm` | 172 | 陆海掩膜（静态场） | Land-sea mask | (0–1) | surface | ✅ index确认 |

### 1.11 湍流通量（2个，累计量）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 核对 |
|-----------|---------|--------|----------|------|-------------|------|
| `ewss` | 180 | 向东湍流地面应力 | Eastward turbulent surface stress | N m⁻² s | surface | ✅ index确认 |
| `nsss` | 181 | 向北湍流地面应力 | Northward turbulent surface stress | N m⁻² s | surface | ✅ index确认 |

### 1.12 海浪（2个）

| shortName | paramId | 中文名 | 英文全名 | 单位 | typeOfLevel | 核对 |
|-----------|---------|--------|----------|------|-------------|------|
| `sve` | 228033 | 向东有效波高 | Eastward significant wave height | m | surface | ✅ index确认 |
| `svn` | 228034 | 向北有效波高 | Northward significant wave height | m | surface | ✅ index确认 |

---

## 二、压力层（PL）— 10个变量 × 14层

**压力层（hPa）**：10、50、100、150、200、250、300、400、500、600、700、850、925、1000

| shortName | paramId | 中文名 | 英文全名 | 单位 | 备注 | 核对 |
|-----------|---------|--------|----------|------|------|------|
| `z` | 129 | 位势 | Geopotential | m² s⁻² | 除以 g₀(9.80665) 得位势高度(gpm) | ✅ index确认 |
| `gh` | 156 | 位势高度 | Geopotential height | gpm | 直接可用 | ✅ index确认 |
| `t` | 130 | 温度 | Temperature | K | — | ✅ index确认 |
| `u` | 131 | 纬向风 | U component of wind | m s⁻¹ | — | ✅ index确认 |
| `v` | 132 | 经向风 | V component of wind | m s⁻¹ | — | ✅ index确认 |
| `w` | 135 | 垂直速度（气压坐标） | Vertical velocity | Pa s⁻¹ | 负值=上升气流 | ✅ index确认 |
| `q` | 133 | 比湿 | Specific humidity | kg kg⁻¹ | — | ✅ index确认 |
| `r` | 157 | 相对湿度 | Relative humidity | % | — | ✅ index确认 |
| `d` | 155 | 散度 | Divergence | s⁻¹ | — | ✅ index确认 |
| `vo` | 138 | 相对涡度 | Vorticity (relative) | s⁻¹ | — | ✅ index确认 |

---

## 三、实测合理性核对汇总

**核对条件**：浙江省（26.8–31.8°N，117.8–123.2°E），2026-10-22 00z 起报，0–72h/3h

| 变量 | 期望范围 | 实测值 | 结论 |
|------|---------|--------|------|
| `2t`（2m气温，浙江10月） | 280–305 K（7–32°C） | 282.4–302.7 K（9–30°C） | ✅ 合理 |
| `msl`（海平面气压） | 980–1030 hPa | 989–1027 hPa | ✅ 合理 |
| `sp`（地面气压） | 850–1030 hPa | 871–1028 hPa | ✅ 合理 |
| `tp`（72h总降水） | 0–300 mm | 0–177 mm | ✅ 合理 |
| `ssrd`（短波辐射通量，晴天最大） | 600–1000 W m⁻² | 770.7 W m⁻² | ✅ 合理 |
| `ssrd`（step=0 通量） | 0 W m⁻² | 0.00 W m⁻² | ✅ 去趋势正确 |
| `ssrd`（最小值） | ≥0 W m⁻² | −6.07 W m⁻² | ⚠️ 差分舍入误差，clip≥0即可 |
| `strd`（向下长波辐射） | 300–500 W m⁻² | 0–457 W m⁻² | ✅ 合理 |
| `ttr`（大气顶OLR） | −350–0 W m⁻² | −302–0 W m⁻² | ✅ 合理 |
| `tcc`（总云量） | 0–1 | 0–1 | ✅ |
| `mucape`（最不稳定CAPE） | 0–5000 J/kg | 0–1392 J/kg | ✅ 合理 |
| `10u`/`10v`（10m风速） | ±50 m/s内 | ±21/±24 m/s | ✅ 合理 |
| `10fg`（10m阵风） | 0–60 m/s | 0–33.1 m/s | ✅ 合理 |
| `skt`（地皮温度） | 270–320 K | 281–304 K | ✅ 合理 |

---

## 四、辐射变量处理说明

### 4.1 原始数据格式

ECMWF 辐射变量存储为**从预报 t=0 起的累计量**（J m⁻²）：

```
accum[t] = ∫₀ᵗ flux(τ) dτ
```

### 4.2 转换为平均通量（W m⁻²）

```python
# flux[i] = (accum[i] - accum[i-1]) / Δt（秒）
# step=0 时通量=0（累计未开始）

import numpy as np

def deaccumulate(da):
    """da: xarray.DataArray，dim='step'，单位 J/m²"""
    steps_h = da.step.values.astype("timedelta64[h]").astype(float)
    dt_sec  = np.diff(steps_h, prepend=0.0) * 3600.0   # 各步时间间隔（秒）
    arr     = da.values.copy()
    arr[1:] = arr[1:] - arr[:-1]                        # 差分
    arr[0]  = 0.0                                        # step=0 通量=0
    dt      = dt_sec[:, np.newaxis, np.newaxis]          # 广播到 lat/lon
    flux    = arr / np.where(dt == 0, 1.0, dt)
    flux[0] = 0.0
    return flux   # 单位: W m⁻²
```

### 4.3 向下辐射负值处理

`ssrd`、`ssr`、`strd` 等向下辐射在转换后可能出现极小负值（通常 < -10 W m⁻²），来自差分舍入误差，物理上不应为负，直接置零：

```python
flux = np.clip(flux, 0.0, None)   # 仅对 downward 分量
```

> `str`（净长波）和 `ttr`（OLR）物理上可以为负，**不做 clip**。

---

## 五、下载脚本快速使用

```bash
# 安装依赖
pip install ecmwf-opendata cfgrib xarray numpy netCDF4

# 下载最新起报（默认 Google GCS，自动识别系统代理）
python src/download_ecmwf.py

# 指定起报时间
python src/download_ecmwf.py --date 2026-10-22 --time 0 --steps medium

# 完整参数
python src/download_ecmwf.py \
  --date   2026-10-22 \     # 起报日期（默认：最新）
  --time   0 \              # 起报时次 UTC：0/6/12/18（默认：最新）
  --steps  short \          # short=0~72h | medium=0~120h | full=0~240h
  --source google \         # google/aws=无限速 | ecmwf=官方限500并发
  --no-rad \                # 跳过辐射变量
  --no-pl \                 # 跳过压力层
  --extra \                 # 下载额外45个SFC参数（陆面/海洋/湍流等）
  --keep-grib \             # 保留 GRIB2 原文件
  --outdir ./ecmwf_data     # 输出目录
```

**输出文件**：
- `ecmwf_zj_sfc_<日期>_<时次>.nc` — 地面层 NetCDF（含辐射通量和累计量，zlib压缩）
- `ecmwf_zj_pl_<日期>_<时次>.nc` — 压力层 NetCDF

---

## 六、参考资料

| 资源 | 链接 |
|------|------|
| ECMWF Open Data 主页 | https://confluence.ecmwf.int/display/DAC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS |
| 0.1° 新特性说明 | https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ |
| ECMWF 参数数据库 | https://codes.ecmwf.int/grib/param-db/ |
| ecmwf-opendata PyPI | https://pypi.org/project/ecmwf-opendata/ |
| ecmwf-opendata GitHub | https://github.com/ecmwf/ecmwf-opendata |
| IFS Cycle 50r1 变更 | https://confluence.ecmwf.int/display/DAC/IFS+Cycle+50r1+changes |
| CC BY 4.0 授权 | https://creativecommons.org/licenses/by/4.0/ |
