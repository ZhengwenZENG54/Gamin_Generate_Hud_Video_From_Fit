# -*- coding: utf-8 -*-
"""
Beta_time_distance_elevation.py
时间/距离/海拔 透明视频生成器（与 Alpha_SPHC 架构一致）
支持三种视频分别根据字体大小、文本长度自动计算紧凑分辨率。

用法:
  1) 单独运行 (CLI):  python Beta_time_distance_elevation.py
  2) 被 GUI 调用:     generate_beta_video(**kwargs)   <- 无 input() 阻塞
"""

import os
import sys
import glob
import time
import shutil
import subprocess
import traceback
from datetime import datetime, timedelta
from fitparse import FitFile
from scipy.interpolate import interp1d
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# ==================== 全局可覆盖 ====================
FFMPEG_PATH = "ffmpeg"

DEFAULT_PARAMS_TIME = {
    "fps": 1, "font_size": 60, "font_color": (255, 255, 255),
    "outline_width": 3, "outline_color": (0, 0, 0),
    "video_width": None, "video_height": None, "padding": 30, "timezone_offset": 8,
}
DEFAULT_PARAMS_DISTANCE = {
    "fps": 5, "font_size": 50, "font_color": (255, 255, 255),
    "outline_width": 3, "outline_color": (0, 0, 0),
    "prefix": " Dist: ", "suffix": " km",
    "video_width": None, "video_height": None, "padding": 30,
}
DEFAULT_PARAMS_ELEVATION = {
    "fps": 5, "font_size": 50, "font_color": (255, 255, 255),
    "outline_width": 3, "outline_color": (0, 0, 0),
    "prefix": " Elev: ", "suffix": " m",
    "video_width": None, "video_height": None, "padding": 30,
}

# ★ 帧目录名用 ASCII（避免中文路径问题），但日志前缀用中文 [Beta_时间]
BETA_TIME_FRAMES = "frames_Beta_TIME"
BETA_DISTANCE_FRAMES = "frames_Beta_DISTANCE"
BETA_ELEVATION_FRAMES = "frames_Beta_ELEVATION"

PRINT_INTERVAL = 5.0
FONT_PATH = None


# ============================================================
# 数据加载与插值
# ============================================================
def load_fit_data(fit_path, lap_start, lap_end):
    """加载 FIT 数据（None 安全）"""
    fit = FitFile(fit_path)
    times, distances, elevations = [], [], []
    first_dist = None
    first_elev = None
    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None:
            continue
        if lap_start is not None and ts < lap_start:
            continue
        if lap_end is not None and ts > lap_end:
            continue

        d = vals.get('distance')
        if d is not None:
            if first_dist is None:
                first_dist = d
            distances.append(d - first_dist)
        else:
            distances.append(np.nan)

        e = vals.get('enhanced_altitude') or vals.get('altitude')
        if e is not None:
            if first_elev is None:
                first_elev = e
            elevations.append(e)
        else:
            elevations.append(np.nan)

        times.append(ts)
    print(f"[Beta_加载] 数据点 {len(times)} 个, 距离有效 {sum(not np.isnan(x) for x in distances)}, "
          f"海拔有效 {sum(not np.isnan(x) for x in elevations)}")
    return times, distances, elevations


def interpolate_data(times, values, start_time, end_time, fps, data_type="distance"):
    """线性插值（距离单调递增保护）"""
    if not times or len(times) < 2:
        return None, None
    time_offsets = np.array([(t - start_time).total_seconds() for t in times], dtype=float)
    duration = (end_time - start_time).total_seconds()
    interp_times = np.linspace(0, duration, int(duration * fps) + 1)
    valid = ~np.isnan(values)
    vt = time_offsets[valid]
    vv = np.array(values)[valid]
    if len(vt) < 2:
        return None, None
    f = interp1d(vt, vv, kind='linear', fill_value="extrapolate", bounds_error=False)
    iv = f(interp_times)
    if data_type == "distance":
        for i in range(1, len(iv)):
            if iv[i] < iv[i - 1]:
                iv[i] = iv[i - 1]
    return interp_times, iv


# ============================================================
# 字体 / 帧渲染
# ============================================================
def load_font(font_size):
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            return ImageFont.truetype(FONT_PATH, font_size)
        try:
            return ImageFont.truetype("arial.ttf", font_size)
        except:
            return ImageFont.truetype("DejaVuSans.ttf", font_size)
    except:
        return ImageFont.load_default()


