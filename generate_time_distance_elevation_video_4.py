import os
import sys
import glob
import time
import subprocess
import shutil
import threading
from datetime import datetime, timedelta
from fitparse import FitFile
import cv2
import numpy as np
from scipy.interpolate import interp1d
from PIL import Image, ImageDraw, ImageFont, ImageOps
import traceback
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("警告: tqdm库未安装，将使用简单进度显示")
    # 简单的进度显示替代
    class tqdm:
        def __init__(self, total, desc="", unit="帧"):
            self.total = total
            self.desc = desc
            self.unit = unit
            self.n = 0
            self.start_time = time.time()
            print(f"{desc}: 0/{total} {unit} (0.0%)")
        
        def update(self, n=1):
            self.n += n
            percentage = (self.n / self.total) * 100
            elapsed = time.time() - self.start_time
            fps = self.n / elapsed if elapsed > 0 else 0
            remaining = (self.total - self.n) / fps if fps > 0 else 0
            print(f"\r{self.desc}: {self.n}/{self.total} {self.unit} ({percentage:.1f}%) | "
                  f"已用: {elapsed:.1f}s | 剩余: {remaining:.1f}s | "
                  f"速度: {fps:.1f}帧/s", end="")
            
        def __enter__(self):
            return self
            
        def __exit__(self, *args):
            print()
            
        def close(self):
            pass

# ==================== 用户可配置参数 ====================
# FIT文件路径（设置为None则自动查找最新文件）
FIT_PATH = None
# FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"

# 输出视频参数
FPS_TIME = 1  # 时间视频帧率（1秒1帧）
FPS_DISTANCE = 5  # 距离视频帧率
FPS_ELEVATION = 5  # 海拔视频帧率
OUTPUT_DIR_TIME = "frames_timestamp"  # 时间帧目录
OUTPUT_DIR_DISTANCE = "frames_distance"  # 距离帧目录
OUTPUT_DIR_ELEVATION = "frames_elevation"  # 海拔帧目录
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_VIDEO_TIME = f"beta_timestamp_overlay_{timestamp}.mov"  # 时间视频文件名
OUTPUT_VIDEO_DISTANCE = f"beta_distance_overlay_{timestamp}.mov"  # 距离视频文件名
OUTPUT_VIDEO_ELEVATION = f"beta_elevation_overlay_{timestamp}.mov"  # 海拔视频文件名

# 时区设置（北京时间 = UTC+8）
TIMEZONE_OFFSET = 8  # 小时

# 时间显示样式
TIME_FONT_SIZE = 60
TIME_FONT_COLOR =  (255, 255, 255)  # 白色
TIME_OUTLINE_WIDTH = 5
TIME_OUTLINE_COLOR = (0, 0, 0)  # 黑色

# 距离显示样式
DIST_FONT_SIZE = 50
DIST_FONT_COLOR = (255, 255, 255)  # 白色
DIST_OUTLINE_WIDTH = 5
DIST_OUTLINE_COLOR = (0, 0, 0)  # 黑色

# 海拔显示样式
ELEV_FONT_SIZE = 50
ELEV_FONT_COLOR = (255, 255, 255)  # 白色
ELEV_OUTLINE_WIDTH = 5 
ELEV_OUTLINE_COLOR = (0, 0, 0)  # 黑色

# 视频尺寸设置（设置为None则自动计算）
VIDEO_WIDTH = None
VIDEO_HEIGHT = None
VIDEO_PADDING = 30  # 像素，文本周围的边距

# 字体文件路径
FONT_PATH = None

# 平滑插值参数
SMOOTHING_WINDOW = 5  # 平滑窗口大小（帧数）

# 默认生成选项
GENERATE_TIME_VIDEO = True
GENERATE_DISTANCE_VIDEO = True
GENERATE_ELEVATION_VIDEO = True

# 新增：批处理设置
BATCH_SIZE = 100  # 批处理大小，每生成多少帧保存一次进度
# =====================================================

def find_latest_fit_file():
    """查找当前目录下最新的.fit文件"""
    fit_files = glob.glob("*.fit")
    
    if not fit_files:
        fit_files = glob.glob("**/*.fit", recursive=True)
    
    if not fit_files:
        return None
    
    fit_files.sort(key=os.path.getmtime, reverse=True)
    latest_fit = os.path.abspath(fit_files[0])
    print(f"找到最新的FIT文件: {latest_fit}")
    return latest_fit

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
        total_distance = vals.get("total_distance", 0.0)
        
        if start_time is not None and elapsed is not None:
            end_time = start_time + timedelta(seconds=elapsed)
            
            lap_info = {
                "index": i + 1,
                "start_time": start_time,
                "end_time": end_time,
                "elapsed_seconds": elapsed,
                "total_distance": total_distance,
                "trigger": trigger
            }
            laps.append(lap_info)
            
            start_beijing = start_time + timedelta(hours=TIMEZONE_OFFSET)
            end_beijing = end_time + timedelta(hours=TIMEZONE_OFFSET)
            
            print(f"[Lap {i+1}]")
            print(f"  开始时间(UTC): {start_time}")
            print(f"  开始时间(北京): {start_beijing}")
            print(f"  结束时间(北京): {end_beijing.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  持续时间: {elapsed:.1f}秒 ({elapsed//60}分{elapsed%60:.0f}秒)")
            print(f"  总距离: {total_distance/1000:.2f}km")
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
        start_beijing = lap['start_time'] + timedelta(hours=TIMEZONE_OFFSET)
        print(f"{lap['index']}. Lap {lap['index']} ({lap['elapsed_seconds']:.1f}秒, {start_beijing.strftime('%H:%M:%S')})")
    
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
                    start_beijing = selected_start + timedelta(hours=TIMEZONE_OFFSET)
                    end_beijing = selected_end + timedelta(hours=TIMEZONE_OFFSET)
                    
                    print(f"\n已选择 {len(selected_laps)} 个Lap:")
                    for lap in selected_laps:
                        lap_start_beijing = lap['start_time'] + timedelta(hours=TIMEZONE_OFFSET)
                        lap_end_beijing = lap['end_time'] + timedelta(hours=TIMEZONE_OFFSET)
                        print(f"  Lap {lap['index']}: {lap_start_beijing} 到 {lap_end_beijing}")
                    print(f"合并时间范围: {start_beijing} 到 {end_beijing}")
                    return selected_start, selected_end, selected_laps
                else:
                    print("没有有效的选择")
            except ValueError:
                print("输入无效，请重新输入")

