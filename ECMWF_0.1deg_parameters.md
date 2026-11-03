# ECMWF IFS 0.1° 高分辨率预报数据要素清单

## 概述

ECMWF（欧洲中期天气预报中心）于 **2026 年 10 月 20 日**通过 Open Data 计划发布了 **9 km（0.1°）**分辨率的 IFS 全球预报数据，是现有 0.25° 数据的升级版本。本文档列出所有可用要素并与[官方文档](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ECMWF+open+data+what+s+new+at+0.1%C2%B0)核对。

---

## 数据规格

| 项目 | 说明 |
|-----|-----|
| **空间分辨率** | 0.1° × 0.1°（约 9 km 赤道处） |
| **数据格式** | GRIB2 |
| **预报层次** | 地面单层（`levtype=sfc`） |
| **起报时次** | 00z/06z/12z/18z UTC（每天 4 次） |
| **预报步长** | 00z/12z: 0–144h（3h）+ 150–360h（6h）<br>06z/18z: 0–90h（**3h**，31步）⚠️ 官方文档所写1h/91步有误 |
| **覆盖范围** | 全球（0–360°E, 90°S–90°N） |
| **数据源** | AWS, Google Cloud, Azure, ECMWF（推荐 Google Cloud，国内代理友好） |

---

## 要素列表（官方声明 28 个核心变量；index 文件实际含 45 个）

### 温度相关（5 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `2t` | 2 metre temperature | K | 2米温度（瞬时） |
| `2d` | 2 metre dewpoint temperature | K | 2米露点温度 |
| `skt` | Skin temperature | K | 表面皮肤温度 |
| `mn2t3` | Minimum temperature at 2 metres since previous post-processing | K | 2米最低温度（过去3小时） |
| `mx2t3` | Maximum temperature at 2 metres since previous post-processing | K | 2米最高温度（过去3小时） |

### 风相关（5 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `10u` | 10 metre U wind component | m/s | 10米东西向风速 |
| `10v` | 10 metre V wind component | m/s | 10米南北向风速 |
| `10fg` | Maximum 10 metre wind gust since previous post-processing | m/s | **过去3小时最大阵风**（stepType=max，非瞬时值） |
| `100u` | 100 metre U wind component | m/s | 100米东西向风速 |
| `100v` | 100 metre V wind component | m/s | 100米南北向风速 |

### 气压相关（2 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `msl` | Mean sea level pressure | Pa | 海平面气压 |
| `sp` | Surface pressure | Pa | 地表气压 |

### 降水与冰雪（3 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `tp` | Total precipitation | m | 总降水量（累积） |
| `cp` | Convective precipitation | m | 对流性降水（累积） |
| `sf` | Total snowfall | m | 总降雪量（水当量，累积） |

### 云量相关（4 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `tcc` | Total cloud cover | 0–1 | 总云量 |
| `lcc` | Low cloud cover | 0–1 | 低云量 |
| `mcc` | Medium cloud cover | 0–1 | 中云量 |
| `hcc` | High cloud cover | 0–1 | 高云量 |

### 辐射相关（5 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `ssrd` | Surface solar radiation downwards | J/m² | 地表短波辐射（累积） |
| `strd` | Surface thermal radiation downwards | J/m² | 地表长波辐射（累积） |
| `ssr` | Surface net solar radiation | J/m² | 地表净短波辐射（累积） |
| `str` | Surface net thermal radiation | J/m² | 地表净长波辐射（累积） |
| `ttr` | Top net thermal radiation | J/m² | 大气顶净长波辐射/OLR（累积，**向外为负**，有效统计量看 min） |

### 水汽相关（3 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `tcwv` | Total column water vapour | kg/m² | 大气柱总水汽 |
| `tclw` | Total column cloud liquid water | kg/m² | 大气柱云液水 |
| `tciw` | Total column cloud ice water | kg/m² | 大气柱云冰水 |

### 对流与其他（2 个）

| shortName | 全名 | 单位 | 说明 |
|-----------|-----|-----|-----|
| `mucape` | Most unstable CAPE | J/kg | 最不稳定对流有效位能 |
| `ptype` | Precipitation type | code | 降水类型（分类码） |

