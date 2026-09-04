# -*- coding: utf-8 -*-
"""
Delta_elevation.py
==================
Delta 模块：海拔 / 坡度 / 累计爬升 HUD 视频（1Hz FIT · 长坡修复版）

与 Alpha/Beta/Gamma 一致的调用接口：
  generate_delta_elevation_video(fit_path, lap_start, lap_end, ...)
"""

import os
import sys
import shutil
import subprocess
import time
import math
from datetime import datetime, timedelta

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# 全局可配置变量（兼容 exe / GUI 打包场景）
# ============================================================
FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR_DELTA = None
OUTPUT_MOV_DELTA = None

DELTA_DEFAULT_FPS = 5
DEFAULT_FRAMES_DIR = "frames_Delta"

# ============================================================
# 默认参数（可通过 params_dict 覆盖）
# ============================================================
DEFAULT_PARAMS = {
    # 画布
    'width': 720,
    'height': 80,
    'font_size': 28,
    'padding': 12,
    # 平滑
    'elev_weak_smooth_sec': 2.0,
    'grad_strong_smooth_sec': 3.0,
    'gain_smooth_sec': 7.0,
    'grad_compensation_sec': 1.5,
    # 显示
    'grad_display_decimals': 1,
    'grad_min_speed_kmh': 3.0,
    'gain_min_height_m': 5.0,
    'gain_min_dist_m': 50.0,
    'print_interval': 5.0,
    # 字体
    'font_path': None,
}


def _merge_params(params_dict):
    merged = dict(DEFAULT_PARAMS)
    if params_dict:
        merged.update(params_dict)
    return merged


def _resolve_paths(output_dir, output_file):
    global OUTPUT_DIR_DELTA, OUTPUT_MOV_DELTA

    if output_dir:
        frames_dir = output_dir
    elif OUTPUT_DIR_DELTA:
        frames_dir = OUTPUT_DIR_DELTA
    else:
        frames_dir = DEFAULT_FRAMES_DIR

    if output_file:
        video_file = output_file
    elif OUTPUT_MOV_DELTA:
        video_file = OUTPUT_MOV_DELTA
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = f"delta_elevation_{timestamp}.mov"

    return frames_dir, video_file


def cleanup_frames(frames_dir=DEFAULT_FRAMES_DIR):
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
        return True
    return False


