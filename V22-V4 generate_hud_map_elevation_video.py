import sys
import os
from datetime import datetime, timedelta
from fitparse import FitFile
import importlib.util
import glob
import json
import time
import traceback

# ==================== 用户可修改的配置 ====================
# FIT文件路径，可以设置为具体路径或None
# 如果设置为None，将自动查找脚本所在目录下最新的.fit文件
FIT_PATH = None
# FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-18-18-20-58.fit"

# 原模块路径
MODULE_PATH_A = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\Gamin_Generate_Hud_Video_From_Fit\generate_hud_map_elevation_video_22.py"
MODULE_PATH_C = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\Gamin_Generate_Hud_Video_From_Fit\generate_time_distance_elevation_video_4.py" 

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

# 新增：是否在A运行后自动运行C
AUTO_RUN_C = True
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
            
            # 模块alpha生成结果
            f.write("\n=== 模块alpha生成结果 ===\n")
            video_types_a = []
            if audit_info.get('generate_hud_a'):
                video_types_a.append("HUD视频")
            if audit_info.get('generate_map_a'):
                video_types_a.append("地图视频")
            if audit_info.get('generate_elevation_a'):
                video_types_a.append("海拔视频")
            
            f.write(f"生成视频类型: {' + '.join(video_types_a) if video_types_a else '无'}\n")
            
            # 视频帧率设置
            f.write("视频帧率设置:\n")
            if audit_info.get('generate_hud_a'):
                f.write(f"  HUD视频: {audit_info.get('hud_fps_a', 'N/A')} FPS\n")
            if audit_info.get('generate_map_a'):
                f.write(f"  地图视频: {audit_info.get('map_fps_a', 'N/A')} FPS\n")
            if audit_info.get('generate_elevation_a'):
                f.write(f"  海拔视频: {audit_info.get('elevation_fps_a', 'N/A')} FPS\n")
            
            # 时间统计
            f.write(f"时间统计:\n")
            if audit_info.get('hud_time_a') is not None and audit_info.get('generate_hud_a'):
                f.write(f"  HUD视频生成时间: {audit_info['hud_time_a']:.2f}秒\n")
            if audit_info.get('map_time_a') is not None and audit_info.get('generate_map_a'):
                f.write(f"  地图视频生成时间: {audit_info['map_time_a']:.2f}秒\n")
            if audit_info.get('elevation_time_a') is not None and audit_info.get('generate_elevation_a'):
                f.write(f"  海拔视频生成时间: {audit_info['elevation_time_a']:.2f}秒\n")
            
            f.write(f"  模块alpha总耗时: {audit_info.get('total_time_a', 0):.2f}秒\n")
            
            # 生成的帧数
            f.write("生成的帧数:\n")
            if audit_info.get('hud_frame_count_a') and audit_info.get('generate_hud_a'):
                f.write(f"  HUD视频: {audit_info['hud_frame_count_a']} 帧\n")
            if audit_info.get('map_frame_count_a') and audit_info.get('generate_map_a'):
                f.write(f"  地图视频: {audit_info['map_frame_count_a']} 帧\n")
            if audit_info.get('elevation_frame_count_a') and audit_info.get('generate_elevation_a'):
                f.write(f"  海拔视频: {audit_info['elevation_frame_count_a']} 帧\n")
            
            # 模块alpha生成的文件路径
            f.write(f"模块alpha生成的文件:\n")
            for key, value in audit_info.get('result_a', {}).items():
                if isinstance(value, str) and os.path.exists(value):
                    f.write(f"  {key}: {value}\n")
            
            # 模块beta生成结果
            f.write("\n=== 模块beta生成结果 ===\n")
            video_types_c = []
            if audit_info.get('generate_time_c'):
                video_types_c.append("时间视频")
            if audit_info.get('generate_distance_c'):
                video_types_c.append("距离视频")
            if audit_info.get('generate_elevation_c'):
                video_types_c.append("海拔视频")
            
            f.write(f"生成视频类型: {' + '.join(video_types_c) if video_types_c else '无'}\n")
            
            # 视频帧率设置
            f.write("视频帧率设置:\n")
            if audit_info.get('generate_time_c'):
                f.write(f"  时间视频: {audit_info.get('time_fps_c', 'N/A')} FPS\n")
            if audit_info.get('generate_distance_c'):
                f.write(f"  距离视频: {audit_info.get('distance_fps_c', 'N/A')} FPS\n")
            if audit_info.get('generate_elevation_c'):
                f.write(f"  海拔视频: {audit_info.get('elevation_fps_c', 'N/A')} FPS\n")
            
            # 时间统计
            f.write(f"时间统计:\n")
            if audit_info.get('time_time_c') is not None and audit_info.get('generate_time_c'):
                f.write(f"  时间视频生成时间: {audit_info['time_time_c']:.2f}秒\n")
            if audit_info.get('distance_time_c') is not None and audit_info.get('generate_distance_c'):
                f.write(f"  距离视频生成时间: {audit_info['distance_time_c']:.2f}秒\n")
            if audit_info.get('elevation_time_c') is not None and audit_info.get('generate_elevation_c'):
                f.write(f"  海拔视频生成时间: {audit_info['elevation_time_c']:.2f}秒\n")
            
            f.write(f"  模块beta总耗时: {audit_info.get('total_time_c', 0):.2f}秒\n")
            
            # 生成的帧数
            f.write("生成的帧数:\n")
            if audit_info.get('time_frame_count_c') and audit_info.get('generate_time_c'):
                f.write(f"  时间视频: {audit_info['time_frame_count_c']} 帧\n")
            if audit_info.get('distance_frame_count_c') and audit_info.get('generate_distance_c'):
                f.write(f"  距离视频: {audit_info['distance_frame_count_c']} 帧\n")
            if audit_info.get('elevation_frame_count_c') and audit_info.get('generate_elevation_c'):
                f.write(f"  海拔视频: {audit_info['elevation_frame_count_c']} 帧\n")
            
            # 模块beta生成的文件路径
            f.write(f"模块beta生成的文件:\n")
            for key, value in audit_info.get('result_c', {}).items():
                if isinstance(value, str) and os.path.exists(value):
                    f.write(f"  {key}: {value}\n")
            
            # 总体统计
            f.write(f"\n=== 总体统计 ===\n")
            f.write(f"总耗时: {audit_info['total_time']:.2f}秒\n")
            
            # 状态
            status_a = "成功" if audit_info.get('success_a', True) else "失败"
            status_c = "成功" if audit_info.get('success_c', True) else "失败"
            f.write(f"模块alpha状态: {status_a}")
            if audit_info.get('error_a'):
                f.write(f" (错误: {audit_info['error_a']})")
            f.write(f"\n模块beta状态: {status_c}")
            if audit_info.get('error_c'):
                f.write(f" (错误: {audit_info['error_c']})")
            
            f.write("\n")
            f.write("-"*80 + "\n\n")
        
        print(f"✅ 审计日志已保存到: {os.path.abspath(LOG_FILE)}")
        
    except Exception as e:
        print(f"❌ 写入审计日志失败: {e}")