def get_video_selection():
    """让用户选择生成哪种视频"""
    print("\n请选择要生成的视频类型:")
    print("1. 只生成时间戳视频")
    print("2. 只生成距离视频")
    print("3. 只生成海拔视频")
    print("4. 生成时间戳+距离")
    print("5. 生成时间戳+海拔")
    print("6. 生成距离+海拔")
    print("7. 全部生成")
    print("q. 退出")
    
    while True:
        choice = input("请输入选择 (1/2/3/4/5/6/7/q): ").strip().lower()
        
        if choice == 'q':
            return None, None, None
        elif choice == '1':
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
        elif choice == '7':
            return True, True, True
        else:
            print("输入无效，请重新输入")

def get_fit_path():
    """获取FIT文件路径"""
    if FIT_PATH is None:
        print("未指定FIT_PATH，正在查找当前目录下最新的.fit文件...")
        fit_path = find_latest_fit_file()
        if fit_path is None:
            print("❌ 未找到任何.fit文件")
            return None
        return fit_path
    else:
        if not os.path.exists(FIT_PATH):
            print(f"❌ 找不到指定的FIT文件: {FIT_PATH}")
            return None
        return os.path.abspath(FIT_PATH)

def load_fit_data(fit_path, lap_start, lap_end):
    """加载FIT文件数据"""
    print(f"\n[数据加载] 加载FIT数据，时间范围: {lap_start} 到 {lap_end}")
    fit = FitFile(fit_path)
    
    times, distances, elevations = [], [], []
    first_valid_distance = None
    first_valid_elevation = None
    
    for m in fit.get_messages('record'):
        vals = m.get_values()
        if 'timestamp' in vals:
            ts = vals['timestamp']
            if lap_start <= ts <= lap_end:
                # 距离数据
                distance_m = vals.get('distance')
                if distance_m is not None:
                    if first_valid_distance is None:
                        first_valid_distance = distance_m
                    # 重置距离，从0开始
                    relative_distance = distance_m - first_valid_distance
                    distances.append(relative_distance)
                else:
                    distances.append(np.nan)
                
                # 海拔数据 - 优先使用增强海拔
                elevation = vals.get('enhanced_altitude') or vals.get('altitude')
                if elevation is not None:
                    if first_valid_elevation is None:
                        first_valid_elevation = elevation
                    # 从第一个有效海拔开始
                    relative_elevation = elevation
                    elevations.append(relative_elevation)
                else:
                    elevations.append(np.nan)
                
                times.append(ts)
    
    if not times:
        print("❌ 在指定时间范围内没有找到数据")
        return None, None, None
    
    # 检查数据有效性
    valid_distances = sum(1 for d in distances if not np.isnan(d))
    valid_elevations = sum(1 for e in elevations if not np.isnan(e))
    
    print(f"[数据加载] 找到 {len(times)} 个数据点")
    print(f"[距离数据] 有效点: {valid_distances}/{len(distances)}")
    print(f"[海拔数据] 有效点: {valid_elevations}/{len(elevations)}")
    
    if valid_distances > 0:
        valid_dist_values = [d for d in distances if not np.isnan(d)]
        print(f"[距离范围] {min(valid_dist_values):.2f}m 到 {max(valid_dist_values):.2f}m")
    
    if valid_elevations > 0:
        valid_elev_values = [e for e in elevations if not np.isnan(e)]
        print(f"[海拔范围] {min(valid_elev_values):.1f}m 到 {max(valid_elev_values):.1f}m")
    
    return times, distances, elevations

