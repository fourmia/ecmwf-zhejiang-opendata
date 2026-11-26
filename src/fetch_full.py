#!/usr/bin/env python3
"""
ECMWF IFS 0.1° 全量同步（index 驱动）
=====================================
与 cron_fetch_ecmwf.py（指定要素、仅 sfc）不同，本脚本：

  1. 先拉取官方 .index 清单（每步长每层类型一个，体积小）
  2. 以 index 实际字段为准生成请求（不信任任何硬编码参数表，
     自动规避 gh/sve 等存疑参数问题）
  3. 全量下载 sfc(+sol) 与 pl 两个文件的所有可用步长
  4. 下载后逐条 GRIB 消息与 index 对账（条数/参数/步长覆盖）
  5. 未发布的步长（404）自动跳过并报告——最新起报远期步长可能尚未发布

用法:
    # 最新起报，全量（sfc+pl，全部已发布步长）
    python src/fetch_full.py --outdir ./ecmwf_full

    # 只拉 index 出清单（几 MB，快速核对参数全集 / 裁决文档疑点）
    python src/fetch_full.py --index-only --outdir ./ecmwf_full

    # 指定起报
    python src/fetch_full.py --date 20261118 --time 12

输出目录结构:
    {outdir}/{date}/{time}z/
    ├── index/                     原始 index 文件
    ├── inventory.json             参数×层×步长清单（index 汇总）
    ├── ifs_0p1_{date}_{time}z_sfc.grib2
    ├── ifs_0p1_{date}_{time}z_pl.grib2
    └── validation.json            下载完整性对账结果
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ecmwf_common import retry_call, setup_proxy, steps_for_run  # noqa: E402

from ecmwf.opendata import Client  # noqa: E402
from ecmwf.opendata.urls import URLS  # noqa: E402

LOG = logging.getLogger("fetch_full")

# 0p1 分文件规则（与 ecmwf.opendata.client.LEVTYPE_FILES 一致）
LEVFILES = {"-sfc": ["sfc", "sol"], "-pl": ["pl"]}


def parse_args():
    p = argparse.ArgumentParser(
        description="ECMWF IFS 0.1° 全量同步（index 驱动）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--date", type=int, default=None, help="起报日期 YYYYMMDD（默认最新）")
    p.add_argument("--time", type=int, default=None, choices=[0, 6, 12, 18],
                   help="起报时次 UTC（默认最新）")
    p.add_argument("--source", default="google", choices=["aws", "google", "azure", "ecmwf"])
    p.add_argument("--proxy", default=None)
    p.add_argument("--outdir", default="./ecmwf_full")
    p.add_argument("--levfiles", default="-sfc,-pl", help="要同步的文件类型")
    p.add_argument("--index-only", action="store_true", help="只拉 index 出清单，不下载 GRIB")
    p.add_argument("--retry", type=int, default=3)
    p.add_argument("--retry-delay", type=float, default=30.0)
    p.add_argument("--timeout", type=float, default=60.0, help="单次 HTTP 超时秒数")
    p.add_argument("--logfile", default=None)
    return p.parse_args()


def index_url(base, date, hour, step, levfile):
    return (f"{base}/{date}/{hour:02d}z/ifs/0p1/oper/"
            f"{date}{hour:02d}0000-{step}h-oper-fc{levfile}.index")


def fetch_indexes(session, base, date, hour, steps, levfiles, idxdir, args):
    """拉取全部 index。返回 {levfile: {step: [entry,...]}}，404 记为未发布。"""
    idxdir.mkdir(parents=True, exist_ok=True)
    data, unavailable = {}, []
    for lf in levfiles:
        data[lf] = {}
        for s in steps:
            url = index_url(base, date, hour, s, lf)
            dest = idxdir / f"{date}{hour:02d}0000-{s}h-oper-fc{lf}.index"

            def _get(url=url, dest=dest):
                if dest.exists() and dest.stat().st_size > 0:
                    return dest.read_text(encoding="utf-8")
                r = session.get(url, timeout=args.timeout)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                dest.write_text(r.text, encoding="utf-8")
                return r.text

            try:
                text = retry_call(_get, retries=args.retry, delay=args.retry_delay,
                                  logger=LOG)
            except Exception as exc:
                LOG.warning("index 拉取失败 step=%s%s: %s（按未发布处理）", s, lf, exc)
                text = None
            if text is None:
                unavailable.append((lf, s))
                continue
            entries = [json.loads(line) for line in text.splitlines() if line.strip()]
            data[lf][s] = entries
        LOG.info("%s: %d/%d 步长 index 可用", lf, len(data[lf]), len(steps))
    return data, unavailable


def build_inventory(data, date, hour):
    """汇总 index → 清单。同时给出存疑参数的存在性裁决。"""
    inv = {"run": f"{date} {hour:02d}z", "files": {}}
    for lf, by_step in data.items():
        params = defaultdict(lambda: {"levtype": set(), "levels": set(), "steps": []})
        for s, entries in sorted(by_step.items()):
            for e in entries:
                p = params[e["param"]]
                p["levtype"].add(e.get("levtype", ""))
                if e.get("levelist") not in (None, ""):
                    p["levels"].add(e["levelist"])
                p["steps"].append(s)
        inv["files"][lf] = {
            "n_steps": len(by_step),
            "n_params": len(params),
            "n_messages": sum(len(v) for v in by_step.values()),
            "params": {k: {"levtype": sorted(v["levtype"]),
                           "levels": sorted(v["levels"]),
                           "n_steps": len(v["steps"])}
                       for k, v in sorted(params.items())},
        }
    return inv


def report_suspects(inv):
    """打印审查记录 C7 存疑参数的裁决结果。"""
    suspects = {"-pl": ["gh", "z", "vo", "w", "d"],
                "-sfc": ["sve", "svn", "zos", "sithick", "sot", "vsw", "tcrw"]}
    for lf, names in suspects.items():
        if lf not in inv["files"]:
            continue
        present = inv["files"][lf]["params"]
        LOG.info("存疑参数裁决 [%s]:", lf)
        for n in names:
            if n in present:
                info = present[n]
                LOG.info("  ✓ %-8s 存在 levtype=%s levels=%s (%d 步)",
                         n, info["levtype"], info["levels"] or "-", info["n_steps"])
            else:
                LOG.info("  ✗ %-8s 不存在于 index", n)


def download_parts(client, data, date, hour, outdir, args):
    """按 (参数集,层集) 签名分组步长，逐组 retrieve，再按步长顺序拼接。"""
    finals = {}
    for lf, by_step in data.items():
        if not by_step:
            continue
        groups = defaultdict(list)
        for s, entries in sorted(by_step.items()):
            sig = (tuple(sorted({e["param"] for e in entries})),
                   tuple(sorted({e["levelist"] for e in entries
                                 if e.get("levelist") not in (None, "")})),
                   tuple(sorted({e.get("levtype") for e in entries})))
            groups[sig].append(s)
        LOG.info("[%s] %d 步长 → %d 个请求组", lf, len(by_step), len(groups))
        parts = []
        for i, ((params, levels, levtypes), steps) in enumerate(
                sorted(groups.items(), key=lambda kv: kv[1][0])):
            part = outdir / f"part{lf}_{i:02d}.grib2"
            req = dict(type="fc", date=date, time=hour, step=steps,
                       levtype=list(levtypes), param=list(params),
                       target=str(part))
            if levels:
                req["levelist"] = list(levels)
            LOG.info("[%s] 组%d: %d 变量 × %d 步长 (step %s..%s)",
                     lf, i, len(params), len(steps), steps[0], steps[-1])

            def _cleanup(part=part):
                if part.exists():
                    part.unlink()

            retry_call(lambda: client.retrieve(**req), retries=args.retry,
                       delay=args.retry_delay, logger=LOG, cleanup=_cleanup)
            parts.append((steps[0], part))
        final = outdir / f"ifs_0p1_{date}_{hour:02d}z{lf}.grib2"
        with open(final, "wb") as out:
            for _, part in sorted(parts):
                out.write(part.read_bytes())
                part.unlink()
        LOG.info("[%s] ✓ 合并完成: %s (%.1f MB)", lf, final.name,
                 final.stat().st_size / 1e6)
        finals[lf] = final
    return finals


def validate(finals, data):
    """逐条 GRIB 消息与 index 对账：按步长的消息数 + 参数覆盖。"""
    try:
        import eccodes as ec
    except ImportError:
        LOG.warning("eccodes 未安装，跳过完整性校验")
        return None
    report = {}
    for lf, path in finals.items():
        expected = defaultdict(lambda: defaultdict(int))  # step -> param -> n
        for s, entries in data[lf].items():
            for e in entries:
                expected[s][e["param"]] += 1
        actual = defaultdict(lambda: defaultdict(int))
        with open(path, "rb") as f:
            while True:
                h = ec.codes_grib_new_from_file(f)
                if h is None:
                    break
                actual[ec.codes_get(h, "endStep")][ec.codes_get(h, "shortName")] += 1
                ec.codes_release(h)
        missing, extra = [], []
        for s in sorted(set(expected) | set(actual)):
            for p in sorted(set(expected[s]) | set(actual[s])):
                ne, na = expected[s][p], actual[s][p]
                if na < ne:
                    missing.append({"step": s, "param": p, "expected": ne, "actual": na})
                elif na > ne:
                    extra.append({"step": s, "param": p, "expected": ne, "actual": na})
        n_exp = sum(sum(v.values()) for v in expected.values())
        n_act = sum(sum(v.values()) for v in actual.values())
        ok = not missing and not extra
        report[lf] = {"file": path.name, "expected_messages": n_exp,
                      "actual_messages": n_act, "missing": missing,
                      "extra": extra, "ok": ok}
        LOG.info("[%s] 对账: 期望 %d 条 / 实际 %d 条 → %s", lf, n_exp, n_act,
                 "✅ 完整" if ok else f"⚠ 缺 {len(missing)} / 多 {len(extra)}")
    return report


def main():
    args = parse_args()
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.logfile:
        handlers.append(logging.FileHandler(args.logfile, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    proxy = setup_proxy(args.proxy)
    if proxy:
        LOG.info("代理: %s", proxy)

    client = Client(source=args.source, model="ifs", resol="0p1",
                    preserve_request_order=False,
                    maximum_retries=args.retry, retry_after=args.retry_delay)
    # 给客户端所有 HTTP 请求注入默认超时（原生无超时，断网时会永久挂起）
    _orig_request = client.session.request

    def _request_with_timeout(method, url, **kw):
        kw.setdefault("timeout", args.timeout)
        return _orig_request(method, url, **kw)

    client.session.request = _request_with_timeout

    # ── 确定起报 ──────────────────────────────────────────────
    if args.date is not None and args.time is not None:
        date, hour = args.date, args.time
    else:
        try:
            latest = client.latest(type="fc", levtype="sfc")
        except Exception as exc:
            LOG.error("无法连接数据源探测最新起报（检查网络/代理 --proxy）: %s", exc)
            sys.exit(1)
        date, hour = int(latest.strftime("%Y%m%d")), latest.hour
        LOG.info("最新可用起报: %s %02dz", date, hour)
    steps = steps_for_run(hour)
    LOG.info("批次步长: %d 步 (0–%dh)", len(steps), steps[-1])

    outdir = Path(args.outdir) / str(date) / f"{hour:02d}z"
    outdir.mkdir(parents=True, exist_ok=True)
    levfiles = [x.strip() for x in args.levfiles.split(",") if x.strip()]

    # ── 1. index ─────────────────────────────────────────────
    session = requests.Session()
    data, unavailable = fetch_indexes(session, URLS[args.source], date, hour,
                                      steps, levfiles, outdir / "index", args)
    if not any(data.values()):
        LOG.error("所有 index 均不可用（网络或批次未发布），退出")
        sys.exit(1)
    if unavailable:
        LOG.warning("未发布/不可用步长 %d 个: %s%s", len(unavailable),
                    unavailable[:6], " ..." if len(unavailable) > 6 else "")

    # ── 2. 清单 ──────────────────────────────────────────────
    inv = build_inventory(data, date, hour)
    inv["unavailable_steps"] = unavailable
    (outdir / "inventory.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    for lf, f in inv["files"].items():
        LOG.info("清单 [%s]: %d 参数, %d 步长, %d 条消息",
                 lf, f["n_params"], f["n_steps"], f["n_messages"])
        LOG.info("  参数: %s", ", ".join(f["params"]))
    report_suspects(inv)
    if args.index_only:
        LOG.info("--index-only 完成，清单: %s", outdir / "inventory.json")
        return

    # ── 3. 下载 ──────────────────────────────────────────────
    finals = download_parts(client, data, date, hour, outdir, args)

    # ── 4. 对账 ──────────────────────────────────────────────
    report = validate(finals, data)
    if report is not None:
        (outdir / "validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        if not all(r["ok"] for r in report.values()):
            LOG.error("完整性校验未通过，详见 validation.json")
            sys.exit(2)
    LOG.info("✅ 全量同步完成: %s", outdir)


if __name__ == "__main__":
    main()
