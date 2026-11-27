#!/usr/bin/env python3
"""Sequential GCS IFS GRIB2/index downloads with proxy, byte resume and MD5 checks.

Ported from the scripts used for the complete 20261125 12z download.
Python 3.9+, macOS/Linux (fcntl file lock); standard library only.
"""
import argparse
import base64, fcntl, hashlib, json, os, re, signal, time
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
from socket import timeout as SocketTimeout
from ssl import SSLError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, getproxies

from ecmwf_common import steps_for_run

ROOT = Path('./ecmwf_full')
VOLUME = None
DATE = '20261125'
HOUR = 12
PREFIX = f'{DATE}/{HOUR:02d}z/ifs/0p1/oper/'
BUCKET='https://storage.googleapis.com/ecmwf-open-data/'
STEPS = steps_for_run(HOUR)
CHUNK=1024*1024


def system_proxy_opener(explicit=None):
    proxy = explicit or getproxies().get('https')
    if not proxy:
        raise SystemExit('Google 存储桶需要通过系统 HTTPS 代理访问，请检查代理配置。')
    # 用本进程的排除列表，避免 macOS 按解析所得的地址绕过代理。
    os.environ['no_proxy'] = 'localhost,127.0.0.1'
    return build_opener(ProxyHandler({'https': proxy}))


class TransferError(Exception):
    pass

def log(s): print(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {s}',flush=True)

def names(layer, extension):
    return [f'{DATE}{HOUR:02d}0000-{s}h-oper-fc-{layer}.{extension}' for s in STEPS]

def get_manifest(opener, layer, extension):
    cache=ROOT/f'.manifest-{layer}-{extension}.json'
    if cache.exists():
        records = json.loads(cache.read_text())
        if set(records) != set(names(layer, extension)):
            raise RuntimeError(f'缓存清单与当前批次不一致：{cache}')
        return records
    query=urlencode({'prefix':PREFIX,'maxResults':1000,'fields':'nextPageToken,items(name,size,generation,md5Hash)'})
    with opener.open('https://storage.googleapis.com/storage/v1/b/ecmwf-open-data/o?'+query,timeout=45) as r: listing=json.load(r)
    if listing.get('nextPageToken'): raise RuntimeError('GCS 列表有分页，停止以免漏文件')
    wanted=set(names(layer,extension)); found={}
    for obj in listing.get('items',[]):
        name=obj['name'].removeprefix(PREFIX)
        if name in wanted: found[name]=(int(obj['size']),obj['generation'],obj['md5Hash'])
    if set(found)!=wanted: raise RuntimeError(f'{layer}.{extension} 缺文件: {sorted(wanted-set(found))}')
    tmp=cache.with_suffix('.tmp'); tmp.write_text(json.dumps(found,indent=2)); tmp.replace(cache)
    return found

def is_valid(path,size,md5):
    if not path.exists() or path.stat().st_size!=size: return False
    d=hashlib.md5()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(CHUNK),b''): d.update(block)
    return base64.b64encode(d.digest()).decode()==md5

def get_file(opener, layer, extension, name, meta, n, total):
    size,generation,md5=meta
    folder=ROOT/'index'/layer if extension=='index' else ROOT
    folder.mkdir(parents=True,exist_ok=True)
    final=folder/name; part=folder/(name+'.part')
    if final.exists():
        if is_valid(final,size,md5): log(f'[{n}/{total}] 已校验，跳过 {name}'); return
        raise RuntimeError(f'已有文件校验失败，保留现场不覆盖：{final}')
    url=f'{BUCKET}{PREFIX}{name}?generation={generation}'
    consecutive_failures = 0
    while consecutive_failures < 8:
        if VOLUME is not None and not os.path.ismount(VOLUME):
            raise RuntimeError(f'{VOLUME} 已卸载。断点已保留。')
        start = part.stat().st_size if part.exists() else 0
        if start > size:
            raise RuntimeError(f'断点超过文件长度，已保留：{part}')
        try:
            if start < size:
                log(f'[{n}/{total}] {name} {"续传" if start else "下载"} {start:,}/{size:,}（系统代理）')
                transfer(opener, url, part, start, size)
            if not is_valid(part, size, md5):
                part.unlink()
                raise TransferError('GCS MD5 不匹配，将重新下载此文件。')
            part.replace(final)
            log(f'[{n}/{total}] 完成，GCS MD5 通过：{name}')
            return
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise
            reason = str(error)
        except (URLError, TimeoutError, SocketTimeout, ConnectionError, SSLError, HTTPException, TransferError) as error:
            reason = str(error)
        current = part.stat().st_size if part.exists() else 0
        consecutive_failures = 0 if start < current < size else consecutive_failures + 1
        log(f'系统代理下载中断：{reason} 断点 {current:,}/{size:,}，连续无进展计数 {consecutive_failures}/8。')
        if consecutive_failures == 8:
            raise RuntimeError(f'多次重试仍无法完成 {name}，断点已保留：{reason}')
        time.sleep(max(5, consecutive_failures * 5))


