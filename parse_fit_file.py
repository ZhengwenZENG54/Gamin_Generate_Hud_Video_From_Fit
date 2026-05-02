# # # import numpy as np
# # # # from fitparse import FitFile
# # # # import matplotlib.pyplot as plt

# # # # def examine_fit_structure(file_path, start_time=None, end_time=None):
# # # #     """
# # # #     详细检查FIT文件结构，特别是record消息中的字段
    
# # # #     参数:
# # # #     ----------
# # # #     file_path : str
# # # #         FIT文件路径
# # # #     start_time : datetime, optional
# # # #         开始时间
# # # #     end_time : datetime, optional
# # # #         结束时间
# # # #     """
# # # #     print("="*60)
# # # #     print("FIT文件结构详细分析")
# # # #     print("="*60)
    
# # # #     try:
# # # #         fit = FitFile(file_path)
# # # #     except Exception as e:
# # # #         print(f"无法打开FIT文件: {e}")
# # # #         return
    
# # # #     # 1. 检查record消息的字段
# # # #     print("\n1. 检查record消息的字段结构")
# # # #     print("-"*40)
    
# # # #     record_fields = {}
# # # #     record_samples = []
    
# # # #     for i, record in enumerate(fit.get_messages('record')):
# # # #         if i >= 10:  # 只检查前10条记录
# # # #             break
            
# # # #         record_data = record.get_values()
# # # #         record_samples.append(record_data)
        
# # # #         for field_name in record_data.keys():
# # # #             if field_name not in record_fields:
# # # #                 record_fields[field_name] = {
# # # #                     'count': 0,
# # # #                     'example_value': record_data[field_name]
# # # #                 }
# # # #             record_fields[field_name]['count'] += 1
    
# # # #     print("record消息中的字段:")
# # # #     for field_name, info in sorted(record_fields.items()):
# # # #         example = info['example_value']
# # # #         if field_name == 'timestamp':
# # # #             example = str(example)
# # # #         print(f"  {field_name:20s} - 出现次数: {info['count']:3d}, 示例: {example}")
    
# # # #     # 2. 检查是否有累计爬升相关字段
# # # #     print("\n2. 检查累计爬升相关字段")
# # # #     print("-"*40)
    
# # # #     ascent_fields = [f for f in record_fields.keys() 
# # # #                     if 'ascent' in f.lower() or 'climb' in f.lower() or 'elev' in f.lower()]
    
# # # #     if ascent_fields:
# # # #         print("找到与爬升相关的字段:")
# # # #         for field in ascent_fields:
# # # #             print(f"  - {field}")
# # # #     else:
# # # #         print("未找到明确的爬升相关字段")
    
# # # #     # 3. 检查session消息
# # # #     print("\n3. 检查session消息")
# # # #     print("-"*40)
    
# # # #     for session in fit.get_messages('session'):
# # # #         session_data = session.get_values()
# # # #         print("session消息字段:")
# # # #         for key, value in session_data.items():
# # # #             print(f"  {key:20s}: {value}")
# # # #         break  # 只显示第一个session
    
# # # #     # 4. 检查lap消息
# # # #     print("\n4. 检查lap消息")
# # # #     print("-"*40)
    
# # # #     for i, lap in enumerate(fit.get_messages('lap')):
# # # #         if i >= 3:  # 只显示前3个lap
# # # #             print("... (更多lap消息省略)")
# # # #             break
            
# # # #         lap_data = lap.get_values()
# # # #         print(f"Lap {i+1}:")
# # # #         for key, value in lap_data.items():
# # # #             if 'total' in key.lower() or 'distance' in key or 'ascent' in key or 'time' in key:
# # # #                 print(f"  {key:20s}: {value}")
# # # #         print()
    
# # # #     # 5. 提取并分析海拔和距离数据
# # # #     print("\n5. 数据序列分析")
# # # #     print("-"*40)
    
# # # #     timestamps = []
# # # #     distances = []
# # # #     enhanced_alts = []
# # # #     altitudes = []
    
# # # #     for record in fit.get_messages('record'):
# # # #         data = record.get_values()
        
# # # #         if 'timestamp' not in data:
# # # #             continue
            
# # # #         # 时间过滤
# # # #         if start_time and end_time:
# # # #             if not (start_time <= data['timestamp'] <= end_time):
# # # #                 continue
        
# # # #         timestamps.append(data['timestamp'])
# # # #         distances.append(data.get('distance', np.nan))
# # # #         enhanced_alts.append(data.get('enhanced_altitude', np.nan))
# # # #         altitudes.append(data.get('altitude', np.nan))
    
# # # #     print(f"总记录数: {len(timestamps)}")
# # # #     print(f"有效距离点数: {sum(1 for d in distances if not np.isnan(d))}")
# # # #     print(f"有效增强海拔点数: {sum(1 for ea in enhanced_alts if not np.isnan(ea))}")
# # # #     print(f"有效普通海拔点数: {sum(1 for a in altitudes if not np.isnan(a))}")
    
# # # #     # 6. 分析海拔变化
# # # #     print("\n6. 海拔数据分析")
# # # #     print("-"*40)
    
# # # #     # 使用增强海拔，如果不存在则使用普通海拔
# # # #     altitude_source = enhanced_alts
# # # #     if all(np.isnan(enhanced_alts)):
# # # #         altitude_source = altitudes
# # # #         print("使用普通海拔数据")
# # # #     else:
# # # #         print("使用增强海拔数据")
    
# # # #     # 计算总爬升
# # # #     total_ascent = 0.0
# # # #     prev_alt = None
    
# # # #     for alt in altitude_source:
# # # #         if not np.isnan(alt) and prev_alt is not None:
# # # #             diff = alt - prev_alt
# # # #             if diff > 0:  # 只计算上升
# # # #                 total_ascent += diff
# # # #         if not np.isnan(alt):
# # # #             prev_alt = alt
    
# # # #     print(f"从海拔数据计算的总爬升: {total_ascent:.1f} 米")
    
# # # #     # 7. 绘制海拔剖面图
# # # #     print("\n7. 生成海拔剖面图...")
    
# # # #     # 过滤有效数据
# # # #     valid_indices = [i for i, alt in enumerate(altitude_source) if not np.isnan(alt)]
    
# # # #     if len(valid_indices) > 10:
# # # #         # 提取有效海拔
# # # #         valid_alts = [altitude_source[i] for i in valid_indices]
# # # #         valid_dists = [distances[i] for i in valid_indices if not np.isnan(distances[i])]
        
# # # #         plt.figure(figsize=(12, 6))
        
# # # #         if len(valid_dists) > 0 and len(valid_dists) == len(valid_alts):
# # # #             # 使用距离作为X轴
# # # #             plt.subplot(1, 2, 1)
# # # #             plt.plot(valid_dists, valid_alts, 'b-', linewidth=1)
# # # #             plt.xlabel('Distance (m)')
# # # #             plt.ylabel('Altitude (m)')
# # # #             plt.title('Altitude vs Distance')
# # # #             plt.grid(True, alpha=0.3)
        
# # # #         # 使用时间作为X轴
# # # #         plt.subplot(1, 2, 2)
# # # #         plt.plot(range(len(valid_alts)), valid_alts, 'g-', linewidth=1)
# # # #         plt.xlabel('Sample Index')
# # # #         plt.ylabel('Altitude (m)')
# # # #         plt.title('Altitude Profile')
# # # #         plt.grid(True, alpha=0.3)
        
# # # #         plt.tight_layout()
# # # #         plt.savefig('altitude_profile.png', dpi=150, bbox_inches='tight')
# # # #         plt.close()
        
# # # #         print("海拔剖面图已保存到: altitude_profile.png")
    
# # # #     return {
# # # #         'record_fields': record_fields,
# # # #         'session_data': session_data if 'session_data' in locals() else None,
# # # #         'timestamps': timestamps,
# # # #         'distances': distances,
# # # #         'enhanced_alts': enhanced_alts,
# # # #         'calculated_total_ascent': total_ascent
# # # #     }

# # # # # 测试代码
# # # # if __name__ == "__main__":
# # # #     file_path = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
# # # #     #我觉得可以这样修改map方案：距离直接使用码表数据，放在hud中显示。海拔或高度的展示用另一个类似map的动态动画
# # # #     # 可选：指定时间范围
# # # #     from datetime import datetime
# # # #     start_time = datetime(2026, 4, 25, 2, 7, 30)
# # # #     end_time = datetime(2026, 4, 25, 2, 15, 52)
    
# # # #     result = examine_fit_structure(file_path, start_time, end_time)
    
# # # #     print("\n" + "="*60)
# # # #     print("关键发现:")
# # # #     print("="*60)
    
