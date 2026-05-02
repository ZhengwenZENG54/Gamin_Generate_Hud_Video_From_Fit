import sys
import os
from datetime import datetime, timedelta
from fitparse import FitFile
import importlib.util
import glob

# ==================== 用户可修改的配置 ====================
# FIT文件路径，可以设置为具体路径或None
# 如果设置为None，将自动查找脚本所在目录下最新的.fit文件
FIT_PATH = None
# FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-18-18-20-58.fit"

# 原模块路径
MODULE_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\Gamin_Generate_Hud_Video_From_Fit\generate_hud_and_map_video_20.py"

# 注意：这里改为默认不生成任何视频，让用户选择
GENERATE_HUD = False    # 是否生成HUD视频
GENERATE_MAP = False    # 是否生成地图视频
GENERATE_ELEVATION = False  # 是否生成海拔视频
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

def main():
    """主函数"""
    # 检查原模块文件是否存在
    if not os.path.exists(MODULE_PATH):
        print(f"❌ 找不到原模块文件: {MODULE_PATH}")
        return
    
    # 获取FIT文件路径
    fit_path = get_fit_path()
    if fit_path is None:
        return
    
    try:
        # 动态导入原模块
        hud_module = load_module_from_path("hud_module", MODULE_PATH)
        print("✅ 成功导入原模块")
    except Exception as e:
        print(f"❌ 导入模块失败: {e}")
        return
    
    # 获取所有lap信息
    laps = get_all_laps(fit_path)
    
    if not laps:
        print("文件中没有Lap信息，无法生成视频")
        return
    else:
        # 让用户选择要生成的lap
        selection = select_laps_for_generation(laps)
        if selection is None:
            print("用户取消操作")
            return
        lap_start, lap_end, selected_laps = selection
    
    # 让用户选择生成哪种视频
    generate_hud, generate_map, generate_elevation = get_video_selection()
    if generate_hud is None or generate_map is None or generate_elevation is None:
        print("用户取消操作")
        return
    
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
        return
    
    if selected_laps:
        print(f"选择的Lap: {[lap['index'] for lap in selected_laps]}")
    
    try:
        # 调用生成函数
        result = hud_module.generate_hud_map_elevation_video(
            fit_path=fit_path,
            lap_start=lap_start,
            lap_end=lap_end,
            generate_hud=generate_hud,
            generate_map=generate_map,
            generate_elevation=generate_elevation
        )
        
        print("\n" + "="*50)
        print("生成结果:")
        for key, value in result.items():
            print(f"{key}: {value}")
        print("="*50)
        
    except Exception as e:
        print(f"❌ 生成过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