def interpolate_data(times, values, start_time, end_time, fps, data_type="distance"):
    """对数据进行平滑插值"""
    print(f"\n[数据插值] 开始插值{data_type}数据，目标帧率: {fps} FPS")
    
    # 计算时间偏移（秒）
    time_offsets = [(t - start_time).total_seconds() for t in times]
    duration = (end_time - start_time).total_seconds()
    
    # 生成插值时间点
    interp_times = np.linspace(0, duration, int(duration * fps) + 1)
    
    if len(time_offsets) < 2:
        print(f"❌ {data_type}数据点不足，无法进行插值")
        return None, None
    
    # 过滤NaN值
    valid_mask = ~np.isnan(values)
    valid_times = np.array(time_offsets)[valid_mask]
    valid_values = np.array(values)[valid_mask]
    
    if len(valid_times) < 2:
        print(f"❌ {data_type}有效数据点不足，无法进行插值")
        return None, None
    
    # 使用线性插值
    interp_func = interp1d(valid_times, valid_values, kind='linear', 
                          fill_value="extrapolate", bounds_error=False)
    interp_values = interp_func(interp_times)
    
    # 对于距离数据，确保不会减少（单调递增）
    if data_type == "distance":
        for i in range(1, len(interp_values)):
            if interp_values[i] < interp_values[i-1]:
                interp_values[i] = interp_values[i-1]
    
    print(f"[{data_type}插值] 生成 {len(interp_times)} 个插值点")
    if len(interp_values) > 0:
        print(f"[{data_type}插值] 范围: {min(interp_values):.2f} 到 {max(interp_values):.2f}")
    
    return interp_times, interp_values

def load_font(font_size):
    """加载字体"""
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            font = ImageFont.truetype(FONT_PATH, font_size)
        else:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", font_size)
                except:
                    font = ImageFont.load_default()
                    print("⚠️ 使用PIL默认字体")
    except Exception as e:
        print(f"⚠️ 字体加载失败: {e}，使用默认字体")
        font = ImageFont.load_default()
    
    return font

def calculate_text_size(text, font):
    """计算文本尺寸"""
    temp_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height

def calculate_video_dimensions(time_font, dist_font=None, elev_font=None, 
                              max_time_text="9999-12-31 23:59:59", 
                              max_dist_text="999.999 km",
                              max_elev_text="9999.9 m"):
    """计算视频尺寸"""
    # 计算时间文本尺寸
    time_width, time_height = calculate_text_size(max_time_text, time_font)
    time_width += TIME_OUTLINE_WIDTH * 2
    time_height += TIME_OUTLINE_WIDTH * 2
    
    # 计算距离文本尺寸
    if dist_font:
        dist_width, dist_height = calculate_text_size(max_dist_text, dist_font)
        dist_width += DIST_OUTLINE_WIDTH * 2
        dist_height += DIST_OUTLINE_WIDTH * 2
    else:
        dist_width, dist_height = 0, 0
    
    # 计算海拔文本尺寸
    if elev_font:
        elev_width, elev_height = calculate_text_size(max_elev_text, elev_font)
        elev_width += ELEV_OUTLINE_WIDTH * 2
        elev_height += ELEV_OUTLINE_WIDTH * 2
    else:
        elev_width, elev_height = 0, 0
    
    # 取最大宽度
    text_width = max(time_width, dist_width, elev_width)
    
    # 计算总高度（考虑最多三种文本）
    text_heights = []
    if time_height > 0:
        text_heights.append(time_height)
    if dist_height > 0:
        text_heights.append(dist_height)
    if elev_height > 0:
        text_heights.append(elev_height)
    
    if text_heights:
        text_height = sum(text_heights) + (len(text_heights) - 1) * 20  # 间距
    else:
        text_height = time_height
    
    # 计算最终尺寸
    if VIDEO_WIDTH is None or VIDEO_HEIGHT is None:
        width = int(text_width + VIDEO_PADDING * 2)
        height = int(text_height + VIDEO_PADDING * 2)
        
        # 确保宽高是偶数
        if width % 2 != 0:
            width += 1
        if height % 2 != 0:
            height += 1
        
        print(f"自动计算视频尺寸: {width}x{height}")
    else:
        width, height = VIDEO_WIDTH, VIDEO_HEIGHT
        print(f"使用指定视频尺寸: {width}x{height}")
    
    return width, height

def create_time_frame(timestamp_str, width, height, time_font):
    """创建时间戳帧"""
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 计算文本尺寸和位置
    text_width, text_height = calculate_text_size(timestamp_str, time_font)
    x = (width - text_width) / 2
    y = (height - text_height) / 2 - 40  # 上移，为其他数据留出空间
    
    # 绘制描边
    if TIME_OUTLINE_WIDTH > 0:
        for dx in [-TIME_OUTLINE_WIDTH, 0, TIME_OUTLINE_WIDTH]:
            for dy in [-TIME_OUTLINE_WIDTH, 0, TIME_OUTLINE_WIDTH]:
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), timestamp_str, font=time_font, fill=TIME_OUTLINE_COLOR)
    
    # 绘制主文本
    draw.text((x, y), timestamp_str, font=time_font, fill=TIME_FONT_COLOR)
    
    return image

def create_distance_frame(distance_km, width, height, dist_font):
    """创建距离帧"""
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 格式化距离文本
    distance_text = f" Dist: {distance_km:.2f} km"
    
    # 计算文本尺寸和位置
    text_width, text_height = calculate_text_size(distance_text, dist_font)
    x = (width - text_width) / 2
    y = (height - text_height) / 2  # 居中显示
    
    # 绘制描边
    if DIST_OUTLINE_WIDTH > 0:
        for dx in [-DIST_OUTLINE_WIDTH, 0, DIST_OUTLINE_WIDTH]:
            for dy in [-DIST_OUTLINE_WIDTH, 0, DIST_OUTLINE_WIDTH]:
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), distance_text, font=dist_font, fill=DIST_OUTLINE_COLOR)
    
    # 绘制主文本
    draw.text((x, y), distance_text, font=dist_font, fill=DIST_FONT_COLOR)
    
    return image

