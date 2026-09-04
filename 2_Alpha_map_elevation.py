# -*- coding: utf-8 -*-
"""
Alpha_map_elevation.py
========================
Alpha 模块的 MAP / ELEVATION 子模块。

职责：
  - Alpha_MAP        : 骑行轨迹地图叠加层视频
  - Alpha_ELEVATION  : 海拔剖面图叠加层视频

两个模块强制共用同一时间轴（无论单独运行还是被调用）。

两种使用方式：
  1) 单独运行（CLI）：交互式选择 FIT 文件 / Lap（一次选择，两个模块共用）
  2) 被调用：通过 generate_map_elevation_video() / generate_map_video() /
             generate_elevation_video() 传入参数，无 input() 阻塞

设计原则（与 Alpha_SPHC 对称）：
  - 自包含：不 import SPHC，load_and_filter / interpolate / assemble 等均在本文件
  - 串行执行：一次只处理一个视频（生成 frames + 合成），无多线程分支
  - 统一清理：两个视频都生成完毕后，最后统一清理中间帧目录
  - 边界检查：渲染前纯数学估算，越界只警告 + 写入 warnings，不阻断渲染
  - 数据缺失：只跳过缺失模块，另一模块照常生成，并在返回中明确标注
  - 冲突处理：API 模式帧目录已存在则抛 FileExistsError；CLI 入口先清理再调用
"""

import os
import math
import time
import shutil
import datetime
import subprocess
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ============================================================
# 全局可配置变量（兼容 exe / GUI 打包场景，允许外部覆盖）
# ============================================================
FFMPEG_PATH = "ffmpeg"

OUTPUT_DIR_MAP = None        # None 表示使用默认固定名 "frames_Alpha_MAP"
OUTPUT_MOV_MAP = None
OUTPUT_DIR_ELEVATION = None  # None 表示使用默认固定名 "frames_Alpha_ELEVATION"
OUTPUT_MOV_ELEVATION = None

# 默认帧率（图像层，5fps）
MAP_DEFAULT_FPS = 5
ELEVATION_DEFAULT_FPS = 5

# 固定帧目录名（不加时间戳，冲突处理见下方逻辑）
DEFAULT_FRAMES_DIR_MAP = "frames_Alpha_MAP"
DEFAULT_FRAMES_DIR_ELEVATION = "frames_Alpha_ELEVATION"


# ============================================================
# 默认参数（可通过 params_dict 覆盖）
#   数值直接抄原 Alpha 模块
# ============================================================
# ---------- MAP ----------
DEFAULT_PARAMS_MAP = {
    'width': 270,
    'height': 270,
    'map_line_width': 5,
    'map_line_color': (1.0, 0.5, 0.0, 1.0),       # RGBA: 橙色不透明
    'map_completed_color': (0.0, 0.6, 1.0, 1.0),   # RGBA: 蓝色
    'map_marker_color': (1.0, 0.0, 0.0, 1.0),      # RGBA: 红色
    'map_marker_size': 15,
    'map_marker_type': 'triangle',                  # triangle / arrow
    'map_background_color': (0.0, 0.0, 0.0, 0.0),  # 完全透明
    'map_circle_bg_color': (0.2, 0.2, 0.2, 0.6),  # 灰色半透明背景
    'map_circle_padding_percent': 10,
    'map_margin': 0.1,
    'flip_map_vertical': False,
    'print_interval': 5,
}

# ---------- ELEVATION ----------
DEFAULT_PARAMS_ELEVATION = {
    'elevation_width': 800,
    'elevation_aspect_ratio': 8,    # 长宽比 宽:高
    'elevation_line_width': 3,
    'elevation_completed_color': (0.0, 0.8, 0.0, 1.0),  # RGBA: 绿色
    'elevation_background_color': (1.0, 1.0, 1.0, 0.2),  # RGBA: 白色半透明
    'elevation_marker_color': (1.0, 0.0, 0.0, 1.0),      # RGBA: 红色
    'elevation_marker_size': 12,
    'elevation_margin': 0.1,
    'print_interval': 5,
}


def _merge_params(defaults, params_dict):
    """合并用户参数与默认参数。"""
    merged = dict(defaults)
    if params_dict:
        merged.update(params_dict)
    return merged


# ============================================================
# 边界检查（图像专用，与 SPHC 的文字检查逻辑不同）
# ============================================================
def check_map_bounds(params, valid_gps_count, time_point_count):
    """
    MAP 边界/可行性检查。越界只警告，不阻断。
    返回 warnings 列表（无问题时为空）。
    """
    warns = []
    width = params['width']
    height = params['height']

    if width <= 0 or height <= 0:
        warns.append(f"MAP 画布尺寸非法: {width}x{height}")

    if valid_gps_count < 2:
        # 点数不足以成线：属于数据缺失，不在这里强制报错（由调用方走降级逻辑）
        warns.append(f"MAP 有效 GPS 点不足 2 个，无法绘制轨迹 (valid={valid_gps_count})")

    if time_point_count <= 0:
        warns.append("MAP 插值后无有效时间点")

    # 圆形背景内边距合理性
    pad = params.get('map_circle_padding_percent', 10)
    if pad < 0 or pad > 50:
        warns.append(f"MAP map_circle_padding_percent={pad} 超出合理范围 [0,50]，轨迹背景可能异常")

    return warns