---

## 与官方文档对比核验

### ✅ 官方声明 28 个，index 文件实际含 45 个

官方文档列出核心 28 个地面要素。从 Google Cloud Storage index 文件直接读取，实际可用 **45 个** shortName：

```
100u, 100v, 10fg, 10u, 10v, 2d, 2t, asn, cp, ewss, hcc, lcc, lsm,
mcc, mn2t3, msl, mucape, mx2t3, nsss, ptype, ro, rsn, sd, sf,
sithick, skt, sot, sp, ssr, ssrd, str, strd, sve, svn, tcc, tciw,
tclw, tcrw, tcw, tcwv, tp, tprate, ttr, vsw, zos
```

本文档重点列出常用 28 个变量，其余参数可按需请求。

### 已知问题

1. **辐射变量符号约定**
   - `ssrd`/`strd` 向下辐射：夜间差分后因数值噪声可能出现小负值（约 -1 W/m²），后处理截断为 0 即可。
   - `str`/`ttr` 净辐射与 OLR：**正常为负值**（向外辐射定义为负），`max≈0` 属正常，有效统计量应看 `min`。

2. **累积变量计算**  
   辐射（`ssrd`/`strd`/`ssr`/`str`/`ttr`）和降水（`tp`/`cp`/`sf`）为**累积值**（从起报时间开始），需差分计算小时累积量：  
   `hourly_value = step_N - step_(N-1)`

3. **06z/18z 时次覆盖**（⚠️ 已更正）
   06z/18z 提供 0–90h，步长 **3h**（31步）。**不存在官方声称的 1h 步长文件**（GCS index 文件 404 验证）。00z/12z 提供完整 **0–360h**（15天，85步），非早期所述 240h。

---

## 推荐配置方案

### 最小集合（6 个核心要素）
用于快速验证或资源受限场景：
```
2t,2d,10u,10v,tp,msl
```

### 标准集合（12 个常用要素）
覆盖温度、风、降水、气压、云量、辐射：
```
2t,2d,10u,10v,tp,msl,sp,tcc,10fg,mucape,ssrd,strd
```

### 完整集合（28 个核心要素）
用于科研或完整归档：
```
2t,2d,mn2t3,mx2t3,skt,10u,10v,10fg,100u,100v,msl,sp,tp,cp,sf,ptype,tcc,lcc,mcc,hcc,mucape,ssrd,strd,ssr,str,ttr,tcwv,tclw,tciw
```

---

## 下载脚本说明

本项目提供的 `cron_fetch_ecmwf.py` 脚本支持：
- 自动推算起报时间（滞后8小时避免数据未就绪）
- 下载全时长（00z/12z: 0–360h / 85步；06z/18z: 0–90h / 3h / 31步）
- 失败自动重试
- 代理自动检测（macOS）
- 输出原始 GRIB2（无后处理）

示例：
```bash
python cron_fetch_ecmwf.py \
  --params 2t,2d,10u,10v,tp,msl,ssrd \
  --outdir /data/ecmwf/{date}/{time} \
  --logfile /var/log/ecmwf_fetch.log
```

详见脚本顶部文档字符串。

---

## 参考资料

1. [ECMWF Open Data: What's new at 0.1°](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ECMWF+open+data+what+s+new+at+0.1%C2%B0)
2. [ecmwf-opendata Python 客户端](https://github.com/ecmwf/ecmwf-opendata)
3. [GRIB2 参数表](https://codes.ecmwf.int/grib/param-db/)

---

**最初核对日期**: 2026-10-23
**勘误更新日期**: 2026-10-26
**核对人**: Kiro (Claude Opus 5.5)
**勘误说明**:
- 06z/18z 步长：1h/91步 → **3h/31步**（实测更正，官方文档有误）
- 00z/12z 时效：240h → **360h**（实测更正）
- `10fg`："瞬时阵风" → **过去3小时最大阵风**（stepType=max）
- `ttr`：补充负值说明（向外辐射为负）
- 变量总数：官方 28 个，index 文件实际含 **45 个**
