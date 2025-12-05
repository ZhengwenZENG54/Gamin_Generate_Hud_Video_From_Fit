from fitparse import FitFile
from datetime import timedelta


# 使用示例
file_path = r"2025-12-03-18-23-42.fit"

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





#peak_times = parse_fit_file(file_path)
print_all_laps_and_events(file_path)