def check_elevation_bounds(params, valid_point_count, time_point_count):
    """
    ELEVATION 边界/可行性检查。越界只警告，不阻断。
    """
    warns = []
    aspect = params.get('elevation_aspect_ratio', 8)
    ew = params.get('elevation_width', 800)

    if ew <= 0:
        warns.append(f"ELEVATION elevation_width 非法: {ew}")
    if aspect <= 0:
        warns.append(f"ELEVATION elevation_aspect_ratio 非法: {aspect}")

    if valid_point_count < 2:
        warns.append(f"ELEVATION 有效海拔/距离点不足 2 个，无法绘制曲线 (valid={valid_point_count})")

    if time_point_count <= 0:
        warns.append("ELEVATION 插值后无有效时间点")

    return warns


# ============================================================
# 辅助函数
# ============================================================
def _resolve_map_paths(output_dir, output_file):
    """MAP：解析帧目录与输出视频路径（参数 > 全局 > 默认）。"""
    global OUTPUT_DIR_MAP, OUTPUT_MOV_MAP
    if output_dir:
        frames_dir = output_dir
    elif OUTPUT_DIR_MAP:
        frames_dir = OUTPUT_DIR_MAP
    else:
        frames_dir = DEFAULT_FRAMES_DIR_MAP

    if output_file:
        video_file = output_file
    elif OUTPUT_MOV_MAP:
        video_file = OUTPUT_MOV_MAP
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = f"alpha_map_{ts}.mov"
    return frames_dir, video_file


def _resolve_elevation_paths(output_dir, output_file):
    """ELEVATION：解析帧目录与输出视频路径（参数 > 全局 > 默认）。"""
    global OUTPUT_DIR_ELEVATION, OUTPUT_MOV_ELEVATION
    if output_dir:
        frames_dir = output_dir
    elif OUTPUT_DIR_ELEVATION:
        frames_dir = OUTPUT_DIR_ELEVATION
    else:
        frames_dir = DEFAULT_FRAMES_DIR_ELEVATION

    if output_file:
        video_file = output_file
    elif OUTPUT_MOV_ELEVATION:
        video_file = OUTPUT_MOV_ELEVATION
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = f"alpha_elev_{ts}.mov"
    return frames_dir, video_file


def cleanup_frames_map(frames_dir=DEFAULT_FRAMES_DIR_MAP):
    """清理 MAP 帧目录。"""
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
        return True
    return False


def cleanup_frames_elevation(frames_dir=DEFAULT_FRAMES_DIR_ELEVATION):
    """清理 ELEVATION 帧目录。"""
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
        return True
    return False


# ============================================================
# FIT 数据加载与插值（自包含，从原 Alpha 复制，算法不变）
# ============================================================
def load_and_filter(fit_path, start_abs_time, end_abs_time, speed_threshold=3.0):
    """加载 FIT 文件并过滤到指定时间范围。"""
    try:
        from fitparse import FitFile
    except ImportError:
        raise ImportError("缺少依赖 fitparse，请运行: pip install fitparse")

    print("[Alpha_MAP/ELEVATION] [DEBUG] 正在加载FIT数据...")
    fit = FitFile(fit_path)
    recs = []
    for m in fit.get_messages('record'):
        vals = m.get_values()
        if 'timestamp' in vals:
            recs.append(vals)

    if not recs:
        raise RuntimeError("FIT文件中没有数据")

    offs, spd, pwr, hr, cad = [], [], [], [], []
    lats, lons, alts, dists = [], [], [], []
    for r in recs:
        ts = r['timestamp']
        if not (start_abs_time <= ts <= end_abs_time):
            continue
        offs.append((ts - start_abs_time).total_seconds())

        s = r.get('enhanced_speed') or r.get('speed', 0.0)
        raw_speed = float(s) * 3.6
        spd.append(0.0 if raw_speed < speed_threshold else raw_speed)

        pwr.append(r.get('power', np.nan))
        hr.append(r.get('heart_rate', np.nan))
        cad.append(r.get('cadence', np.nan))

        lat = r.get('position_lat')
        lon = r.get('position_long')
        if lat is not None and lon is not None:
            lats.append(lat * (180.0 / 2 ** 31))
            lons.append(lon * (180.0 / 2 ** 31))
        else:
            lats.append(np.nan)
            lons.append(np.nan)

        alt = r.get('enhanced_altitude') or r.get('altitude')
        alts.append(alt if alt is not None else np.nan)

        dist = r.get('distance')
        dists.append(dist if dist is not None else np.nan)

    if not offs:
        raise RuntimeError("指定时间范围内没有数据")

    zero_count = sum(1 for s in spd if s == 0.0)
    print(f"[Alpha_MAP/ELEVATION] [速度过滤] 将{zero_count}个低速点(<{speed_threshold}km/h)设为0")

    return {
        'offsets': np.array(offs, dtype=float),
        'speed': np.array(spd, dtype=float),
        'power': np.array(pwr, dtype=float),
        'hr': np.array(hr, dtype=float),
        'cad': np.array(cad, dtype=float),
        'lats': np.array(lats, dtype=float),
        'lons': np.array(lons, dtype=float),
        'alts': np.array(alts, dtype=float),
        'dists': np.array(dists, dtype=float),
    }