# # # #     # 检查是否有累计爬升字段
# # # #     if 'total_ascent' in result['record_fields']:
# # # #         print("✅ record消息中包含'total_ascent'字段，可以直接使用实时累计爬升")
# # # #     elif 'ascent' in result['record_fields']:
# # # #         print("✅ record消息中包含'ascent'字段，可以直接使用实时累计爬升")
# # # #     else:
# # # #         print("❌ record消息中不包含实时累计爬升字段")
# # # #         print("💡 需要使用海拔数据计算实时累计爬升")
        
# # # #     if 'distance' in result['record_fields']:
# # # #         print("✅ record消息中包含'distance'字段，可以直接使用实时累计距离")

# # # import numpy as np
# # # from fitparse import FitFile
# # # from datetime import datetime, timedelta
# # # import pytz  # 用于时区处理

# # # def analyze_fit_timestamps(file_path, lap_start=None, lap_end=None):
# # #     """
# # #     分析FIT文件中的时间戳结构
    
# # #     参数:
# # #     ----------
# # #     file_path : str
# # #         FIT文件路径
# # #     lap_start : datetime, optional
# # #         圈开始时间（用于验证）
# # #     lap_end : datetime, optional
# # #         圈结束时间（用于验证）
# # #     """
# # #     print("="*70)
# # #     print("FIT文件时间戳详细分析")
# # #     print("="*70)
    
# # #     try:
# # #         fit = FitFile(file_path)
# # #     except Exception as e:
# # #         print(f"无法打开FIT文件: {e}")
# # #         return None
    
# # #     # 1. 收集所有记录的时间戳
# # #     all_timestamps = []
# # #     records_data = []
    
# # #     for record in fit.get_messages('record'):
# # #         data = record.get_values()
# # #         if 'timestamp' in data:
# # #             all_timestamps.append(data['timestamp'])
# # #             records_data.append(data)
    
# # #     if not all_timestamps:
# # #         print("FIT文件中没有时间戳数据")
# # #         return None
    
# # #     print(f"\n1. 基本统计")
# # #     print("-"*40)
# # #     print(f"总记录数: {len(all_timestamps)}")
# # #     print(f"最早时间戳: {all_timestamps[0]}")
# # #     print(f"最晚时间戳: {all_timestamps[-1]}")
    
# # #     # 计算总时长
# # #     total_duration = (all_timestamps[-1] - all_timestamps[0]).total_seconds()
# # #     hours = int(total_duration // 3600)
# # #     minutes = int((total_duration % 3600) // 60)
# # #     seconds = int(total_duration % 60)
# # #     print(f"总时长: {hours}:{minutes:02d}:{seconds:02d} ({total_duration:.0f}秒)")
    
# # #     # 2. 时间间隔分析
# # #     print(f"\n2. 时间间隔分析")
# # #     print("-"*40)
    
# # #     intervals = []
# # #     for i in range(1, len(all_timestamps)):
# # #         interval = (all_timestamps[i] - all_timestamps[i-1]).total_seconds()
# # #         intervals.append(interval)
    
# # #     if intervals:
# # #         avg_interval = np.mean(intervals)
# # #         min_interval = np.min(intervals)
# # #         max_interval = np.max(intervals)
# # #         std_interval = np.std(intervals)
        
# # #         print(f"平均采样间隔: {avg_interval:.3f} 秒")
# # #         print(f"最小采样间隔: {min_interval:.3f} 秒")
# # #         print(f"最大采样间隔: {max_interval:.3f} 秒")
# # #         print(f"间隔标准差: {std_interval:.3f} 秒")
        
# # #         # 统计间隔分布
# # #         interval_counts = {}
# # #         for interval in intervals:
# # #             rounded = round(interval, 2)
# # #             interval_counts[rounded] = interval_counts.get(rounded, 0) + 1
        
# # #         print(f"\n采样间隔分布:")
# # #         for interval, count in sorted(interval_counts.items())[:10]:  # 显示前10个
# # #             print(f"  {interval:.2f}秒: {count}次 ({count/len(intervals)*100:.1f}%)")
        
# # #         if len(interval_counts) > 1:
# # #             print(f"  ... 还有其他{len(interval_counts)-10}种间隔")
    
# # #     # 3. 与指定时间范围对比
# # #     if lap_start and lap_end:
# # #         print(f"\n3. 与指定时间范围对比")
# # #         print("-"*40)
        
# # #         # 找到在指定时间范围内的记录
# # #         in_range_timestamps = [ts for ts in all_timestamps if lap_start <= ts <= lap_end]
        
# # #         print(f"指定时间范围: {lap_start} 到 {lap_end}")
# # #         print(f"指定范围内记录数: {len(in_range_timestamps)}")
        
# # #         if in_range_timestamps:
# # #             actual_start = min(in_range_timestamps)
# # #             actual_end = max(in_range_timestamps)
# # #             print(f"实际找到的最早时间: {actual_start}")
# # #             print(f"实际找到的最晚时间: {actual_end}")
            
# # #             # 检查时间是否精确匹配
# # #             if actual_start != lap_start:
# # #                 time_diff = (actual_start - lap_start).total_seconds()
# # #                 print(f"⚠ 开始时间差异: {time_diff:.1f}秒")
            
# # #             if actual_end != lap_end:
# # #                 time_diff = (actual_end - lap_end).total_seconds()
# # #                 print(f"⚠ 结束时间差异: {time_diff:.1f}秒")
            
# # #             # 计算持续时长
# # #             range_duration = (actual_end - actual_start).total_seconds()
# # #             print(f"实际持续时长: {range_duration:.1f}秒 ({range_duration/60:.1f}分钟)")
# # #         else:
# # #             print("⚠ 在指定时间范围内没有找到记录")
    
# # #     # 4. 检查session/lap的时间戳
# # #     print(f"\n4. Session和Lap时间戳")
# # #     print("-"*40)
    
# # #     # Session时间戳
# # #     for session in fit.get_messages('session'):
# # #         session_data = session.get_values()
# # #         if 'start_time' in session_data:
# # #             session_start = session_data['start_time']
# # #             print(f"Session开始时间: {session_start}")
# # #         if 'timestamp' in session_data:
# # #             session_ts = session_data['timestamp']
# # #             print(f"Session时间戳: {session_ts}")
# # #         break  # 只取第一个session
    
# # #     # Lap时间戳
# # #     print(f"\nLap时间戳:")
# # #     lap_count = 0
# # #     for lap in fit.get_messages('lap'):
# # #         lap_data = lap.get_values()
# # #         lap_count += 1
        
# # #         if 'start_time' in lap_data:
# # #             lap_start_ts = lap_data['start_time']
# # #         elif 'timestamp' in lap_data:
# # #             lap_start_ts = lap_data['timestamp']
# # #         else:
# # #             continue
            
# # #         if 'total_elapsed_time' in lap_data:
# # #             lap_duration = lap_data['total_elapsed_time']
# # #             lap_end_ts = lap_start_ts + timedelta(seconds=lap_duration)
# # #             print(f"  Lap {lap_count}: {lap_start_ts} → {lap_end_ts} ({lap_duration:.0f}秒)")
# # #         else:
# # #             print(f"  Lap {lap_count}: 开始于 {lap_start_ts}")
    
# # #     # 5. 检查时区信息
# # #     print(f"\n5. 时区信息")
# # #     print("-"*40)
    
# # #     # 检查是否有本地时间字段
# # #     local_time_fields = []
# # #     for record in records_data[:5]:  # 检查前5条记录
# # #         for field_name in record.keys():
# # #             if 'local' in field_name.lower() and 'time' in field_name.lower():
# # #                 if field_name not in local_time_fields:
# # #                     local_time_fields.append(field_name)
    
# # #     if local_time_fields:
# # #         print(f"找到本地时间字段: {', '.join(local_time_fields)}")
# # #     else:
# # #         print("未找到明确的本地时间字段，所有时间戳均为UTC时间")
    
# # #     # 6. 时间戳连续性检查
# # #     print(f"\n6. 时间戳连续性检查")
# # #     print("-"*40)
    
# # #     gaps = []
# # #     for i in range(1, len(all_timestamps)):
# # #         interval = (all_timestamps[i] - all_timestamps[i-1]).total_seconds()
# # #         if interval > 5.0:  # 超过5秒的间隔视为可能的数据间隙
# # #             gaps.append((i, interval, all_timestamps[i-1], all_timestamps[i]))
    
# # #     if gaps:
# # #         print(f"发现 {len(gaps)} 个时间间隙 (>5秒):")
# # #         for idx, gap, ts1, ts2 in gaps[:5]:  # 显示前5个间隙
# # #             print(f"  间隙 {idx}: {ts1} → {ts2} ({gap:.1f}秒)")
        
