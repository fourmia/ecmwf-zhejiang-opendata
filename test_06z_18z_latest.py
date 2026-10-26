"""
测试最新可用的 06z 和 18z 数据（辅助批次，0-90h）
使用 date=-1 自动获取最新日期
"""
from ecmwf.opendata import Client
import eccodes
import os
import time

def test_cycle(time_label, time_int):
    """测试单个起报时次"""
    print(f"\n{'='*80}")
    print(f"[{time_label}] 开始下载最新 0-90h 数据...")
    print(f"{'='*80}")
    
    client = Client(source='google', resol='0p1')
    
    # 生成 0-90h 每小时步长
    steps = list(range(0, 91))
    print(f"  请求步长数: {len(steps)}")
    print(f"  步长范围: 0-90h/1h")
    
    fname = f'test_all_cycles/latest_{time_label}_2t.grib2'
    os.makedirs('test_all_cycles', exist_ok=True)
    
    start_time = time.time()
    
    try:
        result = client.retrieve(
            date=-1,  # 最新可用日期
            time=time_int,
            step=steps,
            param=['2t'],
            target=fname
        )
        
        elapsed = time.time() - start_time
        size_mb = os.path.getsize(fname) / 1e6
        
        print(f"  文件大小: {size_mb:.1f} MB")
        print(f"  下载耗时: {int(elapsed//60)}分{int(elapsed%60)}秒")
        
        # 验证步长
        actual_steps = []
        with open(fname, 'rb') as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                actual_steps.append(eccodes.codes_get(gid, 'endStep'))
                eccodes.codes_release(gid)
        
        actual_steps_sorted = sorted(set(actual_steps))
        
        print(f"  实际步长数: {len(actual_steps)} (期望 {len(steps)})")
        print(f"  步长范围: {actual_steps_sorted[0]}-{actual_steps_sorted[-1]}h")
        
        # 检查是否完整
        if len(actual_steps) == len(steps):
            print(f"  ✅ 通过")
            status = '✅'
        else:
            print(f"  ⚠️  步长数不匹配")
            status = '⚠️'
        
        # 获取实际日期
        with open(fname, 'rb') as f:
            gid = eccodes.codes_grib_new_from_file(f)
            data_date = eccodes.codes_get(gid, 'dataDate')
            data_time = eccodes.codes_get(gid, 'dataTime')
            eccodes.codes_release(gid)
        
        date_str = str(data_date)
        print(f"  数据日期: {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {data_time//100:02d}z")
        
        return {
            'time': time_label,
            'status': status,
            'expected': len(steps),
            'actual': len(actual_steps),
            'size_mb': size_mb,
            'elapsed': elapsed,
            'date': date_str,
            'range': f"{actual_steps_sorted[0]}-{actual_steps_sorted[-1]}h"
        }
        
    except Exception as e:
        print(f"  ❌ 下载失败: {e}")
        return {
            'time': time_label,
            'status': '❌',
            'expected': len(steps),
            'actual': 0,
            'size_mb': 0,
            'elapsed': time.time() - start_time,
            'error': str(e)
        }

# 主测试流程
if __name__ == '__main__':
    print("=" * 80)
    print("测试最新可用的 06z 和 18z 数据（辅助批次 0-90h）")
    print("=" * 80)
    
    results = []
    
    # 测试 06z
    results.append(test_cycle('06z', 6))
    
    # 测试 18z
    results.append(test_cycle('18z', 18))
    
    # 汇总报告
    print("\n" + "=" * 80)
    print("测试结果汇总")
    print("=" * 80)
    print(f"\n{'时次':<8} {'数据日期':<12} {'期望':<8} {'实际':<8} {'文件大小':<12} {'耗时':<10} {'状态'}")
    print("-" * 80)
    
    for r in results:
        date_str = r.get('date', 'N/A')
        if date_str != 'N/A':
            date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            date_fmt = 'N/A'
        
        elapsed_str = f"{int(r['elapsed']//60)}m{int(r['elapsed']%60)}s"
        size_str = f"{r['size_mb']:.1f} MB"
        
        print(f"{r['time']:<8} {date_fmt:<12} {r['expected']:<8} {r['actual']:<8} {size_str:<12} {elapsed_str:<10} {r['status']}")
        
        if r['status'] == '❌' and 'error' in r:
            print(f"         错误: {r['error']}")
    
    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    
    all_pass = all(r['status'] == '✅' for r in results)
    
    if all_pass:
        print("✅ 所有测试通过")
        print("\n辅助批次规律确认：")
        print("  - 06z/18z: 0-90h，每小时步长，91 步")
        print(f"  - 平均文件大小: {sum(r['size_mb'] for r in results)/len(results):.1f} MB")
        print(f"  - 平均下载时间: {int(sum(r['elapsed'] for r in results)/len(results)//60)}分钟")
    else:
        print("⚠️  存在失败或不完整的测试")
        for r in results:
            if r['status'] != '✅':
                print(f"  - {r['time']}: {r['status']}")