def interpolate(data, duration_sec, fps, speed_threshold=3.0):
    """按指定 fps 对原始数据进行线性插值。"""
    x = data['offsets']
    time_points = np.linspace(0, duration_sec, int(duration_sec * fps) + 1)

    is_stopped_original = data['speed'] < speed_threshold

    # 速度插值 + 停车段冻结
    interp_speed = np.interp(time_points, x, data['speed'])
    stop_flags = np.zeros_like(time_points, dtype=bool)
    for i, t in enumerate(time_points):
        idx = np.searchsorted(x, t, side='right') - 1
        if 0 <= idx < len(is_stopped_original):
            stop_flags[i] = is_stopped_original[idx]
    interp_speed_clean = interp_speed.copy()
    interp_speed_clean[stop_flags] = 0.0
    interp_speed_clean = np.where(interp_speed_clean < speed_threshold, 0.0, interp_speed_clean)

    def interp_arr(arr):
        # NaN->0 再转 int，避免直接 astype(int) 的未定义行为
        return np.nan_to_num(np.interp(time_points, x, arr), nan=0.0).astype(int)

    # GPS 插值（仅用有效点）
    lats = data['lats']; lons = data['lons']
    valid_gps = ~(np.isnan(lats) | np.isnan(lons))
    if np.any(valid_gps):
        interp_lats = np.interp(time_points, x[valid_gps], lats[valid_gps])
        interp_lons = np.interp(time_points, x[valid_gps], lons[valid_gps])
    else:
        interp_lats = np.full_like(time_points, np.nan)
        interp_lons = np.full_like(time_points, np.nan)

    # 海拔插值
    alts = data['alts']
    valid_alt = ~np.isnan(alts)
    if np.any(valid_alt):
        interp_alts = np.interp(time_points, x[valid_alt], alts[valid_alt])
    else:
        interp_alts = np.full_like(time_points, np.nan)

    # 距离插值
    dists = data['dists']
    valid_dist = ~np.isnan(dists)
    if np.any(valid_dist):
        interp_dists = np.interp(time_points, x[valid_dist], dists[valid_dist])
    else:
        interp_dists = np.full_like(time_points, np.nan)

    print(f"[Alpha_MAP/ELEVATION] [插值] 生成 {len(time_points)} 个时间点 (FPS={fps})")

    return {
        'speed': interp_speed_clean,
        'power': interp_arr(data['power']),
        'hr': interp_arr(data['hr']),
        'cad': interp_arr(data['cad']),
        'lats': interp_lats,
        'lons': interp_lons,
        'alats': interp_alts,
        'dists': interp_dists,
        'time_points': time_points,
    }


# ============================================================
# 坐标归一化（MAP：GPS -> 像素；ELEVATION：海拔/距离 -> 像素）
# ============================================================
def normalize_coordinates(lats, lons, params):
    """将经纬度归一化到 [0,1]，保持纵横比。返回像素坐标 x/y 及范围。"""
    valid = ~(np.isnan(lats) | np.isnan(lons))
    valid_lats = lats[valid]
    valid_lons = lons[valid]

    if len(valid_lats) < 2:
        return None, None, None, None, None, None

    min_lat, max_lat = valid_lats.min(), valid_lats.max()
    min_lon, max_lon = valid_lons.min(), valid_lons.max()
    lat_range = max_lat - min_lat if max_lat - min_lat != 0 else 0.0001
    lon_range = max_lon - min_lon if max_lon - min_lon != 0 else 0.0001

    width = params['width']
    height = params['height']
    video_aspect = width / height

    # 按纵横比调整边界
    if (lon_range / lat_range) > video_aspect:
        lat_margin = (lon_range / video_aspect - lat_range) / 2
        min_lat -= lat_margin; max_lat += lat_margin
    else:
        lon_margin = (lat_range * video_aspect - lon_range) / 2
        min_lon -= lon_margin; max_lon += lon_margin

    margin = params.get('map_margin', 0.1)
    lat_range_adj = (max_lat - min_lat) * (1 + 2 * margin)
    lon_range_adj = (max_lon - min_lon) * (1 + 2 * margin)
    c_lat = (min_lat + max_lat) / 2
    c_lon = (min_lon + max_lon) / 2
    min_lat, max_lat = c_lat - lat_range_adj / 2, c_lat + lat_range_adj / 2
    min_lon, max_lon = c_lon - lon_range_adj / 2, c_lon + lon_range_adj / 2

    flip = params.get('flip_map_vertical', False)

    def norm(lat, lon):
        if np.isnan(lat) or np.isnan(lon):
            return np.nan, np.nan
        nx = (lon - min_lon) / (max_lon - min_lon)
        ny = (lat - min_lat) / (max_lat - min_lat)
        ny = 1.0 - ny if flip else ny
        return nx, ny

    norm_x = np.array([norm(la, lo)[0] for la, lo in zip(lats, lons)])
    norm_y = np.array([norm(la, lo)[1] for la, lo in zip(lats, lons)])
    px = np.where(np.isnan(norm_x), np.nan, norm_x * width)
    py = np.where(np.isnan(norm_y), np.nan, norm_y * height)

    return px, py, min_lat, max_lat, min_lon, max_lon


def normalize_elevation_by_distance(alts, dists, params):
    """将海拔/距离归一化到 [0,1]。返回像素坐标 x/y 及范围。"""
    valid = ~(np.isnan(alts) | np.isnan(dists))
    valid_alts = alts[valid]
    valid_dists = dists[valid]

    if len(valid_alts) < 2:
        return None, None, None, None, None, None

    min_alt, max_alt = valid_alts.min(), valid_alts.max()
    min_dist, max_dist = valid_dists.min(), valid_dists.max()
    alt_range = max_alt - min_alt if max_alt - min_alt != 0 else 0.0001
    dist_range = max_dist - min_dist if max_dist - min_dist != 0 else 0.0001

    margin = params.get('elevation_margin', 0.1)
    min_alt -= alt_range * margin; max_alt += alt_range * margin
    min_dist -= dist_range * margin; max_dist += dist_range * margin

    ew = params['elevation_width']
    eh = int(ew / params.get('elevation_aspect_ratio', 8))

    def norm(alt, dist):
        if np.isnan(alt) or np.isnan(dist):
            return np.nan, np.nan
        return (dist - min_dist) / (max_dist - min_dist), \
               (alt - min_alt) / (max_alt - min_alt)

    norm_pts = [norm(a, d) for a, d in zip(alts, dists)]
    px = np.array([(np.nan if np.isnan(p[0]) else p[0] * ew) for p in norm_pts])
    py = np.array([(np.nan if np.isnan(p[1]) else p[1] * eh) for p in norm_pts])

    return px, py, min_alt, max_alt, min_dist, max_dist