# # #         if len(gaps) > 5:
# # #             print(f"  ... 还有{len(gaps)-5}个间隙未显示")
# # #     else:
# # #         print("时间戳连续性良好，无明显数据间隙")
    
# # #     # 7. 验证绝对时间特性
# # #     print(f"\n7. 绝对时间验证")
# # #     print("-"*40)
    
# # #     # 检查时间戳是否包含完整的日期时间信息
# # #     sample_timestamp = all_timestamps[0]
# # #     print(f"示例时间戳: {sample_timestamp}")
# # #     print(f"  年份: {sample_timestamp.year}")
# # #     print(f"  月份: {sample_timestamp.month}")
# # #     print(f"  日期: {sample_timestamp.day}")
# # #     print(f"  小时: {sample_timestamp.hour}")
# # #     print(f"  分钟: {sample_timestamp.minute}")
# # #     print(f"  秒: {sample_timestamp.second}")
# # #     print(f"  微秒: {sample_timestamp.microsecond}")
    
# # #     # 检查是否是UTC（无时区信息）
# # #     if sample_timestamp.tzinfo is None:
# # #         print("  时区信息: 无 (通常表示为UTC)")
# # #     else:
# # #         print(f"  时区信息: {sample_timestamp.tzinfo}")
    
# # #     # 8. 与系统时间对比
# # #     print(f"\n8. 与当前系统时间对比")
# # #     print("-"*40)
    
# # #     now_utc = datetime.utcnow()
# # #     print(f"当前系统时间 (UTC): {now_utc}")
    
# # #     # 计算时间差
# # #     time_diff = now_utc - all_timestamps[-1]
# # #     print(f"FIT文件最新记录与现在的差值: {time_diff}")
    
# # #     # 如果是今天的数据
# # #     if sample_timestamp.date() == now_utc.date():
# # #         print("✅ FIT文件包含今天的记录")
# # #     else:
# # #         print(f"📅 FIT文件记录日期: {sample_timestamp.date()}")
    
# # #     # 9. 返回分析结果
# # #     result = {
# # #         'file_path': file_path,
# # #         'total_records': len(all_timestamps),
# # #         'first_timestamp': all_timestamps[0],
# # #         'last_timestamp': all_timestamps[-1],
# # #         'total_duration_seconds': total_duration,
# # #         'avg_interval': avg_interval if intervals else 0,
# # #         'timestamp_list': all_timestamps,
# # #         'has_large_gaps': len(gaps) > 0,
# # #         'timezone_info': 'UTC' if sample_timestamp.tzinfo is None else str(sample_timestamp.tzinfo)
# # #     }
    
# # #     print(f"\n" + "="*70)
# # #     print("关键结论:")
# # #     print("="*70)
# # #     print("1. ✅ FIT文件使用**绝对UTC时间**存储时间戳")
# # #     print("2. ✅ 每个记录点都有完整的年-月-日 时:分:秒信息")
# # #     print("3. ✅ 时间戳可以直接用于时间范围过滤")
# # #     print("4. ✅ 代码中传递的 lap_start/lap_end 应该是UTC时间")
    
# # #     if lap_start and lap_end:
# # #         # 验证是否能在文件中找到指定时间的记录
# # #         matching_records = 0
# # #         for ts in all_timestamps:
# # #             if lap_start <= ts <= lap_end:
# # #                 matching_records += 1
        
# # #         print(f"5. ✅ 在指定时间范围内找到 {matching_records} 条记录")
        
# # #         if matching_records == 0:
# # #             print("   ⚠ 注意：可能需要检查时区设置，确保lap_start/lap_end与FIT文件时区一致")
    
# # #     return result

# # # # 测试代码
# # # if __name__ == "__main__":
# # #     # 修改为您的FIT文件路径
# # #     file_path = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    
# # #     # 指定您代码中使用的lap_start和lap_end
# # #     lap_start = datetime(2026, 4, 25, 2, 7, 30)  # UTC时间
# # #     lap_end = datetime(2026, 4, 25, 2, 15, 52)    # UTC时间
    
# # #     print(f"分析文件: {file_path}")
# # #     print(f"测试时间范围: {lap_start} 到 {lap_end}")
# # #     print()
    
# # #     result = analyze_fit_timestamps(file_path, lap_start, lap_end)
    
# # #     if result:
# # #         print(f"\n分析完成!")
# # #         print(f"FIT文件时间戳范围: {result['first_timestamp']} → {result['last_timestamp']}")
# # #         print(f"总记录数: {result['total_records']}")
# # #         print(f"平均采样间隔: {result['avg_interval']:.3f}秒")


# # import matplotlib
# # # 设置非交互式后端
# # matplotlib.use('Agg')
# # import matplotlib.pyplot as plt
# # import numpy as np
# # import os

# # def test_elevation_dimensions():
# #     """
# #     测试爬坡图尺寸和布局
# #     """
# #     print("="*60)
# #     print("爬坡图尺寸测试")
# #     print("="*60)
    
# #     # 视频参数
# #     width, height = 480, 270
    
# #     # 爬坡图参数
# #     elevation_height_ratio = 0.3  # 占整个视频高度的比例
# #     elevation_aspect_ratio = 5.0  # 宽高比，长条形
    
# #     # 创建模拟数据
# #     np.random.seed(42)
# #     num_points = 100
    
# #     # 距离数据（米）
# #     distances = np.linspace(0, 5000, num_points)
    
# #     # 海拔数据（米）- 模拟爬坡
# #     altitudes = np.zeros(num_points)
# #     altitude = 100
# #     for i in range(num_points):
# #         altitudes[i] = altitude
# #         if 20 < i < 40:
# #             altitude += np.random.uniform(0.5, 2)  # 上坡
# #         elif 40 < i < 60:
# #             altitude -= np.random.uniform(0.2, 1)  # 下坡
# #         elif 60 < i < 80:
# #             altitude += np.random.uniform(0.3, 1.5)  # 缓上坡
# #         else:
# #             altitude += np.random.uniform(-0.2, 0.2)  # 平路
    
# #     # 创建输出目录
# #     output_dir = "elevation_test_output"
# #     os.makedirs(output_dir, exist_ok=True)
    
# #     # 测试不同的宽高比
# #     aspect_ratios = [3.0, 4.0, 5.0, 6.0, 7.0]
# #     height_ratios = [0.2, 0.25, 0.3, 0.35, 0.4]
    
# #     for aspect_ratio in aspect_ratios:
# #         for height_ratio in height_ratios:
# #             test_name = f"ar{aspect_ratio}_hr{height_ratio}"
# #             print(f"\n测试: {test_name}")
            
# #             # 计算图形尺寸
# #             fig_width = width / 100
# #             fig_height = height * height_ratio / 100
            
# #             # 创建图形
# #             fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=100)
# #             fig.patch.set_alpha(0)  # 透明背景
            
# #             # 设置轴位置
# #             ax.set_position([0, 0, 1, 1])
# #             ax.set_facecolor((0, 0, 0, 0.2))  # 半透明背景，方便查看
            
# #             # 计算数据范围
# #             min_dist, max_dist = np.min(distances), np.max(distances)
# #             min_alt, max_alt = np.min(altitudes), np.max(altitudes)
            
# #             # 添加边距
# #             dist_range = max_dist - min_dist
# #             alt_range = max_alt - min_alt
            
# #             if dist_range == 0:
# #                 dist_range = 1
# #             if alt_range == 0:
# #                 alt_range = 1
            
# #             margin_top = 0.1
# #             margin_bottom = 0.2
            
# #             min_dist -= dist_range * 0.05
# #             max_dist += dist_range * 0.05
# #             min_alt -= alt_range * margin_bottom
# #             max_alt += alt_range * margin_top
            
# #             ax.set_xlim(min_dist, max_dist)
# #             ax.set_ylim(min_alt, max_alt)
            
# #             # 隐藏坐标轴
# #             ax.axis('off')
            
# #             # 绘制完整海拔剖面
# #             ax.plot(distances, altitudes, color=(0.0, 0.8, 0.2, 1.0), 
# #                    linewidth=3, alpha=0.3, zorder=1)
            
# #             # 绘制已完成部分（模拟到一半）
# #             completed_idx = num_points // 2
# #             completed_dist = distances[:completed_idx]
# #             completed_alt = altitudes[:completed_idx]
            
# #             ax.plot(completed_dist, completed_alt, color=(1.0, 0.8, 0.0, 1.0), 
# #                    linewidth=3, zorder=2)
            
# #             # 添加当前位置标记
# #             current_dist = distances[completed_idx]
# #             current_alt = altitudes[completed_idx]
            
# #             ax.scatter([current_dist], [current_alt], s=64, c=[(1.0, 0.0, 0.0, 1.0)], 
# #                       marker='^', edgecolors='white', linewidths=1, zorder=3)
            
