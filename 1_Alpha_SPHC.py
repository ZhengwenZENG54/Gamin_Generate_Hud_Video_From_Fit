# -*- coding: utf-8 -*-
"""
Alpha_SPHC.py
=============
Alpha 模块的 SPHC 子模块（Speed / Power / HR / Cadence）。
"""

import os
import math
import time
import shutil
import datetime
import subprocess
import sys
import warnings

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ============================================================
# 全局可配置变量
# ============================================================
FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR_SPHC = None
OUTPUT_MOV_SPHC = None

SPHC_DEFAULT_FPS = 30
DEFAULT_FRAMES_DIR = "frames_Alpha_SPHC"


# ============================================================
# 默认参数
# ============================================================
DEFAULT_PARAMS = {
    'width': 400,
    'height': 200,
    'font_size': 25,
    'font_color': 'white',
    'bg_alpha': 0.4,
    'bg_color': 'black',
    'bg_visible': True, 
    'linespacing': 1.2,
    'speed_threshold': 3.0,
    'print_interval': 10,
    'text_x': 0.05,
    'text_y': 0.92,
}


def _merge_params(params_dict):
    merged = dict(DEFAULT_PARAMS)
    if params_dict:
        merged.update(params_dict)
    return merged


# ============================================================
# 边界检查
# ============================================================
def check_layout_bounds(params):
    warns = []
    width = params['width']
    height = params['height']
    font_size = params['font_size']
    linespacing = params['linespacing']

    line_height = font_size * (100.0 / 72.0) * linespacing
    n_lines = 4
    est_total_height = n_lines * line_height
    safe_height = height * 0.90
    if est_total_height > safe_height:
        warns.append(
            f"字号过大可能导致竖直方向截断: 预估文字高度 {est_total_height:.0f}px > "
            f"安全高度 {safe_height:.0f}px (font_size={font_size}, height={height})"
        )

    max_chars = 20
    est_char_width = font_size * 0.6
    est_total_width = max_chars * est_char_width
    safe_width = width * 0.95
    if est_total_width > safe_width:
        warns.append(
            f"字号过大可能导致水平方向截断: 预估文字宽度 {est_total_width:.0f}px > "
            f"安全宽度 {safe_width:.0f}px (font_size={font_size}, width={width})"
        )

    return warns


# ============================================================
# 辅助函数
# ============================================================
def _resolve_paths(output_dir, output_file):
    global OUTPUT_DIR_SPHC, OUTPUT_MOV_SPHC

    if output_dir:
        frames_dir = output_dir
    elif OUTPUT_DIR_SPHC:
        frames_dir = OUTPUT_DIR_SPHC
    else:
        frames_dir = DEFAULT_FRAMES_DIR

    if output_file:
        video_file = output_file
    elif OUTPUT_MOV_SPHC:
        video_file = OUTPUT_MOV_SPHC
    else:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = f"alpha_SPHC_{timestamp}.mov"

    return frames_dir, video_file


def cleanup_frames(frames_dir=DEFAULT_FRAMES_DIR):
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
        return True
    return False


# ============================================================
# FIT 数据加载与插值
# ============================================================
def load_and_filter(fit_path, start_abs_time, end_abs_time, speed_threshold=3.0):
    try:
        from fitparse import FitFile
    except ImportError:
        raise ImportError("缺少依赖 fitparse，请运行: pip install fitparse")

    print("[Alpha_SPHC] [DEBUG] 正在加载FIT数据...")
    fit = FitFile(fit_path)
    recs = []
    for m in fit.get_messages('record'):
        vals = m.get_values()
        if 'timestamp' in vals:
            recs.append(vals)

    if not recs:
        raise RuntimeError("FIT文件中没有数据")

    offs, spd, pwr, hr, cad = [], [], [], [], []
    for r in recs:
        ts = r['timestamp']
        if not (start_abs_time <= ts <= end_abs_time):
            continue
        offset = (ts - start_abs_time).total_seconds()
        offs.append(offset)

        s = r.get('enhanced_speed') or r.get('speed', 0.0)
        raw_speed = float(s) * 3.6
        speed_value = 0.0 if raw_speed < speed_threshold else raw_speed
        spd.append(speed_value)

        # ★ 关键修复：字段不存在 → -1（哨兵），字段存在但为 NaN → -1，值为 0 → 0（保留）
        raw_pwr = r.get('power')
        if raw_pwr is None or (isinstance(raw_pwr, float) and np.isnan(raw_pwr)):
            pwr.append(-1.0)   # 哨兵：未连接/无效
        else:
            pwr.append(float(raw_pwr))

        hr.append(r.get('heart_rate', np.nan))

        raw_cad = r.get('cadence')
        if raw_cad is None or (isinstance(raw_cad, float) and np.isnan(raw_cad)):
            cad.append(-1.0)   # 哨兵：未连接/无效
        else:
            cad.append(float(raw_cad))

    if not offs:
        raise RuntimeError("指定时间范围内没有数据")

    zero_count = sum(1 for s in spd if s == 0.0)
    print(f"[Alpha_SPHC] [速度过滤] 将{zero_count}个低速点(<{speed_threshold}km/h)设为0")

    return {
        'offsets': np.array(offs, dtype=float),
        'speed': np.array(spd, dtype=float),
        'power': np.array(pwr, dtype=float),
        'hr': np.array(hr, dtype=float),
        'cad': np.array(cad, dtype=float),
    }