# ============================================================
# 圆形背景（MAP）
# ============================================================
def create_perfect_circular_background(pixel_x, pixel_y, width, height, padding_percent=10):
    """计算轨迹的最小外接圆，并将轨迹缩放居中到画布。"""
    valid = [(x, y) for x, y in zip(pixel_x, pixel_y) if not (np.isnan(x) or np.isnan(y))]
    if not valid:
        return None, None, None, 1.0, (pixel_x, pixel_y)

    pts = np.array(valid, dtype=np.float32)
    try:
        import cv2
        (cx, cy), radius = cv2.minEnclosingCircle(pts)
    except ImportError:
        # 无 cv2 时的退化实现：用边界框中心与半径
        cx = (pts[:, 0].min() + pts[:, 0].max()) / 2
        cy = (pts[:, 1].min() + pts[:, 1].max()) / 2
        radius = max(pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()) / 2

    if radius == 0:
        radius = 1.0

    radius_padded = radius * (1 + padding_percent / 100.0)
    max_radius = min(width, height) / 2 * 0.9
    scale = 1.0
    if radius_padded > max_radius:
        scale = max_radius / radius_padded
        radius_padded = max_radius
    elif radius_padded < max_radius * 0.5:
        scale = (max_radius * 0.5) / radius_padded
        radius_padded = max_radius * 0.5

    tcx, tcy = width / 2, height / 2
    tx = [(np.nan if np.isnan(x) else (x - cx) * scale + tcx) for x in pixel_x]
    ty = [(np.nan if np.isnan(y) else (y - cy) * scale + tcy) for y in pixel_y]
    return tcx, tcy, radius_padded, scale, (tx, ty)


def calculate_moving_direction(pixel_x, pixel_y, idx, look_ahead=5):
    """计算移动方向角（弧度）。"""
    if idx < 1 or idx >= len(pixel_x) - 1:
        return 0.0
    s = max(0, idx - look_ahead)
    e = min(len(pixel_x) - 1, idx + look_ahead)
    wx = pixel_x[s:e + 1]; wy = pixel_y[s:e + 1]
    mask = [not (np.isnan(x) or np.isnan(y)) for x, y in zip(wx, wy)]
    vx = [wx[i] for i, m in enumerate(mask) if m]
    vy = [wy[i] for i, m in enumerate(mask) if m]
    if len(vx) < 2:
        return 0.0
    dx = vx[-1] - vx[0]; dy = vy[-1] - vy[0]
    if dx == 0 and dy == 0:
        return 0.0
    return math.atan2(dy, dx)


