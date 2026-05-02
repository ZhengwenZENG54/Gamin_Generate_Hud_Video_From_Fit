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

def generate_hud_map_elevation_video(fit_path, lap_start, lap_end, 
                                   generate_hud=False,
                                   generate_map=False,
                                   generate_elevation=True):
    """
    从FIT文件生成HUD、地图和海拔叠加视频
    
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
        
    返回值:
    ----------
    dict
        包含生成视频文件路径的字典
    """
    
    # ==================== 默认参数设置 ====================
    # 输出目录参数
    output_dir_hud = "frames_hud"
    output_dir_map = "frames_map"
    output_dir_elevation = "frames_elevation"
    
    # 视频参数
    fps = 30
    width, height = 480, 270
    elevation_width, elevation_height = 480, 80  # 6:1 比例
    font_size = 25
    print_interval = 10
    speed_threshold = 3.0
    
    # 控制参数
    use_multithreading = False
    flip_map_vertical = False
    
    # 地图样式参数
    map_line_width = 5
    map_line_color = (1.0, 0.5, 0.0, 0.5)  # RGBA: 橙色半透明
    map_completed_color = (0.0, 0.6, 1.0, 1.0)  # RGBA: 蓝色
    map_marker_color = (1.0, 0.0, 0.0, 1.0)  # RGBA: 红色
    map_marker_size = 12
    map_marker_type = 'triangle'  # 标记类型
    map_background_color = (0.0, 0.0, 0.0, 0.0)  # RGBA: 完全透明
    map_show_grid = False
    map_grid_color = (1.0, 1.0, 1.0, 0.1)  # RGBA: 白色半透明
    map_grid_spacing = 0.2
    map_margin = 0.1  # 边距比例(0-0.5)
    
    # 海拔图参数
    elevation_line_width = 3
    elevation_line_color = (0.0, 1.0, 0.0, 1.0)  # RGBA: 绿色
    elevation_marker_color = (1.0, 0.0, 0.0, 1.0)  # RGBA: 红色
    elevation_marker_size = 10
    elevation_background_color = (0.0, 0.0, 0.0, 0.0)  # RGBA: 完全透明
    elevation_show_grid = True
    elevation_grid_color = (1.0, 1.0, 1.0, 0.2)  # RGBA: 白色半透明
    elevation_grid_spacing = 0.1
    
    # ==================== 内部变量 ====================
    OUTPUT_DIR_HUD = output_dir_hud
    OUTPUT_DIR_MAP = output_dir_map
    OUTPUT_DIR_ELEVATION = output_dir_elevation
    FPS = fps
    WIDTH, HEIGHT = width, height
    ELEVATION_WIDTH, ELEVATION_HEIGHT = elevation_width, elevation_height
    FONT_SIZE = font_size
    PRINT_INTERVAL = print_interval
    SPEED_THRESHOLD = speed_threshold
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    OUTPUT_MOV_HUD = f"hud_overlay_alpha_{timestamp}.mov"
    OUTPUT_MOV_MAP = f"map_overlay_alpha_{timestamp}.mov"
    OUTPUT_MOV_ELEVATION = f"elevation_overlay_alpha_{timestamp}.mov"
    
    def debug_print_config():
        duration = (lap_end - lap_start).total_seconds()
        print("\n=== 配置参数检查 ===")
        print(f"FIT文件路径: {fit_path}")
        print(f"HUD输出目录: {OUTPUT_DIR_HUD}" if generate_hud else "[跳过HUD生成]")
        print(f"地图输出目录: {OUTPUT_DIR_MAP}" if generate_map else "[跳过地图生成]")
        print(f"海拔输出目录: {OUTPUT_DIR_ELEVATION}" if generate_elevation else "[跳过海拔生成]")
        print(f"HUD输出视频: {OUTPUT_MOV_HUD}" if generate_hud else "")
        print(f"地图输出视频: {OUTPUT_MOV_MAP}" if generate_map else "")
        print(f"海拔输出视频: {OUTPUT_MOV_ELEVATION}" if generate_elevation else "")
        print(f"帧率(FPS): {FPS}")
        print(f"HUD/地图分辨率: {WIDTH}x{HEIGHT}")
        print(f"海拔图分辨率: {ELEVATION_WIDTH}x{ELEVATION_HEIGHT}")
        print(f"开始时间: {lap_start} (UTC)")
        print(f"结束时间: {lap_end} (UTC)")
        print(f"计算时长: {duration}秒 ({duration//60}分{duration%60}秒)")
        print(f"预期总帧数: {int(duration*FPS)}帧")
        print(f"速度显示阈值: {SPEED_THRESHOLD} km/h")
        print(f"多线程渲染: {'启用' if use_multithreading else '禁用'}")
        print(f"地图标记类型: {map_marker_type}")
        print(f"地图垂直翻转: {'是' if flip_map_vertical else '否'}")
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

        offs, spd, pwr, hr, cad, lats, lons, distances, altitudes = [], [], [], [], [], [], [], [], []
        lat_found = False
        lon_found = False
        distance_found = False
        altitude_found = False
        
        # 获取第一条记录的距离值，用于从0开始
        first_record_distance = None
        
        for r in recs:
            ts = r['timestamp']
            if not (start_abs_time <= ts <= end_abs_time):
                continue
                
            offset = (ts - start_abs_time).total_seconds()
            offs.append(offset)
            
            # 速度数据
            s = r.get('speed') or r.get('enhanced_speed', 0.0)
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
            
            # 距离数据
            distance = r.get('distance')
            if distance is not None:
                distance_found = True
                if first_record_distance is None:
                    first_record_distance = distance
                # 从0开始计算距离
                distances.append(distance - first_record_distance)
            else:
                distances.append(np.nan)
            
            # 海拔数据
            altitude = r.get('altitude')
            if altitude is not None:
                altitude_found = True
                altitudes.append(altitude)
            else:
                altitudes.append(np.nan)

        if not offs:
            raise RuntimeError("指定时间范围内没有数据")

        print(f"[DEBUG] GPS数据: 纬度{'已找到' if lat_found else '未找到'}, 经度{'已找到' if lon_found else '未找到'}")
        print(f"[DEBUG] 距离数据: {'已找到' if distance_found else '未找到'}")
        print(f"[DEBUG] 海拔数据: {'已找到' if altitude_found else '未找到'}")
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
            'distances': np.array(distances),  # 距离数据
            'altitudes': np.array(altitudes),  # 海拔数据
        }
    
    def interpolate(data, duration_sec):
        print(f"\n[DEBUG] 开始数据插值，目标时长: {duration_sec}秒")
        x = data['offsets']
        time_points = np.linspace(0, duration_sec, int(duration_sec * FPS) + 1)
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
        
        # 对GPS数据进行线性插值
        lats = data['lats']
        lons = data['lons']
        
        # 创建掩码，标识哪些点是有效的GPS点
        valid_gps_mask = ~(np.isnan(lats) | np.isnan(lons))
        
        if np.any(valid_gps_mask):
            # 至少有部分GPS数据
            valid_x = x[valid_gps_mask]
            valid_lats = lats[valid_gps_mask]
            valid_lons = lons[valid_gps_mask]
            
            # 对有效GPS数据进行插值
            interp_lats = interp1d(valid_x, valid_lats, kind='linear', fill_value="extrapolate")(time_points)
            interp_lons = interp1d(valid_x, valid_lons, kind='linear', fill_value="extrapolate")(time_points)
        else:
            # 没有GPS数据，全部设为NaN
            interp_lats = np.full_like(time_points, np.nan)
            interp_lons = np.full_like(time_points, np.nan)
        
        # 对距离数据进行线性插值
        distances = data['distances']
        valid_dist_mask = ~np.isnan(distances)
        if np.any(valid_dist_mask):
            valid_dist_x = x[valid_dist_mask]
            valid_dist = distances[valid_dist_mask]
            interp_dist = interp1d(valid_dist_x, valid_dist, kind='linear', fill_value="extrapolate")(time_points)
        else:
            interp_dist = np.full_like(time_points, np.nan)
        
        # 对海拔数据进行线性插值
        altitudes = data['altitudes']
        valid_alt_mask = ~np.isnan(altitudes)
        if np.any(valid_alt_mask):
            valid_alt_x = x[valid_alt_mask]
            valid_alt = altitudes[valid_alt_mask]
            interp_alt = interp1d(valid_alt_x, valid_alt, kind='linear', fill_value="extrapolate")(time_points)
        else:
            interp_alt = np.full_like(time_points, np.nan)
        
        result = {
            'speed': interp_speed_clean,
            'power': interp(data['power']).astype(int),
            'hr':    interp(data['hr']).astype(int),
            'cad':   interp(data['cad']).astype(int),
            'lats':  interp_lats,
            'lons':  interp_lons,
            'distances': interp_dist,  # 插值后的距离
            'altitudes': interp_alt,    # 插值后的海拔
        }
        
        zero_count = np.sum(result['speed'] < 0.1)
        print(f"[停车段识别] 识别出{np.sum(stop_flags)}个插值点处于停车状态")
        print(f"[最终过滤] 零速点比例: {zero_count}/{len(result['speed'])} ({(zero_count/len(result['speed']))*100:.1f}%)")
        
        # 统计有效GPS数据
        valid_gps_count = np.sum(~np.isnan(interp_lats))
        print(f"[GPS数据] 插值后有效GPS点数: {valid_gps_count}/{len(interp_lats)} ({(valid_gps_count/len(interp_lats))*100:.1f}%)")
        
        # 统计有效距离数据
        valid_dist_count = np.sum(~np.isnan(interp_dist))
        print(f"[距离数据] 插值后有效距离点数: {valid_dist_count}/{len(interp_dist)} ({(valid_dist_count/len(interp_dist))*100:.1f}%)")
        
        # 统计有效海拔数据
        valid_alt_count = np.sum(~np.isnan(interp_alt))
        print(f"[海拔数据] 插值后有效海拔点数: {valid_alt_count}/{len(interp_alt)} ({(valid_alt_count/len(interp_alt))*100:.1f}%)")
        
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
    
    def format_value(value, value_type):
        if value_type == 'speed':
            if value < SPEED_THRESHOLD:
                return f"<{SPEED_THRESHOLD}km/h"
            return f"{value:.1f} km/h"
        elif value_type in ['power', 'cad']:
            if value == -2147483648:
                return "--"
            if value_type == 'power':
                return f"{value} W"
            else:
                return f"{value} rpm"
        elif value_type == 'hr':
            return f"{value} bpm"
        elif value_type == 'distance':
            if np.isnan(value):
                return "0.00 km"
            return f"{value/1000:.2f} km"  # 转换为km，保留2位小数
        elif value_type == 'altitude':
            if np.isnan(value):
                return "0 m"
            return f"{int(value)} m"  # 转换为整数
        return str(value)
    
    def render_hud_frames(data_intp, duration_sec):
        if not generate_hud:
            return 0
            
        print("\n[DEBUG] 开始渲染HUD帧")
        os.makedirs(OUTPUT_DIR_HUD, exist_ok=True)
        frame_count = int(duration_sec * FPS)

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_HUD):
            if f.startswith("frame_"):
                os.remove(os.path.join(OUTPUT_DIR_HUD, f))

        plt.ioff()
        # 关键修改：使用原始代码的图形创建方式
        fig, ax = plt.subplots(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)
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
        
        hud_frame_count = 0

        for idx in range(frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[HUD进度] {processed}/{frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time

            speed_display = format_value(data_intp['speed'][idx], 'speed')
            power_display = format_value(data_intp['power'][idx], 'power')
            hr_display = format_value(data_intp['hr'][idx], 'hr')
            cad_display = format_value(data_intp['cad'][idx], 'cad')

            text_obj.set_text(
                f"Speed: {speed_display}\n"
                f"Power: {power_display}\n"
                f"Heart Rate: {hr_display}\n"
                f"Cadence: {cad_display}"
            )
            
            path = os.path.join(OUTPUT_DIR_HUD, f"frame_{idx:06d}.png")
            # 关键修改：去掉 bbox_inches='tight'，使用原始代码的保存方式
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            hud_frame_count += 1

        plt.close(fig)
        validate_frames(frame_count, OUTPUT_DIR_HUD, "frame_")
        return hud_frame_count
    
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
    
    def render_map_frames(data_intp, pixel_x, pixel_y, duration_sec):
        if not generate_map:
            return 0
            
        print("\n[DEBUG] 开始渲染地图帧（带距离显示）")
        os.makedirs(OUTPUT_DIR_MAP, exist_ok=True)
        frame_count = int(duration_sec * FPS)

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_MAP):
            if f.startswith("frame_map_"):
                os.remove(os.path.join(OUTPUT_DIR_MAP, f))

        plt.ioff()
        fig, ax = plt.subplots(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)  # 设置图形背景透明
        
        # 设置轴位置，使用整个图形区域，为距离文本留出更多底部空间
        ax.set_position([0.05, 0.15, 0.9, 0.75])  # 调整：增加底部空间
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
        
        # 绘制完整轨迹（浅色背景）
        valid_coords = [(x, y) for x, y in zip(pixel_x, pixel_y) if not (np.isnan(x) or np.isnan(y))]
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
        
        # 添加距离显示文本 - 放在更下方避免与轨迹重叠
        distance_text = ax.text(
            0.5, -0.12,  # 位置在轴下方，避免与轨迹重叠
            "Distance: 0.00 km",
            fontsize=FONT_SIZE * 0.8,  # 稍微小一点的字体
            color='white',
            bbox=dict(facecolor='black', alpha=0.5, boxstyle='round,pad=0.2'),
            transform=ax.transAxes,
            horizontalalignment='center',
            verticalalignment='top',
            zorder=4
        )
        
        last_print_time = time.time()
        start_time = time.time()
        map_frame_count = 0
        
        # 存储上一帧的角度，用于平滑旋转
        angle_history = []
        
        # 存储已完成轨迹的点
        completed_x_list = []
        completed_y_list = []

        for idx in range(frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[地图进度] {processed}/{frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time
            
            # 获取当前坐标
            current_x, current_y = pixel_x[idx], pixel_y[idx]
            
            if not (np.isnan(current_x) or np.isnan(current_y)):
                # 增量更新轨迹
                completed_x_list.append(current_x)
                completed_y_list.append(current_y)
                completed_line.set_data(completed_x_list, completed_y_list)
                
                if map_marker_type == 'arrow':
                    # 使用箭头标记
                    # 计算方向
                    if idx > 0 and idx < len(pixel_x) - 1:
                        # 计算前进方向
                        direction_rad = calculate_moving_direction(pixel_x, pixel_y, idx, look_ahead=3)
                        
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
                    if idx > 0 and idx < len(pixel_x) - 1:
                        # 计算前进方向
                        direction_rad = calculate_moving_direction(pixel_x, pixel_y, idx, look_ahead=3)
                        
                        if direction_rad != 0:
                            # 将前进方向转换为角度（度）
                            direction_deg = math.degrees(direction_rad)
                            
                            # 三角形标记默认指向90度（上方），我们需要将它旋转到前进方向
                            rotation_angle = direction_deg - 90
                            
                            # 角度平滑
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
            
            # 更新距离显示
            current_distance = data_intp['distances'][idx]
            distance_display = format_value(current_distance, 'distance')
            distance_text.set_text(f"Distance: {distance_display}")
            
            # 保存帧
            path = os.path.join(OUTPUT_DIR_MAP, f"frame_map_{idx:06d}.png")
            # 关键修改：去掉 bbox_inches='tight'，使用原始代码的保存方式
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            map_frame_count += 1

        plt.close(fig)
        validate_frames(frame_count, OUTPUT_DIR_MAP, "frame_map_")
        return map_frame_count
    
    def render_elevation_frames(data_intp, duration_sec):
        if not generate_elevation:
            return 0
            
        print("\n[DEBUG] 开始渲染海拔帧")
        os.makedirs(OUTPUT_DIR_ELEVATION, exist_ok=True)
        frame_count = int(duration_sec * FPS)

        # 清理旧帧
        for f in os.listdir(OUTPUT_DIR_ELEVATION):
            if f.startswith("frame_elevation_"):
                os.remove(os.path.join(OUTPUT_DIR_ELEVATION, f))

        plt.ioff()
        fig, ax = plt.subplots(figsize=(ELEVATION_WIDTH/100, ELEVATION_HEIGHT/100), dpi=100)
        fig.patch.set_alpha(0)  # 设置图形背景透明
        
        # 设置轴位置，为海拔文本留出底部空间
        ax.set_position([0.1, 0.25, 0.8, 0.6])  # 调整位置以适应6:1比例
        ax.set_facecolor(elevation_background_color)
        
        # 处理海拔数据
        altitudes = data_intp['altitudes']
        time_points = np.linspace(0, duration_sec, len(altitudes))
        
        # 找到有效海拔点
        valid_mask = ~np.isnan(altitudes)
        valid_time = time_points[valid_mask]
        valid_altitudes = altitudes[valid_mask]
        
        if len(valid_altitudes) == 0:
            print("[警告] 没有有效的海拔数据，跳过海拔视频生成")
            return 0
        
        # 设置X轴范围（时间）
        ax.set_xlim(0, duration_sec)
        
        # 设置Y轴范围（海拔），添加一些边距
        alt_min, alt_max = np.min(valid_altitudes), np.max(valid_altitudes)
        alt_range = alt_max - alt_min
        if alt_range == 0:
            alt_range = 10  # 防止除零
        margin = alt_range * 0.1
        ax.set_ylim(alt_min - margin, alt_max + margin)
        
        # 绘制网格
        if elevation_show_grid:
            # 计算网格间距
            x_grid_step = duration_sec * elevation_grid_spacing
            y_grid_step = alt_range * elevation_grid_spacing
            
            # 绘制垂直网格线
            for x in np.arange(0, duration_sec + x_grid_step, x_grid_step):
                ax.axvline(x, color=elevation_grid_color, linewidth=0.5, alpha=0.5)
            
            # 绘制水平网格线
            for y in np.arange(alt_min - margin, alt_max + margin + y_grid_step, y_grid_step):
                ax.axhline(y, color=elevation_grid_color, linewidth=0.5, alpha=0.5)
        
        ax.axis('off')
        
        # 绘制完整海拔曲线（浅色）
        if len(valid_time) > 0:
            ax.plot(valid_time, valid_altitudes, color=elevation_line_color, 
                   linewidth=elevation_line_width, alpha=0.5, zorder=1)
        
        # 绘制已完成的海拔曲线
        completed_line, = ax.plot([], [], color=elevation_line_color, 
                                  linewidth=elevation_line_width, zorder=2)
        
        # 当前位置标记
        current_point = ax.scatter([], [], s=elevation_marker_size**2, 
                                   c=[elevation_marker_color], 
                                   marker='o', edgecolors='white', 
                                   linewidths=1, zorder=3)
        
        # 添加当前海拔显示文本
        altitude_text = ax.text(
            0.5, -0.4,  # 位置在图形底部下方
            "Altitude: 0 m",
            fontsize=FONT_SIZE * 0.7,  # 更小的字体以适应6:1比例
            color='white',
            bbox=dict(facecolor='black', alpha=0.5, boxstyle='round,pad=0.2'),
            transform=ax.transAxes,
            horizontalalignment='center',
            verticalalignment='top',
            zorder=4
        )
        
        last_print_time = time.time()
        start_time = time.time()
        elevation_frame_count = 0
        
        # 存储已完成轨迹的点
        completed_time_list = []
        completed_altitude_list = []

        for idx in range(frame_count):
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL:
                elapsed = current_time - start_time
                processed = idx + 1
                if processed > 0:
                    fps_actual = processed / elapsed
                else:
                    fps_actual = 0
                remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
                print(
                    f"[海拔进度] {processed}/{frame_count}帧 | "
                    f"已用: {elapsed:.1f}s | "
                    f"剩余: {remaining:.1f}s | "
                    f"速度: {fps_actual:.1f}帧/s"
                )
                last_print_time = current_time
            
            # 获取当前时间和海拔
            current_altitude = altitudes[idx]
            current_time_point = time_points[idx]
            
            if not np.isnan(current_altitude):
                # 增量更新曲线
                completed_time_list.append(current_time_point)
                completed_altitude_list.append(current_altitude)
                completed_line.set_data(completed_time_list, completed_altitude_list)
                
                # 更新当前位置标记
                current_point.set_offsets([(current_time_point, current_altitude)])
            
            # 更新海拔显示
            altitude_display = format_value(current_altitude, 'altitude')
            altitude_text.set_text(f"Altitude: {altitude_display}")
            
            # 保存帧
            path = os.path.join(OUTPUT_DIR_ELEVATION, f"frame_elevation_{idx:06d}.png")
            fig.savefig(path, dpi=100, pad_inches=0, transparent=True)
            elevation_frame_count += 1

        plt.close(fig)
        validate_frames(frame_count, OUTPUT_DIR_ELEVATION, "frame_elevation_")
        return elevation_frame_count
    
    def assemble_alpha_mov(frame_dir, output_file, frame_count, prefix="frame_"):
        if not os.path.exists(frame_dir):
            print(f"[错误] 帧目录不存在: {frame_dir}")
            return False
            
        print(f"\n[DEBUG] 合成视频: {output_file}")
        
        # 根据帧目录判断是哪种视频
        if "hud" in frame_dir.lower():
            width, height = WIDTH, HEIGHT
        elif "elevation" in frame_dir.lower():
            width, height = ELEVATION_WIDTH, ELEVATION_HEIGHT
        else:  # map
            width, height = WIDTH, HEIGHT
            
        cmd = (
            f'ffmpeg -y -framerate {FPS} -start_number 0 -i "{frame_dir}/{prefix}%06d.png" '
            f'-vf "scale={width}:{height},setsar=1" '
            f'-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le '
            f'-frames:v {frame_count} "{output_file}"'
        )
        print(f"[DEBUG] FFmpeg命令:\n{cmd}")
        ffmpeg_start = time.time()
        result = os.system(cmd)
        if result != 0:
            print(f"[警告] FFmpeg返回非零状态码: {result}")
        ffmpeg_time = time.time() - ffmpeg_start
        print(f"[DEBUG] FFmpeg合成耗时: {ffmpeg_time:.1f}秒")
        return result == 0
    
    # 主流程
    start_time_total = time.time()
    debug_print_config()
    duration = (lap_end - lap_start).total_seconds()
    
    try:
        # 1. 加载数据
        print("\n[步骤1/4] 加载FIT数据...")
        raw = load_and_filter(fit_path, lap_start, lap_end)
        
        # 2. 插值数据
        print("\n[步骤2/4] 插值数据...")
        data_intp = interpolate(raw, duration)
        
        # 3. 处理GPS坐标
        print("\n[步骤3/4] 处理GPS坐标...")
        pixel_x, pixel_y, min_lat, max_lat, min_lon, max_lon = normalize_coordinates(
            data_intp['lats'], data_intp['lons']
        )
        
        if pixel_x is None:
            print("[警告] 没有有效的GPS数据，将跳过地图视频生成")
            generate_map = False
        else:
            print(f"[GPS坐标] 经度范围: {min_lon:.6f}° 到 {max_lon:.6f}°")
            print(f"[GPS坐标] 纬度范围: {min_lat:.6f}° 到 {max_lat:.6f}°")
        
        # 检查是否有海拔数据
        valid_altitudes = data_intp['altitudes'][~np.isnan(data_intp['altitudes'])]
        if len(valid_altitudes) == 0 and generate_elevation:
            print("[警告] 没有有效的海拔数据，将跳过海拔视频生成")
            generate_elevation = False
        
        # 4. 渲染帧
        print("\n[步骤4/4] 渲染帧...")
        frame_count = int(duration * FPS)
        
        hud_frames_done = 0
        map_frames_done = 0
        elevation_frames_done = 0
        hud_success = False
        map_success = False
        elevation_success = False
        
        if use_multithreading and (generate_hud or generate_map or generate_elevation):
            # 使用多线程并行渲染
            print("[DEBUG] 使用多线程并行渲染...")
            
            def render_hud_thread():
                nonlocal hud_frames_done, hud_success
                try:
                    hud_frames_done = render_hud_frames(data_intp, duration)
                    hud_success = True
                except Exception as e:
                    print(f"[HUD渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    hud_success = False
            
            def render_map_thread():
                nonlocal map_frames_done, map_success
                try:
                    map_frames_done = render_map_frames(data_intp, pixel_x, pixel_y, duration)
                    map_success = True
                except Exception as e:
                    print(f"[地图渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    map_success = False
            
            def render_elevation_thread():
                nonlocal elevation_frames_done, elevation_success
                try:
                    elevation_frames_done = render_elevation_frames(data_intp, duration)
                    elevation_success = True
                except Exception as e:
                    print(f"[海拔渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    elevation_success = False
            
            # 启动渲染线程
            hud_thread = threading.Thread(target=render_hud_thread) if generate_hud else None
            map_thread = threading.Thread(target=render_map_thread) if generate_map else None
            elevation_thread = threading.Thread(target=render_elevation_thread) if generate_elevation else None
            
            if hud_thread:
                hud_thread.start()
            if map_thread:
                map_thread.start()
            if elevation_thread:
                elevation_thread.start()
            
            # 等待线程完成
            if hud_thread:
                hud_thread.join()
            if map_thread:
                map_thread.join()
            if elevation_thread:
                elevation_thread.join()
        else:
            # 顺序渲染
            print("[DEBUG] 使用顺序渲染...")
            if generate_hud:
                try:
                    hud_frames_done = render_hud_frames(data_intp, duration)
                    hud_success = True
                except Exception as e:
                    print(f"[HUD渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    hud_success = False
            
            if generate_map:
                try:
                    map_frames_done = render_map_frames(data_intp, pixel_x, pixel_y, duration)
                    map_success = True
                except Exception as e:
                    print(f"[地图渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    map_success = False
            
            if generate_elevation:
                try:
                    elevation_frames_done = render_elevation_frames(data_intp, duration)
                    elevation_success = True
                except Exception as e:
                    print(f"[海拔渲染错误] {e}")
                    import traceback
                    traceback.print_exc()
                    elevation_success = False
        
        # 5. 合成视频
        print("\n[步骤5/5] 合成视频...")
        if generate_hud and hud_success and hud_frames_done > 0:
            print("\n--- 合成HUD视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_HUD, OUTPUT_MOV_HUD, hud_frames_done, "frame_"):
                print(f"✅ HUD视频生成成功: {OUTPUT_MOV_HUD}")
            else:
                print("❌ HUD视频生成失败")
        else:
            print("⏭️ 跳过HUD视频生成")
        
        if generate_map and map_success and map_frames_done > 0:
            print("\n--- 合成地图视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_MAP, OUTPUT_MOV_MAP, map_frames_done, "frame_map_"):
                print(f"✅ 地图视频生成成功: {OUTPUT_MOV_MAP}")
            else:
                print("❌ 地图视频生成失败")
        else:
            print("⏭️ 跳过地图视频生成")
        
        if generate_elevation and elevation_success and elevation_frames_done > 0:
            print("\n--- 合成海拔视频 ---")
            if assemble_alpha_mov(OUTPUT_DIR_ELEVATION, OUTPUT_MOV_ELEVATION, elevation_frames_done, "frame_elevation_"):
                print(f"✅ 海拔视频生成成功: {OUTPUT_MOV_ELEVATION}")
            else:
                print("❌ 海拔视频生成失败")
        else:
            print("⏭️ 跳过海拔视频生成")
        
        # 6. 清理临时文件
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
generate_hud_and_map_video = generate_hud_map_elevation_video

if __name__ == "__main__":
    FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-25-10-07-30.fit"
    lap_start = datetime(2026, 4, 25, 2, 7, 30)
    lap_end   = datetime(2026, 4, 25, 2, 15, 52)
    
    # 只需要指定这6个参数
    result = generate_hud_map_elevation_video(
        fit_path=FIT_PATH,
        lap_start=lap_start,
        lap_end=lap_end,
        generate_hud=True,      # 是否生成HUD视频
        generate_map=True,       # 是否生成地图视频
        generate_elevation=True  # 是否生成海拔视频
    )
    
    print("\n" + "="*50)
    print("生成结果:")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("="*50)