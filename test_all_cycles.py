#!/usr/bin/env python3
"""
测试四个起报时次的完整下载
验证：00z/12z → 85步(0-360h), 06z/18z → 31步(0-90h/3h)
注意：06z/18z 使用 3h 步长，不是 1h（官方文档错误）
"""
import os
import sys
from ecmwf.opendata import Client
import eccodes

# 设置代理
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:1082'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:1082'

client = Client(source='google', model='ifs', resol='0p1')

# 使用最新数据（date=-1），避免历史数据不可用
test_date = -1
test_param = '2t'
output_dir = 'test_all_cycles'
os.makedirs(output_dir, exist_ok=True)

# 定义预期规则（修正：06z/18z 使用 3h 步长）
test_config = {
    0:  {'steps': list(range(0, 145, 3)) + list(range(150, 361, 6)), 'expected': 85, 'label': '0-360h/主批次'},
    6:  {'steps': list(range(0, 91, 3)), 'expected': 31, 'label': '0-90h/辅助批次（3h步长）'},
    12: {'steps': list(range(0, 145, 3)) + list(range(150, 361, 6)), 'expected': 85, 'label': '0-360h/主批次'},
    18: {'steps': list(range(0, 91, 3)), 'expected': 31, 'label': '0-90h/辅助批次（3h步长）'},
}

print("=" * 80)
print(f"测试四个起报时次完整下载（最新数据 {test_param}）")
print("注意：06z/18z 使用 3h 步长（31步），不是官方文档声称的 1h 步长（91步）")
print("=" * 80)

results = []

for time_utc, config in test_config.items():
    fname = f"{output_dir}/latest_{time_utc:02d}z_{test_param}.grib2"
    
    print(f"\n[{time_utc:02d}z] 开始下载 {config['label']}...")
    print(f"  请求步长数: {len(config['steps'])}")
    print(f"  步长范围: {config['steps'][0]}-{config['steps'][-1]}h")
    
    try:
        # 下载
        result = client.retrieve(
            date=test_date,
            time=time_utc,
            step=config['steps'],
            type='fc',
            param=[test_param],
            target=fname,
        )
        
        # 验证文件
        if not os.path.exists(fname):
            raise Exception("文件未生成")
        
        size_mb = os.path.getsize(fname) / 1e6
        
        # 读取步长
        actual_steps = []
        with open(fname, 'rb') as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None: break
                actual_steps.append(eccodes.codes_get(gid, 'endStep'))
                eccodes.codes_release(gid)
        
        actual_sorted = sorted(set(actual_steps))
        
        # 判断结果
        status = '✅' if len(actual_steps) == config['expected'] else '❌'
        
        print(f"  文件大小: {size_mb:.1f} MB")
        print(f"  实际步长数: {len(actual_steps)} (期望 {config['expected']})")
        print(f"  步长范围: {actual_sorted[0]}-{actual_sorted[-1]}h")
        print(f"  {status} {'通过' if status == '✅' else '失败'}")
        
        results.append({
            'time': time_utc,
            'label': config['label'],
            'expected': config['expected'],
            'actual': len(actual_steps),
            'size_mb': size_mb,
            'max_step': max(actual_steps),
            'status': status
        })
        
    except Exception as e:
        print(f"  ❌ 下载失败: {str(e)[:100]}")
        results.append({
            'time': time_utc,
            'label': config['label'],
            'expected': config['expected'],
            'actual': 0,
            'size_mb': 0,
            'max_step': 0,
            'status': '❌',
            'error': str(e)[:100]
        })

# 汇总报告
print("\n" + "=" * 80)
print("测试结果汇总")
print("=" * 80)
print(f"{'时次':<8} {'类型':<20} {'期望步长':<12} {'实际步长':<12} {'文件大小':<12} {'状态':<6}")
print("-" * 80)

all_pass = True
for r in results:
    size_str = f"{r['size_mb']:.1f} MB"
    print(f"{r['time']:02d}z     {r['label']:<20} {r['expected']:<12} {r['actual']:<12} {size_str:<12} {r['status']}")
    if r['status'] == '❌':
        all_pass = False
        if 'error' in r:
            print(f"         错误: {r['error']}")

print("=" * 80)
if all_pass:
    print("✅ 全部测试通过")
    sys.exit(0)
else:
    print("❌ 部分测试失败")
    sys.exit(1)
