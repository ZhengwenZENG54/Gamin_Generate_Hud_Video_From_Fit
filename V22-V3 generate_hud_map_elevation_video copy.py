import sys
import os
from datetime import datetime, timedelta
from fitparse import FitFile
import importlib.util
import glob
import json
import time

# ==================== 用户可修改的配置 ====================
# FIT文件路径，可以设置为具体路径或None
# 如果设置为None，将自动查找脚本所在目录下最新的.fit文件
FIT_PATH = None
# FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-18-18-20-58.fit"

# 原模块路径
MODULE_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\Gamin_Generate_Hud_Video_From_Fit\generate_hud_map_elevation_video_22.py"

# 日志文件路径
LOG_FILE = r"Gamin_Generate_Hud_Video_From_Fit\fit_video_audit_log.txt"

# 注意：这里改为默认不生成任何视频，让用户选择
GENERATE_HUD = False    # 是否生成HUD视频
GENERATE_MAP = False    # 是否生成地图视频
GENERATE_ELEVATION = False  # 是否生成海拔视频

# 新增：视频帧率配置（默认值，可以根据需要修改）
HUD_FPS = 30     # HUD视频帧率
MAP_FPS = 5     # 地图视频帧率
ELEVATION_FPS = 5  # 海拔视频帧率
# =====================================================