# #             # 添加网格
# #             grid_color = (1.0, 1.0, 1.0, 0.2)
# #             dist_step = dist_range / 10
# #             for x in np.arange(min_dist, max_dist + dist_step, dist_step):
# #                 ax.axvline(x, color=grid_color, linewidth=0.5, alpha=0.3)
            
# #             alt_step = alt_range / 5
# #             for y in np.arange(min_alt, max_alt + alt_step, alt_step):
# #                 ax.axhline(y, color=grid_color, linewidth=0.5, alpha=0.3)
            
# #             # 添加信息文本
# #             info_text = f"宽高比: {aspect_ratio:.1f}\n高度比: {height_ratio:.2f}"
# #             ax.text(0.02, 0.98, info_text, fontsize=8, color='white',
# #                    transform=ax.transAxes, verticalalignment='top',
# #                    bbox=dict(facecolor='black', alpha=0.5, boxstyle='round,pad=0.1'))
            
# #             # 保存测试帧
# #             output_path = os.path.join(output_dir, f"elevation_{test_name}.png")
# #             fig.savefig(output_path, dpi=100, pad_inches=0, transparent=True)
# #             print(f"保存到: {output_path}")
            
# #             plt.close(fig)
    
# #     # 测试保持纵横比的效果
# #     print("\n测试保持纵横比的效果...")
    
# #     # 创建一系列测试，模拟不同阶段的爬坡图
# #     progress_points = [0.2, 0.4, 0.6, 0.8, 1.0]
    
# #     for progress in progress_points:
# #         test_name = f"progress_{int(progress*100)}"
# #         print(f"\n测试进度: {int(progress*100)}%")
        
# #         # 使用推荐的参数
# #         aspect_ratio = 5.0
# #         height_ratio = 0.3
        
# #         fig_width = width / 100
# #         fig_height = height * height_ratio / 100
        
# #         fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=100)
# #         fig.patch.set_alpha(0)
# #         ax.set_position([0, 0, 1, 1])
# #         ax.set_facecolor((0, 0, 0, 0.2))
        
# #         # 计算数据范围
# #         min_dist, max_dist = np.min(distances), np.max(distances)
# #         min_alt, max_alt = np.min(altitudes), np.max(altitudes)
        
# #         dist_range = max_dist - min_dist
# #         alt_range = max_alt - min_alt
        
# #         margin_top = 0.1
# #         margin_bottom = 0.2
        
# #         min_dist -= dist_range * 0.05
# #         max_dist += dist_range * 0.05
# #         min_alt -= alt_range * margin_bottom
# #         max_alt += alt_range * margin_top
        
# #         # 设置坐标轴，保持纵横比
# #         ax.set_xlim(min_dist, max_dist)
# #         ax.set_ylim(min_alt, max_alt)
        
# #         # 计算实际纵横比
# #         data_aspect_ratio = (max_dist - min_dist) / (max_alt - min_alt) if (max_alt - min_alt) > 0 else 1
        
# #         # 如果数据纵横比与期望的不同，调整坐标轴
# #         if data_aspect_ratio > aspect_ratio:
# #             # 数据太宽，调整X轴
# #             current_width = max_dist - min_dist
# #             target_height = current_width / aspect_ratio
# #             height_diff = target_height - (max_alt - min_alt)
# #             min_alt -= height_diff * 0.5
# #             max_alt += height_diff * 0.5
# #         else:
# #             # 数据太高，调整Y轴
# #             current_height = max_alt - min_alt
# #             target_width = current_height * aspect_ratio
# #             width_diff = target_width - (max_dist - min_dist)
# #             min_dist -= width_diff * 0.5
# #             max_dist += width_diff * 0.5
        
# #         ax.set_xlim(min_dist, max_dist)
# #         ax.set_ylim(min_alt, max_alt)
# #         ax.axis('off')
        
# #         # 绘制完整海拔剖面
# #         ax.plot(distances, altitudes, color=(0.0, 0.8, 0.2, 1.0), 
# #                linewidth=3, alpha=0.3, zorder=1)
        
# #         # 绘制已完成部分
# #         completed_idx = int(num_points * progress)
# #         completed_dist = distances[:completed_idx]
# #         completed_alt = altitudes[:completed_idx]
        
# #         ax.plot(completed_dist, completed_alt, color=(1.0, 0.8, 0.0, 1.0), 
# #                linewidth=3, zorder=2)
        
# #         # 添加当前位置标记
# #         if completed_idx > 0:
# #             current_dist = distances[completed_idx-1]
# #             current_alt = altitudes[completed_idx-1]
            
# #             ax.scatter([current_dist], [current_alt], s=64, c=[(1.0, 0.0, 0.0, 1.0)], 
# #                       marker='^', edgecolors='white', linewidths=1, zorder=3)
        
# #         # 添加网格
# #         grid_color = (1.0, 1.0, 1.0, 0.2)
# #         dist_step = (max_dist - min_dist) / 10
# #         for x in np.arange(min_dist, max_dist + dist_step, dist_step):
# #             ax.axvline(x, color=grid_color, linewidth=0.5, alpha=0.3)
        
# #         alt_step = (max_alt - min_alt) / 5
# #         for y in np.arange(min_alt, max_alt + alt_step, alt_step):
# #             ax.axhline(y, color=grid_color, linewidth=0.5, alpha=0.3)
        
# #         # 添加信息文本
# #         info_text = f"进度: {int(progress*100)}%\n数据纵横比: {data_aspect_ratio:.2f}\n目标纵横比: {aspect_ratio:.1f}"
# #         ax.text(0.02, 0.98, info_text, fontsize=8, color='white',
# #                transform=ax.transAxes, verticalalignment='top',
# #                bbox=dict(facecolor='black', alpha=0.5, boxstyle='round,pad=0.1'))
        
# #         output_path = os.path.join(output_dir, f"elevation_{test_name}.png")
# #         fig.savefig(output_path, dpi=100, pad_inches=0, transparent=True)
# #         print(f"保存到: {output_path}")
        
# #         plt.close(fig)
    
# #     # 创建可视化调试图
# #     print("\n创建可视化调试图...")
# #     fig, axes = plt.subplots(2, 3, figsize=(15, 10))
# #     fig.suptitle('爬坡图纵横比对比', fontsize=16)
    
# #     # 使用不同的纵横比测试
# #     test_configs = [
# #         (3.0, 0.3, "窄长型"),
# #         (5.0, 0.3, "推荐型"),
# #         (7.0, 0.3, "超长型"),
# #         (5.0, 0.2, "矮长型"),
# #         (5.0, 0.4, "高长型"),
# #         (4.0, 0.25, "均衡型"),
# #     ]
    
# #     for idx, (aspect_ratio, height_ratio, title) in enumerate(test_configs):
# #         ax = axes[idx//3, idx%3]
        
# #         fig_width_single = width / 100
# #         fig_height_single = height * height_ratio / 100
        
# #         # 模拟创建图形
# #         ax.set_facecolor((0.9, 0.9, 0.9))
        
# #         # 绘制边框
# #         ax.add_patch(plt.Rectangle((0.1, 0.1), 0.8, 0.8, 
# #                                   fill=False, edgecolor='blue', linewidth=2))
        
# #         # 绘制模拟海拔线
# #         x_sim = np.linspace(0.2, 0.8, 50)
# #         y_sim = 0.5 + 0.3 * np.sin(np.linspace(0, 4*np.pi, 50))
# #         ax.plot(x_sim, y_sim, 'g-', linewidth=2)
        
# #         # 添加标记
# #         ax.plot(0.5, 0.5, 'r^', markersize=10)
        
# #         ax.set_xlim(0, 1)
# #         ax.set_ylim(0, 1)
# #         ax.set_aspect('equal')
# #         ax.set_title(f'{title}\n宽高比: {aspect_ratio:.1f}, 高度比: {height_ratio:.2f}', fontsize=10)
# #         ax.axis('off')
    
# #     plt.tight_layout()
# #     debug_path = os.path.join(output_dir, "elevation_aspect_comparison.png")
# #     fig.savefig(debug_path, dpi=150, bbox_inches='tight')
# #     print(f"纵横比对比图保存到: {debug_path}")
    
# #     plt.close(fig)
    
# #     print(f"\n✅ 爬坡图测试完成！所有测试图片保存在: {output_dir}")
# #     print("请检查图片，选择最合适的参数。")
    
# #     # 提供推荐参数
# #     print("\n" + "="*60)
# #     print("参数推荐:")
# #     print("="*60)
# #     print("1. 如果红色三角形被压扁，说明纵横比太大，建议减小elevation_aspect_ratio")
# #     print("2. 如果图形太高，建议减小elevation_height_ratio")
# #     print("3. 推荐起始参数:")
# #     print("   elevation_aspect_ratio = 4.0  # 从5.0减小")
# #     print("   elevation_height_ratio = 0.25  # 从0.3减小")
# #     print("4. 在render_elevation_frames函数中确保设置:")
# #     print("   ax.set_aspect('auto')  # 不强制保持纵横比")