def interpolate(data, duration_sec, fps, speed_threshold=3.0):
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

    # ★ 修复：interp_int 保留 -1 哨兵值（未连接），不把 NaN 转成 0
    def interp_int(arr):
        """插值整数数组，保留 -1 哨兵值表示未连接。"""
        interped = np.interp(time_points, x, arr)
        result = interped.astype(int)
        # 标记原始数据为 -1 的对应插值点
        for i, t in enumerate(time_points):
            idx = np.searchsorted(x, t, side='right') - 1
            if 0 <= idx < len(arr) and arr[idx] == -1:
                result[i] = -1
        return result

    result = {
        'speed': interp_speed_clean,
        'power': interp_int(data['power']),
        'hr': interp_int(data['hr']),
        'cad': interp_int(data['cad']),
        'time_points': time_points,
    }

    print(f"[Alpha_SPHC] [插值] 生成 {len(time_points)} 个时间点 (FPS={fps})")
    return result


# ============================================================
# ★ 修复：数值格式化（区分未连接 vs 有效零值）
# ============================================================
def format_value(value, value_type, speed_threshold=3.0):
    # None / NaN → 未连接
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "--"
    
    if value_type == 'speed':
        if value < speed_threshold:
            return f"<{speed_threshold}km/h"
        return f"{value:.1f} km/h"
    
    elif value_type in ['power', 'cad']:
        # ★ < 0（哨兵 -1）→ 未连接，显示 --
        if value < 0:
            return "--"
        # ★ == 0 → 有效零值（放坡/推行），显示 0
        if value == 0:
            if value_type == 'power':
                return "0 W"
            else:
                return "0 rpm"
        # ★ > 0 → 正常显示
        if value_type == 'power':
            return f"{value} W"
        else:
            return f"{value} rpm"
    
    elif value_type == 'hr':
        if value <= 0:
            return "--"
        return f"{value} bpm"
    
    return str(value)