def load_module_from_path(module_name, file_path):
    """从指定路径动态加载模块"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def get_all_laps(fit_path):
    """获取fit文件中的所有lap信息"""
    print(f"正在读取FIT文件: {fit_path}")
    fit = FitFile(fit_path)
    
    laps = []
    print("\n=== FIT文件中的Lap信息 ===")
    
    for i, lap in enumerate(fit.get_messages("lap")):
        vals = lap.get_values()
        start_time = vals.get("start_time")
        elapsed = vals.get("total_elapsed_time")
        trigger = vals.get("lap_trigger")
        total_distance = vals.get("total_distance", 0.0)  # 获取总距离
        
        if start_time is not None and elapsed is not None:
            end_time = start_time + timedelta(seconds=elapsed)
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
            
            lap_info = {
                "index": i + 1,
                "start_time": start_time,
                "end_time": end_time,
                "elapsed_seconds": elapsed,
                "total_distance": total_distance,
                "trigger": trigger
            }
            laps.append(lap_info)
            
            print(f"[Lap {i+1}]")
            print(f"  开始时间: {start_time}")
            print(f"  结束时间: {end_time_str}")
            print(f"  持续时间: {elapsed:.1f}秒")
            print(f"  总距离: {total_distance:.2f}m ({total_distance/1000:.2f}km)")
            print(f"  触发类型: {trigger}")
            print(f"  {'-'*40}")
    
    if not laps:
        print("未找到Lap信息")
    
    return laps

def select_laps_for_generation(laps):
    """让用户选择要生成的lap"""
    if not laps:
        print("没有可用的Lap信息")
        return None
    
    print("\n请选择要生成视频的Lap（输入序号，多个用逗号分隔，q退出）:")
    for lap in laps:
        print(f"{lap['index']}. Lap {lap['index']} ({lap['elapsed_seconds']:.1f}秒, {lap['total_distance']/1000:.2f}km)")
    
    while True:
        choice = input("请输入选择: ").strip()
        
        if choice.lower() == 'q':
            return None
        
        if choice:
            try:
                selected_indices = [int(idx.strip()) for idx in choice.split(',')]
                selected_laps = []
                selected_start = None
                selected_end = None
                
                for idx in selected_indices:
                    if 1 <= idx <= len(laps):
                        lap = laps[idx-1]
                        selected_laps.append(lap)
                        
                        if selected_start is None or lap['start_time'] < selected_start:
                            selected_start = lap['start_time']
                        if selected_end is None or lap['end_time'] > selected_end:
                            selected_end = lap['end_time']
                    else:
                        print(f"警告: Lap {idx} 不存在，跳过")
                
                if selected_laps:
                    print(f"\n已选择 {len(selected_laps)} 个Lap:")
                    for lap in selected_laps:
                        print(f"  Lap {lap['index']}: {lap['start_time']} 到 {lap['end_time']}")
                    print(f"合并时间范围: {selected_start} 到 {selected_end}")
                    return selected_start, selected_end, selected_laps
                else:
                    print("没有有效的选择")
            except ValueError:
                print("输入无效，请重新输入")

def find_latest_fit_file():
    """查找当前目录下最新的.fit文件"""
    fit_files = glob.glob("*.fit")
    
    if not fit_files:
        # 如果没有找到，尝试在子目录中查找
        fit_files = glob.glob("**/*.fit", recursive=True)
    
    if not fit_files:
        return None
    
    # 按修改时间排序，获取最新的文件
    fit_files.sort(key=os.path.getmtime, reverse=True)
    latest_fit = os.path.abspath(fit_files[0])
    print(f"找到最新的FIT文件: {latest_fit}")
    return latest_fit

def get_fit_path():
    """获取FIT文件路径，如果未指定则自动查找最新文件"""
    if FIT_PATH is None:
        print("未指定FIT_PATH，正在查找当前目录下最新的.fit文件...")
        fit_path = find_latest_fit_file()
        if fit_path is None:
            print("❌ 未找到任何.fit文件")
            print("请在代码开头设置FIT_PATH，或在当前目录下放置.fit文件")
            return None
        return fit_path
    else:
        if not os.path.exists(FIT_PATH):
            print(f"❌ 找不到指定的FIT文件: {FIT_PATH}")
            return None
        return os.path.abspath(FIT_PATH)

def get_video_selection():
    """让用户选择生成哪种视频"""
    print("\n请选择要生成的视频类型:")
    print("1. 只生成HUD视频（数据叠加层）")
    print("2. 只生成地图视频（轨迹动画）")
    print("3. 只生成海拔视频（爬升动画）")
    print("4. 生成HUD + 地图")
    print("5. 生成HUD + 海拔")
    print("6. 生成地图 + 海拔")
    print("7. 全部生成（HUD + 地图 + 海拔）")
    print("q. 退出")
    
    while True:
        choice = input("请输入选择 (1/2/3/4/5/6/7/q): ").strip().lower()
        
        if choice == 'q':
            return None, None, None
        
        if choice in ['1', '2', '3', '4', '5', '6', '7']:
            if choice == '1':
                return True, False, False
            elif choice == '2':
                return False, True, False
            elif choice == '3':
                return False, False, True
            elif choice == '4':
                return True, True, False
            elif choice == '5':
                return True, False, True
            elif choice == '6':
                return False, True, True
            else:  # choice == '7'
                return True, True, True
        else:
            print("输入无效，请重新输入")

def seconds_to_hms(seconds):
    """将秒转换为时-分-秒格式"""
    if seconds is None:
        return "N/A"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

def write_audit_log(audit_info):
    """将审计信息写入日志文件"""
    try:
        # 检查日志文件是否存在，不存在则创建
        file_exists = os.path.exists(LOG_FILE)
        
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            if not file_exists:
                # 写入表头
                f.write("="*80 + "\n")
                f.write("FIT视频生成审计日志\n")
                f.write("="*80 + "\n\n")
            
            # 写入本次调用信息
            f.write(f"[调用时间] {audit_info['timestamp']}\n")
            f.write(f"FIT文件: {audit_info['fit_file']}\n")
            
            if audit_info['selected_laps']:
                f.write(f"选择的Lap: {', '.join(map(str, audit_info['selected_lap_indices']))}\n")
                f.write(f"选择的Lap详细信息:\n")
                for lap in audit_info['selected_laps']:
                    lap_seconds = lap.get('elapsed_seconds', 0)
                    hms = seconds_to_hms(lap_seconds)
                    f.write(f"  Lap {lap.get('index', 'N/A')}: {hms} ({lap_seconds:.1f}秒)\n")
                
                # 总时长
                total_seconds = sum(lap.get('elapsed_seconds', 0) for lap in audit_info['selected_laps'])
                total_hms = seconds_to_hms(total_seconds)
                f.write(f"总时长: {total_hms} ({total_seconds:.1f}秒)\n")
            else:
                f.write("选择的Lap: 无\n")
            
            # 视频类型
            video_types = []
            if audit_info['generate_hud']:
                video_types.append("HUD视频")
            if audit_info['generate_map']:
                video_types.append("地图视频")
            if audit_info['generate_elevation']:
                video_types.append("海拔视频")
            
            f.write(f"生成视频类型: {' + '.join(video_types) if video_types else '无'}\n")
            
            # 新增：视频帧率信息
            f.write("视频帧率设置:\n")
            if audit_info['generate_hud']:
                f.write(f"  HUD视频: {audit_info.get('hud_fps', 'N/A')} FPS\n")
            if audit_info['generate_map']:
                f.write(f"  地图视频: {audit_info.get('map_fps', 'N/A')} FPS\n")
            if audit_info['generate_elevation']:
                f.write(f"  海拔视频: {audit_info.get('elevation_fps', 'N/A')} FPS\n")
            
            # 时间统计
            f.write(f"时间统计:\n")
            if audit_info.get('hud_time') is not None and audit_info['generate_hud']:
                f.write(f"  HUD视频生成时间: {audit_info['hud_time']:.2f}秒\n")
            if audit_info.get('map_time') is not None and audit_info['generate_map']:
                f.write(f"  地图视频生成时间: {audit_info['map_time']:.2f}秒\n")
            if audit_info.get('elevation_time') is not None and audit_info['generate_elevation']:
                f.write(f"  海拔视频生成时间: {audit_info['elevation_time']:.2f}秒\n")
            
            f.write(f"  总耗时: {audit_info['total_time']:.2f}秒\n")
            
            # 新增：帧数信息
            f.write("生成的帧数:\n")
            if audit_info.get('hud_frame_count') and audit_info['generate_hud']:
                f.write(f"  HUD视频: {audit_info['hud_frame_count']} 帧\n")
            if audit_info.get('map_frame_count') and audit_info['generate_map']:
                f.write(f"  地图视频: {audit_info['map_frame_count']} 帧\n")
            if audit_info.get('elevation_frame_count') and audit_info['generate_elevation']:
                f.write(f"  海拔视频: {audit_info['elevation_frame_count']} 帧\n")
            
            # 结果文件路径
            f.write(f"生成的文件:\n")
            for key, value in audit_info.get('result', {}).items():
                if isinstance(value, str) and os.path.exists(value):
                    f.write(f"  {key}: {value}\n")
            
            # 状态
            status = "成功" if audit_info.get('success', True) else "失败"
            f.write(f"状态: {status}")
            
            if audit_info.get('error'):
                f.write(f" (错误: {audit_info['error']})")
            
            f.write("\n")
            f.write("-"*80 + "\n\n")
        
        print(f"✅ 审计日志已保存到: {os.path.abspath(LOG_FILE)}")
        
    except Exception as e:
        print(f"❌ 写入审计日志失败: {e}")

def extract_timing_from_result(result):
    """从生成结果中提取各视频的生成时间"""
    # 这里假设结果字典中包含时间信息
    # 如果原模块返回的字典中有时间信息，我们可以提取
    # 如果没有，我们可以在调用前后分别计时
    
    hud_time = None
    map_time = None
    elevation_time = None
    
    if result:
        # 尝试从结果中提取时间
        # 这里需要根据实际的返回字典键名调整
        if 'hud_video_path' in result and 'time_hud' in result:
            hud_time = result.get('time_hud')
        elif 'hud_time' in result:
            hud_time = result.get('hud_time')
        
        if 'map_video_path' in result and 'time_map' in result:
            map_time = result.get('time_map')
        elif 'map_time' in result:
            map_time = result.get('map_time')
        
        if 'elevation_video_path' in result and 'time_elevation' in result:
            elevation_time = result.get('time_elevation')
        elif 'elevation_time' in result:
            elevation_time = result.get('elevation_time')
    
    return hud_time, map_time, elevation_time

def calculate_expected_frames(duration_sec, fps):
    """计算预期的总帧数"""
    if duration_sec is None or fps is None:
        return None
    return int(duration_sec * fps) + 1  # 加1是因为包含开始和结束帧

def extract_frame_count_from_result(result, audit_info):
    """从结果中提取帧数信息，如果没有则根据时长和FPS计算"""
    duration_sec = None
    if audit_info['selected_laps']:
        duration_sec = sum(lap.get('elapsed_seconds', 0) for lap in audit_info['selected_laps'])
    
    hud_frame_count = None
    map_frame_count = None
    elevation_frame_count = None
    
    if audit_info['generate_hud'] and duration_sec:
        hud_frame_count = calculate_expected_frames(duration_sec, audit_info.get('hud_fps'))
    
    if audit_info['generate_map'] and duration_sec:
        map_frame_count = calculate_expected_frames(duration_sec, audit_info.get('map_fps'))
    
    if audit_info['generate_elevation'] and duration_sec:
        elevation_frame_count = calculate_expected_frames(duration_sec, audit_info.get('elevation_fps'))
    
    return hud_frame_count, map_frame_count, elevation_frame_count

def get_fps_settings():
    """获取视频帧率设置"""
    print("\n" + "="*50)
    print("视频帧率设置（使用默认值或自定义）:")
    print("="*50)
    print(f"当前默认帧率:")
    print(f"  HUD视频: {HUD_FPS} FPS")
    print(f"  地图视频: {MAP_FPS} FPS")
    print(f"  海拔视频: {ELEVATION_FPS} FPS")
    print("\n1. 使用默认帧率")
    print("2. 自定义帧率")
    print("q. 退出")
    
    while True:
        choice = input("请选择 (1/2/q): ").strip().lower()
        
        if choice == 'q':
            return None, None, None
        
        if choice in ['1', '2']:
            if choice == '1':
                print(f"使用默认帧率: HUD={HUD_FPS}, 地图={MAP_FPS}, 海拔={ELEVATION_FPS} FPS")
                return HUD_FPS, MAP_FPS, ELEVATION_FPS
            else:
                # 自定义帧率
                try:
                    print("\n请输入各视频的帧率（正整数）:")
                    hud_fps_input = input(f"HUD视频帧率 (默认{HUD_FPS}): ").strip()
                    map_fps_input = input(f"地图视频帧率 (默认{MAP_FPS}): ").strip()
                    elevation_fps_input = input(f"海拔视频帧率 (默认{ELEVATION_FPS}): ").strip()
                    
                    # 使用默认值或自定义值
                    hud_fps = int(hud_fps_input) if hud_fps_input else HUD_FPS
                    map_fps = int(map_fps_input) if map_fps_input else MAP_FPS
                    elevation_fps = int(elevation_fps_input) if elevation_fps_input else ELEVATION_FPS
                    
                    # 验证帧率有效性
                    if hud_fps <= 0 or map_fps <= 0 or elevation_fps <= 0:
                        print("错误: 帧率必须是正整数")
                        continue
                    
                    print(f"自定义帧率设置: HUD={hud_fps}, 地图={map_fps}, 海拔={elevation_fps} FPS")
                    return hud_fps, map_fps, elevation_fps
                except ValueError:
                    print("错误: 请输入有效的数字")
        else:
            print("输入无效，请重新输入")

def main():
    """主函数"""
    # 记录总开始时间
    total_start_time = time.time()
    
    # 初始化审计信息
    audit_info = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'fit_file': None,
        'selected_lap_indices': [],
        'selected_laps': [],
        'generate_hud': False,
        'generate_map': False,
        'generate_elevation': False,
        'hud_fps': HUD_FPS,
        'map_fps': MAP_FPS,
        'elevation_fps': ELEVATION_FPS,
        'hud_time': None,
        'map_time': None,
        'elevation_time': None,
        'hud_frame_count': None,
        'map_frame_count': None,
        'elevation_frame_count': None,
        'total_time': 0,
        'result': {},
        'success': True,
        'error': None
    }
    
    try:
        # 检查原模块文件是否存在
        if not os.path.exists(MODULE_PATH):
            error_msg = f"找不到原模块文件: {MODULE_PATH}"
            print(f"❌ {error_msg}")
            audit_info['success'] = False
            audit_info['error'] = error_msg
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        # 获取FIT文件路径
        fit_path = get_fit_path()
        if fit_path is None:
            error_msg = "无法获取FIT文件路径"
            print(f"❌ {error_msg}")
            audit_info['success'] = False
            audit_info['error'] = error_msg
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        audit_info['fit_file'] = os.path.basename(fit_path)
        
        try:
            # 动态导入原模块
            hud_module = load_module_from_path("hud_module", MODULE_PATH)
            print("✅ 成功导入原模块")
        except Exception as e:
            error_msg = f"导入模块失败: {e}"
            print(f"❌ {error_msg}")
            audit_info['success'] = False
            audit_info['error'] = error_msg
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        # 获取所有lap信息
        laps = get_all_laps(fit_path)
        
        if not laps:
            error_msg = "文件中没有Lap信息，无法生成视频"
            print(error_msg)
            audit_info['success'] = False
            audit_info['error'] = error_msg
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        else:
            # 让用户选择要生成的lap
            selection = select_laps_for_generation(laps)
            if selection is None:
                print("用户取消操作")
                audit_info['success'] = False
                audit_info['error'] = "用户取消操作"
                audit_info['total_time'] = time.time() - total_start_time
                write_audit_log(audit_info)
                return
            
            lap_start, lap_end, selected_laps = selection
            audit_info['selected_laps'] = selected_laps
            audit_info['selected_lap_indices'] = [lap['index'] for lap in selected_laps]
        
        # 让用户选择生成哪种视频
        generate_hud, generate_map, generate_elevation = get_video_selection()
        if generate_hud is None or generate_map is None or generate_elevation is None:
            print("用户取消操作")
            audit_info['success'] = False
            audit_info['error'] = "用户取消操作"
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        audit_info['generate_hud'] = generate_hud
        audit_info['generate_map'] = generate_map
        audit_info['generate_elevation'] = generate_elevation
        
        # 让用户选择帧率设置
        hud_fps, map_fps, elevation_fps = get_fps_settings()
        if hud_fps is None or map_fps is None or elevation_fps is None:
            print("用户取消操作")
            audit_info['success'] = False
            audit_info['error'] = "用户取消操作"
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        audit_info['hud_fps'] = hud_fps
        audit_info['map_fps'] = map_fps
        audit_info['elevation_fps'] = elevation_fps
        
        print(f"\n开始生成视频...")
        print(f"FIT文件: {fit_path}")
        print(f"时间范围: {lap_start} 到 {lap_end}")
        
        # 显示用户选择的视频类型
        video_types = []
        if generate_hud:
            video_types.append("HUD视频")
        if generate_map:
            video_types.append("地图视频")
        if generate_elevation:
            video_types.append("海拔视频")
        
        if video_types:
            print(f"生成的视频类型: " + " + ".join(video_types))
        else:
            print("未选择任何视频类型，退出")
            audit_info['success'] = False
            audit_info['error'] = "未选择任何视频类型"
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        if selected_laps:
            print(f"选择的Lap: {[lap['index'] for lap in selected_laps]}")
        
        # 显示帧率设置
        print(f"视频帧率设置:")
        if generate_hud:
            print(f"  HUD视频: {hud_fps} FPS")
        if generate_map:
            print(f"  地图视频: {map_fps} FPS")
        if generate_elevation:
            print(f"  海拔视频: {elevation_fps} FPS")
        
        # 计算预期帧数
        hud_frame_count, map_frame_count, elevation_frame_count = extract_frame_count_from_result(None, audit_info)
        audit_info['hud_frame_count'] = hud_frame_count
        audit_info['map_frame_count'] = map_frame_count
        audit_info['elevation_frame_count'] = elevation_frame_count
        
        if hud_frame_count:
            print(f"预期HUD视频帧数: {hud_frame_count}帧")
        if map_frame_count:
            print(f"预期地图视频帧数: {map_frame_count}帧")
        if elevation_frame_count:
            print(f"预期海拔视频帧数: {elevation_frame_count}帧")
        
        # 记录各视频的生成时间
        hud_start_time = None
        map_start_time = None
        elevation_start_time = None
        
        try:
            # 调用生成函数，传递FPS参数
            result = hud_module.generate_hud_map_elevation_video(
                fit_path=fit_path,
                lap_start=lap_start,
                lap_end=lap_end,
                generate_hud=generate_hud,
                generate_map=generate_map,
                generate_elevation=generate_elevation,
                hud_fps=hud_fps,
                map_fps=map_fps,
                elevation_fps=elevation_fps
            )
            
            # 保存结果
            audit_info['result'] = result
            
            print("\n" + "="*50)
            print("生成结果:")
            for key, value in result.items():
                print(f"{key}: {value}")
            print("="*50)
            
            # 从结果中提取时间信息
            hud_time, map_time, elevation_time = extract_timing_from_result(result)
            audit_info['hud_time'] = hud_time
            audit_info['map_time'] = map_time
            audit_info['elevation_time'] = elevation_time
            
        except Exception as e:
            print(f"❌ 生成过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            
            audit_info['success'] = False
            audit_info['error'] = str(e)
        
        finally:
            # 计算总时间
            total_end_time = time.time()
            audit_info['total_time'] = total_end_time - total_start_time
            
            # 写入审计日志
            write_audit_log(audit_info)
            
    except Exception as e:
        print(f"❌ 主程序发生错误: {e}")
        import traceback
        traceback.print_exc()
        
        audit_info['success'] = False
        audit_info['error'] = str(e)
        audit_info['total_time'] = time.time() - total_start_time
        write_audit_log(audit_info)

if __name__ == "__main__":
    main()