# # if __name__ == "__main__":
# #     test_elevation_dimensions()

# import fitparse

# def check_fit_fields(fit_path):
#     """检查FIT文件包含哪些字段"""
#     fitfile = fitparse.FitFile(fit_path)
    
#     # 收集所有record字段
#     all_fields = set()
#     altitude_records = []
    
#     for i, record in enumerate(fitfile.get_messages("record")):
#         if i >= 10:  # 只检查前10条记录
#             break
            
#         record_fields = {}
#         for data in record:
#             if data.value is not None:
#                 all_fields.add(data.name)
#                 record_fields[data.name] = data.value
        
#         if 'enhanced_altitude' in record_fields or 'altitude' in record_fields:
#             altitude_records.append(record_fields)
    
#     print("FIT文件中包含的字段:")
#     for field in sorted(all_fields):
#         print(f"  - {field}")
    
#     print(f"\n海拔数据示例（前{len(altitude_records)}条）:")
#     for i, rec in enumerate(altitude_records[:3]):
#         print(f"  记录{i+1}: {rec}")
    
#     return all_fields

# # 使用示例
# fields = check_fit_fields(r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit")



import os
import numpy as np
from fitparse import FitFile
from datetime import datetime, timedelta
import sys

def test_fit_data(fit_path, lap_start=None, lap_end=None):
    """
    验证FIT文件数据读取情况
    """
    print(f"=== FIT文件数据验证 ===")
    print(f"文件路径: {fit_path}")
    print(f"文件大小: {os.path.getsize(fit_path)} 字节")
    
    if not os.path.exists(fit_path):
        print(f"❌ 文件不存在: {fit_path}")
        return
    
    try:
        # 加载FIT文件
        fit = FitFile(fit_path)
        
        # 获取所有记录
        recs = []
        for m in fit.get_messages('record'):
            vals = m.get_values()
            if 'timestamp' in vals:
                recs.append(vals)
        
        if not recs:
            print("❌ FIT文件中没有数据记录")
            return
        
        print(f"✅ 找到 {len(recs)} 条数据记录")
        print(f"第一条记录时间: {recs[0]['timestamp']}")
        print(f"最后一条记录时间: {recs[-1]['timestamp']}")
        
        # 分析字段
        print("\n=== 字段分析 ===")
        all_fields = set()
        for r in recs:
            all_fields.update(r.keys())
        
        print(f"总字段数: {len(all_fields)}")
        print("可用字段:")
        for field in sorted(all_fields):
            print(f"  - {field}")
        
        # 检查重要字段
        important_fields = ['timestamp', 'distance', 'position_lat', 'position_long', 
                           'enhanced_altitude', 'altitude', 'speed', 'enhanced_speed',
                           'power', 'heart_rate', 'cadence']
        
        print("\n=== 重要字段检查 ===")
        for field in important_fields:
            count = sum(1 for r in recs if field in r)
            if count > 0:
                # 获取该字段的样本值
                for r in recs:
                    if field in r:
                        sample = r[field]
                        if isinstance(sample, (int, float)):
                            unit = ""
                            if field in ['distance']:
                                unit = " m"
                            elif field in ['speed', 'enhanced_speed']:
                                unit = " m/s"
                            elif field in ['enhanced_altitude', 'altitude']:
                                unit = " m"
                            print(f"✅ {field}: {count}/{len(recs)} 条记录, 样本值: {sample}{unit}")
                        else:
                            print(f"✅ {field}: {count}/{len(recs)} 条记录, 样本值: {sample}")
                        break
            else:
                print(f"❌ {field}: 0/{len(recs)} 条记录")
        
        # 检查特定时间范围内的数据
        if lap_start and lap_end:
            print(f"\n=== 时间范围检查: {lap_start} 到 {lap_end} ===")
            filtered_recs = []
            distances = []
            altitudes = []
            
            for r in recs:
                ts = r['timestamp']
                if lap_start <= ts <= lap_end:
                    filtered_recs.append(r)
                    if 'distance' in r:
                        distances.append(r['distance'])
                    if 'enhanced_altitude' in r:
                        altitudes.append(r['enhanced_altitude'])
                    elif 'altitude' in r:
                        altitudes.append(r['altitude'])
            
            print(f"时间范围内记录数: {len(filtered_recs)}")
            if distances:
                print(f"距离范围: {min(distances):.2f} - {max(distances):.2f} 米")
                print(f"距离变化: {max(distances) - min(distances):.2f} 米")
            if altitudes:
                altitudes = [a for a in altitudes if a is not None]
                if altitudes:
                    print(f"海拔范围: {min(altitudes):.1f} - {max(altitudes):.1f} 米")
                    print(f"总爬升: {max(altitudes) - min(altitudes):.1f} 米")
        
        # 打印前几条记录的详细信息
        print(f"\n=== 前5条记录详细信息 ===")
        for i, r in enumerate(recs[:5]):
            print(f"\n记录 {i+1}:")
            for key, value in r.items():
                if key == 'timestamp':
                    print(f"  {key}: {value}")
                elif isinstance(value, (int, float)):
                    if key in ['position_lat', 'position_long']:
                        # 转换semicircles到度
                        deg = value * (180.0 / 2**31)
                        print(f"  {key}: {value} (semicircles) = {deg:.6f}°")
                    elif key in ['distance']:
                        print(f"  {key}: {value} 米")
                    elif key in ['speed', 'enhanced_speed']:
                        print(f"  {key}: {value} m/s = {value * 3.6:.1f} km/h")
                    elif key in ['enhanced_altitude', 'altitude']:
                        print(f"  {key}: {value} 米")
                    else:
                        print(f"  {key}: {value}")
                else:
                    print(f"  {key}: {value}")
        
        # 计算距离数据的统计
        print(f"\n=== 距离数据统计 ===")
        distances = [r.get('distance') for r in recs if 'distance' in r]
        if distances:
            distances = [d for d in distances if d is not None]
            print(f"有效距离记录数: {len(distances)}")
            print(f"最小距离: {min(distances):.2f} 米")
            print(f"最大距离: {max(distances):.2f} 米")
            print(f"平均距离: {np.mean(distances):.2f} 米")
            print(f"距离增量: {max(distances) - min(distances):.2f} 米")
            
            # 检查距离是否单调递增
            is_increasing = all(distances[i] <= distances[i+1] for i in range(len(distances)-1))
            print(f"距离单调递增: {'是' if is_increasing else '否'}")
            
            # 计算每秒钟的距离变化
            if len(distances) > 1:
                time_diffs = []
                dist_diffs = []
                for i in range(1, min(10, len(distances))):  # 只看前10个
                    time_diff = (recs[i]['timestamp'] - recs[i-1]['timestamp']).total_seconds()
                    dist_diff = distances[i] - distances[i-1]
                    if time_diff > 0:
                        speed_mps = dist_diff / time_diff
                        print(f"  记录{i-1}-{i}: 时间差={time_diff:.1f}s, 距离差={dist_diff:.1f}m, 速度={speed_mps:.1f}m/s ({speed_mps*3.6:.1f}km/h)")
        
        print(f"\n✅ 验证完成")
        
    except Exception as e:
        print(f"❌ 验证过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 测试文件路径
    FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    
    # 测试时间范围
    lap_start = datetime(2026, 4, 25, 2, 7, 30)
    lap_end = datetime(2026, 4, 25, 2, 15, 52)
    
    test_fit_data(FIT_PATH, lap_start, lap_end)


from fitparse import FitFile
from datetime import timedelta


# 使用示例
file_path = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"

def parse_fit_file(file_path):
    try:
        fitfile = FitFile(file_path)
        
        # 初始化变量 
        start_time = None
        end_time = None
        total_distance = 0
        total_elapsed_time = 0
        max_speed = 0
        avg_heart_rate = 0
        max_heart_rate = 0
        heart_rate_count = 0
        heart_rate_sum = 0
        max_power = 0
        
        # 用于记录峰值时刻
        max_heart_rate_time = None
        max_power_time = None
        max_speed_time = None
        
        # 可能的speed字段列表
        speed_fields = ['speed', 'enhanced_speed', 'gps_speed']
        
        # 遍历所有记录
        for record in fitfile.get_messages('record'):
            # 获取时间戳
            timestamp = record.get_value('timestamp')
            if not start_time:
                start_time = timestamp
            end_time = timestamp
            
            # 获取距离
            distance = record.get_value('distance')
            if distance is not None:
                total_distance = distance / 1000  # 转换为公里
                
            # 尝试从多个可能的字段获取速度
            current_speed = None
            for field in speed_fields:
                speed_value = record.get_value(field)
                if speed_value is not None:
                    current_speed = speed_value * 3.6  # 转换为km/h
                    break
            
            # 更新最大速度
            if current_speed is not None and current_speed > max_speed:
                max_speed = current_speed
                max_speed_time = timestamp
                
            # 获取心率
            heart_rate = record.get_value('heart_rate')
            if heart_rate is not None:
                heart_rate_sum += heart_rate
                heart_rate_count += 1
                if heart_rate > max_heart_rate:
                    max_heart_rate = heart_rate
                    max_heart_rate_time = timestamp
                    
            # 获取功率
            power = record.get_value('power')
            if power is not None and power > max_power:
                max_power = power
                max_power_time = timestamp
        
        # 计算平均心率
        if heart_rate_count > 0:
            avg_heart_rate = heart_rate_sum / heart_rate_count
            
        # 计算总时间
        if start_time and end_time:
            total_elapsed_time = (end_time - start_time).total_seconds() / 60  # 转换为分钟
            
        # 打印结果
        print(f"骑行日期: {start_time.strftime('%Y-%m-%d')}")
        print(f"开始时间: {start_time.strftime('%H:%M:%S')}")
        print(f"骑行时长: {total_elapsed_time:.1f} 分钟")
        print(f"总距离: {total_distance:.2f} 公里")
        print(f"最大速度: {max_speed:.1f} km/h")
        print(f"平均心率: {avg_heart_rate:.0f} bpm")
        print(f"最大心率: {max_heart_rate} bpm")
        print(f"最大功率: {max_power} watts")
        
        # 获取峰值时刻函数
        def get_peak_times():
            peak_times = {
                'max_heart_rate_time_sec': 0,
                'max_power_time_sec': 0,
                'max_speed_time_sec': 0
            }
            
            if max_heart_rate_time and start_time:
                peak_times['max_heart_rate_time_sec'] = (max_heart_rate_time - start_time).total_seconds()
                
            if max_power_time and start_time:
                peak_times['max_power_time_sec'] = (max_power_time - start_time).total_seconds()
                
            if max_speed_time and start_time:
                peak_times['max_speed_time_sec'] = (max_speed_time - start_time).total_seconds()
                
            return peak_times
        
        peak_times = get_peak_times()
        print(f"最大心率出现时间: {peak_times['max_heart_rate_time_sec']:.0f} 秒")
        print(f"最大功率出现时间: {peak_times['max_power_time_sec']:.0f} 秒")
        print(f"最大速度出现时间: {peak_times['max_speed_time_sec']:.0f} 秒")
        
        # 检查数据合理性
        if max_speed == 0:
            print("\n警告：未能解析到有效的速度数据，请尝试以下方法：")
            print("1. 检查FIT文件是否确实包含速度数据")
            print("2. 使用专业工具如Garmin Connect或FitFileViewer查看文件内容")
            print("3. 尝试从lap/session消息中获取速度信息")
            
            # 尝试从lap消息中获取最大速度
            for lap in fitfile.get_messages('lap'):
                lap_max_speed = lap.get_value('max_speed')
                if lap_max_speed is not None:
                    max_speed = lap_max_speed * 3.6
                    print(f"\n从lap消息中获取到最大速度: {max_speed:.1f} km/h")
                    break
        
        return peak_times
        
    except Exception as e:
        print(f"解析文件时出错: {e}")
        return None


def print_all_laps_and_events(fit_path):
    fit = FitFile(fit_path)

    print("\n=== 所有 lap 消息 ===")
    for i, lap in enumerate(fit.get_messages("lap")):
        vals = lap.get_values()
        start_time = vals.get("start_time")                  # 本圈开始时间
        elapsed    = vals.get("total_elapsed_time")         # 本圈经过时间（秒）
        trigger    = vals.get("lap_trigger")                # 触发类型

        if start_time is not None and elapsed is not None:
            end_time = start_time + timedelta(seconds=elapsed)
            # 格式化 end_time 精确到小数点后一位
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(end_time.microsecond/100000)}"
        else:
            end_time_str = None

        print(f"[Lap {i+1}] start={start_time}, end={end_time_str}, "
              f"elapsed={elapsed:.1f}s, trigger={trigger}")

    print("\n=== 所有 event 消息（只显示 type=lap 或 trigger=manual） ===")
    for i, ev in enumerate(fit.get_messages("event")):
        vals = ev.get_values()
        ts       = vals.get("timestamp")
        etype    = vals.get("event")
        etrigger = vals.get("event_type")       # 用 event_type 判断触发类型
        if etype == "lap" or etrigger == "manual":
            print(f"[Event {i+1}] ts={ts}, event={etype}, event_type={etrigger}")