def transfer(opener, url, part, offset, size):
    request = Request(url, headers={'Range': f'bytes={offset}-', 'Accept-Encoding': 'identity'})
    with opener.open(request, timeout=60) as response:
        if response.status == 206:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if not match or tuple(map(int, match.groups())) != (offset, size - 1, size):
                raise TransferError('Content-Range 与期望不符。')
        elif response.status != 200 or offset != 0 or response.headers.get('Content-Length') != str(size):
            raise TransferError('服务器未返回期望的字节范围。')
        with part.open('ab') as target:
            while block := response.read1(CHUNK):
                offset += len(block)
                if offset > size:
                    raise TransferError('响应超过文件长度。')
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
    if offset != size:
        raise TransferError(f'连接提前结束，已收到 {offset:,}/{size:,} 字节。')

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, help='起报日期 YYYYMMDD 或 YYYY-MM-DD')
    parser.add_argument('--time', required=True, type=int, choices=(0, 6, 12, 18))
    parser.add_argument('--outdir', default='./ecmwf_full', help='输出根目录；自动追加日期/时次')
    parser.add_argument('--layers', nargs='+', choices=('sfc', 'pl'), default=['sfc', 'pl'],
                        help='按给定顺序逐层下载，默认先地面层再压力层')
    parser.add_argument('--index-only', action='store_true', help='仅下载并校验索引')
    parser.add_argument('--proxy', help='显式 HTTPS 代理地址；默认检测系统/环境代理')
    parser.add_argument('--require-mount', type=Path, help='要求此路径为挂载点，外置盘卸载时停止')
    args = parser.parse_args()
    try:
        args.date = datetime.strptime(args.date.replace('-', ''), '%Y%m%d').strftime('%Y%m%d')
    except ValueError:
        parser.error('--date 必须为有效的 YYYYMMDD 或 YYYY-MM-DD 日期')
    return args


def main():
    global ROOT, VOLUME, DATE, HOUR, PREFIX, STEPS
    args = parse_args()
    DATE, HOUR = args.date, args.time
    PREFIX = f'{DATE}/{HOUR:02d}z/ifs/0p1/oper/'
    STEPS = steps_for_run(HOUR)
    VOLUME = args.require_mount.resolve() if args.require_mount else None
    if VOLUME is not None and not os.path.ismount(VOLUME):
        raise SystemExit(f'{VOLUME} 未挂载')
    ROOT = Path(args.outdir).expanduser().resolve() / DATE / f'{HOUR:02d}z'
    if VOLUME is not None and VOLUME not in ROOT.parents:
        raise SystemExit('--outdir 必须位于指定挂载点内')
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'.download.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('已有此批次下载任务运行')
        opener = system_proxy_opener(args.proxy)
        total_files = 0
        for layer in dict.fromkeys(args.layers):
            indexes = get_manifest(opener, layer, 'index')
            gribs = {} if args.index_only else get_manifest(opener, layer, 'grib2')
            log(f'系统代理下载 {layer}：{len(STEPS)} 个时效，索引优先；输出 {ROOT}')
            for i, (grib, index) in enumerate(zip(names(layer, 'grib2'), names(layer, 'index')), 1):
                get_file(opener, layer, 'index', index, indexes[index], i, len(STEPS))
                total_files += 1
                if not args.index_only:
                    get_file(opener, layer, 'grib2', grib, gribs[grib], i, len(STEPS))
                    total_files += 1
        log(f'全部完成：{total_files} 个文件均通过 GCS MD5 校验。')


def stop(sig, frame):
    raise SystemExit(f'信号 {sig}：退出；未完成 .part 已保留，可安全续传。')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop)
    main()