def calc_text_size(text, font):
    img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def calc_video_size_for_text(text, font, padding=30, outline_width=3,
                             video_width=None, video_height=None):
    """
    根据单个文本、字体和描边宽度计算视频尺寸。
    若指定 video_width / video_height 则使用指定值（并保证偶数），
    否则自动计算最紧凑的偶数尺寸（包含 padding 和描边余量）。
    """
    if video_width and video_height:
        if video_width % 2:
            video_width += 1
        if video_height % 2:
            video_height += 1
        return int(video_width), int(video_height)

    w, h = calc_text_size(text, font)
    w += outline_width * 2 + padding * 2
    h += outline_width * 2 + padding * 2
    if w % 2:
        w += 1
    if h % 2:
        h += 1
    return w, h


def make_text_frame(text, width, height, font, color, outline_w, outline_c):
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tw, th = calc_text_size(text, font)
    x = (width - tw) / 2
    y = (height - th) / 2

    if outline_w > 0:
        for dx in [-outline_w, 0, outline_w]:
            for dy in [-outline_w, 0, outline_w]:
                if dx == 0 and dy == 0:
                    continue
                d.text((x + dx, y + dy), text, font=font, fill=outline_c)

    d.text((x, y), text, font=font, fill=color)
    return img


def generate_frames(lap_start, lap_end, fps, width, height, frame_dir,
                    text_fn, print_tag):
    duration = (lap_end - lap_start).total_seconds()
    total = int(duration * fps)
    os.makedirs(frame_dir, exist_ok=True)
    for f in os.listdir(frame_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frame_dir, f))
    if total == 0:
        print(f"[{print_tag}] 时长为0，无帧可生成")
        return 0
    t0 = time.time()
    last = t0
    for i in range(total):
        now = time.time()
        if now - last >= PRINT_INTERVAL:
            el = now - t0
            fa = (i + 1) / el if el > 0 else 0
            rem = (total - i - 1) / fa if fa > 0 else 0
            print(f"[{print_tag}] {i+1}/{total} | {el:.1f}s | 剩余 {rem:.1f}s | {fa:.1f}帧/s")
            last = now
        t = lap_start + timedelta(seconds=i / fps)
        frame = text_fn(t, i)
        frame.save(os.path.join(frame_dir, f"frame_{i:06d}.png"), 'PNG')
    print(f"[{print_tag}] 完成 {total} 帧")
    return total


def compile_video(frame_dir, output_file, frame_count, width, height, fps, prefix="frame_"):
    global FFMPEG_PATH
    if frame_count == 0:
        return False
    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, check=True)
    except Exception:
        print(f"[Beta_合成] ffmpeg 不可用: {FFMPEG_PATH}")
        return False
    cmd = [
        FFMPEG_PATH, "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", os.path.join(frame_dir, f"{prefix}%06d.png"),
        "-vf", f"scale={width}:{height},setsar=1",
        "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file,
    ]
    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode == 0:
        print(f"[Beta_合成] 成功: {output_file}")
        return True
    else:
        print(f"[Beta_合成] 失败: {r.stderr[:300]}")
        return False