import numpy as np
from fitparse import FitFile
import math

def calculate_great_circle_distance(lat1, lon1, lat2, lon2):
    """
    使用Haversine公式计算两个经纬度坐标之间的距离（单位：米）
    """
    # 将角度转换为弧度
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine公式
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    # 地球半径（单位：米）
    R = 6371000
    distance = R * c
    
    return distance

def analyze_fit_file_statistics(file_path, smoothing_window=5, altitude_threshold=0.5):
    """
    分析FIT文件，计算累计距离和累计爬升
    
    参数:
    ----------
    file_path : str
        FIT文件路径
    smoothing_window : int
        海拔平滑窗口大小（用于累计爬升计算）
    altitude_threshold : float
        最小海拔变化阈值，超过此阈值才计入爬升（单位：米）
        
    返回值:
    ----------
    dict
        包含统计信息的字典
    """
    print(f"正在分析FIT文件: {file_path}")
    
    try:
        fit = FitFile(file_path)
    except Exception as e:
        print(f"无法打开FIT文件: {e}")
        return None
    
    # 收集数据
    records = []
    
    # 获取所有记录
    for record in fit.get_messages('record'):
        record_data = record.get_values()
        records.append(record_data)
    
    if not records:
        print("FIT文件中没有记录数据")
        return None
    
    print(f"总记录数: {len(records)}")
    
    # 检查数据字段
    first_record = records[0]
    print("可用字段:", list(first_record.keys()))
    
    # 提取关键数据
    timestamps = []
    distances = []  # 累计距离（米）
    altitudes = []  # 海拔（米）
    positions_lat = []  # 纬度
    positions_long = []  # 经度
    enhanced_altitudes = []  # 增强海拔
    
    for rec in records:
        # 时间戳
        if 'timestamp' in rec:
            timestamps.append(rec['timestamp'])
        
        # 距离
        if 'distance' in rec and rec['distance'] is not None:
            distances.append(rec['distance'])
        else:
            distances.append(np.nan)
        
        # 海拔
        if 'altitude' in rec and rec['altitude'] is not None:
            altitudes.append(rec['altitude'])
        else:
            altitudes.append(np.nan)
            
        # 增强海拔
        if 'enhanced_altitude' in rec and rec['enhanced_altitude'] is not None:
            enhanced_altitudes.append(rec['enhanced_altitude'])
        else:
            enhanced_altitudes.append(np.nan)
        
        # 位置
        if 'position_lat' in rec and rec['position_lat'] is not None:
            # 从semicircles转换为度
            lat_deg = rec['position_lat'] * (180.0 / 2**31)
            positions_lat.append(lat_deg)
        else:
            positions_lat.append(np.nan)
            
        if 'position_long' in rec and rec['position_long'] is not None:
            lon_deg = rec['position_long'] * (180.0 / 2**31)
            positions_long.append(lon_deg)
        else:
            positions_long.append(np.nan)
    
    # 统计信息
    print("\n=== 数据可用性统计 ===")
    valid_dist_count = sum(1 for d in distances if not np.isnan(d))
    valid_alt_count = sum(1 for a in altitudes if not np.isnan(a))
    valid_enh_alt_count = sum(1 for ea in enhanced_altitudes if not np.isnan(ea))
    valid_gps_count = sum(1 for lat, lon in zip(positions_lat, positions_long) 
                          if not (np.isnan(lat) or np.isnan(lon)))
    
    print(f"距离数据: {valid_dist_count}/{len(distances)} ({valid_dist_count/len(distances)*100:.1f}%)")
    print(f"海拔数据: {valid_alt_count}/{len(altitudes)} ({valid_alt_count/len(altitudes)*100:.1f}%)")
    print(f"增强海拔: {valid_enh_alt_count}/{len(enhanced_altitudes)} ({valid_enh_alt_count/len(enhanced_altitudes)*100:.1f}%)")
    print(f"GPS数据: {valid_gps_count}/{len(positions_lat)} ({valid_gps_count/len(positions_lat)*100:.1f}%)")
    
    # 计算累计距离
    print("\n=== 累计距离计算 ===")
    
    # 方法1: 使用FIT文件中的distance字段
    if valid_dist_count > 0:
        # 找到最后一个有效的距离值
        last_valid_dist_idx = max(i for i, d in enumerate(distances) if not np.isnan(d))
        total_distance_from_fit = distances[last_valid_dist_idx]  # 单位：米
        
        # 如果有多个lap，可能需要在lap/session消息中查找
        session_dist = None
        session = None
        
        # 查找session消息
        for session_msg in fit.get_messages('session'):
            session = session_msg.get_values()
            if 'total_distance' in session and session['total_distance'] is not None:
                session_dist = session['total_distance']
                break
        
        lap_dist = None
        # 查找lap消息
        for lap_msg in fit.get_messages('lap'):
            lap = lap_msg.get_values()
            if 'total_distance' in lap and lap['total_distance'] is not None:
                lap_dist = lap['total_distance']
                break
                
        print(f"从record字段获取的累计距离: {total_distance_from_fit:.2f} 米 ({total_distance_from_fit/1000:.2f} 公里)")
        if session_dist is not None:
            print(f"从session字段获取的累计距离: {session_dist:.2f} 米 ({session_dist/1000:.2f} 公里)")
        if lap_dist is not None:
            print(f"从lap字段获取的累计距离: {lap_dist:.2f} 米 ({lap_dist/1000:.2f} 公里)")
    else:
        total_distance_from_fit = 0
        print("警告: FIT文件中没有distance字段")
    
    # 方法2: 从GPS坐标计算累计距离
    if valid_gps_count >= 2:
        total_distance_from_gps = 0
        prev_lat = None
        prev_lon = None
        
        for i, (lat, lon) in enumerate(zip(positions_lat, positions_long)):
            if not (np.isnan(lat) or np.isnan(lon)):
                if prev_lat is not None and prev_lon is not None:
                    # 计算两点间距离
                    segment_dist = calculate_great_circle_distance(prev_lat, prev_lon, lat, lon)
                    total_distance_from_gps += segment_dist
                prev_lat = lat
                prev_lon = lon
        
        print(f"从GPS坐标计算的累计距离: {total_distance_from_gps:.2f} 米 ({total_distance_from_gps/1000:.2f} 公里)")
    else:
        total_distance_from_gps = 0
        print("警告: GPS数据不足，无法计算距离")
    
    # 计算累计爬升
    print("\n=== 累计爬升计算 ===")
    
    # 确定使用哪个海拔数据源
    if valid_enh_alt_count > valid_alt_count:
        print(f"使用增强海拔数据 (有{valid_enh_alt_count}个点)")
        altitude_source = enhanced_altitudes
    else:
        print(f"使用普通海拔数据 (有{valid_alt_count}个点)")
        altitude_source = altitudes
    
    # 方法1: 简单累加（无过滤）
    simple_ascent = 0
    prev_alt = None
    
    for alt in altitude_source:
        if not np.isnan(alt):
            if prev_alt is not None:
                diff = alt - prev_alt
                if diff > 0:  # 只累加上升
                    simple_ascent += diff
            prev_alt = alt
    
    print(f"简单累加累计爬升: {simple_ascent:.1f} 米")
    
    # 方法2: 阈值过滤
    threshold_ascent = 0
    prev_alt = None
    
    for alt in altitude_source:
        if not np.isnan(alt):
            if prev_alt is not None:
                diff = alt - prev_alt
                if diff > altitude_threshold:  # 超过阈值才计入
                    threshold_ascent += diff
            prev_alt = alt
    
    print(f"阈值过滤累计爬升(阈值={altitude_threshold}米): {threshold_ascent:.1f} 米")
    
    # 方法3: 滑动窗口平均 + 阈值过滤
    if smoothing_window > 0 and valid_enh_alt_count + valid_alt_count > smoothing_window * 2:
        # 合并海拔数据
        merged_alts = []
        for i in range(len(altitudes)):
            if not np.isnan(enhanced_altitudes[i]):
                merged_alts.append(enhanced_altitudes[i])
            elif not np.isnan(altitudes[i]):
                merged_alts.append(altitudes[i])
            else:
                merged_alts.append(np.nan)
        
        # 滑动窗口平均
        smoothed_alts = []
        for i in range(len(merged_alts)):
            if np.isnan(merged_alts[i]):
                smoothed_alts.append(np.nan)
                continue
                
            # 获取窗口内的值
            window_start = max(0, i - smoothing_window)
            window_end = min(len(merged_alts), i + smoothing_window + 1)
            window_values = [merged_alts[j] for j in range(window_start, window_end) 
                           if not np.isnan(merged_alts[j])]
            
            if window_values:
                smoothed_alts.append(np.mean(window_values))
            else:
                smoothed_alts.append(np.nan)
        
        # 计算累计爬升
        smoothed_ascent = 0
        prev_alt = None
        
        for alt in smoothed_alts:
            if not np.isnan(alt):
                if prev_alt is not None:
                    diff = alt - prev_alt
                    if diff > altitude_threshold:  # 超过阈值才计入
                        smoothed_ascent += diff
                prev_alt = alt
        
        print(f"滑动窗口平均累计爬升(窗口={smoothing_window}, 阈值={altitude_threshold}米): {smoothed_ascent:.1f} 米")
    else:
        smoothed_ascent = 0
        print(f"数据不足，无法进行滑动窗口平均(需要至少{smoothing_window*2}个有效海拔点)")
    
    # 尝试从session/lap消息获取累计爬升
    session_ascent = None
    session = None
    
    for session_msg in fit.get_messages('session'):
        session = session_msg.get_values()
        if 'total_ascent' in session and session['total_ascent'] is not None:
            session_ascent = session['total_ascent']
            break
    
    lap_ascent = None
    for lap_msg in fit.get_messages('lap'):
        lap = lap_msg.get_values()
        if 'total_ascent' in lap and lap['total_ascent'] is not None:
            lap_ascent = lap['total_ascent']
            break
    
    if session_ascent is not None:
        print(f"从session字段获取的累计爬升: {session_ascent:.1f} 米")
    if lap_ascent is not None:
        print(f"从lap字段获取的累计爬升: {lap_ascent:.1f} 米")
    
    # 时间统计
    if len(timestamps) >= 2:
        start_time = timestamps[0]
        end_time = timestamps[-1]
        duration = (end_time - start_time).total_seconds()
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        print(f"\n=== 时间统计 ===")
        print(f"开始时间: {start_time}")
        print(f"结束时间: {end_time}")
        print(f"总时长: {hours}:{minutes:02d}:{seconds:02d} ({duration:.0f}秒)")
        
        if total_distance_from_fit > 0:
            avg_speed = total_distance_from_fit / duration * 3.6  # 转换为km/h
            print(f"平均速度: {avg_speed:.1f} km/h")
    
    # 返回结果
    result = {
        'file_path': file_path,
        'records_count': len(records),
        'distance_fit': total_distance_from_fit,  # 从FIT distance字段获取
        'distance_gps': total_distance_from_gps,  # 从GPS计算
        'distance_session': session_dist,  # 从session消息获取
        'ascent_simple': simple_ascent,  # 简单累加
        'ascent_threshold': threshold_ascent,  # 阈值过滤
        'ascent_smoothed': smoothed_ascent,  # 平滑+阈值
        'ascent_session': session_ascent,  # 从session消息获取
        'start_time': timestamps[0] if timestamps else None,
        'end_time': timestamps[-1] if timestamps else None,
        'duration_seconds': (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) >= 2 else 0
    }
    
    print("\n=== 结果汇总 ===")
    print(f"建议使用的累计距离: {result['distance_fit']/1000:.2f} 公里 (来自FIT distance字段)")
    
    # 选择最可靠的累计爬升
    if result['ascent_session'] is not None:
        print(f"建议使用的累计爬升: {result['ascent_session']:.0f} 米 (来自FIT session字段)")
    elif result['ascent_smoothed'] > 0:
        print(f"建议使用的累计爬升: {result['ascent_smoothed']:.0f} 米 (平滑+阈值算法)")
    else:
        print(f"建议使用的累计爬升: {result['ascent_threshold']:.0f} 米 (阈值过滤算法)")
    
    return result