# ============================================================
# 渲染：MAP
# ============================================================
def render_map_frames(data_intp, params, frames_dir):
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.startswith("frame_map_"):
            os.remove(os.path.join(frames_dir, f))

    width = params['width']
    height = params['height']
    print_interval = params['print_interval']

    # 归一化坐标
    px, py, *_ = normalize_coordinates(data_intp['lats'], data_intp['lons'], params)
    if px is None:
        print("[Alpha_MAP] ⚠️ 无有效 GPS 数据，无法渲染地图帧")
        return 0

    # 圆形背景变换
    tcx, tcy, radius, _, transformed = create_perfect_circular_background(
        px.tolist(), py.tolist(), width, height, params['map_circle_padding_percent'])
    if tcx is None:
        print("[Alpha_MAP] ⚠️ 无法计算圆形背景")
        return 0
    px_t, py_t = transformed

    frame_count = len(data_intp['lats'])
    plt.ioff()
    fig, ax = plt.subplots(figsize=(width / 100.0, height / 100.0), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, width); ax.set_ylim(0, height)
    ax.set_aspect('equal'); ax.axis('off')
    ax.set_facecolor(params['map_background_color'])

    ax.add_patch(plt.Circle(
        (tcx, tcy), radius,
        facecolor=params['map_circle_bg_color'], edgecolor='none', zorder=0))

    valid = [(x, y) for x, y in zip(px_t, py_t) if not (np.isnan(x) or np.isnan(y))]
    if valid:
        fx, fy = zip(*valid)
        ax.plot(fx, fy, color=params['map_line_color'],
                linewidth=params['map_line_width'], alpha=1.0, zorder=1)

    completed, = ax.plot([], [], color=params['map_completed_color'],
                         linewidth=params['map_line_width'], zorder=2)

    if params['map_marker_type'] == 'arrow':
        marker = ax.quiver([], [], [], [], color=params['map_marker_color'],
                           scale=1, scale_units='xy', angles='xy',
                           width=params['map_marker_size'] / 100, zorder=3)
    else:
        marker = ax.scatter([], [], s=params['map_marker_size'] ** 2,
                            c=[params['map_marker_color']], marker='^',
                            edgecolors='white', linewidths=1, zorder=3)

    start_time = time.time(); last_print = start_time
    completed_x, completed_y = [], []
    angle_history = []

    for idx in range(frame_count):
        now = time.time()
        if now - last_print >= print_interval:
            elapsed = now - start_time; processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Alpha_Map] [渲染] {processed}/{frame_count}帧 | {elapsed:.1f}s | "
                  f"剩余:{remaining:.1f}s | {fps_actual:.1f}帧/s")
            last_print = now

        cx, cy = px_t[idx], py_t[idx]
        if not (np.isnan(cx) or np.isnan(cy)):
            completed_x.append(cx); completed_y.append(cy)
            completed.set_data(completed_x, completed_y)
            marker.set_offsets([(cx, cy)])

            if idx > 0 and idx < frame_count - 1:
                rad = calculate_moving_direction(px_t, py_t, idx, look_ahead=3)
                if rad != 0:
                    if params['map_marker_type'] == 'arrow':
                        al = params['map_marker_size']
                        marker.set_UVC(al * math.cos(rad), al * math.sin(rad))
                    else:
                        deg = math.degrees(rad) - 90
                        angle_history.append(deg)
                        if len(angle_history) > 5:
                            angle_history.pop(0)
                        smooth = np.mean(angle_history) if len(angle_history) > 1 else deg
                        marker.set_transform(
                            ax.transData + plt.matplotlib.transforms.Affine2D().rotate_deg(smooth))

        fig.savefig(os.path.join(frames_dir, f"frame_map_{idx:06d}.png"),
                    dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    print(f"[Alpha_Map] [渲染] 完成，共 {frame_count} 帧")
    return frame_count


# ============================================================
# 渲染：ELEVATION
# ============================================================
def render_elevation_frames(data_intp, params, frames_dir, dists):
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.startswith("frame_elevation_"):
            os.remove(os.path.join(frames_dir, f))

    ew = params['elevation_width']
    eh = int(ew / params.get('elevation_aspect_ratio', 8))
    print_interval = params['print_interval']

    px, py, *_ = normalize_elevation_by_distance(data_intp['alats'], dists, params)
    if px is None:
        print("[Alpha_ELEVATION] ⚠️ 无有效海拔/距离数据，无法渲染海拔帧")
        return 0

    frame_count = len(data_intp['alats'])
    plt.ioff()
    fig, ax = plt.subplots(figsize=(ew / 100.0, eh / 100.0), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, ew); ax.set_ylim(0, eh)
    ax.set_aspect('equal'); ax.axis('off')
    ax.set_facecolor(params['elevation_background_color'])

    valid = [(x, y) for x, y in zip(px, py) if not (np.isnan(x) or np.isnan(y))]
    if valid:
        fx, fy = zip(*valid)
        ax.plot(fx, fy, color=params['elevation_background_color'],
                linewidth=params['elevation_line_width'], alpha=0.5, zorder=1)

    completed, = ax.plot([], [], color=params['elevation_completed_color'],
                         linewidth=params['elevation_line_width'], zorder=2)
    marker = ax.scatter([], [], s=params['elevation_marker_size'] ** 2,
                        c=[params['elevation_marker_color']], marker='o',
                        edgecolors='white', linewidths=1, zorder=3)

    start_time = time.time(); last_print = start_time
    completed_x, completed_y = [], []
    drawn_idx = 0

    # 预计算有效点索引（按距离递增）
    valid_indices = [i for i in range(frame_count)
                    if i < len(dists) and not np.isnan(dists[i])
                    and not np.isnan(px[i]) and not np.isnan(py[i])]

    for idx in range(frame_count):
        now = time.time()
        if now - last_print >= print_interval:
            elapsed = now - start_time; processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Alpha_Elev] [渲染] {processed}/{frame_count}帧 | {elapsed:.1f}s | "
                  f"剩余:{remaining:.1f}s |{fps_actual:.1f}帧/s")
            last_print = now

        cur_dist = dists[idx] if idx < len(dists) else np.nan
        if not np.isnan(cur_dist):
            while drawn_idx < len(valid_indices):
                pi = valid_indices[drawn_idx]
                if pi >= len(dists) or np.isnan(dists[pi]) or dists[pi] > cur_dist:
                    break
                completed_x.append(px[pi]); completed_y.append(py[pi])
                drawn_idx += 1
            completed.set_data(completed_x, completed_y)

            if valid_indices and drawn_idx > 0:
                li = valid_indices[drawn_idx - 1]
                if not (np.isnan(px[li]) or np.isnan(py[li])):
                    marker.set_offsets([(px[li], py[li])])

        fig.savefig(os.path.join(frames_dir, f"frame_elevation_{idx:06d}.png"),
                    dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    print(f"[Alpha_Elev] [渲染] 完成，共 {frame_count} 帧")
    return frame_count


# ============================================================
# FFmpeg 合成（通用）
# ============================================================
def assemble_mov(frames_dir, output_file, frame_count, fps, width, height, prefix="frame_"):
    """调用 ffmpeg 将帧序列合成为视频。"""
    global FFMPEG_PATH

    if not os.path.exists(frames_dir):
        print(f"[Alpha_MAP/ELEVATION] [错误] 帧目录不存在: {frames_dir}")
        return False

    print(f"[Alpha_MAP/ELEVATION] [合成] {output_file} (FPS={fps}, {width}x{height})")
    input_pattern = os.path.join(frames_dir, f"{prefix}%06d.png")
    vf_filter = f"scale={width}:{height},setsar=1"

    cmd = [
        FFMPEG_PATH, "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", input_pattern,
        "-vf", f"{vf_filter},format=rgba",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file,
    ]

    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600 * 24,
            creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0:
            print(f"[Alpha_MAP/ELEVATION] [合成] 成功: {output_file}")
            return True
        else:
            print(f"[Alpha_MAP/ELEVATION] [警告] ffmpeg 返回码 {result.returncode}: {result.stderr[:500]}")
            return False
    except Exception as e:
        print(f"[Alpha_MAP/ELEVATION] [错误] ffmpeg 执行异常: {e}")
        return False


# ============================================================
# 单个模块执行：生成 frames + 合成（不做清理，清理统一在最后）
# ============================================================
def _execute_map(fit_path, lap_start, lap_end, duration, params, fps,
                 output_dir, output_file):
    """执行 MAP：加载→插值→渲染→合成。返回 (success, video_path, frames_dir, warnings)。"""
    warnings = []
    params_full = _merge_params(DEFAULT_PARAMS_MAP, params)
    frames_dir, video_file = _resolve_map_paths(output_dir, output_file)

    if os.path.exists(frames_dir) and os.listdir(frames_dir):
        raise FileExistsError(
            f"[Alpha_MAP] 帧目录已存在且非空: {frames_dir}\n"
            f"请先删除或调用 Alpha_map_elevation.cleanup_frames_map('{frames_dir}')")

    # speed_threshold 属于内部停车判定逻辑，固定 3.0，不从外部 params 取
    raw = load_and_filter(fit_path, lap_start, lap_end)
    data_intp = interpolate(raw, duration, fps)

    # 边界检查（只警告不阻断）
    warns = check_map_bounds(params_full,
                             int(np.sum(~np.isnan(data_intp['lats']))),
                             len(data_intp['lats']))
    for w in warns:
        print(f"[Alpha_MAP] ⚠️ 警告: {w}")
    warnings.extend(warns)

    # 数据缺失降级：GPS 有效点 < 2 → 跳过 MAP，不报错
    valid_gps = int(np.sum(~np.isnan(data_intp['lats'])))
    if valid_gps < 2:
        print("[Alpha_MAP] ℹ️ GPS 数据不足，跳过 MAP 视频生成")
        return False, None, frames_dir, warnings

    frame_count = render_map_frames(data_intp, params_full, frames_dir)
    if frame_count == 0:
        print("[Alpha_MAP] ❌ 未生成任何帧")
        return False, None, frames_dir, warnings

    success = assemble_mov(frames_dir, video_file, frame_count, fps,
                           params_full['width'], params_full['height'], "frame_map_")
    return success and os.path.exists(video_file), \
           video_file if success else None, frames_dir, warnings


def _execute_elevation(fit_path, lap_start, lap_end, duration, params, fps,
                        output_dir, output_file):
    """执行 ELEVATION：加载→插值→渲染→合成。"""
    warnings = []
    params_full = _merge_params(DEFAULT_PARAMS_ELEVATION, params)
    # elevation_height 由 width / aspect_ratio 决定
    params_full.setdefault('elevation_height',
                           int(params_full['elevation_width'] / params_full['elevation_aspect_ratio']))
    frames_dir, video_file = _resolve_elevation_paths(output_dir, output_file)

    if os.path.exists(frames_dir) and os.listdir(frames_dir):
        raise FileExistsError(
            f"[Alpha_ELEVATION] 帧目录已存在且非空: {frames_dir}\n"
            f"请先删除或调用 Alpha_map_elevation.cleanup_frames_elevation('{frames_dir}')")

    # speed_threshold 属于内部停车判定逻辑，固定 3.0，不从外部 params 取
    raw = load_and_filter(fit_path, lap_start, lap_end)
    data_intp = interpolate(raw, duration, fps)

    warns = check_elevation_bounds(params_full,
                                    int(np.sum(~np.isnan(data_intp['alats']))),
                                    len(data_intp['alats']))
    for w in warns:
        print(f"[Alpha_ELEVATION] ⚠️ 警告: {w}")
    warnings.extend(warns)

    # 降级：海拔/距离有效点 < 2 → 跳过
    valid_alt = int(np.sum(~np.isnan(data_intp['alats'])))
    valid_dist = int(np.sum(~np.isnan(data_intp['dists'])))
    if valid_alt < 2 or valid_dist < 2:
        print("[Alpha_ELEVATION] ℹ️ 海拔/距离数据不足，跳过 ELEVATION 视频生成")
        return False, None, frames_dir, warnings

    frame_count = render_elevation_frames(data_intp, params_full, frames_dir, data_intp['dists'])
    if frame_count == 0:
        print("[Alpha_ELEVATION] ❌ 未生成任何帧")
        return False, None, frames_dir, warnings

    ew = params_full['elevation_width']
    eh = params_full['elevation_height']
    success = assemble_mov(frames_dir, video_file, frame_count, fps, ew, eh, "frame_elevation_")
    return success and os.path.exists(video_file), \
           video_file if success else None, frames_dir, warnings


# ============================================================
# 对外 API：便捷入口（一次性调用两个，强制共用时间轴，串行 + 统一清理）
# ============================================================
def generate_map_elevation_video(
    fit_path,
    lap_start,
    lap_end,
    generate_map=True,
    generate_elevation=True,
    map_fps=None,
    elevation_fps=None,
    cleanup=False,                # 关键：False = 不在视频之间清理，最后统一清理
    map_params_dict=None,
    elevation_params_dict=None,
    ffmpeg_path=None,
    map_output_dir=None,
    map_output_file=None,
    elevation_output_dir=None,
    elevation_output_file=None,
):
    """
    一次性生成 MAP + ELEVATION 视频。

    两个模块强制共用同一时间轴 (lap_start, lap_end)。
    执行顺序：MAP(生成frames+合成) → ELEVATION(生成frames+合成) → 统一清理。

    参数:
        cleanup=True  : 两个都完成后统一清理两个帧目录（CLI 用）
        cleanup=False : 保留帧目录，由调用层统一清理（API 默认，节省等待时间）

    返回:
        dict: {
            'map_video', 'elevation_video',
            'frames_dir_map', 'frames_dir_elevation',
            'warnings': [...],
            'cleaned': True/False,
        }
    """
    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path

    if map_fps is None:
        map_fps = MAP_DEFAULT_FPS
    if elevation_fps is None:
        elevation_fps = ELEVATION_DEFAULT_FPS

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长: {duration}秒")

    result = {
        'map_video': None,
        'elevation_video': None,
        'frames_dir_map': None,
        'frames_dir_elevation': None,
        'warnings': [],
        'cleaned': False,
    }

    print("\n=== [Alpha_MAP/ELEVATION] 配置参数 ===")
    print(f"FIT文件: {fit_path}")
    print(f"时间范围: {lap_start} → {lap_end} (时长 {duration:.1f}s)")
    print(f"MAP FPS: {map_fps}, ELEVATION FPS: {elevation_fps}")
    print(f"自动清理: {'是' if cleanup else '否'}")
    print("===========================\n")

    # -------- 阶段 1：MAP（cleanup=False 保留帧）--------
    if generate_map:
        print("--- [Alpha_MAP] 开始 ---")
        try:
            ok, video, fdir, warns = _execute_map(
                fit_path, lap_start, lap_end, duration,
                map_params_dict, map_fps, map_output_dir, map_output_file)
            result['map_video'] = video
            result['frames_dir_map'] = fdir
            result['warnings'].extend(warns)
            print(f"[Alpha_MAP] {'✅ 完成: ' + video if ok else '❌ 未生成'}")
        except Exception as e:
            print(f"[Alpha_MAP] ❌ 错误: {e}")
            result['warnings'].append(f"MAP 执行异常: {e}")
    else:
        print("--- [Alpha_MAP] 跳过（generate_map=False）---")

    # -------- 阶段 2：ELEVATION（cleanup=False 保留帧）--------
    if generate_elevation:
        print("")
        print("--- [Alpha_ELEVATION] 开始 ---")
        try:
            ok, video, fdir, warns = _execute_elevation(
                fit_path, lap_start, lap_end, duration,
                elevation_params_dict, elevation_fps,
                elevation_output_dir, elevation_output_file)
            result['elevation_video'] = video
            result['frames_dir_elevation'] = fdir
            result['warnings'].extend(warns)
            print(f"[Alpha_ELEVATION] {'✅ 完成: ' + video if ok else '❌ 未生成'}")
        except Exception as e:
            print(f"[Alpha_ELEVATION] ❌ 错误: {e}")
            result['warnings'].append(f"ELEVATION 执行异常: {e}")
    else:
        print("--- [Alpha_ELEVATION] 跳过（generate_elevation=False）---")

    # -------- 阶段 3：最后统一清理 --------
    if cleanup:
        cleanup_start = time.time()
        if result.get('frames_dir_map') and os.path.exists(result['frames_dir_map']):
            cleanup_frames_map(result['frames_dir_map'])
        if result.get('frames_dir_elevation') and os.path.exists(result['frames_dir_elevation']):
            cleanup_frames_elevation(result['frames_dir_elevation'])
        result['cleaned'] = True
        print(f"[Alpha_MAP/ELEVATION] 🧹 已统一清理中间帧目录 (用时 {time.time()-cleanup_start:.2f}s)")

    return result


# ============================================================
# 对外 API：单独调用某一模块
# ============================================================
def generate_map_video(fit_path, lap_start, lap_end,
                       generate_map=True, fps=None, cleanup=False,
                       params_dict=None, ffmpeg_path=None,
                       output_dir=None, output_file=None):
    """仅生成 MAP 视频。共用同一时间轴语义（单个模块）。"""
    if not generate_map:
        return {'map_video': None, 'frames_dir_map': None, 'warnings': []}
    result = generate_map_elevation_video(
        fit_path, lap_start, lap_end,
        generate_map=True, generate_elevation=False,
        map_fps=fps, cleanup=cleanup,
        map_params_dict=params_dict,
        map_output_dir=output_dir, map_output_file=output_file,
        ffmpeg_path=ffmpeg_path)
    return {
        'map_video': result['map_video'],
        'frames_dir_map': result['frames_dir_map'],
        'warnings': result['warnings'],
    }


def generate_elevation_video(fit_path, lap_start, lap_end,
                             generate_elevation=True, fps=None, cleanup=False,
                             params_dict=None, ffmpeg_path=None,
                             output_dir=None, output_file=None):
    """仅生成 ELEVATION 视频。"""
    if not generate_elevation:
        return {'elevation_video': None, 'frames_dir_elevation': None, 'warnings': []}
    result = generate_map_elevation_video(
        fit_path, lap_start, lap_end,
        generate_map=False, generate_elevation=True,
        elevation_fps=fps, cleanup=cleanup,
        elevation_params_dict=params_dict,
        elevation_output_dir=output_dir, elevation_output_file=output_file,
        ffmpeg_path=ffmpeg_path)
    return {
        'elevation_video': result['elevation_video'],
        'frames_dir_elevation': result['frames_dir_elevation'],
        'warnings': result['warnings'],
    }


# ============================================================
# CLI 交互逻辑（仅在 __main__ 中执行）
#   参考 SPHC：选文件 -> 选 Lap（一次）-> 输入参数 -> 串行生成 -> 报告 -> 清理
# ============================================================
def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(os.path.join(p, f) for f in os.listdir(p)
                         if f.lower().endswith(".fit"))
    return sorted(set(files))


def select_lap(fit_path):
    """选择单个 Lap（起止时间）。MAP/ELEVATION 强制共用该时间轴。"""
    try:
        from fitparse import FitFile
    except ImportError:
        print("❌ 缺少依赖 fitparse，请运行: pip install fitparse")
        return None, None

    fit = FitFile(fit_path)
    laps = []
    for lap in fit.get_messages("lap"):
        v = lap.get_values()
        st = v.get("start_time")
        et = st + datetime.timedelta(seconds=v.get("total_elapsed_time", 0))
        if st and et > st:
            laps.append((st, et))

    if not laps:
        print("⚠️ 无有效 Lap")
        return None, None

    for i, (st, et) in enumerate(laps, start=1):
        print(f"[{i}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")

    choice = input("选择单个 Lap (q退出): ").strip().lower()
    if choice == "q":
        return None, None
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(laps)):
            raise ValueError
    except ValueError:
        print("❌ 无效选择")
        return select_lap(fit_path)

    return laps[idx]