# ============================================================
# 字体加载
# ============================================================
def _load_font(font_path, size):
    try:
        if font_path and os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
        for name in ("arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# ============================================================
# 1) 加载原始 1Hz FIT 数据
# ============================================================
def _load_fit_data(fit_path, lap_start, lap_end):
    print("[Delta] [步骤1/6] 加载 FIT 数据（原始 1Hz record）...")
    try:
        from fitparse import FitFile
    except ImportError:
        raise ImportError("缺少依赖 fitparse，请运行: pip install fitparse")

    fit = FitFile(fit_path)
    offsets, alts, dists, speeds = [], [], [], []

    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None or not (lap_start <= ts <= lap_end):
            continue
        offsets.append((ts - lap_start).total_seconds())
        alt = vals.get('enhanced_altitude') or vals.get('altitude')
        alts.append(alt if alt is not None else np.nan)
        dist = vals.get('distance')
        dists.append(dist if dist is not None else np.nan)
        s = vals.get('enhanced_speed', vals.get('speed', None))
        speeds.append(float(s) * 3.6 if s is not None else np.nan)

    if not offsets:
        raise RuntimeError("指定时间范围内无有效数据")

    print(f"[Delta] 有效记录数: {len(offsets)}")
    print(f"[Delta] 海拔有效: {sum(~np.isnan(alts))}/{len(alts)}")

    return {
        'offsets': np.array(offsets, dtype=float),
        'alts': np.array(alts, dtype=float),
        'dists': np.array(dists, dtype=float),
        'speeds': np.array(speeds, dtype=float),
    }


# ============================================================
# 2) 1Hz 网格平滑
# ============================================================
def _apply_smooth_1hz(values, dt_sec, window_sec, polyorder=2):
    window = int(round(window_sec / dt_sec))
    if window % 2 == 0:
        window += 1
    if window < 5 or len(values) < window:
        return values.copy()

    v = values.copy()
    valid = ~np.isnan(v)
    if not np.all(valid):
        f = interp1d(np.where(valid)[0], v[valid], kind='linear', fill_value="extrapolate")
        v[~valid] = f(np.where(~valid)[0])

    return savgol_filter(v, window, polyorder)


# ============================================================
# 3) 坡度计算（速度法）
# ============================================================
def _compute_gradient_1hz(alts_smooth, speeds, dt, min_speed_kmh, compensation_sec):
    n = len(alts_smooth)
    gradient = np.full(n, np.nan)
    dz = np.diff(alts_smooth)

    v_avg = (speeds[:-1] + speeds[1:]) / 2
    v_ms = v_avg / 3.6
    denom = v_ms * dt
    with np.errstate(divide='ignore', invalid='ignore'):
        g = dz / denom * 100.0

    g = np.where(np.abs(g) > 60, np.nan, g)
    valid = (v_ms >= min_speed_kmh / 3.6) & (~np.isnan(v_ms)) & (~np.isnan(g))
    g_out = np.full_like(g, np.nan)
    g_out[valid] = g[valid]
    gradient[1:] = g_out

    shift = int(round(compensation_sec / dt))
    if shift > 0 and shift < n:
        gradient_shifted = np.full(n, np.nan)
        gradient_shifted[:-shift] = gradient[shift:]
        gradient = gradient_shifted
    return gradient


# ============================================================
# 4) 累计爬升（长坡修复版）
# ============================================================
def _compute_cumulative_gain(alts_smooth, dists, min_height_m, min_dist_m):
    n = len(alts_smooth)
    if n < 2:
        return np.zeros(n)

    dh = np.diff(alts_smooth)
    if len(dh) >= 3:
        dh = np.convolve(dh, np.ones(3) / 3, mode='same')

    gain = np.cumsum(np.maximum(0.0, dh))
    gain = np.concatenate(([0.0], gain))

    raw_alt_diff = alts_smooth[-1] - alts_smooth[0] if n > 1 else 0.0
    total_rise = gain[-1]
    print(f"[Delta] 原始海拔总差: {raw_alt_diff:.1f}m | 算法累计爬升: {total_rise:.1f}m")

    total_dist = 0.0
    if n > 1 and not np.isnan(dists[0]) and not np.isnan(dists[-1]):
        total_dist = dists[-1] - dists[0]
    if total_dist < 0:
        total_dist = 0.0

    if total_rise < min_height_m or total_dist < min_dist_m:
        print(f"  [Delta] 有效性过滤: 爬升{total_rise:.1f}m < {min_height_m}m 或 距离{total_dist:.1f}m < {min_dist_m}m，累计置0")
        return np.zeros(n)
    return gain


# ============================================================
# 5) 坡度显示裁剪
# ============================================================
def _clip_gradient_display(gradients, lo=0.1, hi=40.0):
    out = gradients.copy()
    out[np.abs(out) < lo] = 0.0
    out[np.abs(out) > hi] = np.nan
    return out


# ============================================================
# 6) 插值到 FPS
# ============================================================
def _interpolate_to_fps(arrays_dict, duration_sec, fps):
    time_points = np.linspace(0, duration_sec, int(duration_sec * fps) + 1)
    x = arrays_dict['offsets']

    def interp(arr, fill=np.nan):
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full_like(time_points, np.nan)
        f = interp1d(x[valid], arr[valid], kind='linear', fill_value="extrapolate")
        return f(time_points)

    out = {'time': time_points}
    for k, v in arrays_dict.items():
        if k == 'offsets':
            continue
        out[k] = interp(v)
    return out


# ============================================================
# 格式化 / 渲染 / 合成
# ============================================================
def _format_elevation(val):
    return "Elev:    ---- m" if np.isnan(val) else f"Elev: {val:>6.1f} m"

def _format_gradient(val, decimals=1):
    if np.isnan(val):
        return "Grade:     -- %"
    grad_val = round(val, decimals)
    sign = "+" if grad_val >= 0 else "-"
    if decimals == 0:
        return f"Grade: {sign}{abs(int(grad_val)):>3d}%"
    else:
        return f"Grade: {sign}{abs(grad_val):>4.{decimals}f}%"

def _format_gain(val):
    return "Gain:    ---- m" if np.isnan(val) else f"Gain: {val:>6.1f} m"


def _render_delta_frames(alts_weak, gradients, gains, params, frames_dir):
    print(f"[Delta] [步骤5/6] 渲染帧...")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frames_dir, f))

    width = params['width']
    height = params['height']
    font_size = params['font_size']
    padding = params['padding']
    print_interval = params['print_interval']
    decimals = params['grad_display_decimals']

    font = _load_font(params.get('font_path'), font_size)
    n = len(alts_weak)

    dummy_img = Image.new('RGBA', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    sample_elev = _format_elevation(9999.9)
    sample_grad = _format_gradient(99.9, decimals)
    sample_gain = _format_gain(9999.9)

    w_elev = dummy_draw.textbbox((0, 0), sample_elev, font=font)[2]
    w_grad = dummy_draw.textbbox((0, 0), sample_grad, font=font)[2]
    w_gain = dummy_draw.textbbox((0, 0), sample_gain, font=font)[2]

    gap = 40
    total_w = w_elev + gap + w_grad + gap + w_gain
    if total_w > width - 2 * padding:
        print(f"  [Delta] ⚠️ 文本总宽 {total_w}px 超过画布 {width}px")

    start_x = (width - total_w) // 2
    text_height = dummy_draw.textbbox((0, 0), "Ay", font=font)[3]
    y = (height - text_height) // 2

    start_time = time.time()
    last_print = start_time

    for idx in range(n):
        current = time.time()
        if current - last_print >= print_interval:
            elapsed = current - start_time
            processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (n - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Delta] {processed}/{n}帧 | 已用:{elapsed:.1f}s | 剩余:{remaining:.1f}s | {fps_actual:.1f}帧/s")
            last_print = current

        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        x = start_x
        draw.text((x, y), _format_elevation(alts_weak[idx]), font=font, fill=(255, 255, 255))
        x += w_elev + gap
        draw.text((x, y), _format_gradient(gradients[idx], decimals), font=font, fill=(255, 255, 255))
        x += w_grad + gap
        draw.text((x, y), _format_gain(gains[idx]), font=font, fill=(255, 255, 255))

        frame_path = os.path.join(frames_dir, f"frame_{idx:06d}.png")
        img.save(frame_path, 'PNG')

    print(f"[Delta] 渲染完成，共 {n} 帧")
    return n


def _assemble_delta_mov(frames_dir, output_file, frame_count, fps, width, height, prefix="frame_"):
    global FFMPEG_PATH
    print(f"[Delta] [步骤6/6] 合成视频: {output_file}")
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
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            print(f"[Delta] ✅ 合成成功: {output_file}")
            return True
        else:
            print(f"[Delta] ❌ ffmpeg 失败: {result.stderr[:500]}")
            return False
    except Exception as e:
        print(f"[Delta] ❌ ffmpeg 异常: {e}")
        return False


# ============================================================
# 主入口：供 Call 代码调用
# ============================================================
def generate_delta_elevation_video(
    fit_path,
    lap_start,
    lap_end,
    generate_delta=True,
    fps=None,
    cleanup=False,
    params_dict=None,
    ffmpeg_path=None,
    output_dir=None,
    output_file=None,
):
    """
    生成 Delta 海拔/坡度/爬升 HUD 视频。

    参数:
        fit_path        : FIT 文件路径
        lap_start       : Lap 绝对开始时间 (datetime)
        lap_end         : Lap 绝对结束时间 (datetime)
        generate_delta  : 是否生成 Delta 视频
        fps             : 帧率，默认 DELTA_DEFAULT_FPS (5)
        cleanup         : 合成后是否清理帧目录（API 默认 False）
        params_dict     : 覆盖默认渲染参数
        ffmpeg_path     : 覆盖全局 FFmpeg 路径
        output_dir      : 自定义帧目录
        output_file     : 自定义输出视频文件名

    返回:
        dict: {
            'delta_elevation_video': 输出视频路径 (失败时为 None),
            'frames_dir': 帧目录路径,
            'warnings': [警告列表],
        }
    """
    params = _merge_params(params_dict)
    if fps is None:
        fps = DELTA_DEFAULT_FPS

    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path
    frames_dir, video_file = _resolve_paths(output_dir, output_file)

    result = {
        'delta_elevation_video': None,
        'frames_dir': frames_dir,
        'warnings': [],
    }

    if not generate_delta:
        print("[Delta] generate_delta=False，跳过生成")
        return result

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长: {duration}秒")

    # 帧目录冲突检测
    if os.path.exists(frames_dir) and os.listdir(frames_dir):
        raise FileExistsError(
            f"[Delta] 帧目录已存在且非空: {frames_dir}\n"
            f"请先删除该目录或调用 Delta_elevation.cleanup_frames('{frames_dir}') 清理后再试"
        )

    print("\n=== [Delta] 配置参数 ===")
    print(f"FIT文件: {fit_path}")
    print(f"时间范围: {lap_start} → {lap_end} (时长 {duration:.1f}s)")
    print(f"帧率: {fps} Hz")
    print(f"分辨率: {params['width']}x{params['height']}")
    print(f"帧目录: {frames_dir}")
    print(f"输出视频: {video_file}")
    print(f"自动清理: {'是' if cleanup else '否'}")
    print("========================\n")

    try:
        # 1. 加载数据
        print("[Delta] [步骤1/6] 加载数据...")
        raw = _load_fit_data(fit_path, lap_start, lap_end)

        # 填充海拔 NaN
        alts = raw['alts']
        valid = ~np.isnan(alts)
        if not np.all(valid):
            nan_count = np.sum(~valid)
            print(f"[Delta] 填充 {nan_count} 个海拔NaN值...")
            f_interp = interp1d(raw['offsets'][valid], alts[valid], kind='linear', fill_value="extrapolate")
            raw['alts'] = f_interp(raw['offsets'])

        dt = np.median(np.diff(raw['offsets'])) if len(raw['offsets']) > 1 else 1.0
        print(f"[Delta] 原始网格 dt={dt:.3f}s")

        # 2. 平滑
        print("[Delta] [步骤2/6] 平滑处理...")
        alts_weak = _apply_smooth_1hz(raw['alts'], dt, params['elev_weak_smooth_sec'])
        alts_strong = _apply_smooth_1hz(raw['alts'], dt, params['grad_strong_smooth_sec'])
        alts_gain = _apply_smooth_1hz(raw['alts'], dt, params['gain_smooth_sec'])

        # 3. 坡度 + 爬升
        print("[Delta] [步骤3/6] 坡度 + 累计爬升计算...")
        gradients_1hz = _compute_gradient_1hz(
            alts_strong, raw['speeds'], dt,
            params['grad_min_speed_kmh'], params['grad_compensation_sec']
        )
        gains_1hz = _compute_cumulative_gain(
            alts_gain, raw['dists'],
            params['gain_min_height_m'], params['gain_min_dist_m']
        )

        # 4. 插值到 FPS
        print(f"[Delta] [步骤4/6] 插值到 {fps}Hz...")
        interp_in = {
            'offsets': raw['offsets'],
            'alts_weak': alts_weak,
            'gradients': gradients_1hz,
            'gains': gains_1hz,
        }
        intp = _interpolate_to_fps(interp_in, duration, fps)
        alts_weak_fps = intp['alts_weak']
        gradients_fps = _clip_gradient_display(intp['gradients'])
        gains_fps = intp['gains']

        # 5. 渲染
        print("[Delta] [步骤5/6] 渲染帧...")
        frame_count = _render_delta_frames(alts_weak_fps, gradients_fps, gains_fps, params, frames_dir)

        if frame_count == 0:
            print("[Delta] ❌ 未生成任何帧")
            return result

        # 6. 合成
        success = _assemble_delta_mov(
            frames_dir, video_file, frame_count, fps,
            params['width'], params['height'],
        )

        if success and os.path.exists(video_file):
            result['delta_elevation_video'] = video_file

    except Exception as e:
        print(f"[Delta] ❌ 发生错误: {e}")
        raise

    finally:
        if cleanup and os.path.exists(frames_dir):
            t0 = time.time()
            cleanup_frames(frames_dir)
            print(f"[Delta] 🧹 已清理: {frames_dir} (用时 {time.time()-t0:.2f}s)")

    return result


# ============================================================
# CLI 入口（独立运行）
# ============================================================
def _find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend([os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".fit")])
    return sorted(set(files))