# 测试代码
if __name__ == "__main__":
    # 修改为您的FIT文件路径
    file_path = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    
    # 可调参数
    smoothing_window = 5  # 滑动窗口大小
    altitude_threshold = 0.5  # 最小海拔变化阈值(米)
    
    result = analyze_fit_file_statistics(
        file_path=file_path,
        smoothing_window=smoothing_window,
        altitude_threshold=altitude_threshold
    )
    
    if result:
        print("\n" + "="*50)
        print("最终返回的字典:")
        for key, value in result.items():
            if key not in ['start_time', 'end_time']:
                print(f"  {key}: {value}")


import os
import numpy as np
from fitparse import FitFile
import json
from datetime import datetime
from collections import defaultdict

def analyze_fit_file(fit_path, lap_start=None, lap_end=None):
    """
    深度分析FIT文件的结构和数据内容
    
    参数:
    ----------
    fit_path : str
        FIT文件路径
    lap_start : datetime, 可选
        开始时间，用于筛选数据
    lap_end : datetime, 可选
        结束时间，用于筛选数据
        
    返回值:
    ----------
    dict
        包含分析结果的字典
    """
    print(f"\n=== 开始分析FIT文件: {fit_path} ===")
    
    if not os.path.exists(fit_path):
        print(f"错误: 文件不存在: {fit_path}")
        return None
    
    try:
        fit = FitFile(fit_path)
    except Exception as e:
        print(f"无法打开FIT文件: {e}")
        return None
    
    # 1. 收集所有消息类型
    message_types = defaultdict(int)
    message_fields = defaultdict(set)
    all_fields = set()
    
    print("\n=== 消息类型统计 ===")
    for message in fit.get_messages():
        message_type = message.name
        message_types[message_type] += 1
        
        # 收集这个消息类型的所有字段
        for field in message:
            field_name = field.name
            message_fields[message_type].add(field_name)
            all_fields.add(field_name)
    
    # 打印消息类型统计
    for msg_type, count in sorted(message_types.items()):
        print(f"{msg_type}: {count}条")
    
    # 2. 专门分析'record'消息，查找海拔相关字段
    print("\n=== 记录消息(record)字段分析 ===")
    record_fields = defaultdict(list)
    altitude_variants = ['altitude', 'enhanced_altitude', 'gps_altitude', 'height', 'elevation']
    found_altitude = False
    altitude_data = []
    
    record_count = 0
    for message in fit.get_messages('record'):
        record_count += 1
        values = message.get_values()
        
        # 检查所有可能的海拔字段
        for alt_field in altitude_variants:
            if alt_field in values:
                found_altitude = True
                alt_value = values[alt_field]
                altitude_data.append(alt_value)
                if alt_field not in record_fields:
                    record_fields[alt_field] = []
                record_fields[alt_field].append(alt_value)
        
        # 收集所有字段
        for field_name, field_value in values.items():
            if field_name not in record_fields:
                record_fields[field_name] = [field_value]
            else:
                record_fields[field_name].append(field_value)
    
    print(f"记录消息总数: {record_count}")
    
    # 3. 查找海拔相关字段
    print("\n=== 海拔数据搜索 ===")
    altitude_fields_found = []
    for field_name in altitude_variants:
        if field_name in record_fields:
            altitude_fields_found.append(field_name)
            data = record_fields[field_name]
            valid_data = [d for d in data if d is not None]
            print(f"找到字段 '{field_name}':")
            print(f"  数据点数: {len(data)}")
            print(f"  非空点数: {len(valid_data)}")
            if valid_data:
                print(f"  最小值: {min(valid_data):.2f}")
                print(f"  最大值: {max(valid_data):.2f}")
                print(f"  平均值: {np.mean(valid_data):.2f}")
    
    if not altitude_fields_found:
        print("未找到标准海拔字段，正在搜索其他可能的海拔相关字段...")
        
        # 搜索包含"alt"的字段
        alt_related = [f for f in record_fields.keys() if 'alt' in f.lower()]
        if alt_related:
            print(f"找到可能的海拔相关字段: {alt_related}")
            for field in alt_related:
                data = record_fields[field]
                valid_data = [d for d in data if d is not None]
                print(f"  '{field}': {len(valid_data)}个有效值")
        else:
            print("未找到任何海拔相关字段")
    
    # 4. 分析时间范围
    print("\n=== 时间范围分析 ===")
    if 'timestamp' in record_fields:
        timestamps = record_fields['timestamp']
        if timestamps:
            first_time = min(timestamps)
            last_time = max(timestamps)
            duration = (last_time - first_time).total_seconds()
            print(f"第一条记录: {first_time}")
            print(f"最后一条记录: {last_time}")
            print(f"总时长: {duration:.1f}秒 ({duration/60:.1f}分钟)")
            
            if lap_start and lap_end:
                print(f"\n指定时间范围: {lap_start} 到 {lap_end}")
                in_range = [t for t in timestamps if lap_start <= t <= lap_end]
                print(f"在指定时间范围内的记录数: {len(in_range)}")
    
    # 5. 分析其他重要字段
    print("\n=== 其他重要数据字段 ===")
    important_fields = ['position_lat', 'position_long', 'speed', 'enhanced_speed', 
                       'power', 'heart_rate', 'cadence', 'distance']
    
    for field in important_fields:
        if field in record_fields:
            data = record_fields[field]
            valid_data = [d for d in data if d is not None]
            if valid_data:
                if field in ['position_lat', 'position_long']:
                    # 这些是semicircles，需要转换
                    print(f"{field}: {len(valid_data)}个有效值 (单位: semicircles)")
                else:
                    print(f"{field}: {len(valid_data)}个有效值")
    
    # 6. 输出所有字段的摘要
    print("\n=== 所有字段摘要 ===")
    print(f"总字段数: {len(record_fields)}")
    print("字段列表:")
    for i, field_name in enumerate(sorted(record_fields.keys())):
        data = record_fields[field_name]
        valid_count = sum(1 for d in data if d is not None)
        sample_value = next((d for d in data if d is not None), None)
        value_type = type(sample_value).__name__ if sample_value is not None else "None"
        print(f"  {i+1:2d}. {field_name:20s}: {valid_count:4d}有效/{len(data):4d}总数, 类型: {value_type}")
    
    # 7. 保存分析结果到文件
    output_file = "fit_analysis_report.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"FIT文件分析报告: {fit_path}\n")
        f.write(f"分析时间: {datetime.now()}\n\n")
        
        f.write("=== 消息类型统计 ===\n")
        for msg_type, count in sorted(message_types.items()):
            f.write(f"{msg_type}: {count}条\n")
        
        f.write(f"\n=== 记录消息字段数: {len(record_fields)} ===\n")
        for field_name in sorted(record_fields.keys()):
            data = record_fields[field_name]
            valid_count = sum(1 for d in data if d is not None)
            f.write(f"{field_name}: {valid_count}有效/{len(data)}总数\n")
    
    print(f"\n详细分析报告已保存到: {output_file}")
    
    # 返回分析结果
    result = {
        'file_path': fit_path,
        'record_count': record_count,
        'message_types': dict(message_types),
        'record_fields': {k: len(v) for k, v in record_fields.items()},
        'altitude_fields_found': altitude_fields_found,
        'all_fields': list(all_fields)
    }
    
    return result