def create_elevation_frame(elevation_m, width, height, elev_font):
    """创建海拔帧"""
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 格式化海拔文本
    elevation_text = f" Elev: {elevation_m:.1f} m"
     
    # 计算文本尺寸和位置
    text_width, text_height = calculate_text_size(elevation_text, elev_font)
    x = (width - text_width) / 2
    y = (height - text_height) / 2 + 40  # 下移，为其他数据留出空间
    
    # 绘制描边
    if ELEV_OUTLINE_WIDTH > 0:
        for dx in [-ELEV_OUTLINE_WIDTH, 0, ELEV_OUTLINE_WIDTH]:
            for dy in [-ELEV_OUTLINE_WIDTH, 0, ELEV_OUTLINE_WIDTH]:
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), elevation_text, font=elev_font, fill=ELEV_OUTLINE_COLOR)
    
    # 绘制主文本
    draw.text((x, y), elevation_text, font=elev_font, fill=ELEV_FONT_COLOR)
    
    return image

def generate_time_frames_batch(lap_start, lap_end, width, height, time_font, start_frame=0, end_frame=None):
    """批量生成时间戳帧"""
    # 计算总时长和总帧数
    duration = (lap_end - lap_start).total_seconds()
    total_frames = int(duration * FPS_TIME)
    
    if end_frame is None or end_frame > total_frames:
        end_frame = total_frames
    
    frames_generated = 0
    
    for i in range(start_frame, end_frame):
        # 计算当前时间点
        current_time_utc = lap_start + timedelta(seconds=i / FPS_TIME)
        
        # 转换为北京时间
        current_time_beijing = current_time_utc + timedelta(hours=TIMEZONE_OFFSET)
        
        # 格式化时间字符串
        timestamp_str = current_time_beijing.strftime("%Y-%m-%d %H:%M:%S")
        
        # 创建帧
        frame = create_time_frame(timestamp_str, width, height, time_font)
        
        # 保存帧
        frame_path = os.path.join(OUTPUT_DIR_TIME, f"frame_{i:06d}.png")
        frame.save(frame_path, 'PNG')
        
        frames_generated += 1
    
    return frames_generated

def generate_distance_frames_batch(interp_times, interp_distances, width, height, dist_font, start_frame=0, end_frame=None):
    """批量生成距离帧"""
    total_frames = len(interp_times)
    
    if end_frame is None or end_frame > total_frames:
        end_frame = total_frames
    
    frames_generated = 0
    
    for i in range(start_frame, end_frame):
        # 获取当前距离（转换为km）
        distance_km = interp_distances[i] / 1000.0
        
        # 创建帧
        frame = create_distance_frame(distance_km, width, height, dist_font)
        
        # 保存帧
        frame_path = os.path.join(OUTPUT_DIR_DISTANCE, f"frame_{i:06d}.png")
        frame.save(frame_path, 'PNG')
        
        frames_generated += 1
    
    return frames_generated

def generate_elevation_frames_batch(interp_times, interp_elevations, width, height, elev_font, start_frame=0, end_frame=None):
    """批量生成海拔帧"""
    total_frames = len(interp_times)
    
    if end_frame is None or end_frame > total_frames:
        end_frame = total_frames
    
    frames_generated = 0
    
    for i in range(start_frame, end_frame):
        # 获取当前海拔
        elevation_m = interp_elevations[i]
        
        # 创建帧
        frame = create_elevation_frame(elevation_m, width, height, elev_font)
        
        # 保存帧
        frame_path = os.path.join(OUTPUT_DIR_ELEVATION, f"frame_{i:06d}.png")
        frame.save(frame_path, 'PNG')
        
        frames_generated += 1
    
    return frames_generated

def generate_time_frames(lap_start, lap_end, width, height, time_font):
    """生成时间戳帧序列"""
    print(f"\n[时间视频] 开始生成时间戳帧...")
    
    # 清理临时目录
    if os.path.exists(OUTPUT_DIR_TIME):
        shutil.rmtree(OUTPUT_DIR_TIME)
    os.makedirs(OUTPUT_DIR_TIME, exist_ok=True)
    
    # 计算总时长和总帧数
    duration = (lap_end - lap_start).total_seconds()
    total_frames = int(duration * FPS_TIME)
    
    print(f"[时间视频] 时间范围: {lap_start} 到 {lap_end}")
    print(f"[时间视频] 时长: {duration:.2f}秒")
    print(f"[时间视频] 帧率: {FPS_TIME} FPS")
    print(f"[时间视频] 总帧数: {total_frames}")
    print(f"[时间视频] 视频尺寸: {width}x{height}")
    
    start_time = time.time()
    
    # 使用批处理和进度条
    frame_count = 0
    with tqdm(total=total_frames, desc="生成时间帧", unit="帧") as pbar:
        for batch_start in range(0, total_frames, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_frames)
            frames_generated = generate_time_frames_batch(lap_start, lap_end, width, height, time_font, batch_start, batch_end)
            frame_count += frames_generated
            pbar.update(frames_generated)
    
    elapsed = time.time() - start_time
    fps_actual = frame_count / elapsed if elapsed > 0 else 0
    
    print(f"✅ 时间帧生成完成: {frame_count}帧, 耗时: {elapsed:.2f}秒, 平均速度: {fps_actual:.1f}帧/秒")
    return frame_count

