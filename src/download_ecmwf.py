#!/usr/bin/env python3
"""
ECMWF IFS 0.1° 浙江省预报数据下载脚本
=====================================
数据源  : AWS S3（无连接数限制）/ Google GCS / Azure / ECMWF官方
分辨率  : 0.1°（≈9 km），IFS高分辨率预报
覆盖范围: 浙江省（下载全球后自动裁剪，含0.2°缓冲）
输出格式: NetCDF4（裁剪后，压缩存储）；原始 GRIB2 可选保留

依赖安装:
    pip install ecmwf-opendata cfgrib xarray numpy netCDF4

辐射变量说明:
    ECMWF 所有辐射变量均为从预报 t=0 起的「累计量」（J/m²）。
    本脚本自动差分并除以时间间隔，转换为各步长平均通量（W/m²）。
    原累计量以 <var>_accum 保留在 NetCDF 中。

使用示例:
    # 下载最新起报（默认 short=0~72h，AWS S3）
    python download_ecmwf.py

    # 指定 2026-10-22 00z，中期预报（0~120h）
    python download_ecmwf.py --date 2026-10-22 --time 0 --steps medium

    # 完整10天预报，仅地面层，保留 GRIB2
    python download_ecmwf.py --steps full --no-pl --keep-grib

    # 使用 Google Cloud（同样无限速）
    python download_ecmwf.py --source google

    # 仅下载 GRIB2，不转 NetCDF（自行处理）
    python download_ecmwf.py --grib-only
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 代理自动检测（macOS 系统代理 → 环境变量）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_system_proxy() -> Optional[str]:
    """检测 macOS 系统代理设置，返回 http://host:port 或 None。"""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(["scutil", "--proxy"], timeout=5).decode()
        lines = out.strip().split("\n")
        proxy = {}
        for line in lines:
            line = line.strip().rstrip(";")
            if ":" in line:
                k, v = line.split(":", 1)
                proxy[k.strip()] = v.strip()
        if proxy.get("HTTPSEnable") == "1" and proxy.get("HTTPSProxy"):
            port = proxy.get("HTTPSPort", "443")
            host = proxy["HTTPSProxy"]
            return f"http://{host}:{port}"
        if proxy.get("HTTPEnable") == "1" and proxy.get("HTTPProxy"):
            port = proxy.get("HTTPPort", "80")
            host = proxy["HTTPProxy"]
            return f"http://{host}:{port}"
    except Exception:
        pass
    return None


