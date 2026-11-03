#!/usr/bin/env python3
"""
ARCO-ERA5 再分析数据下载脚本（GCS 公开存储桶）
================================================
数据源  : gs://gcp-public-data-arco-era5（无需认证，直接 HTTP）
分辨率  : 0.25°（721×1440 全球格点）
时间    : 1940 年至今，1h 时间分辨率，逐日更新（滞后约 6 天）
格式    : NetCDF4（每文件 = 1变量 × 1天 × 24h × 全球）
文件路径: raw/date-variable-single_level/YYYY/MM/DD/<变量>/surface.nc
         raw/date-variable-pressure_level/YYYY/MM/DD/<变量>/<hPa>.nc

与 ECMWF 开放数据对比：
  - ERA5：历史再分析，滞后 6 天，0.25°，NetCDF
  - ECMWF Open Data：实时预报，滞后 9h，0.1°，GRIB2

依赖:
    pip install requests xarray netCDF4 numpy

用法示例:
    # 下载最新可用日期的核心气象要素
    python cron_fetch_era5.py

    # 指定日期 + 要素
    python cron_fetch_era5.py --date 2026-10-28 --params 2t,2d,10u,10v,tp

    # 下载压力层数据
    python cron_fetch_era5.py --date 2026-10-28 --pl --no-sfc

    # 查看可用要素预设
    python cron_fetch_era5.py --list-presets

Crontab 示例（每天 06:00 CST 下载 6 天前数据）:
    0 6 * * * /usr/bin/python3 /opt/era5/cron_fetch_era5.py \\
        --params 2t,2d,10u,10v,tp,msl,ssrd,strd \\
        --outdir /data/era5/{date} \\
        --logfile /var/log/era5_fetch.log
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 存储桶基础 URL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GCS_BASE = "https://storage.googleapis.com/gcp-public-data-arco-era5"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 变量名映射（ECMWF 短名 → ARCO-ERA5 长名）
# 全部经 GCS 实测验证存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SFC_VAR_MAP = {
    # 温湿
    "2t":    "2m_temperature",
    "2d":    "2m_dewpoint_temperature",
    "skt":   "skin_temperature",
    # 风场
    "10u":   "10m_u_component_of_wind",
    "10v":   "10m_v_component_of_wind",
    "10fg":  "10m_wind_gust_since_previous_post_processing",
    "100u":  "100m_u_component_of_wind",
    "100v":  "100m_v_component_of_wind",
    # 气压
    "msl":   "mean_sea_level_pressure",
    "sp":    "surface_pressure",
    # 降水
    "tp":    "total_precipitation",
    "cp":    "convective_precipitation",
    "sf":    "snowfall",
    # 云量
    "tcc":   "total_cloud_cover",
    "lcc":   "low_cloud_cover",
    "mcc":   "medium_cloud_cover",
    "hcc":   "high_cloud_cover",
    # 辐射（均为累计量 J/m²）
    "ssrd":  "surface_solar_radiation_downwards",
    "strd":  "surface_thermal_radiation_downwards",
    "ssr":   "surface_net_solar_radiation",
    "str":   "surface_net_thermal_radiation",
    "ttr":   "top_net_thermal_radiation",
    "tisr":  "toa_incident_solar_radiation",           # ERA5 有，ECMWF 0.1° 暂无
    "ssrdc": "surface_solar_radiation_downward_clear_sky",  # ERA5 有，ECMWF 0.1° 暂无
    "fdir":  "total_sky_direct_solar_radiation_at_surface", # ERA5 有，ECMWF 0.1° 暂无
    # 对流
    "cape":  "convective_available_potential_energy",
    "cin":   "convective_inhibition",
}

# 压力层变量映射
PL_VAR_MAP = {
    "z":  "geopotential",
    "t":  "temperature",
    "u":  "u_component_of_wind",
    "v":  "v_component_of_wind",
    "w":  "vertical_velocity",
    "q":  "specific_humidity",
    "r":  "fraction_of_cloud_cover",  # 注：ERA5压力层无相对湿度，用云量替代
}

# 37 个标准压力层（hPa）
ALL_PL_LEVELS = [1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200,
                 225, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750,
                 775, 800, 825, 850, 875, 900, 925, 950, 975, 1000]

# 常用压力层
STANDARD_PL_LEVELS = [1000, 925, 850, 700, 500, 300, 250, 200, 150, 100, 50]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 要素预设
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRESETS = {
    "minimal": ["2t", "2d", "10u", "10v", "tp", "msl"],
    "standard": ["2t", "2d", "10u", "10v", "10fg", "tp", "msl", "sp",
                 "tcc", "cape", "ssrd", "strd"],
    "full_met": list(SFC_VAR_MAP.keys()),  # 全部已映射变量
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 代理自动检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_system_proxy() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(["scutil", "--proxy"], timeout=5).decode()
        proxy = {}
        for line in out.strip().split("\n"):
            line = line.strip().rstrip(";")
            if ":" in line:
                k, v = line.split(":", 1)
                proxy[k.strip()] = v.strip()
        if proxy.get("HTTPSEnable") == "1" and proxy.get("HTTPSProxy"):
            return f"http://{proxy['HTTPSProxy']}:{proxy.get('HTTPSPort', '443')}"
        if proxy.get("HTTPEnable") == "1" and proxy.get("HTTPProxy"):
            return f"http://{proxy['HTTPProxy']}:{proxy.get('HTTPPort', '80')}"
    except Exception:
        pass
    return None


def setup_proxy(explicit: Optional[str] = None) -> Optional[str]:
    proxy = explicit or detect_system_proxy()
    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
    return proxy


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 最新可用日期检测（实测滞后约 6 天）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def find_latest_date(log: logging.Logger) -> Optional[datetime]:
    today = datetime.now(timezone.utc)
    for i in range(3, 15):
        d = today - timedelta(days=i)
        url = (f"{GCS_BASE}/raw/date-variable-single_level/"
               f"{d.year}/{d.month:02d}/{d.day:02d}/2m_temperature/surface.nc")
        try:
            r = requests.head(url, timeout=10)
            if r.status_code == 200:
                log.info(f"最新可用日期: {d.strftime('%Y-%m-%d')}（当前时间滞后 {i} 天）")
                return d
        except Exception:
            pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 单文件下载（带进度和重试）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def download_file(url: str, dest: Path, retry: int = 3,
                  retry_delay: int = 30, log: logging.Logger = None) -> bool:
    log = log or logging.getLogger(__name__)

    for attempt in range(1, retry + 1):
        try:
            r = requests.get(url, stream=True, timeout=60)
            if r.status_code == 404:
                log.warning(f"  文件不存在 (404): {url.split('/')[-2]}/{url.split('/')[-1]}")
                return False
            r.raise_for_status()

            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)

            if total and downloaded < total * 0.99:
                raise IOError(f"文件不完整: {downloaded}/{total} bytes")

            return True

        except Exception as e:
            log.warning(f"  下载失败 (尝试 {attempt}/{retry}): {e}")
            if dest.exists():
                dest.unlink()
            if attempt < retry:
                time.sleep(retry_delay)

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 下载单层地面要素
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def download_sfc(date: datetime, var_codes: list, outdir: Path,
                 retry: int, log: logging.Logger) -> dict:
    """
    下载地面层要素，每个变量存为独立 NetCDF 文件。
    文件命名：era5_sfc_{date}_{varcode}.nc
    返回 {varcode: 成功/失败} 字典
    """
    results = {}
    y, m, d = date.year, date.month, date.day
    date_str = date.strftime("%Y%m%d")

    for code in var_codes:
        era5_name = SFC_VAR_MAP.get(code)
        if not era5_name:
            log.warning(f"  未知变量代码: {code}，跳过")
            results[code] = False
            continue

        url = f"{GCS_BASE}/raw/date-variable-single_level/{y}/{m:02d}/{d:02d}/{era5_name}/surface.nc"
        dest = outdir / f"era5_sfc_{date_str}_{code}.nc"

        if dest.exists():
            size_mb = dest.stat().st_size / 1e6
            log.info(f"  {code:<8} ({era5_name}) 已存在 ({size_mb:.0f} MB)，跳过")
            results[code] = True
            continue

        log.info(f"  {code:<8} ({era5_name}) ...")
        ok = download_file(url, dest, retry=retry, log=log)
        if ok:
            size_mb = dest.stat().st_size / 1e6
            log.info(f"    ✅ {dest.name} ({size_mb:.0f} MB)")
        results[code] = ok

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 下载压力层要素
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def download_pl(date: datetime, var_codes: list, levels: list, outdir: Path,
                retry: int, log: logging.Logger) -> dict:
    """
    下载压力层要素，每个变量存为包含所有层的合并 NetCDF。
    文件命名：era5_pl_{date}_{varcode}.nc
    返回 {varcode: 成功/失败} 字典
    """
    results = {}
    y, m, d = date.year, date.month, date.day
    date_str = date.strftime("%Y%m%d")

    for code in var_codes:
        era5_name = PL_VAR_MAP.get(code)
        if not era5_name:
            log.warning(f"  未知压力层变量: {code}，跳过")
            results[code] = False
            continue

        dest = outdir / f"era5_pl_{date_str}_{code}.nc"
        if dest.exists():
            log.info(f"  {code} 已存在，跳过")
            results[code] = True
            continue

        log.info(f"  {code} ({era5_name}) × {len(levels)} 层 ...")

        # 逐层下载临时文件，再合并
        tmp_files = {}
        for lev in levels:
            url = f"{GCS_BASE}/raw/date-variable-pressure_level/{y}/{m:02d}/{d:02d}/{era5_name}/{lev}.nc"
            tmp = outdir / f"_tmp_{code}_{lev}.nc"
            ok = download_file(url, tmp, retry=retry, log=log)
            if ok:
                tmp_files[lev] = tmp

        if not tmp_files:
            log.error(f"    ❌ {code}: 所有层下载失败")
            results[code] = False
            continue

        # 合并多层为单个 NetCDF
        try:
            import xarray as xr
            datasets = []
            for lev in sorted(tmp_files.keys()):
                ds = xr.open_dataset(tmp_files[lev])
                # 添加 pressure_level 维度
                if "pressure_level" not in ds.dims:
                    ds = ds.expand_dims({"pressure_level": [lev]})
                else:
                    ds = ds.assign_coords(pressure_level=[lev])
                datasets.append(ds)

            merged = xr.concat(datasets, dim="pressure_level")
            merged.to_netcdf(str(dest))
            size_mb = dest.stat().st_size / 1e6
            log.info(f"    ✅ {dest.name} ({size_mb:.0f} MB, {len(tmp_files)}/{len(levels)} 层)")
            results[code] = True

            # 清理临时文件
            for tmp in tmp_files.values():
                if tmp.exists():
                    tmp.unlink()

        except Exception as e:
            log.error(f"    ❌ 合并失败: {e}")
            results[code] = False

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 命令行参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def parse_args():
    p = argparse.ArgumentParser(
        description="ARCO-ERA5 再分析数据下载（GCS 公开存储桶，无需认证）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--date", default=None,
                   help="日期 YYYYMMDD 或 YYYY-MM-DD（默认：自动最新）")
    p.add_argument("--params", default="standard",
                   help="要素列表（逗号分隔 ECMWF 短名）或预设名 minimal/standard/full_met")
    p.add_argument("--no-sfc", action="store_true", help="跳过地面层")
    p.add_argument("--pl", action="store_true", help="下载压力层数据")
    p.add_argument("--pl-vars", default="z,t,u,v,q",
                   help="压力层变量（逗号分隔）")
    p.add_argument("--pl-levels", default="1000,925,850,700,500,300,250,200",
                   help="压力层（逗号分隔，hPa）")
    p.add_argument("--outdir", default="./era5_data",
                   help="输出目录，支持模板 {date}=YYYYMMDD")
    p.add_argument("--proxy", default=None,
                   help="HTTP 代理（macOS 自动检测）")
    p.add_argument("--retry", type=int, default=3, help="失败重试次数")
    p.add_argument("--retry-delay", type=int, default=30, help="重试间隔（秒）")
    p.add_argument("--logfile", default=None, help="日志文件路径")
    p.add_argument("--list-presets", action="store_true",
                   help="列出要素预设并退出")
    return p.parse_args()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    args = parse_args()

    # 列出预设
    if args.list_presets:
        print("ERA5 要素预设（ECMWF 短名）：\n")
        for name, codes in PRESETS.items():
            print(f"  {name:12s}: {', '.join(codes)}")
        print(f"\n使用示例: --params standard")
        print(f"\n变量映射（ECMWF 短名 → ARCO-ERA5 长名）：")
        for k, v in SFC_VAR_MAP.items():
            print(f"  {k:<8} → {v}")
        sys.exit(0)

    # 日志
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.logfile:
        handlers.append(logging.FileHandler(args.logfile, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    log = logging.getLogger(__name__)

    # 代理
    proxy = setup_proxy(args.proxy)
    if proxy:
        log.info(f"代理: {proxy}")

    # 解析日期
    if args.date:
        date_clean = args.date.replace("-", "")
        date = datetime.strptime(date_clean, "%Y%m%d")
        log.info(f"指定日期: {date.strftime('%Y-%m-%d')}")
    else:
        date = find_latest_date(log)
        if not date:
            log.error("无法确定最新可用日期，请手动指定 --date")
            sys.exit(1)

    # 解析要素
    if args.params in PRESETS:
        sfc_codes = PRESETS[args.params]
    else:
        sfc_codes = [v.strip() for v in args.params.split(",") if v.strip()]

    # 压力层
    pl_codes = [v.strip() for v in args.pl_vars.split(",")]
    pl_levels = [int(v.strip()) for v in args.pl_levels.split(",")]

    # 输出目录（支持 {date} 模板）
    date_str = date.strftime("%Y%m%d")
    outdir = Path(args.outdir.replace("{date}", date_str))
    outdir.mkdir(parents=True, exist_ok=True)

    # 摘要
    log.info("=" * 60)
    log.info("ARCO-ERA5 再分析数据下载")
    log.info("=" * 60)
    log.info(f"数据日期  : {date.strftime('%Y-%m-%d')}")
    log.info(f"数据源    : GCS gcp-public-data-arco-era5（无需认证）")
    log.info(f"分辨率    : 0.25°（721×1440）")
    log.info(f"时间分辨率: 1h（24步/天）")
    if not args.no_sfc:
        log.info(f"地面要素  : {len(sfc_codes)} 个 → {', '.join(sfc_codes)}")
    if args.pl:
        log.info(f"压力层    : {len(pl_codes)} 变量 × {len(pl_levels)} 层")
    log.info(f"输出目录  : {outdir.resolve()}")
    log.info("=" * 60)

    overall_ok = True

    # 下载地面层
    if not args.no_sfc:
        log.info(f"\n[SFC] 开始下载 {len(sfc_codes)} 个地面要素...")
        sfc_results = download_sfc(date, sfc_codes, outdir, args.retry, log)
        ok_count = sum(1 for v in sfc_results.values() if v)
        log.info(f"[SFC] 完成: {ok_count}/{len(sfc_codes)} 成功")
        if ok_count < len(sfc_codes):
            failed = [k for k, v in sfc_results.items() if not v]
            log.warning(f"  失败: {failed}")
            overall_ok = False

    # 下载压力层
    if args.pl:
        log.info(f"\n[PL] 开始下载 {len(pl_codes)} 个压力层变量...")
        pl_results = download_pl(date, pl_codes, pl_levels, outdir, args.retry, log)
        ok_count = sum(1 for v in pl_results.values() if v)
        log.info(f"[PL] 完成: {ok_count}/{len(pl_codes)} 成功")
        if ok_count < len(pl_codes):
            overall_ok = False

    # 输出结果列表
    log.info(f"\n📁 {outdir.resolve()}")
    for f in sorted(outdir.glob("era5_*.nc")):
        log.info(f"   {f.name}  ({f.stat().st_size/1e6:.0f} MB)")

    if overall_ok:
        log.info("\n✅ 全部完成")
        sys.exit(0)
    else:
        log.error("\n❌ 部分下载失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