def generate_distance_frames(interp_times, interp_distances, width, height, dist_font):
    """生成距离帧序列"""
    print(f"\n[距离视频] 开始生成距离帧...")
    
    # 清理临时目录
    if os.path.exists(OUTPUT_DIR_DISTANCE):
        shutil.rmtree(OUTPUT_DIR_DISTANCE)
    os.makedirs(OUTPUT_DIR_DISTANCE, exist_ok=True)
    
    total_frames = len(interp_times)
    
    print(f"[距离视频] 总帧数: {total_frames}")
    print(f"[距离视频] 帧率: {FPS_DISTANCE} FPS")
    print(f"[距离视频] 视频尺寸: {width}x{height}")
    print(f"[距离视频] 距离范围: {min(interp_distances)/1000:.2f}km 到 {max(interp_distances)/1000:.2f}km")
    
    start_time = time.time()
    
    # 使用批处理和进度条
    frame_count = 0
    with tqdm(total=total_frames, desc="生成距离帧", unit="帧") as pbar:
        for batch_start in range(0, total_frames, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_frames)
            frames_generated = generate_distance_frames_batch(interp_times, interp_distances, width, height, dist_font, batch_start, batch_end)
            frame_count += frames_generated
            pbar.update(frames_generated)
    
    elapsed = time.time() - start_time
    fps_actual = frame_count / elapsed if elapsed > 0 else 0
    
    print(f"✅ 距离帧生成完成: {frame_count}帧, 耗时: {elapsed:.2f}秒, 平均速度: {fps_actual:.1f}帧/秒")
    return frame_count

def generate_elevation_frames(interp_times, interp_elevations, width, height, elev_font):
    """生成海拔帧序列"""
    print(f"\n[海拔视频] 开始生成海拔帧...")
    
    # 清理临时目录
    if os.path.exists(OUTPUT_DIR_ELEVATION):
        shutil.rmtree(OUTPUT_DIR_ELEVATION)
    os.makedirs(OUTPUT_DIR_ELEVATION, exist_ok=True)
    
    total_frames = len(interp_times)
    
    print(f"[海拔视频] 总帧数: {total_frames}")
    print(f"[海拔视频] 帧率: {FPS_ELEVATION} FPS")
    print(f"[海拔视频] 视频尺寸: {width}x{height}")
    print(f"[海拔视频] 海拔范围: {min(interp_elevations):.1f}m 到 {max(interp_elevations):.1f}m")
    
    start_time = time.time()
    
    # 使用批处理和进度条
    frame_count = 0
    with tqdm(total=total_frames, desc="生成海拔帧", unit="帧") as pbar:
        for batch_start in range(0, total_frames, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_frames)
            frames_generated = generate_elevation_frames_batch(interp_times, interp_elevations, width, height, elev_font, batch_start, batch_end)
            frame_count += frames_generated
            pbar.update(frames_generated)
    
    elapsed = time.time() - start_time
    fps_actual = frame_count / elapsed if elapsed > 0 else 0
    
    print(f"✅ 海拔帧生成完成: {frame_count}帧, 耗时: {elapsed:.2f}秒, 平均速度: {fps_actual:.1f}帧/秒")
    return frame_count

def compile_video_with_progress(frame_dir, output_file, frame_count, width, height, fps, prefix="frame_"):
    """将帧合成为视频（带进度显示）"""
    print(f"\n[视频合成] 开始合成视频: {output_file}")
    
    if frame_count == 0:
        print("❌ 没有帧可合成")
        return False
    
    # 检查ffmpeg是否可用
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 未找到ffmpeg，请先安装ffmpeg")
        return False
    
    # 构建ffmpeg命令
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", os.path.join(frame_dir, f"{prefix}%06d.png"),
        "-vf", f"scale={width}:{height},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file
    ]
    
    print(f"[视频合成] 命令: {' '.join(ffmpeg_cmd)}")
    
    try:
        # 使用Popen启动进程，以便捕获输出
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # 显示进度
        print(f"[视频合成] 正在合成视频，请稍候...")
        start_time = time.time()
        
        # 读取输出并解析进度
        frame_pattern = "frame="
        for line in process.stdout:
            if frame_pattern in line:
                # 尝试从ffmpeg输出中提取帧数
                try:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if frame_pattern in part:
                            current_frame = int(part.split('=')[1])
                            percentage = (current_frame / frame_count) * 100
                            elapsed = time.time() - start_time
                            if current_frame > 0 and elapsed > 0:
                                fps_actual = current_frame / elapsed
                                remaining_time = (frame_count - current_frame) / fps_actual if fps_actual > 0 else 0
                                print(f"\r[视频合成] 进度: {current_frame}/{frame_count}帧 ({percentage:.1f}%) | "
                                      f"已用: {elapsed:.1f}s | 剩余: {remaining_time:.1f}s | "
                                      f"速度: {fps_actual:.1f}帧/s", end="")
                            break
                except (ValueError, IndexError):
                    # 如果解析失败，继续
                    pass
            elif "error" in line.lower():
                print(f"\n[视频合成警告] {line.strip()}")
        
        # 等待进程完成
        process.wait()
        
        if process.returncode == 0:
            elapsed = time.time() - start_time
            print(f"\n✅ 视频生成成功: {output_file}")
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file) / (1024 * 1024)
                print(f"文件大小: {file_size:.2f} MB")
                print(f"合成耗时: {elapsed:.2f}秒")
            return True
        else:
            print(f"\n❌ ffmpeg执行失败，返回码: {process.returncode}")
            return False
            
    except Exception as e:
        print(f"\n❌ 视频合成失败: {e}")
        traceback.print_exc()
        return False