def _select_laps(fit_path):
    try:
        from fitparse import FitFile
    except ImportError:
        print("❌ 缺少依赖 fitparse")
        return None, None

    fit = FitFile(fit_path)
    laps = []
    for i, lap in enumerate(fit.get_messages("lap")):
        v = lap.get_values()
        st = v.get("start_time")
        et = st + timedelta(seconds=v.get("total_elapsed_time", 0))
        if st and et > st:
            laps.append((i, st, et))
    if not laps:
        print("⚠️ 无有效 Lap")
        return None, None

    for display_num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{display_num}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")
    choice = input("选择 Lap (q退出，支持多选如1,3): ").strip().lower()
    if choice == "q":
        return None, None
    try:
        selected_nums = sorted({int(x.strip()) for x in choice.split(',')})
    except ValueError:
        print("❌ 输入无效")
        return _select_laps(fit_path)
    if not (1 <= min(selected_nums) <= max(selected_nums) <= len(laps)):
        print(f"❌ 无效选择")
        return _select_laps(fit_path)

    selected_indices = [n - 1 for n in selected_nums]
    return laps[min(selected_indices)][1], laps[max(selected_indices)][2]

def main():
    print("=" * 60)
    print("Delta: 海拔/坡度/累计爬升 HUD (1Hz FIT · 长坡修复版)")
    print("=" * 60)

    fit_arg = sys.argv[1] if len(sys.argv) > 1 else None
    fits = [fit_arg] if fit_arg else _find_fit_files()
    if not fits:
        print("❌ 未找到 .fit 文件")
        return

    if fit_arg:
        fit_path = fit_arg
    else:
        for i, f in enumerate(fits, 1):
            print(f"[{i}] {f}")
        choice = input("选择文件 (q退出): ").strip()
        if choice.lower() == 'q':
            return
        try:
            fit_path = fits[int(choice) - 1]
        except Exception:
            print("❌ 无效选择")
            return

    lap_start, lap_end = _select_laps(fit_path)
    if lap_start is None:
        return

    try:
        fps = int(input(f"帧率 (回车默认{DELTA_DEFAULT_FPS}): ").strip() or DELTA_DEFAULT_FPS)
    except ValueError:
        fps = DELTA_DEFAULT_FPS

    # CLI 模式：自动清理
    frames_dir = DEFAULT_FRAMES_DIR
    if os.path.exists(frames_dir):
        print(f"[Delta] CLI 模式将覆盖清理已有帧目录")
        cleanup_frames(frames_dir)

    total_start = time.time()
    try:
        result = generate_delta_elevation_video(
            fit_path, lap_start, lap_end,
            fps=fps,
            cleanup=True,  # CLI 自动清理
        )
    except Exception as e:
        print(f"[Delta] ❌ 运行失败: {e}")
        return
    total_elapsed = time.time() - total_start

    if result.get('delta_elevation_video') and os.path.exists(result['delta_elevation_video']):
        print(f"\n[Delta] ✅ 视频生成完成: {result['delta_elevation_video']}")
        print(f"[Delta] ⏱️ 总用时: {total_elapsed:.2f}s")
    else:
        print(f"\n[Delta] ❌ 视频未成功生成")

if __name__ == "__main__":
    main()