def calculate_expected_frames(duration_sec, fps):
    """计算预期的总帧数"""
    if duration_sec is None or fps is None:
        return None
    return int(duration_sec * fps) + 1  # 加1是因为包含开始和结束帧

def get_fps_settings():
    """获取视频帧率设置"""
    print("\n" + "="*50)
    print("模块alpha视频帧率设置（使用默认值或自定义）:")
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

def run_module_a(fit_path, lap_start, lap_end, generate_hud, generate_map, generate_elevation, 
                 hud_fps, map_fps, elevation_fps, audit_info):
    """运行模块alpha并收集结果"""
    print("\n" + "="*60)
    print("开始运行模块alpha")
    print("="*60)
    
    try:
        # 检查模块文件是否存在
        if not os.path.exists(MODULE_PATH_A):
            error_msg = f"找不到模块alpha文件: {MODULE_PATH_A}"
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
        
        # 动态导入模块alpha
        module_a = load_module_from_path("module_a", MODULE_PATH_A)
        print("✅ 成功导入模块alpha")
        
        # 计算预期的帧数
        duration_sec = (lap_end - lap_start).total_seconds()
        hud_frame_count = calculate_expected_frames(duration_sec, hud_fps) if generate_hud else None
        map_frame_count = calculate_expected_frames(duration_sec, map_fps) if generate_map else None
        elevation_frame_count = calculate_expected_frames(duration_sec, elevation_fps) if generate_elevation else None
        
        # 更新审计信息
        audit_info.update({
            'generate_hud_a': generate_hud,
            'generate_map_a': generate_map,
            'generate_elevation_a': generate_elevation,
            'hud_fps_a': hud_fps,
            'map_fps_a': map_fps,
            'elevation_fps_a': elevation_fps,
            'hud_frame_count_a': hud_frame_count,
            'map_frame_count_a': map_frame_count,
            'elevation_frame_count_a': elevation_frame_count
        })
        
        # 显示开始信息
        print(f"FIT文件: {fit_path}")
        print(f"时间范围: {lap_start} 到 {lap_end}")
        print(f"时长: {duration_sec:.1f}秒")
        
        if generate_hud:
            print(f"生成HUD视频: 是 (FPS: {hud_fps}, 预期帧数: {hud_frame_count})")
        if generate_map:
            print(f"生成地图视频: 是 (FPS: {map_fps}, 预期帧数: {map_frame_count})")
        if generate_elevation:
            print(f"生成海拔视频: 是 (FPS: {elevation_fps}, 预期帧数: {elevation_frame_count})")
        
        # 记录开始时间
        start_time = time.time()
        
        # 调用模块alpha的生成函数
        result_a = module_a.generate_hud_map_elevation_video(
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
        
        # 记录结束时间
        end_time = time.time()
        total_time_a = end_time - start_time
        
        # 更新审计信息
        audit_info.update({
            'result_a': result_a,
            'total_time_a': total_time_a,
            'success_a': True
        })
        
        print(f"\n模块alpha运行完成，耗时: {total_time_a:.2f}秒")
        
        # 显示结果
        if result_a:
            print("\n模块alpha生成结果:")
            for key, value in result_a.items():
                print(f"  {key}: {value}")
        
        return {'success': True, 'result': result_a, 'total_time': total_time_a}
        
    except Exception as e:
        print(f"❌ 模块alpha运行失败: {e}")
        traceback.print_exc()
        
        error_msg = str(e)
        audit_info.update({
            'success_a': False,
            'error_a': error_msg
        })
        
        return {'success': False, 'error': error_msg}

def run_module_c(fit_path, lap_start, lap_end, audit_info):
    """运行模块beta并收集结果"""
    print("\n" + "="*60)
    print("开始运行模块beta")
    print("="*60)
    
    try:
        # 检查模块文件是否存在
        if not os.path.exists(MODULE_PATH_C):
            error_msg = f"找不到模块beta文件: {MODULE_PATH_C}"
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
        
        # 动态导入模块beta
        module_c = load_module_from_path("module_c", MODULE_PATH_C)
        print("✅ 成功导入模块beta")
        
        # 检查模块beta是否有可调用的函数
        # 我们假设模块beta有一个函数可以以编程方式调用
        # 首先尝试使用generate_videos_from_fit函数，如果不存在则尝试调用main函数
        
        # 默认生成所有三种视频
        generate_time = True
        generate_distance = True
        generate_elevation = True
        
        # 模块beta的默认FPS（从模块beta的配置中获取，或者使用默认值）
        # 我们需要从模块beta中导入这些值，如果不可用则使用默认值
        try:
            time_fps = module_c.FPS_TIME
        except AttributeError:
            time_fps = 1
        
        try:
            distance_fps = module_c.FPS_DISTANCE
        except AttributeError:
            distance_fps = 5
        
        try:
            elevation_fps = module_c.FPS_ELEVATION
        except AttributeError:
            elevation_fps = 5
        
        # 计算预期的帧数
        duration_sec = (lap_end - lap_start).total_seconds()
        time_frame_count = calculate_expected_frames(duration_sec, time_fps) if generate_time else None
        distance_frame_count = calculate_expected_frames(duration_sec, distance_fps) if generate_distance else None
        elevation_frame_count = calculate_expected_frames(duration_sec, elevation_fps) if generate_elevation else None
        
        # 更新审计信息
        audit_info.update({
            'generate_time_c': generate_time,
            'generate_distance_c': generate_distance,
            'generate_elevation_c': generate_elevation,
            'time_fps_c': time_fps,
            'distance_fps_c': distance_fps,
            'elevation_fps_c': elevation_fps,
            'time_frame_count_c': time_frame_count,
            'distance_frame_count_c': distance_frame_count,
            'elevation_frame_count_c': elevation_frame_count
        })
        
        # 显示开始信息
        print(f"FIT文件: {fit_path}")
        print(f"时间范围: {lap_start} 到 {lap_end}")
        print(f"时长: {duration_sec:.1f}秒")
        print(f"生成时间视频: 是 (FPS: {time_fps}, 预期帧数: {time_frame_count})")
        print(f"生成距离视频: 是 (FPS: {distance_fps}, 预期帧数: {distance_frame_count})")
        print(f"生成海拔视频: 是 (FPS: {elevation_fps}, 预期帧数: {elevation_frame_count})")
        
        # 记录开始时间
        start_time = time.time()
        
        # 尝试调用模块beta的生成函数
        # 我们假设模块beta有一个generate_videos函数可以接受参数
        result_c = None
        
        # 方法1: 尝试调用generate_videos_from_fit函数
        if hasattr(module_c, 'generate_videos_from_fit'):
            print("调用模块beta的generate_videos_from_fit函数...")
            result_c = module_c.generate_videos_from_fit(
                fit_path=fit_path,
                lap_start=lap_start,
                lap_end=lap_end,
                generate_time=generate_time,
                generate_distance=generate_distance,
                generate_elevation=generate_elevation
            )
        # 方法2: 尝试调用main函数
        elif hasattr(module_c, 'main'):
            print("警告: 模块beta没有generate_videos_from_fit函数，尝试调用main函数...")
            # 由于main函数可能需要用户交互，这里可能需要特殊处理
            # 我们可以设置一些全局变量来模拟用户输入
            result_c = module_c.main()
        else:
            error_msg = "模块beta没有可调用的生成函数"
            print(f"❌ {error_msg}")
            audit_info.update({
                'success_c': False,
                'error_c': error_msg
            })
            return {'success': False, 'error': error_msg}
        
        # 记录结束时间
        end_time = time.time()
        total_time_c = end_time - start_time
        
        # 更新审计信息
        audit_info.update({
            'result_c': result_c or {},
            'total_time_c': total_time_c,
            'success_c': True
        })
        
        print(f"\n模块beta运行完成，耗时: {total_time_c:.2f}秒")
        
        # 显示结果
        if result_c and isinstance(result_c, dict):
            print("\n模块beta生成结果:")
            for key, value in result_c.items():
                print(f"  {key}: {value}")
        
        return {'success': True, 'result': result_c, 'total_time': total_time_c}
        
    except Exception as e:
        print(f"❌ 模块beta运行失败: {e}")
        traceback.print_exc()
        
        error_msg = str(e)
        audit_info.update({
            'success_c': False,
            'error_c': error_msg
        })
        
        return {'success': False, 'error': error_msg}

def get_auto_run_c_choice():
    """询问用户是否在A运行后自动运行C"""
    print("\n" + "="*50)
    print("是否在模块alpha运行后自动运行模块beta？")
    print("="*50)
    print("模块beta将使用模块alpha中选择的Lap，生成时间、距离、海拔三种视频。")
    print("\n1. 是，自动运行模块beta")
    print("2. 否，只运行模块alpha")
    print("q. 退出")
    
    while True:
        choice = input("请选择 (1/2/q): ").strip().lower()
        
        if choice == 'q':
            return None
        elif choice == '1':
            return True
        elif choice == '2':
            return False
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
        'total_time': 0,
        'success_a': True,
        'success_c': True,
        'error_a': None,
        'error_c': None
    }
    
    try:
        # 获取FIT文件路径
        fit_path = get_fit_path()
        if fit_path is None:
            error_msg = "无法获取FIT文件路径"
            print(f"❌ {error_msg}")
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        audit_info['fit_file'] = os.path.basename(fit_path)
        
        # 获取所有lap信息
        laps = get_all_laps(fit_path)
        
        if not laps:
            error_msg = "文件中没有Lap信息，无法生成视频"
            print(error_msg)
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        else:
            # 让用户选择要生成的lap
            selection = select_laps_for_generation(laps)
            if selection is None:
                print("用户取消操作")
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
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        if not generate_hud and not generate_map and not generate_elevation:
            print("未选择任何视频类型，退出")
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        # 让用户选择帧率设置
        hud_fps, map_fps, elevation_fps = get_fps_settings()
        if hud_fps is None or map_fps is None or elevation_fps is None:
            print("用户取消操作")
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        # 询问是否自动运行模块beta
        auto_run_c = get_auto_run_c_choice()
        if auto_run_c is None:
            print("用户取消操作")
            audit_info['total_time'] = time.time() - total_start_time
            write_audit_log(audit_info)
            return
        
        # 运行模块alpha
        result_a = run_module_a(fit_path, lap_start, lap_end, generate_hud, generate_map, generate_elevation,
                              hud_fps, map_fps, elevation_fps, audit_info)
        
        # 如果需要，运行模块beta
        result_c = None
        if auto_run_c and result_a.get('success', False):
            result_c = run_module_c(fit_path, lap_start, lap_end, audit_info)
        
        # 计算总时间
        total_end_time = time.time()
        audit_info['total_time'] = total_end_time - total_start_time
        
        # 写入审计日志
        write_audit_log(audit_info)
        
        # 显示最终结果
        print("\n" + "="*60)
        print("处理完成")
        print("="*60)
        print(f"模块alpha状态: {'成功' if result_a.get('success') else '失败'}")
        if auto_run_c:
            print(f"模块beta状态: {'成功' if result_c and result_c.get('success') else '未运行或失败'}")
        print(f"总耗时: {audit_info['total_time']:.2f}秒")
        print(f"审计日志: {os.path.abspath(LOG_FILE)}")
        
    except Exception as e:
        print(f"❌ 主程序发生错误: {e}")
        traceback.print_exc()
        
        audit_info['total_time'] = time.time() - total_start_time
        write_audit_log(audit_info)

if __name__ == "__main__":
    main()