# ============================================================
# 可编程入口（被 GUI 调用）
# ============================================================
def generate_beta_video(fit_path, lap_start=None, lap_end=None,
                        generate_time=True, generate_distance=True, generate_elevation=True,
                        time_fps=None, distance_fps=None, elevation_fps=None,
                        params_dict_time=None, params_dict_distance=None, params_dict_elevation=None,
                        ffmpeg_path=None, output_dir=None,
                        output_file_time=None, output_file_distance=None, output_file_elevation=None,
                        cleanup=False):
    """
    cleanup=False (默认) -> 保留帧目录，由 GUI 统一清理
    cleanup=True  (CLI)  -> 合成后自清理
    """
    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path

    p_time = {**DEFAULT_PARAMS_TIME, **(params_dict_time or {})}
    p_dist = {**DEFAULT_PARAMS_DISTANCE, **(params_dict_distance or {})}
    p_elev = {**DEFAULT_PARAMS_ELEVATION, **(params_dict_elevation or {})}

    fps_t = time_fps if time_fps is not None else p_time["fps"]
    fps_d = distance_fps if distance_fps is not None else p_dist["fps"]
    fps_e = elevation_fps if elevation_fps is not None else p_elev["fps"]

    out_dir = output_dir or os.getcwd()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_time = output_file_time or os.path.join(out_dir, f"beta_time_{ts}.mov")
    out_dist = output_file_distance or os.path.join(out_dir, f"beta_dist_{ts}.mov")
    out_elev = output_file_elevation or os.path.join(out_dir, f"beta_elev_{ts}.mov")

    result = {
        "success": False, "time_video": None, "distance_video": None,
        "elevation_video": None, "cleanup_time": 0.0, "total_time": 0.0,
    }
    t0_all = time.time()

    try:
        if lap_start is None or lap_end is None:
            print("[Beta_加载] lap_start/lap_end 为 None，自动从 FIT 推导...")
            tmp = FitFile(fit_path)
            all_ts = [m.get_values()['timestamp'] for m in tmp.get_messages('record')
                      if 'timestamp' in m.get_values()]
            if not all_ts:
                raise ValueError("FIT 中无时间戳数据")
            lap_start = lap_start or min(all_ts)
            lap_end = lap_end or max(all_ts)

        if not os.path.exists(fit_path):
            raise FileNotFoundError(fit_path)

        duration = (lap_end - lap_start).total_seconds()
        if duration <= 0:
            raise ValueError(f"无效时间范围: {duration}秒")

        print(f"[Beta] 时间范围: {lap_start} -> {lap_end} ({duration:.1f}秒)")

        times, dists, elevs = load_fit_data(fit_path, lap_start, lap_end)
        if not times:
            raise ValueError("指定时间范围内无数据")

        time_font = load_font(p_time["font_size"])
        dist_font = load_font(p_dist["font_size"]) if generate_distance else None
        elev_font = load_font(p_elev["font_size"]) if generate_elevation else None

        # ---- 分别计算三种视频尺寸 ----
        time_w = time_h = None
        dist_w = dist_h = None
        elev_w = elev_h = None

        if generate_time:
            sample_time = "9999-12-31 23:59:59"
            time_w, time_h = calc_video_size_for_text(
                sample_time, time_font,
                padding=p_time.get("padding", 30),
                outline_width=p_time["outline_width"],
                video_width=p_time.get("video_width"),
                video_height=p_time.get("video_height"),
            )
            print(f"[Beta] 时间视频尺寸: {time_w}x{time_h}")

        if generate_distance:
            # 使用足够长的示例文本，保证不会裁剪实际内容
            sample_dist = f"{p_dist['prefix']}9999.99{p_dist['suffix']}"
            dist_w, dist_h = calc_video_size_for_text(
                sample_dist, dist_font,
                padding=p_dist.get("padding", p_time.get("padding", 30)),
                outline_width=p_dist["outline_width"],
                video_width=p_dist.get("video_width"),
                video_height=p_dist.get("video_height"),
            )
            print(f"[Beta] 距离视频尺寸: {dist_w}x{dist_h}")

        if generate_elevation:
            sample_elev = f"{p_elev['prefix']}9999.9{p_elev['suffix']}"
            elev_w, elev_h = calc_video_size_for_text(
                sample_elev, elev_font,
                padding=p_elev.get("padding", p_time.get("padding", 30)),
                outline_width=p_elev["outline_width"],
                video_width=p_elev.get("video_width"),
                video_height=p_elev.get("video_height"),
            )
            print(f"[Beta] 海拔视频尺寸: {elev_w}x{elev_h}")

        tz = p_time["timezone_offset"]
        iv_dist = None
        iv_elev = None
        if generate_distance:
            _, iv_dist = interpolate_data(times, dists, lap_start, lap_end, fps_d, "distance")
        if generate_elevation:
            _, iv_elev = interpolate_data(times, elevs, lap_start, lap_end, fps_e, "elevation")

        dir_t = os.path.join(out_dir, BETA_TIME_FRAMES)
        dir_d = os.path.join(out_dir, BETA_DISTANCE_FRAMES)
        dir_e = os.path.join(out_dir, BETA_ELEVATION_FRAMES)

        cnt_t = cnt_d = cnt_e = 0
        if generate_time:
            cnt_t = generate_frames(
                lap_start, lap_end, fps_t, time_w, time_h, dir_t,
                lambda t, i: make_text_frame(
                    (t + timedelta(hours=tz)).strftime("%Y-%m-%d %H:%M:%S"),
                    time_w, time_h, time_font, p_time["font_color"],
                    p_time["outline_width"], p_time["outline_color"]),
                "Beta_Time")
        if generate_distance and iv_dist is not None:
            cnt_d = generate_frames(
                lap_start, lap_end, fps_d, dist_w, dist_h, dir_d,
                lambda t, i: make_text_frame(
                    f"{p_dist['prefix']}{iv_dist[i]/1000:.2f}{p_dist['suffix']}",
                    dist_w, dist_h, dist_font, p_dist["font_color"],
                    p_dist["outline_width"], p_dist["outline_color"]),
                "Beta_Dist")
        if generate_elevation and iv_elev is not None:
            cnt_e = generate_frames(
                lap_start, lap_end, fps_e, elev_w, elev_h, dir_e,
                lambda t, i: make_text_frame(
                    f"{p_elev['prefix']}{iv_elev[i]:.1f}{p_elev['suffix']}",
                    elev_w, elev_h, elev_font, p_elev["font_color"],
                    p_elev["outline_width"], p_elev["outline_color"]),
                "Beta_Elev")

        if generate_time and cnt_t > 0:
            if compile_video(dir_t, out_time, cnt_t, time_w, time_h, fps_t):
                result["time_video"] = out_time
        if generate_distance and cnt_d > 0:
            if compile_video(dir_d, out_dist, cnt_d, dist_w, dist_h, fps_d):
                result["distance_video"] = out_dist
        if generate_elevation and cnt_e > 0:
            if compile_video(dir_e, out_elev, cnt_e, elev_w, elev_h, fps_e):
                result["elevation_video"] = out_elev

        result["success"] = True

    except Exception as e:
        print(f"[Beta] 错误: {e}")
        traceback.print_exc()
        result["success"] = False

    finally:
        if cleanup and result.get("success"):
            result["cleanup_time"] = cleanup_all(out_dir)

    result["total_time"] = time.time() - t0_all
    return result