def input_int_or_quit(prompt, default, allow_zero=True):
    """
    读取一个整数输入，支持：
      - 回车         : 使用 default
      - q / Q        : 抛出 SystemExit，随时退出整个 CLI
      - 0 (仅 allow_zero=True): 返回 0，表示"跳过该模块"
    其他非法输入视为回车，使用 default。
    """
    raw = input(prompt).strip().lower()
    if raw == "q":
        print("👋 已取消")
        raise SystemExit(0)
    if raw == "":
        return default
    if allow_zero and raw == "0":
        return 0
    try:
        return int(raw)
    except ValueError:
        print(f"⚠️ 输入无效，使用默认值 {default}")
        return default


def main():
    """CLI 入口：交互选择文件/Lap，两个模块共用时间轴，串行生成后统一清理。"""
    print("=== Alpha_MAP / Alpha_ELEVATION 视频生成 ===\n")

    # 1. 选择 FIT 文件（q 退出）
    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 FIT 文件（扫描了 . / ./data / ./fit / ./activities）")
        return
    for i, f in enumerate(fits, start=1):
        print(f"[{i}] {f}")
    choice = input("选择文件 (q退出): ").strip().lower()
    if choice == "q":
        print("👋 已取消")
        return
    try:
        file_no = int(choice)
        if not (1 <= file_no <= len(fits)):
            raise ValueError
    except ValueError:
        print("❌ 无效选择")
        return
    fit_path = fits[file_no - 1]

    # 2. 选择单个 Lap（MAP 与 ELEVATION 强制共用此时间轴，q 退出）
    lap = select_lap(fit_path)
    if lap[0] is None:
        return
    lap_start, lap_end = lap

    # 3. 帧率输入：直接问帧率，输入 0 = 跳过该模块，回车 = 使用默认值，q = 退出
    map_fps = input_int_or_quit(
        f"MAP 帧率 (0=跳过, 回车默认{MAP_DEFAULT_FPS}, q退出): ",
        default=MAP_DEFAULT_FPS)
    elev_fps = input_int_or_quit(
        f"ELEVATION 帧率 (0=跳过, 回车默认{ELEVATION_DEFAULT_FPS}, q退出): ",
        default=ELEVATION_DEFAULT_FPS)

    generate_map = map_fps > 0
    generate_elevation = elev_fps > 0
    if not generate_map and not generate_elevation:
        print("ℹ️ 两个模块的帧率都为 0，无需生成任何视频")
        return

    # 4. CLI 模式：帧目录若存在则覆盖清理（先清理再调，避免 FileExistsError）
    for d in (DEFAULT_FRAMES_DIR_MAP, DEFAULT_FRAMES_DIR_ELEVATION):
        if os.path.exists(d):
            print(f"[Alpha_MAP/ELEVATION] 检测到已存在帧目录 {d}，CLI 模式将覆盖清理")
            if "MAP" in d:
                cleanup_frames_map(d)
            else:
                cleanup_frames_elevation(d)

    # 5. 执行（CLI 模式 cleanup=True，全部完成后统一清理）
    #    跳过的模块 fps 传 None（内部使用默认值），避免传 0 导致无帧
    total_start = time.time()
    try:
        result = generate_map_elevation_video(
            fit_path, lap_start, lap_end,
            generate_map=generate_map, generate_elevation=generate_elevation,
            map_fps=map_fps if generate_map else None,
            elevation_fps=elev_fps if generate_elevation else None,
            cleanup=True,
        )
    except Exception as e:
        print(f"[Alpha_MAP/ELEVATION] ❌ 运行失败: {e}")
        return
    total_elapsed = time.time() - total_start

    # 6. 报告结果（带模块前缀）
    minutes, seconds = divmod(int(total_elapsed), 60)
    print("")
    if result.get('map_video'):
        print(f"[Alpha_MAP] ✅ 视频生成完成: {result['map_video']}")
    if result.get('elevation_video'):
        print(f"[Alpha_ELEVATION] ✅ 视频生成完成: {result['elevation_video']}")
    if not result.get('map_video') and not result.get('elevation_video'):
        print("\n[Alpha_MAP/ELEVATION] ❌ 未生成任何视频（可能数据缺失）")
    print(f"[Alpha_MAP/ELEVATION] ⏱️ 总用时: {minutes}分{seconds}秒 ({total_elapsed:.2f}s)")

    # 清理计时（cleanup=True 时已在函数内统一清理并打印，此处无兜底需要）
    for w in result.get('warnings', []):
        print(f"[Alpha_MAP/ELEVATION] ⚠️ {w}")


if __name__ == "__main__":
    main()