def compile_video_simple(frame_dir, output_file, frame_count, width, height, fps, prefix="frame_"):
    """简单视频合成函数（不显示详细进度）"""
    print(f"\n[视频合成] 开始合成视频: {output_file}")
    
    if frame_count == 0:
        print("❌ 没有帧可合成")
        return False
    
    # 检查ffmpeg是否可用
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 未找到ffmpeg，请先安装ffmpeg")
        return False
    
    # 构建ffmpeg命令
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", os.path.join(frame_dir, f"{prefix}%06d.png"),
        "-vf", f"scale={width}:{height},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file
    ]
    
    print(f"[视频合成] 正在合成视频，请稍候...")
    start_time = time.time()
    
    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            print(f"✅ 视频生成成功: {output_file}")
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file) / (1024 * 1024)
                print(f"文件大小: {file_size:.2f} MB")
                print(f"合成耗时: {elapsed:.2f}秒")
            return True
        else:
            print(f"❌ ffmpeg执行失败: {result.stderr[:500]}")
            return False
            
    except Exception as e:
        print(f"❌ 视频合成失败: {e}")
        return False

def compile_all_videos(videos_to_compile, show_progress=True):
    """合成所有视频，显示总体进度"""
    if not videos_to_compile:
        print("没有需要合成的视频")
        return {}
    
    print(f"\n{'='*60}")
    print("开始合成所有视频")
    print(f"{'='*60}")
    
    results = {}
    total_videos = len(videos_to_compile)
    
    for i, (video_type, frame_dir, output_file, frame_count, width, height, fps, prefix) in enumerate(videos_to_compile, 1):
        print(f"\n[{i}/{total_videos}] 合成{video_type}视频...")
        
        if show_progress:
            success = compile_video_with_progress(frame_dir, output_file, frame_count, width, height, fps, prefix)
        else:
            success = compile_video_simple(frame_dir, output_file, frame_count, width, height, fps, prefix)
        
        results[video_type] = {
            'success': success,
            'output_file': output_file,
            'frame_count': frame_count
        }
    
    return results

def cleanup():
    """清理临时文件"""
    dirs_to_clean = [OUTPUT_DIR_TIME, OUTPUT_DIR_DISTANCE, OUTPUT_DIR_ELEVATION]
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            print(f"已清理临时目录: {dir_path}")