def test_fit_loading(fit_path, sample_count=5):
    """
    测试FIT文件加载并显示样本数据
    """
    print(f"\n=== 测试加载: {fit_path} ===")
    
    try:
        fit = FitFile(fit_path)
    except Exception as e:
        print(f"无法打开FIT文件: {e}")
        return
    
    # 获取前几个记录消息
    records = []
    for i, message in enumerate(fit.get_messages('record')):
        if i >= sample_count:
            break
        records.append(message.get_values())
    
    print(f"前{sample_count}条记录消息:")
    for i, rec in enumerate(records):
        print(f"\n记录 {i+1}:")
        for key, value in rec.items():
            print(f"  {key}: {value}")
    
    return records

if __name__ == "__main__":
    # 使用您的FIT文件路径
    FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    
    # 分析整个文件
    result = analyze_fit_file(FIT_PATH)
    
    if result:
        print("\n=== 分析完成 ===")
        print(f"找到海拔字段: {result.get('altitude_fields_found', [])}")
        
        # 如果找到了海拔字段，测试数据加载
        if result.get('altitude_fields_found'):
            print("\n正在测试海拔数据加载...")
            fit = FitFile(FIT_PATH)
            
            # 收集所有海拔数据
            all_altitudes = []
            for message in fit.get_messages('record'):
                values = message.get_values()
                for alt_field in result['altitude_fields_found']:
                    if alt_field in values and values[alt_field] is not None:
                        all_altitudes.append(values[alt_field])
            
            if all_altitudes:
                print(f"海拔数据统计:")
                print(f"  数据点数: {len(all_altitudes)}")
                print(f"  最小值: {min(all_altitudes):.2f}")
                print(f"  最大值: {max(all_altitudes):.2f}")
                print(f"  平均值: {np.mean(all_altitudes):.2f}")
                print(f"  单位: 可能是米(m)，但需要确认")


# peak_times = parse_fit_file(file_path)
# print_all_laps_and_events(file_path)
#result = analyze_fit_file_statistics(file_path)