# ============================================================
# 渲染
# ============================================================
def render_sphc_frames(data_intp, params, frames_dir):
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frames_dir, f))

    width = params['width']
    height = params['height']
    font_size = params['font_size']
    font_color = params['font_color']
    bg_alpha = params['bg_alpha']
    linespacing = params['linespacing']
    text_x = params['text_x']
    text_y = params['text_y']
    speed_threshold = params['speed_threshold']
    print_interval = params['print_interval']

    frame_count = len(data_intp['speed'])
    plt.ioff()
    fig, ax = plt.subplots(figsize=(width / 100.0, height / 100.0), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0.02, 1, 0.94])
    ax.axis('off')

    bbox_config = None
    if params.get('bg_visible', True):
        bbox_config = dict(
            facecolor=params.get('bg_color', 'black'),
            alpha=params.get('bg_alpha', 0.4),
            boxstyle='round,pad=0.25'
        )
        
    text_obj = ax.text(
        text_x, text_y, "",
        fontsize=font_size,
        color=font_color,
        verticalalignment='top',
        bbox=bbox_config,
        transform=ax.transAxes,
        linespacing=linespacing,
    )

    start_time = time.time()
    last_print_time = start_time

    for idx in range(frame_count):
        current_time = time.time()
        if current_time - last_print_time >= print_interval:
            elapsed = current_time - start_time
            processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (frame_count - processed) / fps_actual if fps_actual > 0 else 0
            print(
                f"[Alpha_SPHC] [渲染] {processed}/{frame_count}帧 | "
                f"已用: {elapsed:.1f}s | 剩余: {remaining:.1f}s | "
                f"速度: {fps_actual:.1f}帧/s"
            )
            last_print_time = current_time

        speed_display = format_value(data_intp['speed'][idx], 'speed', speed_threshold)
        power_display = format_value(data_intp['power'][idx], 'power')
        hr_display = format_value(data_intp['hr'][idx], 'hr')
        cad_display = format_value(data_intp['cad'][idx], 'cad')

        text_obj.set_text(
            f"Speed: {speed_display}\n"
            f"Power: {power_display}\n"
            f"Heart Rate: {hr_display}\n"
            f"Cadence: {cad_display}"
        )

        path = os.path.join(frames_dir, f"frame_{idx:06d}.png")
        fig.savefig(path, dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    print(f"[Alpha_SPHC] [渲染] 完成，共 {frame_count} 帧")
    return frame_count


# ============================================================
# FFmpeg 合成
# ============================================================
def assemble_sphc_mov(frames_dir, output_file, frame_count, fps, width, height, prefix="frame_"):
    global FFMPEG_PATH

    if not os.path.exists(frames_dir):
        print(f"[Alpha_SPHC] [错误] 帧目录不存在: {frames_dir}")
        return False

    print(f"[Alpha_SPHC] [合成] {output_file} (FPS={fps}, {width}x{height})")
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
            print(f"[Alpha_SPHC] [合成] 成功: {output_file}")
            return True
        else:
            print(f"[Alpha_SPHC] [警告] ffmpeg 返回码 {result.returncode}: {result.stderr[:500]}")
            return False
    except Exception as e:
        print(f"[Alpha_SPHC] [错误] ffmpeg 执行异常: {e}")
        return False


# ============================================================
# 主入口：供 Call 代码调用
# ============================================================
def generate_sphc_video(
    fit_path,
    lap_start,
    lap_end,
    generate_sphc=True,
    fps=None,
    cleanup=False,
    params_dict=None,
    ffmpeg_path=None,
    output_dir=None,
    output_file=None,
):
    params = _merge_params(params_dict)
    if fps is None:
        fps = SPHC_DEFAULT_FPS

    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path
    frames_dir, video_file = _resolve_paths(output_dir, output_file)

    result = {
        'sphc_video': None,
        'frames_dir': frames_dir,
        'warnings': [],
    }

    warns = check_layout_bounds(params)
    if warns:
        for w in warns:
            print(f"[Alpha_SPHC] ⚠️ 警告: {w}")
        result['warnings'] = warns

    if not generate_sphc:
        print("[Alpha_SPHC] generate_sphc=False，跳过生成")
        return result

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长: {duration}秒")

    if os.path.exists(frames_dir) and os.listdir(frames_dir):
        raise FileExistsError(
            f"[Alpha_SPHC] 帧目录已存在且非空: {frames_dir}\n"
            f"请先删除该目录或调用 Alpha_SPHC.cleanup_frames('{frames_dir}') 清理后再试"
        )

    print("\n=== [Alpha_SPHC] 配置参数 ===")
    print(f"FIT文件: {fit_path}")
    print(f"时间范围: {lap_start} → {lap_end} (时长 {duration:.1f}s)")
    print(f"帧率: {fps} Hz")
    print(f"分辨率: {params['width']}x{params['height']}")
    print(f"字号: {params['font_size']}pt")
    print(f"帧目录: {frames_dir}")
    print(f"输出视频: {video_file}")
    print(f"自动清理: {'是' if cleanup else '否'}")
    print("===========================\n")

    try:
        print("[Alpha_SPHC] [步骤1/3] 加载FIT数据...")
        raw = load_and_filter(fit_path, lap_start, lap_end, params['speed_threshold'])

        print("[Alpha_SPHC] [步骤2/3] 插值数据...")
        data_intp = interpolate(raw, duration, fps, params['speed_threshold'])

        print("[Alpha_SPHC] [步骤3/3] 渲染帧...")
        frame_count = render_sphc_frames(data_intp, params, frames_dir)

        if frame_count == 0:
            print("[Alpha_SPHC] ❌ 未生成任何帧")
            return result

        success = assemble_sphc_mov(
            frames_dir, video_file, frame_count, fps,
            params['width'], params['height'],
        )

        if success and os.path.exists(video_file):
            result['sphc_video'] = video_file

    except Exception as e:
        print(f"[Alpha_SPHC] ❌ 发生错误: {e}")
        raise

    finally:
        if cleanup and os.path.exists(frames_dir):
            t0 = time.time()
            cleanup_frames(frames_dir)
            print(f"[Alpha_SPHC] 🧹 已清理: {frames_dir} (用时 {time.time()-t0:.2f}s)")

    return result


# ============================================================
# CLI 交互逻辑
# ============================================================
def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(
                os.path.join(p, f) for f in os.listdir(p)
                if f.lower().endswith(".fit")
            )
    return sorted(set(files))


def select_laps(fit_path):
    try:
        from fitparse import FitFile
    except ImportError:
        print("❌ 缺少依赖 fitparse，请运行: pip install fitparse")
        return None, None, None, None

    fit = FitFile(fit_path)
    laps = []
    for i, lap in enumerate(fit.get_messages("lap")):
        v = lap.get_values()
        st = v.get("start_time")
        et = st + datetime.timedelta(seconds=v.get("total_elapsed_time", 0))
        if st and et > st:
            laps.append((i, st, et))

    if not laps:
        print("⚠️ 无有效 Lap")
        return None, None, None, None

    for display_num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{display_num}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")

    choice = input("选择 Lap (q退出，支持多选逗号分隔，如1,3): ").strip().lower()
    if choice == "q":
        return None, None, None, None

    try:
        selected_nums = sorted({int(x.strip()) for x in choice.split(',') if x.strip()})
    except ValueError:
        print("❌ 输入无效，请输入数字并用逗号分隔（如1,3）")
        return select_laps(fit_path)

    if not (1 <= min(selected_nums) <= max(selected_nums) <= len(laps)):
        print(f"❌ 无效选择，请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)

    selected_indices = [n - 1 for n in selected_nums]
    min_idx = min(selected_indices)
    max_idx = max(selected_indices)

    return laps[min_idx][1], laps[max_idx][2], selected_nums, list(range(min_idx + 1, max_idx + 2))


def main():
    print("=== Alpha_SPHC 文字叠加层视频生成 ===\n")

    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 FIT 文件（扫描了 . / ./data / ./fit / ./activities）")
        return

    for i, f in enumerate(fits, start=1):
        print(f"[{i}] {f}")
    choice = input("选择文件 (q退出): ").strip().lower()
    if choice == "q":
        return

    try:
        file_no = int(choice)
        if not (1 <= file_no <= len(fits)):
            raise ValueError
    except ValueError:
        print("❌ 无效选择")
        return
    fit_path = fits[file_no - 1]

    lap_start, lap_end, selected_nums, covered_nums = select_laps(fit_path)
    if lap_start is None:
        return

    try:
        fps = int(input(f"帧率 (回车默认{SPHC_DEFAULT_FPS}): ") or SPHC_DEFAULT_FPS)
    except ValueError:
        fps = SPHC_DEFAULT_FPS

    frames_dir = DEFAULT_FRAMES_DIR
    if os.path.exists(frames_dir):
        print(f"[Alpha_SPHC] 检测到已存在帧目录 {frames_dir}，CLI 模式将覆盖清理")
        cleanup_frames(frames_dir)

    total_start = time.time()
    try:
        result = generate_sphc_video(
            fit_path, lap_start, lap_end,
            fps=fps,
            cleanup=True,
        )
    except Exception as e:
        print(f"[Alpha_SPHC] ❌ 运行失败: {e}")
        return
    total_elapsed = time.time() - total_start

    minutes, seconds = divmod(int(total_elapsed), 60)
    if result.get('sphc_video') and os.path.exists(result['sphc_video']):
        print(f"\n[Alpha_SPHC] ✅ 视频生成完成: {result['sphc_video']}")
        print(f"[Alpha_SPHC] ⏱️ 总用时: {minutes}分{seconds}秒 ({total_elapsed:.2f}s)")
    else:
        print(f"\n[Alpha_SPHC] ❌ 视频未成功生成")

    if os.path.exists(DEFAULT_FRAMES_DIR):
        cleanup_start = time.time()
        cleanup_frames(DEFAULT_FRAMES_DIR)
        print(f"[Alpha_SPHC] 🧹 兜底已清理: {DEFAULT_FRAMES_DIR}")
        print(f"[Alpha_SPHC] ⏱️ 清理用时: {time.time()-cleanup_start:.2f}秒")


if __name__ == "__main__":
    main()