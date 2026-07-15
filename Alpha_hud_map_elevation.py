import os
import numpy as np
from fitparse import FitFile
import matplotlib
# 设置非交互式后端，避免GUI线程问题
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import time
from datetime import datetime, timedelta
import shutil
import math
import threading
import cv2
from scipy.spatial import ConvexHull
from matplotlib.patches import Circle
import subprocess
import subprocess
import ctypes, sys

# ==================== 可被外部覆盖的路径变量 ====================
FFMPEG_PATH = "ffmpeg"   # 默认使用系统 PATH 中的 ffmpeg，GUI 可修改为打包内的路径

def generate_hud_map_elevation_video(fit_path, lap_start, lap_end, 
                               generate_hud=True,
                               generate_map=True,
                               generate_elevation=True,
                               hud_fps=30,
                               map_fps=5,
                               elevation_fps=5):
    """
    从FIT文件生成HUD、地图和海拔叠加视频（海拔图基于距离）
    
    参数:
    ----------
    fit_path : str
        FIT文件路径
    lap_start : datetime
        圈开始时间（UTC时区）
    lap_end : datetime
        圈结束时间（UTC时区）
    generate_hud : bool, 默认True
        是否生成HUD视频
    generate_map : bool, 默认True
        是否生成地图视频
    generate_elevation : bool, 默认True
        是否生成海拔视频
    hud_fps : int, 默认5
        HUD视频的帧率
    map_fps : int, 5
        地图视频的帧率
    elevation_fps : int, 默认5
        海拔视频的帧率
        
    返回值:
    ----------
    dict
        包含生成视频文件路径的字典
    """
    # 声明全局变量，以便外部（如GUI）可以修改输出路径
    global OUTPUT_DIR_HUD, OUTPUT_DIR_MAP, OUTPUT_DIR_ELEVATION, \
           OUTPUT_MOV_HUD, OUTPUT_MOV_MAP, OUTPUT_MOV_ELEVATION

    # 如果这些变量尚未定义（例如独立运行），则设置默认值
    if 'OUTPUT_DIR_HUD' not in globals():
        OUTPUT_DIR_HUD = "frames_hud"
    if 'OUTPUT_DIR_MAP' not in globals():
        OUTPUT_DIR_MAP = "frames_map"
    if 'OUTPUT_DIR_ELEVATION' not in globals():
        OUTPUT_DIR_ELEVATION = "frames_elevation"
    if 'OUTPUT_MOV_HUD' not in globals():
        OUTPUT_MOV_HUD = None
    if 'OUTPUT_MOV_MAP' not in globals():
        OUTPUT_MOV_MAP = None
    if 'OUTPUT_MOV_ELEVATION' not in globals():
        OUTPUT_MOV_ELEVATION = None

    # 生成时间戳并设置视频文件名（如果外部未设置）
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if OUTPUT_MOV_HUD is None:
        OUTPUT_MOV_HUD = f"alpha_hud__{timestamp}.mov"
    if OUTPUT_MOV_MAP is None:
        OUTPUT_MOV_MAP = f"alpha_map__{timestamp}.mov"
    if OUTPUT_MOV_ELEVATION is None:
        OUTPUT_MOV_ELEVATION = f"alpha_elev_{timestamp}.mov"
    
    # 视频参数 - 分别设置FPS
    width, height = 480, 270
    font_size = 25
    print_interval = 1
    speed_threshold = 3.0
    
    # 控制参数
    use_multithreading = False
    flip_map_vertical = False
    
    # 地图样式参数
    map_line_width = 5
    map_line_color = (1.0, 0.5, 0.0, 1.0)  # RGBA: 橙色不透明 map_line_color = (1.0, 0.5, 0.0, 0.5)  # RGBA: 橙色半透明
    map_completed_color = (0.0, 0.6, 1.0, 1.0)  # RGBA: 蓝色
    map_marker_color = (1.0, 0.0, 0.0, 1.0)  # RGBA: 红色
    map_marker_size = 15 #12
    map_marker_type = 'triangle'  # 标记类型
    map_background_color = (0.0, 0.0, 0.0, 0.0)  # RGBA: 完全透明
    map_circle_bg_color = (0.2, 0.2, 0.2, 0.6)  # RGBA: 灰色半透明背景
    map_circle_padding_percent = 10  # 圆形背景的内边距百分比
    map_show_grid = False  # 禁用网格
    map_grid_color = (1.0, 1.0, 1.0, 0.1)  # RGBA: 白色半透明
    map_grid_spacing = 0.2
    map_margin = 0.1  # 边距比例(0-0.5)
    
    # 海拔样式参数
    elevation_line_width = 3
    elevation_completed_color = (0.0, 0.8, 0.0, 1.0)  # RGBA: 绿色
    elevation_background_color = (1.0, 1.0, 1.0, 0.2)  # RGBA: 白色半透明
    elevation_marker_color = (1.0, 0.0, 0.0, 1.0)  # RGBA: 红色
    elevation_marker_size = 12 #10
    elevation_show_grid = False  # 禁用网格
    elevation_grid_color = (0.5, 0.5, 0.5, 0.3)  # RGBA: 灰色半透明
    elevation_grid_spacing_x = 0.1  # X轴网格间距（时间比例）
    elevation_grid_spacing_y = 50  # Y轴网格间距（米）
    elevation_margin = 0.1  # 边距比例(0-0.5)
    elevation_aspect_ratio = 8  # 长宽比 宽度:高度
    
    # ==================== 内部变量（非路径） ====================
    HUD_FPS = hud_fps
    MAP_FPS = map_fps
    ELEVATION_FPS = elevation_fps
    WIDTH, HEIGHT = width, height
    ELEVATION_WIDTH = 800  # 指定宽度
    ELEVATION_HEIGHT = int(ELEVATION_WIDTH / elevation_aspect_ratio)  # 根据宽度和长宽比计算高度
    FONT_SIZE = font_size
    PRINT_INTERVAL = print_interval
    SPEED_THRESHOLD = speed_threshold #速度小于该值认为是推车步行或停车
    
    def debug_print_config():
        duration = (lap_end - lap_start).total_seconds()
        print("\n=== 配置参数检查 ===")
        print(f"FIT文件路径: {fit_path}")
        print(f"HUD输出目录: {OUTPUT_DIR_HUD}" if generate_hud else "[跳过HUD生成]")
        print(f"地图输出目录: {OUTPUT_DIR_MAP}" if generate_map else "[跳过地图生成]")
        print(f"海拔输出目录: {OUTPUT_DIR_ELEVATION}" if generate_elevation else "[跳过海拔生成]")
        print(f"HUD输出视频: {OUTPUT_MOV_HUD} (FPS: {HUD_FPS})" if generate_hud else "")
        print(f"地图输出视频: {OUTPUT_MOV_MAP} (FPS: {MAP_FPS})" if generate_map else "")
        print(f"海拔输出视频: {OUTPUT_MOV_ELEVATION} (FPS: {ELEVATION_FPS})" if generate_elevation else "")
        print(f"HUD/地图分辨率: {WIDTH}x{HEIGHT}")
        print(f"海拔分辨率: {ELEVATION_WIDTH}x{ELEVATION_HEIGHT} (长宽比 {elevation_aspect_ratio}:1)")
        print(f"开始时间: {lap_start} (UTC)")
        print(f"结束时间: {lap_end} (UTC)")
        print(f"计算时长: {duration}秒 ({duration//60}分{duration%60}秒)")
        print(f"HUD预期总帧数: {int(duration*HUD_FPS)}帧" if generate_hud else "")
        print(f"地图预期总帧数: {int(duration*MAP_FPS)}帧" if generate_map else "")
        print(f"海拔预期总帧数: {int(duration*ELEVATION_FPS)}帧" if generate_elevation else "")
        print(f"速度显示阈值: {SPEED_THRESHOLD} km/h")
        print(f"多线程渲染: {'启用' if use_multithreading else '禁用'}")
        print(f"地图标记类型: {map_marker_type}")
        print(f"地图垂直翻转: {'是' if flip_map_vertical else '否'}")
        print(f"地图圆形背景内边距: {map_circle_padding_percent}%")
        print(f"海拔网格显示: {'启用' if elevation_show_grid else '禁用'}")
        print("==================\n")
    
    def validate_frames(frame_count, output_dir, frame_prefix="frame_"):
        if not os.path.exists(output_dir):
            raise RuntimeError(f"输出目录不存在: {output_dir}")
            
        existing_frames = len([f for f in os.listdir(output_dir) if f.startswith(frame_prefix)])
        if existing_frames != frame_count:
            raise RuntimeError(
                f"帧数不匹配！预期 {frame_count} 帧，实际生成 {existing_frames} 帧\n"
                "可能原因：渲染过程中断或文件名冲突"
            )
        print(f"[验证] {output_dir}帧连续性检查通过: 共{existing_frames}帧")
    
    def load_and_filter(fit_path, start_abs_time, end_abs_time):
        print(f"\n[DEBUG] 正在加载FIT数据，绝对时间范围: {start_abs_time} - {end_abs_time}")
        fit = FitFile(fit_path)
        recs = []
        for m in fit.get_messages('record'):
            vals = m.get_values()
            if 'timestamp' in vals:
                recs.append(vals)

        if not recs:
            raise RuntimeError("FIT文件中没有数据")

        print(f"[DEBUG] 第一条记录时间: {recs[0]['timestamp']} (UTC)")
        print(f"[DEBUG] 总记录数: {len(recs)}")

        offs, spd, pwr, hr, cad, lats, lons, alts, dists = [], [], [], [], [], [], [], [], []
        lat_found = False
        lon_found = False
        alt_found = False
        dist_found = False
        
        for r in recs:
            ts = r['timestamp']
            if not (start_abs_time <= ts <= end_abs_time):
                continue
                
            offset = (ts - start_abs_time).total_seconds()
            offs.append(offset)
            
            # 速度数据 - 优先使用enhanced_speed
            s = r.get('enhanced_speed') or r.get('speed', 0.0)
            raw_speed = s * 3.6
            if raw_speed < SPEED_THRESHOLD:
                speed_value = 0.0
            else:
                speed_value = raw_speed
                
            spd.append(speed_value)
            pwr.append(r.get('power', np.nan))
            hr.append(r.get('heart_rate', np.nan))
            cad.append(r.get('cadence', np.nan))
            
            # GPS数据
            lat = r.get('position_lat')
            lon = r.get('position_long')
            
            if lat is not None and lon is not None:
                lat_found = True
                lon_found = True
                # FIT文件中的经纬度单位是"semicircles"，需要转换为度
                # 1 semicircle = 180 / 2^31 度
                lat_deg = lat * (180.0 / 2**31)
                lon_deg = lon * (180.0 / 2**31)
                lats.append(lat_deg)
                lons.append(lon_deg)
            else:
                # 如果没有GPS数据，使用NaN占位
                lats.append(np.nan)
                lons.append(np.nan)
            
            # 海拔数据 - 优先使用enhanced_altitude
            alt = r.get('enhanced_altitude') or r.get('altitude')
            if alt is not None:
                alt_found = True
                alts.append(alt)
            else:
                alts.append(np.nan)
            
            # 距离数据 - 新增
            dist = r.get('distance')
            if dist is not None:
                dist_found = True
                dists.append(dist)
            else:
                dists.append(np.nan)

        if not offs:
            raise RuntimeError("指定时间范围内没有数据")

        print(f"[DEBUG] GPS数据: 纬度{'已找到' if lat_found else '未找到'}, 经度{'已找到' if lon_found else '未找到'}")
        print(f"[DEBUG] 海拔数据: {'已找到' if alt_found else '未找到'}")
        print(f"[DEBUG] 距离数据: {'已找到' if dist_found else '未找到'}")
        print(f"[DEBUG] 过滤后有效记录数: {len(offs)}条")
        print(f"[DEBUG] 实际数据时间范围: {min(offs):.1f}-{max(offs):.1f}秒")
        
        zero_count = sum(1 for s in spd if s == 0.0)
        print(f"[速度过滤] 加载阶段将{zero_count}个低速点(<{SPEED_THRESHOLD}km/h)设为0")
        print(f"[速度过滤] 零速点比例: {zero_count}/{len(spd)} ({(zero_count/len(spd))*100:.1f}%)")

        return {
            'offsets': np.array(offs),
            'speed':   np.array(spd),
            'power':   np.array(pwr),
            'hr':      np.array(hr),
            'cad':     np.array(cad),
            'lats':    np.array(lats),
            'lons':    np.array(lons),
            'alts':    np.array(alts),
            'dists':   np.array(dists),  # 新增距离数组
        }
    
    def interpolate(data, duration_sec, fps):
        print(f"\n[DEBUG] 开始数据插值，目标时长: {duration_sec}秒, 目标FPS: {fps}")
        x = data['offsets']
        time_points = np.linspace(0, duration_sec, int(duration_sec * fps) + 1)
        print(f"[DEBUG] 生成{len(time_points)}个时间点")
        
        is_stopped_original = data['speed'] < SPEED_THRESHOLD
        
        interp_speed = interp1d(x, data['speed'], kind='linear', fill_value="extrapolate")(time_points)
        
        stop_flags = np.zeros_like(time_points, dtype=bool)
        
        for i, t in enumerate(time_points):
            idx = np.searchsorted(x, t, side='right') - 1
            if idx >= 0 and idx < len(is_stopped_original):
                stop_flags[i] = is_stopped_original[idx]
            else:
                stop_flags[i] = False
        
        interp_speed_clean = interp_speed.copy()
        interp_speed_clean[stop_flags] = 0.0
        interp_speed_clean = np.where(interp_speed_clean < SPEED_THRESHOLD, 0.0, interp_speed_clean)
        
        interp = lambda arr: interp1d(x, arr, kind='linear', fill_value="extrapolate")(time_points)
        
        # GPS插值
        lats = data['lats']
        lons = data['lons']
        valid_gps_mask = ~(np.isnan(lats) | np.isnan(lons))
        
        if np.any(valid_gps_mask):
            valid_x = x[valid_gps_mask]
            valid_lats = lats[valid_gps_mask]
            valid_lons = lons[valid_gps_mask]
            interp_lats = interp1d(valid_x, valid_lats, kind='linear', fill_value="extrapolate")(time_points)
            interp_lons = interp1d(valid_x, valid_lons, kind='linear', fill_value="extrapolate")(time_points)
        else:
            interp_lats = np.full_like(time_points, np.nan)
            interp_lons = np.full_like(time_points, np.nan)
        
        # 海拔插值
        alts = data['alts']
        valid_alt_mask = ~np.isnan(alts)
        
        if np.any(valid_alt_mask):
            valid_x_alt = x[valid_alt_mask]
            valid_alts = alts[valid_alt_mask]
            interp_alts = interp1d(valid_x_alt, valid_alts, kind='linear', fill_value="extrapolate")(time_points)
        else:
            interp_alts = np.full_like(time_points, np.nan)
        
        # 距离插值 - 新增
        dists = data['dists']
        valid_dist_mask = ~np.isnan(dists)
        
        if np.any(valid_dist_mask):
            valid_x_dist = x[valid_dist_mask]
            valid_dists = dists[valid_dist_mask]
            interp_dists = interp1d(valid_x_dist, valid_dists, kind='linear', fill_value="extrapolate")(time_points)
        else:
            interp_dists = np.full_like(time_points, np.nan)
        
        result = {
            'speed': interp_speed_clean,
            'power': interp(data['power']).astype(int),
            'hr':    interp(data['hr']).astype(int),
            'cad':   interp(data['cad']).astype(int),
            'lats':  interp_lats,
            'lons':  interp_lons,
            'alts':  interp_alts,
            'dists': interp_dists,  # 新增插值后的距离
            'time_points': time_points,
        }
        
        zero_count = np.sum(result['speed'] < 0.1)
        print(f"[停车段识别] 识别出{np.sum(stop_flags)}个插值点处于停车状态")
        print(f"[最终过滤] 零速点比例: {zero_count}/{len(result['speed'])} ({(zero_count/len(result['speed']))*100:.1f}%)")
        
        valid_gps_count = np.sum(~np.isnan(interp_lats))
        print(f"[GPS数据] 插值后有效GPS点数: {valid_gps_count}/{len(interp_lats)} ({(valid_gps_count/len(interp_lats))*100:.1f}%)")
        
        valid_alt_count = np.sum(~np.isnan(interp_alts))
        print(f"[海拔数据] 插值后有效海拔点数: {valid_alt_count}/{len(interp_alts)} ({(valid_alt_count/len(interp_alts))*100:.1f}%)")
        
        valid_dist_count = np.sum(~np.isnan(interp_dists))
        print(f"[距离数据] 插值后有效距离点数: {valid_dist_count}/{len(interp_dists)} ({(valid_dist_count/len(interp_dists))*100:.1f}%)")
        
        return result
    
    def normalize_coordinates(lats, lons, margin=map_margin):
        """将经纬度归一化到0-1范围，保持纵横比"""
        # 找到有效的经纬度点
        valid_mask = ~(np.isnan(lats) | np.isnan(lons))
        valid_lats = lats[valid_mask]
        valid_lons = lons[valid_mask]
        
        if len(valid_lats) == 0 or len(valid_lons) == 0:
            return None, None, None, None, None, None
        
        min_lat, max_lat = np.min(valid_lats), np.max(valid_lats)
        min_lon, max_lon = np.min(valid_lons), np.max(valid_lons)
        
        # 计算经纬度范围
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon
        
        # 防止除零
        if lat_range == 0:
            lat_range = 0.0001
        if lon_range == 0:
            lon_range = 0.0001
        
        # 计算轨迹的纵横比
        trajectory_aspect = lon_range / lat_range
        
        # 计算视频的纵横比
        video_aspect = WIDTH / HEIGHT
        
        # 根据纵横比调整边界，保持轨迹不变形
        if trajectory_aspect > video_aspect:
            # 经度范围相对较大，以经度范围为基准
            lat_margin = (lon_range / video_aspect - lat_range) / 2
            min_lat -= lat_margin
            max_lat += lat_margin
        else:
            # 纬度范围相对较大，以纬度范围为基准
            lon_margin = (lat_range * video_aspect - lon_range) / 2
            min_lon -= lon_margin
            max_lon += lon_margin
        
        # 添加额外的边距
        lat_range_adj = max_lat - min_lat
        lon_range_adj = max_lon - min_lon
        
        min_lat -= lat_range_adj * margin
        max_lat += lat_range_adj * margin
        min_lon -= lon_range_adj * margin
        max_lon += lon_range_adj * margin
        
        # 归一化函数
        def normalize(lat, lon):
            if np.isnan(lat) or np.isnan(lon):
                return np.nan, np.nan
            norm_x = (lon - min_lon) / (max_lon - min_lon)
            # 关键修改：根据参数决定是否反转Y轴
            if flip_map_vertical:
                norm_y = 1.0 - (lat - min_lat) / (max_lat - min_lat)  # 反转Y轴
            else:
                norm_y = (lat - min_lat) / (max_lat - min_lat)  # 不反转Y轴
            return norm_x, norm_y
        
        # 归一化所有点
        normalized_coords = []
        for lat, lon in zip(lats, lons):
            if np.isnan(lat) or np.isnan(lon):
                normalized_coords.append((np.nan, np.nan))
            else:
                norm_x, norm_y = normalize(lat, lon)
                normalized_coords.append((norm_x, norm_y))
        
        # 转换为像素坐标
        pixel_coords = []
        for norm_x, norm_y in normalized_coords:
            if np.isnan(norm_x) or np.isnan(norm_y):
                pixel_coords.append((np.nan, np.nan))
            else:
                pixel_x = norm_x * WIDTH
                pixel_y = norm_y * HEIGHT
                pixel_coords.append((pixel_x, pixel_y))
        
        # 分离X和Y坐标
        pixel_x = [c[0] for c in pixel_coords]
        pixel_y = [c[1] for c in pixel_coords]
        
        return pixel_x, pixel_y, min_lat, max_lat, min_lon, max_lon
    
    def normalize_elevation_by_distance(alts, dists, margin=elevation_margin):
        """
        基于距离归一化海拔数据（替换原来的时间归一化）
        
        参数:
        ----------
        alts : array
            海拔数据数组（可能包含NaN）
        dists : array
            距离数据数组（可能包含NaN）
        margin : float
            边距比例
                
        返回值:
        ----------
        pixel_x, pixel_y, min_alt, max_alt, min_dist, max_dist
        """
        # 过滤有效数据
        valid_mask = ~(np.isnan(alts) | np.isnan(dists))
        valid_alts = alts[valid_mask]
        valid_dists = dists[valid_mask]
        
        if len(valid_alts) == 0 or len(valid_dists) == 0:
            return None, None, None, None, None, None
        
        # 计算海拔范围
        min_alt, max_alt = np.min(valid_alts), np.max(valid_alts)
        alt_range = max_alt - min_alt
        if alt_range == 0:
            alt_range = 0.0001
        
        # 计算距离范围
        min_dist, max_dist = np.min(valid_dists), np.max(valid_dists)
        dist_range = max_dist - min_dist
        if dist_range == 0:
            dist_range = 0.0001
        
        # 添加边距
        alt_margin = alt_range * margin
        dist_margin = dist_range * margin
        
        min_alt -= alt_margin
        max_alt += alt_margin
        min_dist -= dist_margin
        max_dist += dist_margin
        
        # 归一化函数
        def normalize(alt, dist):
            if np.isnan(alt) or np.isnan(dist):
                return np.nan, np.nan
            # X轴：距离归一化到0-1
            norm_x = (dist - min_dist) / (max_dist - min_dist)
            # Y轴：海拔归一化到0-1（不翻转）
            norm_y = (alt - min_alt) / (max_alt - min_alt)
            return norm_x, norm_y
        
        # 归一化所有点
        normalized_coords = []
        for alt, dist in zip(alts, dists):
            if np.isnan(alt) or np.isnan(dist):
                normalized_coords.append((np.nan, np.nan))
            else:
                norm_x, norm_y = normalize(alt, dist)
                normalized_coords.append((norm_x, norm_y))
        
        # 转换为像素坐标
        pixel_coords = []
        for norm_x, norm_y in normalized_coords:
            if np.isnan(norm_x) or np.isnan(norm_y):
                pixel_coords.append((np.nan, np.nan))
            else:
                pixel_x = norm_x * ELEVATION_WIDTH
                pixel_y = norm_y * ELEVATION_HEIGHT
                pixel_coords.append((pixel_x, pixel_y))
        
        # 分离X和Y坐标
        pixel_x = [c[0] for c in pixel_coords]
        pixel_y = [c[1] for c in pixel_coords]
        
        return pixel_x, pixel_y, min_alt, max_alt, min_dist, max_dist
    
    def format_value(value, value_type):
        if value_type == 'speed':
            if value < SPEED_THRESHOLD:
                return f"<{SPEED_THRESHOLD}km/h"
            return f"{value:.1f} km/h"
        elif value_type in ['power', 'cad']:
            if value < 0: 
                return "--"
            if value_type == 'power':
                return f"{value} W"
            else:
                return f"{value} rpm"
        elif value_type == 'hr':
            return f"{value} bpm"
        return str(value)
    
    def render_hud_frames(data_intp_hud, duration_sec):
        if not generate_hud:
            return 0
            
        print(f"\n[DEBUG] 开始渲染HUD帧 (FPS: {HUD_FPS})")
        os.makedirs(OUTPUT_DIR_HUD, exist_ok=True)
        hud_frame_count = len(data_intp_hud['speed'])  # 使用插值后的数据长度

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_HUD):
            if f.startswith("frame_"):
                os.remove(os.path.join(OUTPUT_DIR_HUD, f))

        plt.ioff()
        # 关键修改：使用原始代码的图形创建方式
        fig, ax = plt.subplots(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)
        ax.set_facecolor('none')  # 轴域背景透明
        # 设置轴位置，留出上下边距
        ax.set_position([0, 0.05, 1, 0.9])
        ax.axis('off')

        # 设置文本位置和样式
        text_obj = ax.text(
            0.05, 0.4, "",  # 位置稍微下移，避免被截断
            fontsize=FONT_SIZE,
            color='white',
            bbox=dict(facecolor='black', alpha=0.4, boxstyle='round,pad=0.25'),
            transform=ax.transAxes
        )

        last_print_time = time.time()
        start_time = time.time()
        
        hud_frames_rendered = 0

        for idx in range(hud_frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (hud_frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[Alpha_HUD] {processed}/{hud_frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time

            speed_display = format_value(data_intp_hud['speed'][idx], 'speed')
            power_display = format_value(data_intp_hud['power'][idx], 'power')
            hr_display = format_value(data_intp_hud['hr'][idx], 'hr')
            cad_display = format_value(data_intp_hud['cad'][idx], 'cad')

            text_obj.set_text(
                f"Speed: {speed_display}\n"
                f"Power: {power_display}\n"
                f"Heart Rate: {hr_display}\n"
                f"Cadence: {cad_display}"
            )
            
            path = os.path.join(OUTPUT_DIR_HUD, f"frame_{idx:06d}.png")
            # 关键修改：去掉 bbox_inches='tight'，使用原始代码的保存方式
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            hud_frames_rendered += 1

        plt.close(fig)
        validate_frames(hud_frame_count, OUTPUT_DIR_HUD, "frame_")
        return hud_frames_rendered
    
    def calculate_moving_direction(pixel_x, pixel_y, idx, look_ahead=5):
        """优化版：计算移动方向，使用数组切片提高效率"""
        if idx < 1 or idx >= len(pixel_x) - 1:
            return 0
        
        # 获取窗口内的坐标
        start_idx = max(0, idx - look_ahead)
        end_idx = min(len(pixel_x) - 1, idx + look_ahead)
        
        # 使用切片获取窗口数据
        window_x = pixel_x[start_idx:end_idx+1]
        window_y = pixel_y[start_idx:end_idx+1]
        
        # 过滤NaN值
        valid_mask = [not (np.isnan(x) or np.isnan(y)) for x, y in zip(window_x, window_y)]
        valid_x = [window_x[i] for i, valid in enumerate(valid_mask) if valid]
        valid_y = [window_y[i] for i, valid in enumerate(valid_mask) if valid]
        
        if len(valid_x) < 2:
            return 0
        
        # 使用首尾点计算方向
        dx = valid_x[-1] - valid_x[0]
        dy = valid_y[-1] - valid_y[0]
        
        if dx == 0 and dy == 0:
            return 0
        
        # 计算角度（弧度）
        angle_rad = math.atan2(dy, dx)
        return angle_rad
    
    def create_perfect_circular_background(pixel_x, pixel_y, width, height, padding_percent=map_circle_padding_percent):
        """
        创建完美的圆形背景，确保轨迹完全在圆形内部
        
        参数:
        ----------
        pixel_x, pixel_y : list
            轨迹像素坐标
        width, height : int
            画布尺寸
        padding_percent : float
            内边距百分比
            
        返回值:
        ----------
        (circle_center_x, circle_center_y, circle_radius, scale_factor, transform_points)
        """
        # 过滤NaN值
        valid_points = [(x, y) for x, y in zip(pixel_x, pixel_y) if not (np.isnan(x) or np.isnan(y))]
        
        if not valid_points:
            return None, None, None, 1.0, (pixel_x, pixel_y)
        
        # 转换为numpy数组
        points = np.array(valid_points, dtype=np.float32)
        
        # 1. 计算轨迹的最小外接圆
        (center_x, center_y), radius = cv2.minEnclosingCircle(points)
        
        if radius == 0:
            # 如果半径为0，则使用边界框
            min_x, max_x = np.min(points[:, 0]), np.max(points[:, 0])
            min_y, max_y = np.min(points[:, 1]), np.max(points[:, 1])
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            radius = max(max_x - min_x, max_y - min_y) / 2
        
        # 添加内边距
        radius_with_padding = radius * (1 + padding_percent / 100.0)
        
        # 2. 确保圆形在画布内
        canvas_center_x = width / 2
        canvas_center_y = height / 2
        
        # 计算缩放因子，使圆形适应画布
        max_radius = min(width, height) / 2 * 0.9  # 90%的画布可用空间
        scale_factor = 1.0
        
        if radius_with_padding > max_radius:
            scale_factor = max_radius / radius_with_padding
            radius_with_padding = max_radius
        else:
            # 如果圆形太小，可以稍微放大
            if radius_with_padding < max_radius * 0.5:
                scale_factor = max_radius * 0.5 / radius_with_padding
                radius_with_padding = max_radius * 0.5
        
        # 3. 计算圆形在画布中的位置
        # 将轨迹中心映射到画布中心
        target_center_x = canvas_center_x
        target_center_y = canvas_center_y
        
        # 4. 计算变换后的轨迹点
        transformed_x = []
        transformed_y = []
        
        for i, (x, y) in enumerate(zip(pixel_x, pixel_y)):
            if np.isnan(x) or np.isnan(y):
                transformed_x.append(np.nan)
                transformed_y.append(np.nan)
            else:
                # 相对于轨迹中心
                dx = x - center_x
                dy = y - center_y
                
                # 缩放
                dx_scaled = dx * scale_factor
                dy_scaled = dy * scale_factor
                
                # 映射到画布中心
                new_x = target_center_x + dx_scaled
                new_y = target_center_y + dy_scaled
                
                transformed_x.append(new_x)
                transformed_y.append(new_y)
        
        return target_center_x, target_center_y, radius_with_padding, scale_factor, (transformed_x, transformed_y)
    
    def render_map_frames(data_intp_map, pixel_x_map, pixel_y_map, duration_sec):
        if not generate_map:
            return 0
            
        print(f"\n[DEBUG] 开始渲染地图帧（带完美圆形背景）(FPS: {MAP_FPS})")
        os.makedirs(OUTPUT_DIR_MAP, exist_ok=True)
        map_frame_count = len(data_intp_map['lats'])  # 使用插值后的数据长度

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_MAP):
            if f.startswith("frame_map_"):
                os.remove(os.path.join(OUTPUT_DIR_MAP, f))

        # 1. 计算完美圆形背景和变换后的轨迹点
        print("[地图计算] 计算完美圆形背景...")
        circle_center_x, circle_center_y, circle_radius, scale_factor, transformed_points = create_perfect_circular_background(
            pixel_x_map, pixel_y_map, WIDTH, HEIGHT, map_circle_padding_percent
        )
        
        if circle_center_x is None:
            print("[警告] 无法计算轨迹的圆形背景，将跳过地图视频生成")
            return 0
        
        print(f"[地图背景] 圆形中心: ({circle_center_x:.1f}, {circle_center_y:.1f}), 半径: {circle_radius:.1f}, 缩放因子: {scale_factor:.3f}")
        
        # 解包变换后的轨迹点
        pixel_x_transformed, pixel_y_transformed = transformed_points
        
        plt.ioff()
        fig, ax = plt.subplots(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)  # 设置图形背景透明
        ax.set_facecolor('none')  # 轴域背景透明
        # 设置轴位置，使用整个图形区域
        ax.set_position([0, 0, 1, 1])
        ax.set_xlim(0, WIDTH)
        ax.set_ylim(0, HEIGHT)
        ax.set_aspect('equal')
        ax.axis('off')
        
        # 设置背景色
        ax.set_facecolor(map_background_color)
        
        # 绘制网格（可选）
        if map_show_grid:
            grid_step_x = WIDTH * map_grid_spacing
            grid_step_y = HEIGHT * map_grid_spacing
            for x in np.arange(0, WIDTH + grid_step_x, grid_step_x):
                ax.axvline(x, color=map_grid_color, linewidth=0.5, alpha=0.5)
            for y in np.arange(0, HEIGHT + grid_step_y, grid_step_y):
                ax.axhline(y, color=map_grid_color, linewidth=0.5, alpha=0.5)
        
        # 绘制圆形背景
        circle = plt.Circle(
            (circle_center_x, circle_center_y), 
            circle_radius, 
            facecolor=map_circle_bg_color,  # 灰色半透明背景
            edgecolor='none',  # 无边线
            zorder=0  # 在最底层
        )
        ax.add_patch(circle)
        
        # 绘制完整轨迹（浅色背景）- 使用变换后的坐标
        valid_coords = [(x, y) for x, y in zip(pixel_x_transformed, pixel_y_transformed) 
                       if not (np.isnan(x) or np.isnan(y))]
        if valid_coords:
            full_x, full_y = zip(*valid_coords)
            ax.plot(full_x, full_y, color=map_line_color, linewidth=map_line_width, alpha=0.5, zorder=1)
        
        # 绘制已完成轨迹和当前位置标记
        completed_line, = ax.plot([], [], color=map_completed_color, linewidth=map_line_width, zorder=2)
        
        # 根据标记类型选择不同的标记
        if map_marker_type == 'arrow':
            # 使用箭头标记
            marker = ax.quiver([], [], [], [], color=map_marker_color, 
                              scale=1, scale_units='xy', angles='xy', 
                              width=map_marker_size/100, zorder=3)
        else:
            # 默认使用三角形标记
            marker = ax.scatter([], [], s=map_marker_size**2, c=[map_marker_color], 
                              marker='^', edgecolors='white', linewidths=1, zorder=3)
        
        last_print_time = time.time()
        start_time = time.time()
        map_frames_rendered = 0
        
        # 存储上一帧的角度，用于平滑旋转
        angle_history = []
        
        # 存储已完成轨迹的点
        completed_x_list = []
        completed_y_list = []

        for idx in range(map_frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (map_frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[Alpha_地图] {processed}/{map_frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time
            
            # 获取当前坐标 - 使用变换后的坐标
            current_x, current_y = pixel_x_transformed[idx], pixel_y_transformed[idx]
            
            if not (np.isnan(current_x) or np.isnan(current_y)):
                # 增量更新轨迹
                completed_x_list.append(current_x)
                completed_y_list.append(current_y)
                completed_line.set_data(completed_x_list, completed_y_list)
                
                if map_marker_type == 'arrow':
                    # 使用箭头标记
                    # 计算方向
                    if idx > 0 and idx < len(pixel_x_transformed) - 1:
                        # 计算前进方向
                        direction_rad = calculate_moving_direction(pixel_x_transformed, pixel_y_transformed, idx, look_ahead=3)
                        
                        if direction_rad != 0:
                            # 转换为箭头的dx, dy分量
                            arrow_length = map_marker_size
                            dx = arrow_length * math.cos(direction_rad)
                            dy = arrow_length * math.sin(direction_rad)
                            
                            # 更新箭头
                            marker.set_offsets([(current_x, current_y)])
                            marker.set_UVC(dx, dy)
                else:
                    # 使用三角形标记
                    # 更新位置
                    marker.set_offsets([(current_x, current_y)])
                    
                    # 计算并设置标记方向
                    if idx > 0 and idx < len(pixel_x_transformed) - 1:
                        # 计算前进方向
                        direction_rad = calculate_moving_direction(pixel_x_transformed, pixel_y_transformed, idx, look_ahead=3)
                        
                        if direction_rad != 0:
                            # 将前进方向转换为角度（度）
                            direction_deg = math.degrees(direction_rad)
                            
                            # 三角形标记默认指向90度（上方），我们需要将它旋转到前进方向
                            # 前进方向角度 - 90度，使三角形顶点指向前进方向
                            rotation_angle = direction_deg - 90
                            
                            # 角度平滑（可选）
                            angle_history.append(rotation_angle)
                            if len(angle_history) > 5:
                                angle_history.pop(0)
                            
                            if len(angle_history) > 1:
                                # 使用简单平均平滑角度
                                smoothed_angle = np.mean(angle_history)
                                rotation_angle = smoothed_angle
                            
                            # 应用旋转
                            marker.set_transform(ax.transData + 
                                               plt.matplotlib.transforms.Affine2D().rotate_deg(rotation_angle))
            
            # 保存帧
            path = os.path.join(OUTPUT_DIR_MAP, f"frame_map_{idx:06d}.png")
            # 关键修改：使用pad_inches=0去除白边
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            map_frames_rendered += 1

        plt.close(fig)
        validate_frames(map_frame_count, OUTPUT_DIR_MAP, "frame_map_")
        return map_frames_rendered
    
    def render_elevation_frames(data_intp_elevation, pixel_x_elev, pixel_y_elev, dists, duration_sec):
        """
        基于距离渲染海拔帧（优化版，O(N)时间复杂度）
        
        参数:
        ----------
        data_intp_elevation : dict
            插值后的数据
        pixel_x_elev, pixel_y_elev : list
            海拔曲线的像素坐标
        dists : array
            插值后的距离数据
        duration_sec : float
            总时长（秒）
        """
        if not generate_elevation:
            return 0
            
        print(f"\n[DEBUG] 开始渲染海拔帧 (FPS: {ELEVATION_FPS})")
        os.makedirs(OUTPUT_DIR_ELEVATION, exist_ok=True)
        elevation_frame_count = len(data_intp_elevation['alts'])  # 使用插值后的数据长度

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_ELEVATION):
            if f.startswith("frame_elevation_"):
                os.remove(os.path.join(OUTPUT_DIR_ELEVATION, f))

        plt.ioff()
        fig, ax = plt.subplots(figsize=(ELEVATION_WIDTH/100, ELEVATION_HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)  # 设置图形背景透明
        ax.set_facecolor('none')  # 轴域背景透明
        # 设置轴位置，使用整个图形区域
        ax.set_position([0, 0, 1, 1])
        ax.set_xlim(0, ELEVATION_WIDTH)
        ax.set_ylim(0, ELEVATION_HEIGHT)
        ax.set_aspect('equal')
        ax.axis('off')
        
        # 设置背景色
        ax.set_facecolor(map_background_color)  # 使用与地图相同的透明背景
        
        # 绘制网格（可选）- 已禁用
        if elevation_show_grid:
            # X轴网格（时间）
            grid_step_x = ELEVATION_WIDTH * elevation_grid_spacing_x
            for x in np.arange(0, ELEVATION_WIDTH + grid_step_x, grid_step_x):
                ax.axvline(x, color=elevation_grid_color, linewidth=0.5, alpha=0.5)
            
            # Y轴网格（海拔）
            # 需要先获取海拔范围来计算实际网格
            valid_pixel_y = [y for y in pixel_y_elev if not np.isnan(y)]
            if valid_pixel_y:
                min_y = min(valid_pixel_y)
                max_y = max(valid_pixel_y)
                # 将海拔网格间距转换为像素
                y_range = max_y - min_y
                if y_range > 0:
                    # 计算每个海拔单位的像素数
                    alt_range_px = ELEVATION_HEIGHT
                    grid_step_y_px = (elevation_grid_spacing_y / y_range) * alt_range_px
                    
                    if grid_step_y_px > 0:
                        for y in np.arange(0, ELEVATION_HEIGHT + grid_step_y_px, grid_step_y_px):
                            ax.axhline(y, color=elevation_grid_color, linewidth=0.5, alpha=0.5)
        
        # 绘制完整海拔曲线（浅色背景）
        valid_coords = [(x, y) for x, y in zip(pixel_x_elev, pixel_y_elev) if not (np.isnan(x) or np.isnan(y))]
        if valid_coords:
            full_x, full_y = zip(*valid_coords)
            ax.plot(full_x, full_y, color=elevation_background_color, 
                   linewidth=elevation_line_width, alpha=0.5, zorder=1)
        
        # 绘制已完成海拔曲线
        completed_line, = ax.plot([], [], color=elevation_completed_color, 
                                linewidth=elevation_line_width, zorder=2)
        
        # 当前位置标记（红色圆形）
        marker = ax.scatter([], [], s=elevation_marker_size**2, c=[elevation_marker_color], 
                          marker='o', edgecolors='white', linewidths=1, zorder=3)
        
        last_print_time = time.time()
        start_time = time.time()
        elevation_frames_rendered = 0
        
        # ===== 优化：使用指针追踪已绘制的点，避免O(N²)复杂度 =====
        completed_x_list = []
        completed_y_list = []
        drawn_point_index = 0  # 指向下一个待检查的点
        total_points = len(pixel_x_elev)
        
        # 预计算所有有效点的索引，避免每帧检查NaN
        valid_indices = []
        for i in range(total_points):
            if i < len(dists) and not np.isnan(dists[i]):
                if i < len(pixel_x_elev) and i < len(pixel_y_elev):
                    px = pixel_x_elev[i]
                    py = pixel_y_elev[i]
                    if not (np.isnan(px) or np.isnan(py)):
                        valid_indices.append(i)
        
        # 存储已完成轨迹的点
        completed_x_list = []
        completed_y_list = []

        for idx in range(elevation_frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (elevation_frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[Alpha_海拔] {processed}/{elevation_frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time
            
            # 获取当前距离
            current_dist = dists[idx] if idx < len(dists) else np.nan
            
            if not np.isnan(current_dist):
                # ===== 优化：增量添加点，而不是重新遍历所有历史点 =====
                # 只检查尚未绘制的点，当点的距离超过当前距离时停止
                while drawn_point_index < len(valid_indices):
                    point_idx = valid_indices[drawn_point_index]
                    
                    # 如果这个点的距离超过了当前距离，停止添加
                    if point_idx >= len(dists) or np.isnan(dists[point_idx]) or dists[point_idx] > current_dist:
                        break
                    
                    # 添加这个点
                    px = pixel_x_elev[point_idx]
                    py = pixel_y_elev[point_idx]
                    completed_x_list.append(px)
                    completed_y_list.append(py)
                    drawn_point_index += 1
                
                # 更新线条数据
                completed_line.set_data(completed_x_list, completed_y_list)
                
                # 当前位置标记 - 使用最近的有效点
                if valid_indices and drawn_point_index > 0:
                    last_valid_idx = valid_indices[drawn_point_index - 1]
                    if last_valid_idx < len(pixel_x_elev) and last_valid_idx < len(pixel_y_elev):
                        current_x = pixel_x_elev[last_valid_idx]
                        current_y = pixel_y_elev[last_valid_idx]
                        if not (np.isnan(current_x) or np.isnan(current_y)):
                            marker.set_offsets([(current_x, current_y)])
            
            # 保存帧
            path = os.path.join(OUTPUT_DIR_ELEVATION, f"frame_elevation_{idx:06d}.png")
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            elevation_frames_rendered += 1

        plt.close(fig)
        validate_frames(elevation_frame_count, OUTPUT_DIR_ELEVATION, "frame_elevation_")
        return elevation_frames_rendered

    def assemble_alpha_mov(frame_dir, output_file, frame_count, fps, prefix="frame_", width=None, height=None):
        global FFMPEG_PATH

        if not os.path.exists(frame_dir):
            print(f"[错误] 帧目录不存在: {frame_dir}")
            return False

        print(f"\n[DEBUG] 合成视频: {output_file} (FPS: {fps})")
        target_width = width or WIDTH
        target_height = height or HEIGHT

        # 构建 ffmpeg 参数列表（避免字符串拼接）
        input_pattern = os.path.join(frame_dir, f"{prefix}%06d.png")
        vf_filter = f"scale={target_width}:{target_height},setsar=1"

        cmd = [
            FFMPEG_PATH,
            "-y",
            "-framerate", str(fps),
            "-start_number", "0",
            "-i", input_pattern,
            "-vf", f"{vf_filter},format=rgba",  # 确保输入为 RGBA
            "-c:v", "prores_ks",
            "-profile:v", "4444",
            "-pix_fmt", "yuva444p10le",
            "-frames:v", str(frame_count),
            output_file
        ]

        print(f"[DEBUG] FFmpeg命令: {' '.join(cmd)}")
        ffmpeg_start = time.time()
        alpha_ffmpeg_timeout = 3600*24
        try:
            CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=alpha_ffmpeg_timeout,creationflags=CREATE_NO_WINDOW)
            elapsed = time.time() - ffmpeg_start
            if result.returncode == 0:
                print(f"[成功] 视频生成成功: {output_file}")
                print(f"[DEBUG] FFmpeg合成耗时: {elapsed:.1f}秒")
                return True
            else:
                print(f"[警告] FFmpeg返回非零状态码: {result.returncode}")
                print(f"[FFmpeg stderr]: {result.stderr[:500]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"[错误] FFmpeg超时（超过{alpha_ffmpeg_timeout}秒）")
            return False
        except Exception as e:
            print(f"[错误] FFmpeg执行异常: {e}")
            return False
    
    # 主流程
    start_time_total = time.time()
    debug_print_config()
    duration = (lap_end - lap_start).total_seconds()
    
    try:
        # 1. 加载数据
        print("\n[步骤1/6] 加载FIT数据...")
        raw = load_and_filter(fit_path, lap_start, lap_end)
        
        # 2. 分别用不同的FPS插值数据
        print("\n[步骤2/6] 插值数据...")
        data_intp_hud = None
        data_intp_map = None
        data_intp_elevation = None
        
        if generate_hud:
            data_intp_hud = interpolate(raw, duration, HUD_FPS)
            print(f"[HUD插值] 生成了{len(data_intp_hud['speed'])}帧 (FPS: {HUD_FPS})")
        
        if generate_map:
            data_intp_map = interpolate(raw, duration, MAP_FPS)
            print(f"[地图插值] 生成了{len(data_intp_map['speed'])}帧 (FPS: {MAP_FPS})")
        
        if generate_elevation:
            data_intp_elevation = interpolate(raw, duration, ELEVATION_FPS)
            print(f"[海拔插值] 生成了{len(data_intp_elevation['speed'])}帧 (FPS: {ELEVATION_FPS})")
        
        # 3. 处理GPS坐标（地图）
        if generate_map and data_intp_map is not None:
            print("\n[步骤3/6] 处理GPS坐标（地图）...")
            pixel_x_map, pixel_y_map, min_lat, max_lat, min_lon, max_lon = normalize_coordinates(
                data_intp_map['lats'], data_intp_map['lons']
            )
            
            if pixel_x_map is None:
                print("[警告] 没有有效的GPS数据，将跳过地图视频生成")
                generate_map = False
        else:
            pixel_x_map = pixel_y_map = None
        
        # 4. 处理海拔坐标（基于距离）
        if generate_elevation and data_intp_elevation is not None:
            print("\n[步骤4/6] 处理海拔坐标（基于距离）...")
            pixel_x_elev, pixel_y_elev, min_alt, max_alt, min_dist, max_dist = normalize_elevation_by_distance(
                data_intp_elevation['alts'], 
                data_intp_elevation['dists']
            )
            
            if pixel_x_elev is None:
                print("[警告] 没有有效的海拔或距离数据，将跳过海拔视频生成")
                generate_elevation = False
            else:
                print(f"[海拔范围] {min_alt:.1f}米 到 {max_alt:.1f}米 (跨度: {max_alt-min_alt:.1f}米)")
                print(f"[距离范围] {min_dist:.1f}米 到 {max_dist:.1f}米 (总长: {max_dist-min_dist:.1f}米)")
        else:
            pixel_x_elev = pixel_y_elev = None
        
        # 5. 渲染帧
        print("\n[步骤5/6] 渲染帧...")
        
        hud_frames_done = 0
        map_frames_done = 0
        elevation_frames_done = 0
        hud_success = False
        map_success = False
        elevation_success = False
        
        if use_multithreading and (generate_hud or generate_map or generate_elevation):
            # 使用多线程并行渲染
            print("[DEBUG] 使用多线程并行渲染...")
            threads = []
            results = {
                'hud': {'frames': 0, 'success': False},
                'map': {'frames': 0, 'success': False},
                'elevation': {'frames': 0, 'success': False}
            }
            
            def render_hud_thread():
                try:
                    frames = render_hud_frames(data_intp_hud, duration)
                    results['hud']['frames'] = frames
                    results['hud']['success'] = True
                except Exception as e:
                    print(f"[HUD渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
            
            def render_map_thread():
                try:
                    frames = render_map_frames(data_intp_map, pixel_x_map, pixel_y_map, duration)
                    results['map']['frames'] = frames
                    results['map']['success'] = True
                except Exception as e:
                    print(f"[地图渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
            
            def render_elevation_thread():
                try:
                    frames = render_elevation_frames(
                        data_intp_elevation, 
                        pixel_x_elev, 
                        pixel_y_elev, 
                        data_intp_elevation['dists'],  # 传递距离数组
                        duration
                    )
                    results['elevation']['frames'] = frames
                    results['elevation']['success'] = True
                except Exception as e:
                    print(f"[海拔渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
            
            # 启动渲染线程
            if generate_hud and data_intp_hud is not None:
                hud_thread = threading.Thread(target=render_hud_thread)
                threads.append(hud_thread)
                hud_thread.start()
            
            if generate_map and data_intp_map is not None and pixel_x_map is not None:
                map_thread = threading.Thread(target=render_map_thread)
                threads.append(map_thread)
                map_thread.start()
            
            if generate_elevation and data_intp_elevation is not None and pixel_x_elev is not None:
                elevation_thread = threading.Thread(target=render_elevation_thread)
                threads.append(elevation_thread)
                elevation_thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join()
            
            # 获取结果
            hud_frames_done = results['hud']['frames']
            map_frames_done = results['map']['frames']
            elevation_frames_done = results['elevation']['frames']
            hud_success = results['hud']['success']
            map_success = results['map']['success']
            elevation_success = results['elevation']['success']
        else:
            # 顺序渲染
            print("[DEBUG] 使用顺序渲染...")
            if generate_hud and data_intp_hud is not None:
                try:
                    hud_frames_done = render_hud_frames(data_intp_hud, duration)
                    hud_success = True
                except Exception as e:
                    print(f"[HUD渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    hud_success = False
            
            if generate_map and data_intp_map is not None and pixel_x_map is not None:
                try:
                    map_frames_done = render_map_frames(data_intp_map, pixel_x_map, pixel_y_map, duration)
                    map_success = True
                except Exception as e:
                    print(f"[地图渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    map_success = False
            
            if generate_elevation and data_intp_elevation is not None and pixel_x_elev is not None:
                try:
                    elevation_frames_done = render_elevation_frames(
                        data_intp_elevation, 
                        pixel_x_elev, 
                        pixel_y_elev, 
                        data_intp_elevation['dists'],  # 传递距离数组
                        duration
                    )
                    elevation_success = True
                except Exception as e:
                    print(f"[海拔渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    elevation_success = False
        
        # 6. 合成视频
        print("\n[步骤6/6] 合成视频...")
        if generate_hud and hud_success and hud_frames_done > 0:
            print("\n--- 合成HUD视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_HUD, OUTPUT_MOV_HUD, hud_frames_done, HUD_FPS, "frame_"):
                print(f"✅ HUD视频生成成功: {OUTPUT_MOV_HUD} (FPS: {HUD_FPS})")
            else:
                print("❌ HUD视频生成失败")
        else:
            print("⏭️ 跳过HUD视频生成")
        
        if generate_map and map_success and map_frames_done > 0:
            print("\n--- 合成地图视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_MAP, OUTPUT_MOV_MAP, map_frames_done, MAP_FPS, "frame_map_"):
                print(f"✅ 地图视频生成成功: {OUTPUT_MOV_MAP} (FPS: {MAP_FPS})")
            else:
                print("❌ 地图视频生成失败")
        else:
            print("⏭️ 跳过地图视频生成")
        
        if generate_elevation and elevation_success and elevation_frames_done > 0:
            print("\n--- 合成海拔视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_ELEVATION, OUTPUT_MOV_ELEVATION, 
                                 elevation_frames_done, ELEVATION_FPS, "frame_elevation_", 
                                 ELEVATION_WIDTH, ELEVATION_HEIGHT):
                print(f"✅ 海拔视频生成成功: {OUTPUT_MOV_ELEVATION} (FPS: {ELEVATION_FPS})")
            else:
                print("❌ 海拔视频生成失败")
        else:
            print("⏭️ 跳过海拔视频生成")
        
        # 7. 清理临时文件
        print("\n[清理] 删除临时帧目录...")
        if os.path.exists(OUTPUT_DIR_HUD) and generate_hud:
            shutil.rmtree(OUTPUT_DIR_HUD)
            print(f"已删除HUD临时帧目录: {OUTPUT_DIR_HUD}")
        
        if os.path.exists(OUTPUT_DIR_MAP) and generate_map:
            shutil.rmtree(OUTPUT_DIR_MAP)
            print(f"已删除地图临时帧目录: {OUTPUT_DIR_MAP}")
        
        if os.path.exists(OUTPUT_DIR_ELEVATION) and generate_elevation:
            shutil.rmtree(OUTPUT_DIR_ELEVATION)
            print(f"已删除海拔临时帧目录: {OUTPUT_DIR_ELEVATION}")
            
    except Exception as e:
        print(f"❌ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
    
    end_time_total = time.time()
    elapsed = end_time_total - start_time_total
    minutes, seconds = divmod(int(elapsed), 60)
    print(f"\n✅ 总耗时：{minutes}分{seconds}秒（{elapsed:.2f}秒）")
    
    # 返回生成的文件路径
    result = {}
    if generate_hud and hud_success and os.path.exists(OUTPUT_MOV_HUD):
        result['hud_video'] = OUTPUT_MOV_HUD
    if generate_map and map_success and os.path.exists(OUTPUT_MOV_MAP):
        result['map_video'] = OUTPUT_MOV_MAP
    if generate_elevation and elevation_success and os.path.exists(OUTPUT_MOV_ELEVATION):
        result['elevation_video'] = OUTPUT_MOV_ELEVATION
    
    return result

# 为了向后兼容，保留原函数名
generate_hud_video = generate_hud_map_elevation_video

if __name__ == "__main__":
    # 测试数据
    FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    lap_start = datetime(2026, 4, 25, 2, 7, 30)
    lap_end   = datetime(2026, 4, 25, 2, 15, 52)
    
    # 调用函数，生成所有三种视频，可以分别设置不同的FPS
    result = generate_hud_map_elevation_video(
        fit_path=FIT_PATH,
        lap_start=lap_start,
        lap_end=lap_end,
        generate_hud=True,         # 是否生成HUD视频
        generate_map=True,         # 是否生成地图视频
        generate_elevation=True,    # 是否生成海拔视频
        hud_fps=5,                 # HUD视频帧率
        map_fps=2,                 # 地图视频帧率
        elevation_fps=10           # 海拔视频帧率
    )
    
    print("\n" + "="*50)
    print("生成结果:")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("="*50)