def setup_proxy(explicit: Optional[str] = None):
    """设置 HTTP_PROXY / HTTPS_PROXY 环境变量，让 requests 库走代理。"""
    proxy = explicit or detect_system_proxy()
    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
        return proxy
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 浙江省边界框（含 0.2° 缓冲，覆盖舟山群岛）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BBOX = {
    "north": 31.8,   # 北界（天目山北缘以北）
    "south": 26.8,   # 南界（温州以南）
    "west":  117.8,  # 西界（开化以西）
    "east":  123.2,  # 东界（舟山外海）
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 变量配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 地面层 — 常用气象变量
# 注：0p1 tier 实际可用参数以 index 文件为准，已验证
PARAMS_SFC_MET = [
    "2t",     # 2米气温 (K)
    "2d",     # 2米露点温度 (K)
    "10u",    # 10米纬向风 (m/s)
    "10v",    # 10米经向风 (m/s)
    "10fg",   # 10米阵风 (m/s)
    "mn2t3",  # 过去3小时最低2米气温 (K)
    "mx2t3",  # 过去3小时最高2米气温 (K)
    "msl",    # 海平面气压 (Pa)
    "sp",     # 地面气压 (Pa)
    "tp",     # 累计总降水 (m)
    "tcc",    # 总云量 (0-1)
    "lcc",    # 低云量 (0-1)
    "mcc",    # 中云量 (0-1)
    "hcc",    # 高云量 (0-1)
    "mucape", # 最不稳定对流有效位能 (J/kg)
    "skt",    # 皮温 (K)
]

# 地面层 — 辐射变量（原始为累计量 J/m²，脚本自动转 W/m²）
# 注：0p1 tier 暂未提供 tisr/ssrdc/strdc/fdir，仅以下辐射可用
PARAMS_SFC_RAD = [
    "ssrd",   # 地面向下太阳短波辐射（GHI 分量基础）
    "strd",   # 地面向下长波（热红外）辐射
    "ssr",    # 地面净短波辐射
    "str",    # 地面净长波辐射
    "ttr",    # 大气层顶净长波辐射（OLR，累计）
]

# 辐射变量名集合（用于后处理识别）
RAD_ACCUM_VARS = set(PARAMS_SFC_RAD)
# 向下辐射（物理上不可为负，差分误差 clip 到 0）
RAD_DOWNWARD_VARS = {"ssrd", "ssr", "strd"}

# 地面层 — 可选扩展变量（完整 45 个 SFC 参数的剩余部分，--extra 启用）
PARAMS_SFC_EXTRA = [
    "100u", "100v",                          # 100米风场（风能行业）
    "cp", "sf", "ptype", "tprate",           # 降水细分
    "tcwv", "tclw", "tciw", "tcrw", "tcw",  # 整层水汽与云水
    "sd", "rsn", "asn", "ro", "vsw", "sot", # 陆面与土壤
    "sithick", "zos", "lsm",                 # 海洋与静态场
    "ewss", "nsss",                          # 湍流通量（累计量）
    "sve", "svn",                            # 海浪
]

# 压力层变量（完整 10 个）
PARAMS_PL = ["z", "gh", "t", "u", "v", "w", "q", "r", "d", "vo"]
# z=位势, gh=位势高度, t=温度, u/v=风场, w=垂直速度
# q=比湿, r=相对湿度, d=散度, vo=相对涡度

# 标准压力层（hPa）—— 14层
LEVELS_PL = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50, 10]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 预报步长预设
# IFS 00z/12z 标准输出节奏：0-144h/3h，150-360h/6h
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP_PRESETS = {
    "short":  list(range(0, 73, 3)),                                    # 0~72h  / 3h
    "medium": list(range(0, 121, 3)),                                   # 0~120h / 3h
    "full":   list(range(0, 145, 3)) + list(range(150, 241, 6)),        # 0~240h
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 命令行参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="下载 ECMWF IFS 0.1° 浙江省预报数据",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--date", default=None,
        help="起报日期，YYYYMMDD 或 YYYY-MM-DD（不指定则自动获取最新）",
    )
    p.add_argument(
        "--time", type=int, default=None, choices=[0, 6, 12, 18],
        help="起报时次 UTC，0/6/12/18（不指定则自动获取最新）",
    )
    p.add_argument(
        "--steps", default="short", choices=list(STEP_PRESETS.keys()),
        help="预报步长预设: short=0~72h | medium=0~120h | full=0~240h",
    )
    p.add_argument(
        "--no-rad", action="store_true",
        help="跳过辐射变量，仅下载常规气象变量",
    )
    p.add_argument(
        "--no-pl", action="store_true",
        help="跳过压力层数据，仅下载地面层",
    )
    p.add_argument(
        "--source", default="google",
        choices=["aws", "google", "azure", "ecmwf"],
        help="数据源（google/aws 无限速；ecmwf 官方限500并发）",
    )
    p.add_argument(
        "--proxy", default=None,
        help="HTTP 代理地址，如 http://127.0.0.1:1082（默认自动检测 macOS 系统代理）",
    )
    p.add_argument(
        "--outdir", default="./ecmwf_data",
        help="输出目录",
    )
    p.add_argument(
        "--keep-grib", action="store_true",
        help="保留原始 GRIB2 文件（默认转 NetCDF 后删除）",
    )
    p.add_argument(
        "--grib-only", action="store_true",
        help="仅下载 GRIB2，不转 NetCDF",
    )
    p.add_argument(
        "--extra", action="store_true",
        help="下载扩展 SFC 参数（100m风、降水细分、陆面、海洋等共24个额外变量）",
    )
    return p.parse_args()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 下载：通用函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def download_fields(
    client,
    levtype: str,
    params: list,
    steps: list,
    outdir: Path,
    date=None,
    time=None,
    levelist=None,
) -> tuple:
    """
    下载指定层类型的 GRIB2 字段。
    返回 (Path 到 grib2 文件, datetime 起报时间)
    """
    label = levtype.upper()
    grib_path = outdir / f"raw_{levtype}.grib2"

    req = dict(
        type="fc",
        step=steps,
        levtype=levtype,
        param=params,
        target=str(grib_path),
    )
    if date is not None:
        req["date"] = date
    if time is not None:
        req["time"] = time
    if levelist is not None:
        req["levelist"] = levelist

    extra = f" × {len(levelist)} 压力层" if levelist else ""
    print(f"\n[{label}] 正在下载 {len(params)} 变量 × {len(steps)} 步长{extra} ...")

    result = client.retrieve(**req)
    size_mb = grib_path.stat().st_size / 1e6 if grib_path.exists() else 0
    print(f"[{label}] ✓  起报时间: {result.datetime} | 文件大小: {size_mb:.1f} MB")
    return grib_path, result.datetime


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 后处理①：辐射去趋势 — 累计量(J/m²) → 平均通量(W/m²)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def deaccumulate_radiation(ds):
    """
    ECMWF 辐射变量是从预报 t=0 的累计量（J/m²）。
    公式: flux[i] = (accum[i] - accum[i-1]) / (dt[i] 秒)
    step=0 时通量为 0。

    处理后：
      <var>_accum  ← 原始累计量（保留）
      <var>        ← 平均通量 W/m²（新增）
    """
    import xarray as xr

    rad_found = [v for v in ds.data_vars if v in RAD_ACCUM_VARS]
    if not rad_found or "step" not in ds.dims:
        return ds

    # 步长 → 小时 → 各步时间间隔（秒）
    steps_ns = ds.step.values
    steps_h  = steps_ns.astype("timedelta64[h]").astype(float)
    dt_h     = np.diff(steps_h, prepend=0.0)  # shape: (n_steps,)

    rename_map = {}
    new_flux   = {}

    for var in rad_found:
        da = ds[var]  # dims: (step, latitude, longitude)

        # 沿 step 轴差分：result[i] = da[i] - da[i-1]，shape 不变
        # 用 numpy 直接操作，避免 xarray concat 坐标冲突
        arr = da.values.copy()          # (n_steps, lat, lon)
        arr[1:] = arr[1:] - arr[:-1]    # 差分
        arr[0]  = 0.0                   # step=0 通量为 0

        # 除以时间间隔（广播到 lat/lon）
        dt = dt_h * 3600.0              # 秒
        if arr.ndim == 3:               # (step, lat, lon)
            dt = dt[:, np.newaxis, np.newaxis]
        elif arr.ndim == 2:             # (step, lat) or (step, lon)
            dt = dt[:, np.newaxis]
        # dt==0 时（step=0）令通量=0，避免除零
        dt_safe  = np.where(dt == 0, 1.0, dt)
        flux_arr = arr / dt_safe
        flux_arr[0] = 0.0  # 确保 step=0 通量为0

        # 向下辐射物理上不可为负（差分舍入误差），clip 到 0
        if var in RAD_DOWNWARD_VARS:
            flux_arr = np.where(flux_arr < 0, 0.0, flux_arr)

        flux = xr.DataArray(
            flux_arr,
            coords=da.coords,
            dims=da.dims,
            attrs={
                **da.attrs,
                "units":     "W m**-2",
                "long_name": da.attrs.get("long_name", var) + " (mean flux per interval)",
            },
        )
        rename_map[var] = f"{var}_accum"
        new_flux[var]   = flux

    ds = ds.rename(rename_map)
    for var, flux in new_flux.items():
        ds[var] = flux

    return ds


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 后处理②：GRIB2 → 裁剪浙江 → NetCDF
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 完整 45 个 sfc GRIB shortName（以 index 文件验证为准）
_SFC_SHORT_NAMES = [
    # 核心气象（21个，已验证）
    "10fg", "10u", "10v", "2d", "2t", "hcc", "lcc", "mcc",
    "mn2t3", "msl", "mucape", "mx2t3", "skt", "sp",
    "ssr", "ssrd", "str", "strd", "tcc", "tp", "ttr",
    # 扩展参数（24个）
    "100u", "100v",
    "asn", "cp", "ewss", "lsm", "nsss", "ptype",
    "ro", "rsn", "sd", "sf", "sithick", "sve", "svn",
    "tciw", "tclw", "tcrw", "tcw", "tcwv", "tprate",
    "vsw", "zos", "sot",
]

