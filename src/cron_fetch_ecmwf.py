#!/usr/bin/env python3
"""
ECMWF IFS 0.1° 业务化下载脚本（Cron 友好）
============================================
用途    : 定时下载指定要素的全球 GRIB2，不做后处理
触发    : crontab 每天两次（追 00z/12z）
时间策略: 当前时间 - 8 小时 → 自动推算前一个起报批次
输出    : 原始 GRIB2（按日期/时次分目录存储）
依赖    : ecmwf-opendata

特性:
  - 自动推算起报时间（滞后 8 小时避免数据未就绪）
  - 下载所有可用时长（00z/12z: 0–240h, 06z/18z: 0–90h）
  - 失败自动重试（可配置次数和间隔）
  - 日志写文件 + stdout（cron 邮件友好）
  - 错误时退出码非 0

示例:
    # 下载核心气象要素（全球，全时长）
    python cron_fetch_ecmwf.py \\
        --params 2t,2d,10u,10v,tp,msl,sp,tcc \\
        --outdir /data/ecmwf/{date}/{time}

    # 加上辐射要素
    python cron_fetch_ecmwf.py \\
        --params 2t,2d,10u,10v,tp,ssrd,strd \\
        --outdir /data/ecmwf/{date}/{time}

    # 手动指定起报时间（调试用）
    python cron_fetch_ecmwf.py \\
        --params 2t,10u,10v \\
        --date 2026-10-22 --time 12 \\
        --outdir /data/ecmwf/test

Crontab 示例:
    # 每天 05:00 和 17:00 CST 触发（追前一天 20z UTC 和当天 08z UTC）
    0 5,17 * * * /usr/bin/python3 /path/to/cron_fetch_ecmwf.py \\
        --params 2t,2d,10u,10v,tp,msl,ssrd \\
        --outdir /data/ecmwf/{date}/{time} \\
        --logfile /var/log/ecmwf_fetch.log
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 推荐要素列表（供参考）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECOMMENDED_PARAMS = {
    "minimal": [
        "2t", "2d", "10u", "10v", "tp", "msl",  # 6个核心变量
    ],
    "standard": [
        "2t", "2d", "10u", "10v", "tp", "msl", "sp", "tcc",
        "10fg", "mucape", "ssrd", "strd",  # 12个常用变量
    ],
    "full_met": [
        "2t", "2d", "mn2t3", "mx2t3", "skt",
        "10u", "10v", "10fg", "100u", "100v",
        "msl", "sp", "tp", "cp", "sf", "ptype",
        "tcc", "lcc", "mcc", "hcc", "mucape",
        "ssrd", "strd", "ssr", "str", "ttr",
        "tcwv", "tclw", "tciw",  # 28个地面层气象变量
    ],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 代理自动检测（复用现有逻辑）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_system_proxy() -> Optional[str]:
    """检测 macOS 系统代理，Linux 返回 None（依赖环境变量）。"""
    if sys.platform != "darwin":
        return None
    try:
        import subprocess
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
    """设置 HTTP_PROXY / HTTPS_PROXY 环境变量。"""
    proxy = explicit or detect_system_proxy()
    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
        return proxy
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 自动推算起报时间（当前时间 - 8 小时 → 前一个批次）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def infer_run_time(lag_hours: int = 8) -> tuple[int, int]:
    """
    根据当前时间减去滞后小时数，推算最近的起报批次。
    返回: (YYYYMMDD, HH)
    
    示例:
      当前 CST 2026-10-23 05:00 → UTC 2026-10-22 21:00
      减去 8h → UTC 2026-10-22 13:00 → 向下取整到 12z
      → 返回 (20261022, 12)
    """
    now_utc = datetime.now(timezone.utc)
    target = now_utc - timedelta(hours=lag_hours)
    
    # 向下取整到最近的 00/06/12/18z
    hour = target.hour
    if hour >= 18:
        run_hour = 18
    elif hour >= 12:
        run_hour = 12
    elif hour >= 6:
        run_hour = 6
    else:
        run_hour = 0
    
    run_dt = target.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    date_str = run_dt.strftime("%Y%m%d")
    return int(date_str), run_hour


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 下载逻辑（带重试）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def download_with_retry(
    client,
    params: list[str],
    steps: list[int],
    outfile: Path,
    date: int,
    run_time: int,
    retry: int = 3,
    retry_delay: int = 60,
    logger: logging.Logger = None,
) -> bool:
    """
    下载 GRIB2，失败自动重试。
    返回: True=成功, False=失败
    """
    log = logger or logging.getLogger(__name__)
    
    for attempt in range(1, retry + 1):
        try:
            log.info(f"[尝试 {attempt}/{retry}] 下载 {len(params)} 变量 × {len(steps)} 步长 ...")
            result = client.retrieve(
                type="fc",
                date=date,
                time=run_time,
                step=steps,
                levtype="sfc",
                param=params,
                target=str(outfile),
            )
            size_mb = outfile.stat().st_size / 1e6 if outfile.exists() else 0
            log.info(f"✓ 下载成功 | 起报: {result.datetime} | 大小: {size_mb:.1f} MB")
            return True
        except Exception as e:
            log.error(f"✗ 下载失败 (尝试 {attempt}/{retry}): {e}")
            if attempt < retry:
                log.info(f"  等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                log.error(f"  已达到最大重试次数，放弃。")
                return False
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 命令行参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ECMWF IFS 0.1° 业务化下载（Cron 友好）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--params", required=True,
        help="要素列表（逗号分隔），如: 2t,2d,10u,10v,tp,msl,ssrd",
    )
    p.add_argument(
        "--date", type=int, default=None,
        help="手动指定起报日期 YYYYMMDD（不指定则自动推算，滞后8小时）",
    )
    p.add_argument(
        "--time", type=int, default=None, choices=[0, 6, 12, 18],
        help="手动指定起报时次 UTC（不指定则自动推算）",
    )
    p.add_argument(
        "--lag-hours", type=int, default=8,
        help="自动推算时的滞后小时数（默认 8h，避免数据未就绪）",
    )
    p.add_argument(
        "--source", default="google",
        choices=["aws", "google", "azure", "ecmwf"],
        help="数据源（默认 google，国内代理友好）",
    )
    p.add_argument(
        "--outdir", required=True,
        help="输出目录，支持模板: {date}=YYYYMMDD, {time}=HH，如 /data/ecmwf/{date}/{time}",
    )
    p.add_argument(
        "--filename", default="ifs_0p1_{date}_{time}z.grib2",
        help="输出文件名模板（默认 ifs_0p1_{date}_{time}z.grib2）",
    )
    p.add_argument(
        "--retry", type=int, default=3,
        help="失败重试次数（默认 3）",
    )
    p.add_argument(
        "--retry-delay", type=int, default=60,
        help="重试间隔秒数（默认 60）",
    )
    p.add_argument(
        "--proxy", default=None,
        help="HTTP 代理地址（macOS 自动检测，Linux 需显式指定或设环境变量）",
    )
    p.add_argument(
        "--logfile", default=None,
        help="日志文件路径（默认仅输出到 stdout）",
    )
    p.add_argument(
        "--list-presets", action="store_true",
        help="列出推荐要素预设并退出",
    )
    return p.parse_args()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    args = parse_args()
    
    # ── 列出预设 ──────────────────────────────────────────
    if args.list_presets:
        print("推荐要素预设:\n")
        for name, params in RECOMMENDED_PARAMS.items():
            print(f"  {name:12s}: {', '.join(params)}")
        print(f"\n使用方法: --params {','.join(RECOMMENDED_PARAMS['standard'])}")
        sys.exit(0)
    
    # ── 日志配置 ──────────────────────────────────────────
    log_handlers = [logging.StreamHandler(sys.stdout)]
    if args.logfile:
        log_handlers.append(logging.FileHandler(args.logfile, encoding="utf-8"))
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=log_handlers,
    )
    log = logging.getLogger(__name__)
    
    # ── 代理设置 ──────────────────────────────────────────
    proxy_url = setup_proxy(args.proxy)
    if proxy_url:
        log.info(f"代理: {proxy_url}")
    
    # ── 推算/指定起报时间 ──────────────────────────────────
    if args.date is not None and args.time is not None:
        date, time_utc = args.date, args.time
        log.info(f"手动指定起报: {date} {time_utc:02d}z UTC")
    else:
        date, time_utc = infer_run_time(lag_hours=args.lag_hours)
        log.info(f"自动推算起报: {date} {time_utc:02d}z UTC（滞后 {args.lag_hours}h）")
    
    # ── 确定预报步长（00z/12z 完整360h，06z/18z 仅 0–90h）────────
    if time_utc in [0, 12]:
        # 00z/12z: 0–144h/3h + 150–360h/6h (共 85 步)
        steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
        log.info(f"预报步长: 0–360h（主运行批次，15天）")
    else:
        # 06z/18z: 0–90h/1h
        steps = list(range(0, 91, 1))
        log.info(f"预报步长: 0–90h（辅助批次，1h步长）")
    
    # ── 解析要素列表 ──────────────────────────────────────
    params = [p.strip() for p in args.params.split(",") if p.strip()]
    if not params:
        log.error("--params 参数为空，退出。")
        sys.exit(1)
    log.info(f"要素列表 ({len(params)}): {', '.join(params)}")
    
    # ── 输出路径（模板替换）────────────────────────────────
    date_str = str(date)
    time_str = f"{time_utc:02d}"
    outdir_str = args.outdir.replace("{date}", date_str).replace("{time}", time_str)
    outdir = Path(outdir_str)
    outdir.mkdir(parents=True, exist_ok=True)
    
    filename = args.filename.replace("{date}", date_str).replace("{time}", time_str)
    outfile = outdir / filename
    
    log.info(f"输出路径: {outfile}")
    
    # ── 检查文件是否已存在 ────────────────────────────────
    if outfile.exists():
        size_mb = outfile.stat().st_size / 1e6
        log.warning(f"文件已存在 ({size_mb:.1f} MB)，跳过下载。")
        log.info(f"如需重新下载，请删除: {outfile}")
        sys.exit(0)
    
    # ── 导入 ecmwf-opendata ───────────────────────────────
    try:
        from ecmwf.opendata import Client
    except ImportError:
        log.error("ecmwf-opendata 未安装，请执行: pip install ecmwf-opendata")
        sys.exit(1)
    
    client = Client(
        source=args.source,
        model="ifs",
        resol="0p1",
        preserve_request_order=False,
    )
    
    # ── 下载（带重试）────────────────────────────────────
    success = download_with_retry(
        client, params, steps, outfile,
        date, time_utc,
        retry=args.retry,
        retry_delay=args.retry_delay,
        logger=log,
    )
    
    if success:
        log.info(f"✅ 下载完成: {outfile}")
        sys.exit(0)
    else:
        log.error(f"❌ 下载失败，退出。")
        # 删除不完整文件（如果存在）
        if outfile.exists():
            outfile.unlink()
            log.info(f"已删除不完整文件: {outfile}")
        sys.exit(1)


if __name__ == "__main__":
    main()
