"""
测试 06z 和 18z 使用 3h 步长（与 00z/12z 相同）
根据实际检查，1h 步长文件不存在，所有时次都使用 3h 步长
"""
from ecmwf.opendata import Client
import eccodes
import os
import time

def test_cycle_3h(time_label, time_int):
    """测试单个起报时次（3h步长）"""
    print(f"\n{'='*80}")
    print(f"[{time_label}] 开始下载最新数据（3h步长）...")
    print(f"{'='*80}")
    
    client = Client(source='google', resol='0p1')
    
    # 尝试两种可能的步长模式
    # 模式1: 0-90h/3h (官方文档声称的辅助批次)
    # 模式2: 0-144h/3h + 150-360h/6h（与主批次相同）
    
    print(f"  尝试模式1: 0-90h/3h (官方声称的辅助批次)")
    steps_90h = list(range(0, 91, 3))
    
    fname = f'test_all_cycles/latest_{time_label}_2t_3h.grib2'
    os.makedirs('test_all_cycles', exist_ok=True)
    
    start_time = time.time()
    
    try:
        result = client.retrieve(
            date=-1,
            time=time_int,
            step=steps_90h,
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
        
        print(f"  实际步长数: {len(actual_steps)}")
        print(f"  步长范围: {actual_steps_sorted[0]}-{actual_steps_sorted[-1]}h")
        
        # 检查最大时效
        max_step = max(actual_steps)
        
        if max_step == 90:
            print(f"  ✅ 确认为辅助批次（0-90h，{len(actual_steps)}步）")
            status = '✅ 辅助批次'
            mode = '0-90h/3h'
        elif max_step == 360:
            print(f"  ⚠️  实际为主批次（0-360h，与00z/12z相同）")
            status = '⚠️ 主批次'
            mode = '0-360h（与00z/12z相同）'
        else:
            print(f"  ⚠️  未知模式（最大时效 {max_step}h）")
            status = '⚠️ 未知'
            mode = f'0-{max_step}h'
        
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
            'mode': mode,
            'steps': len(actual_steps),
            'max_hour': max_step,
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
            'mode': 'N/A',
            'steps': 0,
            'max_hour': 0,
            'size_mb': 0,
            'elapsed': time.time() - start_time,
            'error': str(e)
        }

# 主测试流程
if __name__ == '__main__':
    print("=" * 80)
    print("测试 06z 和 18z 实际步长模式（使用 3h 步长）")
    print("=" * 80)
    
    results = []
    
    # 测试 06z
    results.append(test_cycle_3h('06z', 6))
    
    # 测试 18z
    results.append(test_cycle_3h('18z', 18))
    
    # 汇总报告
    print("\n" + "=" * 80)
    print("测试结果汇总")
    print("=" * 80)
    print(f"\n{'时次':<8} {'数据日期':<12} {'模式':<30} {'步数':<8} {'最大时效':<10} {'状态'}")
    print("-" * 80)
    
    for r in results:
        date_str = r.get('date', 'N/A')
        if date_str != 'N/A':
            date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            date_fmt = 'N/A'
        
        print(f"{r['time']:<8} {date_fmt:<12} {r['mode']:<30} {r['steps']:<8} {r['max_hour']}h{' '*(7-len(str(r['max_hour'])))} {r['status']}")
        
        if '❌' in r['status'] and 'error' in r:
            print(f"         错误: {r['error']}")
    
    print("\n" + "=" * 80)
    print("核心发现")
    print("=" * 80)
    
    if all('❌' not in r['status'] for r in results):
        max_hours = [r['max_hour'] for r in results]
        
        if all(h == 90 for h in max_hours):
            print("✅ 06z/18z 确认为辅助批次（0-90h）")
        elif all(h == 360 for h in max_hours):
            print("⚠️  06z/18z 实际与 00z/12z 相同（0-360h）")
            print("    官方文档描述有误，所有时次都提供完整 360h 预报")
        else:
            print("⚠️  06z/18z 使用不同的时效配置")
        
        print(f"\n实际情况：")
        for r in results:
            print(f"  - {r['time']}: {r['range']}，{r['steps']} 步，{r['size_mb']:.1f} MB")
    else:
        print("❌ 部分测试失败，无法确认 06z/18z 规律")