# mn2t3/mx2t3 与 2t 在 cfgrib 中都读成 t2m，按 paramId 区分
_RENAME_BY_PARAMID = {
    228027: "mn2t3",   # Minimum temperature at 2 metres in the last 3 hours
    228026: "mx2t3",   # Maximum temperature at 2 metres in the last 3 hours
}


def grib_to_netcdf(
    grib_path: Path,
    nc_path: Path,
    run_dt: datetime,
    do_deaccum: bool = True,
):
    """
    读取 GRIB2 → 裁剪到浙江省范围 → 辐射去趋势（可选）→ 保存压缩 NetCDF4

    策略：逐 shortName 读取，避免 cfgrib 在同一 typeOfLevel 下多 heightAboveGround
    层坐标冲突（2m 和 10m 同属 heightAboveGround，混读会报 DatasetBuildError）。
    """
    try:
        import cfgrib
        import xarray as xr
    except ImportError:
        print("  ⚠  cfgrib/xarray 未安装，跳过转换。运行: pip install cfgrib xarray netCDF4")
        return

    print(f"  读取 {grib_path.name} ({grib_path.stat().st_size / 1e9:.2f} GB) ...")

    # 根据层类型决定读哪些 shortName
    is_pl = ("pl" in grib_path.name)
    if is_pl:
        # 压力层：open_datasets 处理效果好（只有一种 typeOfLevel=isobaricInhPa）
        try:
            datasets = cfgrib.open_datasets(str(grib_path))
        except Exception as e:
            print(f"  ⚠  cfgrib 读取失败: {e}")
            return
        processed = []
        for ds in datasets:
            if "latitude" in ds.coords and "longitude" in ds.coords:
                ds = ds.sel(
                    latitude=slice(BBOX["north"], BBOX["south"]),
                    longitude=slice(BBOX["west"],  BBOX["east"]),
                )
            processed.append(ds)
        if not processed:
            print(f"  ⚠  {grib_path.name} 无可读数据集")
            return
        final = xr.merge(processed, compat="override") if len(processed) > 1 else processed[0]
    else:
        # 地面层：逐 shortName 读，彻底规避坐标冲突
        per_var = []
        for name in _SFC_SHORT_NAMES:
            try:
                ds = cfgrib.open_dataset(
                    str(grib_path),
                    backend_kwargs={"filter_by_keys": {"shortName": name},
                                    "indexpath": ""},
                )
                if "latitude" in ds.coords and "longitude" in ds.coords:
                    ds = ds.sel(
                        latitude=slice(BBOX["north"], BBOX["south"]),
                        longitude=slice(BBOX["west"],  BBOX["east"]),
                    )
                # mn2t3/mx2t3 cfgrib 读为 t2m，按 paramId 重命名
                for v in list(ds.data_vars):
                    pid = ds[v].attrs.get("GRIB_paramId") or ds[v].attrs.get("paramId")
                    if pid and int(pid) in _RENAME_BY_PARAMID:
                        ds = ds.rename({v: _RENAME_BY_PARAMID[int(pid)]})
                per_var.append(ds)
            except Exception:
                pass  # 该变量在此文件中不存在则跳过
        if not per_var:
            print(f"  ⚠  {grib_path.name} 无可读变量")
            return
        final = xr.merge(per_var, compat="override") if len(per_var) > 1 else per_var[0]
        print(f"  读取 {len(per_var)}/{len(_SFC_SHORT_NAMES)} 个变量")

    if do_deaccum:
        final = deaccumulate_radiation(final)

    final.attrs.update({
        "title":       "ECMWF IFS 0.1° Open Data — Zhejiang Province",
        "institution": "European Centre for Medium-Range Weather Forecasts",
        "source":      "IFS high-resolution deterministic forecast, 0.1°",
        "run_time_utc": str(run_dt),
        "bbox":        (
            f"N{BBOX['north']} S{BBOX['south']} "
            f"W{BBOX['west']} E{BBOX['east']}"
        ),
        "history": f"Downloaded and cropped {datetime.now(timezone.utc).isoformat()}",
    })

    encoding = {v: {"zlib": True, "complevel": 4} for v in final.data_vars}
    final.to_netcdf(str(nc_path), encoding=encoding)
    print(f"  ✓ 已保存: {nc_path.name}  ({nc_path.stat().st_size / 1e6:.1f} MB)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    args   = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    steps      = STEP_PRESETS[args.steps]
    sfc_params = PARAMS_SFC_MET + ([] if args.no_rad else PARAMS_SFC_RAD)
    if args.extra:
        sfc_params = sfc_params + PARAMS_SFC_EXTRA

    # ── 摘要 ──────────────────────────────────────────────────────
    print("=" * 60)
    print("  ECMWF IFS 0.1° 浙江省预报数据下载")
    print("=" * 60)
    # ── 代理设置（macOS 自动检测 + 手动指定）────────────────────────
    proxy_url = setup_proxy(args.proxy)
    if proxy_url:
        print(f"  代理    : {proxy_url}")
    else:
        print(f"  代理    : 无")

    print(f"  数据源  : {args.source.upper()}")
    print(f"  分辨率  : 0.1° (≈9 km)")
    print(f"  步长    : {steps[0]}h ~ {steps[-1]}h  ({len(steps)} 步)")
    print(f"  地面变量: {len(sfc_params)} 个"
          + ("（含辐射）" if not args.no_rad else "（不含辐射）"))
    if not args.no_pl:
        print(f"  压力层  : {len(PARAMS_PL)} 变量 × {len(LEVELS_PL)} 层")
    if args.date:
        t_str = f"{args.time:02d}z" if args.time is not None else "(时次自动)"
        print(f"  起报时间: {args.date} {t_str}")
    else:
        print(f"  起报时间: 自动获取最新可用预报")
    print(f"  区域    : 浙江省 {BBOX['south']}–{BBOX['north']}°N, "
          f"{BBOX['west']}–{BBOX['east']}°E")
    print(f"  输出目录: {outdir.resolve()}")
    print("=" * 60)

    # ── 导入 ecmwf-opendata ───────────────────────────────────────
    try:
        from ecmwf.opendata import Client
    except ImportError:
        print("\n❌ ecmwf-opendata 未安装，请执行:")
        print("   pip install ecmwf-opendata")
        sys.exit(1)

    client = Client(
        source=args.source,
        model="ifs",
        resol="0p1",
        preserve_request_order=False,   # 最少 HTTP 请求，速度更快
    )

    run_dt     = None
    grib_files = []

    # ── 地面层下载 ────────────────────────────────────────────────
    sfc_grib, run_dt = download_fields(
        client, "sfc", sfc_params, steps, outdir,
        date=args.date, time=args.time,
    )
    grib_files.append(sfc_grib)

    # ── 压力层下载 ────────────────────────────────────────────────
    if not args.no_pl:
        pl_grib, _ = download_fields(
            client, "pl", PARAMS_PL, steps, outdir,
            date=args.date, time=args.time,
            levelist=LEVELS_PL,
        )
        grib_files.append(pl_grib)

    # ── 文件名标签（含起报时次）──────────────────────────────────
    run_tag = run_dt.strftime("%Y%m%d_%Hz") if run_dt else "unknown"

    # ── 转 NetCDF ────────────────────────────────────────────────
    if not args.grib_only:
        print("\n[后处理] 裁剪至浙江省 + 辐射去趋势 + 转 NetCDF ...")
        if sfc_grib.exists():
            grib_to_netcdf(
                sfc_grib,
                outdir / f"ecmwf_zj_sfc_{run_tag}.nc",
                run_dt,
                do_deaccum=(not args.no_rad),
            )
        if not args.no_pl:
            pl_raw = outdir / "raw_pl.grib2"
            if pl_raw.exists():
                grib_to_netcdf(
                    pl_raw,
                    outdir / f"ecmwf_zj_pl_{run_tag}.nc",
                    run_dt,
                    do_deaccum=False,
                )

    # ── 清理 / 重命名 GRIB ───────────────────────────────────────
    if args.grib_only or args.keep_grib:
        renames = {
            "raw_sfc.grib2": f"ecmwf_zj_sfc_{run_tag}.grib2",
            "raw_pl.grib2":  f"ecmwf_zj_pl_{run_tag}.grib2",
        }
        for old, new in renames.items():
            src = outdir / old
            if src.exists():
                src.rename(outdir / new)
                print(f"  重命名: {old} → {new}")
    else:
        for f in grib_files:
            if f.exists():
                f.unlink()
                print(f"  已删除临时文件: {f.name}")

    print(f"\n✅ 完成！文件保存至: {outdir.resolve()}")
    if run_dt:
        print(f"   起报时间: {run_dt.strftime('%Y-%m-%d %Hz UTC')}")


if __name__ == "__main__":
    main()