def generate_videos_from_fit(fit_path, lap_start, lap_end, 
                           generate_time=True, generate_distance=True, generate_elevation=True,
                           time_fps=None, distance_fps=None, elevation_fps=None,
                           interactive=False):
    """
    从FIT文件生成时间、距离、海拔视频（可编程调用）
    
    参数:
    ----------
    fit_path : str
        FIT文件路径
    lap_start : datetime
        圈开始时间
    lap_end : datetime
        圈结束时间
    generate_time : bool, 默认True
        是否生成时间视频
    generate_distance : bool, 默认True
        是否生成距离视频
    generate_elevation : bool, 默认True
        是否生成海拔视频
    time_fps : int, 可选
        时间视频帧率，None则使用默认值
    distance_fps : int, 可选
        距离视频帧率，None则使用默认值
    elevation_fps : int, 可选
        海拔视频帧率，None则使用默认值
    interactive : bool, 默认False
        是否交互式运行（用于调试）
        
    返回值:
    ----------
    dict
        包含生成结果的字典
    """
    # 设置全局FPS变量
    global FPS_TIME, FPS_DISTANCE, FPS_ELEVATION
    
    if time_fps is not None:
        FPS_TIME = time_fps
    if distance_fps is not None:
        FPS_DISTANCE = distance_fps
    if elevation_fps is not None:
        FPS_ELEVATION = elevation_fps
    
    # 记录开始时间
    program_start_time = time.time()
    
    # 初始化结果字典
    result = {
        'success': True,
        'time_video': None,
        'distance_video': None,
        'elevation_video': None,
        'time_frame_count': 0,
        'distance_frame_count': 0,
        'elevation_frame_count': 0,
        'time_fps': FPS_TIME,
        'distance_fps': FPS_DISTANCE,
        'elevation_fps': FPS_ELEVATION,
        'total_time': 0
    }
    
    try:
        if interactive:
            print("=" * 60)
            print("FIT文件时间戳/距离/海拔透明视频生成器")
            print("=" * 60)
            print(f"时区偏移: UTC+{TIMEZONE_OFFSET}")
            print(f"时间帧率: {FPS_TIME} FPS")
            print(f"距离帧率: {FPS_DISTANCE} FPS")
            print(f"海拔帧率: {FPS_ELEVATION} FPS")
            print()
        
        # 检查FIT文件是否存在
        if not os.path.exists(fit_path):
            print(f"❌ 找不到FIT文件: {fit_path}")
            result['success'] = False
            return result
        
        # 加载字体
        if interactive:
            print("\n加载字体...")
        time_font = load_font(TIME_FONT_SIZE)
        dist_font = load_font(DIST_FONT_SIZE) if generate_distance else None
        elev_font = load_font(ELEV_FONT_SIZE) if generate_elevation else None
        
        # 计算视频尺寸
        if interactive:
            print("计算视频尺寸...")
        width, height = calculate_video_dimensions(time_font, dist_font, elev_font)
        
        # 加载数据（如果需要生成距离或海拔视频）
        interp_times_dist, interp_distances = None, None
        interp_times_elev, interp_elevations = None, None
        
        if generate_distance or generate_elevation:
            times, distances, elevations = load_fit_data(fit_path, lap_start, lap_end)
            if times is None:
                print("❌ 无法加载FIT数据")
                result['success'] = False
                return result
            
            # 插值距离数据
            if generate_distance:
                interp_times_dist, interp_distances = interpolate_data(
                    times, distances, lap_start, lap_end, FPS_DISTANCE, "distance"
                )
                if interp_times_dist is None:
                    print("❌ 距离数据插值失败，跳过距离视频生成")
                    generate_distance = False
            
            # 插值海拔数据
            if generate_elevation:
                interp_times_elev, interp_elevations = interpolate_data(
                    times, elevations, lap_start, lap_end, FPS_ELEVATION, "elevation"
                )
                if interp_times_elev is None:
                    print("❌ 海拔数据插值失败，跳过海拔视频生成")
                    generate_elevation = False
        
        # 第一阶段：生成所有帧
        if interactive:
            print(f"\n{'='*60}")
            print("第一阶段：生成所有帧")
            print(f"{'='*60}")
        
        time_frame_count = 0
        distance_frame_count = 0
        elevation_frame_count = 0
        time_success = False
        distance_success = False
        elevation_success = False
        
        # 使用多线程并行生成帧
        threads = []
        results_dict = {}
        
        def generate_time_thread():
            try:
                frames = generate_time_frames(lap_start, lap_end, width, height, time_font)
                results_dict['time_frames'] = frames
                results_dict['time_success'] = True
            except Exception as e:
                print(f"[时间帧生成错误] {e}")
                traceback.print_exc()
                results_dict['time_success'] = False
        
        def generate_distance_thread():
            try:
                frames = generate_distance_frames(interp_times_dist, interp_distances, width, height, dist_font)
                results_dict['distance_frames'] = frames
                results_dict['distance_success'] = True
            except Exception as e:
                print(f"[距离帧生成错误] {e}")
                traceback.print_exc()
                results_dict['distance_success'] = False
        
        def generate_elevation_thread():
            try:
                frames = generate_elevation_frames(interp_times_elev, interp_elevations, width, height, elev_font)
                results_dict['elevation_frames'] = frames
                results_dict['elevation_success'] = True
            except Exception as e:
                print(f"[海拔帧生成错误] {e}")
                traceback.print_exc()
                results_dict['elevation_success'] = False
        
        if generate_time:
            t1 = threading.Thread(target=generate_time_thread)
            threads.append(t1)
            t1.start()
        
        if generate_distance:
            t2 = threading.Thread(target=generate_distance_thread)
            threads.append(t2)
            t2.start()
        
        if generate_elevation:
            t3 = threading.Thread(target=generate_elevation_thread)
            threads.append(t3)
            t3.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 获取结果
        if generate_time:
            time_frame_count = results_dict.get('time_frames', 0)
            time_success = results_dict.get('time_success', False)
            result['time_frame_count'] = time_frame_count
        
        if generate_distance:
            distance_frame_count = results_dict.get('distance_frames', 0)
            distance_success = results_dict.get('distance_success', False)
            result['distance_frame_count'] = distance_frame_count
        
        if generate_elevation:
            elevation_frame_count = results_dict.get('elevation_frames', 0)
            elevation_success = results_dict.get('elevation_success', False)
            result['elevation_frame_count'] = elevation_frame_count
        
        # 第二阶段：合成所有视频
        if interactive:
            print(f"\n{'='*60}")
            print("第二阶段：合成所有视频")
            print(f"{'='*60}")
        
        # 准备要合成的视频列表
        videos_to_compile = []
        
        if generate_time and time_success and time_frame_count > 0:
            videos_to_compile.append((
                "时间", OUTPUT_DIR_TIME, OUTPUT_VIDEO_TIME, 
                time_frame_count, width, height, FPS_TIME, "frame_"
            ))
        
        if generate_distance and distance_success and distance_frame_count > 0:
            videos_to_compile.append((
                "距离", OUTPUT_DIR_DISTANCE, OUTPUT_VIDEO_DISTANCE, 
                distance_frame_count, width, height, FPS_DISTANCE, "frame_"
            ))
        
        if generate_elevation and elevation_success and elevation_frame_count > 0:
            videos_to_compile.append((
                "海拔", OUTPUT_DIR_ELEVATION, OUTPUT_VIDEO_ELEVATION, 
                elevation_frame_count, width, height, FPS_ELEVATION, "frame_"
            ))
        
        # 合成所有视频
        if videos_to_compile:
            video_results = compile_all_videos(videos_to_compile, show_progress=True)
        else:
            video_results = {}
            if interactive:
                print("没有视频需要合成")
        
        # 更新结果
        if generate_time and video_results.get('时间', {}).get('success', False):
            result['time_video'] = OUTPUT_VIDEO_TIME
        if generate_distance and video_results.get('距离', {}).get('success', False):
            result['distance_video'] = OUTPUT_VIDEO_DISTANCE
        if generate_elevation and video_results.get('海拔', {}).get('success', False):
            result['elevation_video'] = OUTPUT_VIDEO_ELEVATION
        
        # 清理临时文件
        cleanup()
        
        # 计算总时间
        program_end_time = time.time()
        result['total_time'] = program_end_time - program_start_time
        
        if interactive:
            # 显示生成结果
            print(f"\n{'='*60}")
            print("生成结果汇总:")
            print(f"{'='*60}")
            
            if generate_time:
                success = video_results.get('时间', {}).get('success', False)
                status = "✅ 成功" if success else "❌ 失败"
                print(f"时间视频: {status}")
                if success:
                    print(f"  文件: {os.path.abspath(OUTPUT_VIDEO_TIME)}")
                    print(f"  帧数: {time_frame_count}")
                    print(f"  帧率: {FPS_TIME}")
            
            if generate_distance:
                success = video_results.get('距离', {}).get('success', False)
                status = "✅ 成功" if success else "❌ 失败"
                print(f"距离视频: {status}")
                if success:
                    print(f"  文件: {os.path.abspath(OUTPUT_VIDEO_DISTANCE)}")
                    print(f"  帧数: {distance_frame_count}")
                    print(f"  帧率: {FPS_DISTANCE}")
            
            if generate_elevation:
                success = video_results.get('海拔', {}).get('success', False)
                status = "✅ 成功" if success else "❌ 失败"
                print(f"海拔视频: {status}")
                if success:
                    print(f"  文件: {os.path.abspath(OUTPUT_VIDEO_ELEVATION)}")
                    print(f"  帧数: {elevation_frame_count}")
                    print(f"  帧率: {FPS_ELEVATION}")
            
            total_seconds = result['total_time']
            minutes = int(total_seconds // 60)
            seconds = total_seconds % 60
            print(f"\n总运行时间: {minutes}分{seconds:.2f}秒")
        
        return result
        
    except Exception as e:
        print(f"\n❌ 程序发生错误: {e}")
        traceback.print_exc()
        result['success'] = False
        result['error'] = str(e)
        return result

def main_interactive():
    """交互式主函数"""
    program_start_time = time.time()
    
    print("=" * 60)
    print("FIT文件时间戳/距离/海拔透明视频生成器")
    print("=" * 60)
    
    # 显示当前配置
    print(f"时区偏移: UTC+{TIMEZONE_OFFSET}")
    print(f"时间帧率: {FPS_TIME} FPS")
    print(f"距离帧率: {FPS_DISTANCE} FPS")
    print(f"海拔帧率: {FPS_ELEVATION} FPS")
    print()
    
    # 获取FIT文件路径
    fit_path = get_fit_path()
    if fit_path is None:
        return
    
    # 获取所有lap信息
    laps = get_all_laps(fit_path)
    if not laps:
        print("文件中没有Lap信息，无法生成视频")
        return
    
    # 让用户选择要生成的lap
    selection = select_laps_for_generation(laps)
    if selection is None:
        print("用户取消操作")
        return
    
    lap_start, lap_end, selected_laps = selection
    
    # 让用户选择生成哪种视频
    generate_time, generate_distance, generate_elevation = get_video_selection()
    if generate_time is None or generate_distance is None or generate_elevation is None:
        print("用户取消操作")
        return
    
    if not generate_time and not generate_distance and not generate_elevation:
        print("未选择任何视频类型，退出")
        return
    
    # 调用生成函数
    result = generate_videos_from_fit(
        fit_path=fit_path,
        lap_start=lap_start,
        lap_end=lap_end,
        generate_time=generate_time,
        generate_distance=generate_distance,
        generate_elevation=generate_elevation,
        interactive=True
    )
    
    if result.get('success'):
        print("\n✅ 程序运行完成")
    else:
        print("\n❌ 程序运行失败")
        if 'error' in result:
            print(f"错误信息: {result['error']}")

def main():
    """主函数入口，根据是否被导入决定运行方式"""
    if __name__ == "__main__":
        # 作为独立脚本运行，使用交互模式
        try:
            main_interactive()
        except KeyboardInterrupt:
            print("\n\n程序被用户中断")
            cleanup()
        except Exception as e:
            print(f"\n❌ 程序发生错误: {e}")
            traceback.print_exc()
            cleanup()
    else:
        # 被导入为模块，不自动运行
        pass

if __name__ == "__main__":
    main()