# ============================================================
# 统一清理
# ============================================================
def cleanup_all(output_dir):
    t0 = time.time()
    cleaned = 0
    for d in [BETA_TIME_FRAMES, BETA_DISTANCE_FRAMES, BETA_ELEVATION_FRAMES]:
        full = os.path.join(output_dir, d)
        if os.path.isdir(full):
            shutil.rmtree(full)
            cleaned += 1
    elapsed = time.time() - t0
    print(f"[Beta_清理] 共清理 {cleaned}/3 个目录, 合计 {elapsed:.2f}s")
    return elapsed


# ============================================================
# CLI 交互（与 SPHC 对齐：每步均可按 q 退出）
# ============================================================
def _check_quit(choice):
    """检查用户是否输入 q/Q，是则抛出 SystemExit 退出"""
    if choice.strip().lower() == 'q':
        print("用户取消，退出程序。")
        sys.exit(0)


def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".fit"))
    return sorted(set(files))


def select_laps(fit_path):
    fit = FitFile(fit_path)
    laps = []
    for i, lap in enumerate(fit.get_messages("lap")):
        v = lap.get_values()
        st = v.get("start_time")
        et = st + timedelta(seconds=v.get("total_elapsed_time", 0))
        if st and et > st:
            laps.append((i, st, et))
    if not laps:
        print("[Beta] 无有效 Lap")
        return None, None, None, None
    tz = DEFAULT_PARAMS_TIME["timezone_offset"]
    for num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{num}] {(st+timedelta(hours=tz)).strftime('%H:%M:%S')} -> "
              f"{(et+timedelta(hours=tz)).strftime('%H:%M:%S')}")
    choice = input("请选择 Lap (输入 q 退出，可多选逗号分隔，如 1,3): ").strip().lower()
    _check_quit(choice)
    try:
        nums = sorted({int(x.strip()) for x in choice.split(',') if x.strip()})
    except ValueError:
        print("[Beta] 输入无效，请重新输入")
        return select_laps(fit_path)
    if not (1 <= min(nums) <= max(nums) <= len(laps)):
        print(f"[Beta] 请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)
    idxs = [n - 1 for n in nums]
    return laps[min(idxs)][1], laps[max(idxs)][2], nums, list(range(min(idxs)+1, max(idxs)+2))


def _input_with_quit(prompt, default):
    """带 q 退出的 input，返回 (value, quit=False)"""
    raw = input(prompt).strip()
    if raw.lower() == 'q':
        print("用户取消，退出程序。")
        sys.exit(0)
    if raw == '':
        return default
    try:
        return int(raw)
    except ValueError:
        print("[Beta] 输入无效，使用默认值")
        return default


def main():
    print("=== Beta 时间/距离/海拔 透明视频生成器 ===\n")

    # 1. 选文件（可 q 退出）
    fits = find_fit_files()
    if not fits:
        print("[Beta] 未找到 FIT 文件（已扫描 . / ./data / ./fit / ./activities）")
        return
    for i, f in enumerate(fits, start=1):
        print(f"[{i}] {f}")
    c = input("请选择文件 (输入 q 退出): ").strip().lower()
    _check_quit(c)
    try:
        fit_path = fits[int(c) - 1]
    except (ValueError, IndexError):
        print("[Beta] 无效选择")
        return

    # 2. 选 Lap（可 q 退出）
    lap_start, lap_end, _, _ = select_laps(fit_path)
    if lap_start is None:
        return

    # 3. FPS 输入（0 = 跳过；可 q 退出）
    print("\n请设置各视频帧率（输入 0 表示不生成该类型，直接回车使用默认值，输入 q 退出）:")
    fps_t = _input_with_quit(f"  时间视频 FPS (默认 {DEFAULT_PARAMS_TIME['fps']}, 0=跳过): ", DEFAULT_PARAMS_TIME['fps'])
    fps_d = _input_with_quit(f"  距离视频 FPS (默认 {DEFAULT_PARAMS_DISTANCE['fps']}, 0=跳过): ", DEFAULT_PARAMS_DISTANCE['fps'])
    fps_e = _input_with_quit(f"  海拔视频 FPS (默认 {DEFAULT_PARAMS_ELEVATION['fps']}, 0=跳过): ", DEFAULT_PARAMS_ELEVATION['fps'])

    gen_t = fps_t > 0
    gen_d = fps_d > 0
    gen_e = fps_e > 0

    if not (gen_t or gen_d or gen_e):
        print("[Beta] 三种视频帧率均为 0，无需生成，退出。")
        return

    print(f"\n即将生成: 时间={'是' if gen_t else '否'}(fps={fps_t if gen_t else 0}), "
          f"距离={'是' if gen_d else '否'}(fps={fps_d if gen_d else 0}), "
          f"海拔={'是' if gen_e else '否'}(fps={fps_e if gen_e else 0})")

    # 4. CLI：清理已存在的帧目录
    for d in [BETA_TIME_FRAMES, BETA_DISTANCE_FRAMES, BETA_ELEVATION_FRAMES]:
        if os.path.exists(d):
            print(f"[Beta_清理] 检测到已存在目录 {d}，CLI 模式将覆盖清理")
            shutil.rmtree(d)

    # 5. 执行
    t0 = time.time()
    try:
        result = generate_beta_video(
            fit_path=fit_path, lap_start=lap_start, lap_end=lap_end,
            generate_time=gen_t, generate_distance=gen_d, generate_elevation=gen_e,
            time_fps=fps_t if gen_t else 1,
            distance_fps=fps_d if gen_d else 1,
            elevation_fps=fps_e if gen_e else 1,
            cleanup=True,
        )
    except Exception as e:
        print(f"[Beta] 运行失败: {e}")
        traceback.print_exc()
        return
    total = time.time() - t0

    # 6. 报告
    m, s = divmod(int(total), 60)
    for label, key in [("时间", "time_video"), ("距离", "distance_video"), ("海拔", "elevation_video")]:
        if result.get(key) and os.path.exists(result[key]):
            print(f"[Beta] ✅ {label}视频: {result[key]}")
    print(f"[Beta] ⏱️ 总用时: {m}分{s}秒 ({total:.2f}s)")
    if result.get("cleanup_time"):
        print(f"[Beta_清理] 清理用时: {result['cleanup_time']:.2f}s")


if __name__ == "__main__":
    main()