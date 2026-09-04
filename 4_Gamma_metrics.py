# -*- coding: utf-8 -*-
"""
Gamma_metrics.py
============================================================
Gamma: 训练指标视频（Strava-like NP / AP / IF / VI / TSS / HR / AvgSPD）

与 Alpha(Beta/SPHC/MAP/ELEVATION) 完全一致的编程接口与 CLI 交互约定:

编程调用 (GUI 场景, cleanup=False, 保留帧目录由调用方统一清理):
    result = generate_gamma_metrics_video(
        fit_path, lap_start, lap_end,
        fps=1, cleanup=False,
        params_dict=None,        # 覆盖 DEFAULT_PARAMS 中的项
        ffmpeg_path=None,
        output_dir="frames_gamma",
        output_file="gamma_metrics_xxx.mov",
    )

CLI 独立运行:
    python Gamma_metrics.py
    -> 选文件(q退出) -> 选 Lap(可多选, q退出) -> FTP / FPS(0=跳过, 回车默认, q退出)
"""

import os
import sys
import shutil
import time
import traceback
import subprocess
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from fitparse import FitFile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d


# ============================================================
# === 可配置默认参数（与 Alpha/Beta 的 DEFAULT_PARAMS_* 一致） ===
# ============================================================
DEFAULT_PARAMS = {
    "fps": 1,                # 帧率 (CLI 输入 0 = 跳过)
    "ftp": 250,              # 功能阈值功率 (W)
    "width": 480,            # 视频宽度 (像素)
    "height": 270,           # 视频高度 (像素)
    "font_size": 22,         # 字号
    "font_color": "white",   # 字体颜色 (matplotlib 颜色字符串)
    "bg_color": "black",     # 背景框颜色
    "bg_alpha": 0.4,         # 背景框透明度 0~1
    "ema_span": 25,          # NP 的指数加权跨度
    "speed_min_kmh": 3.0,    # 停车判定阈值 (km/h)，低于此值冻结指标
    "if_min_valid_seconds": 30,
    "print_interval": 5,      # 进度打印间隔 (秒)
}

# 帧目录名（ASCII，避免中文/特殊字符路径问题；日志前缀仍用中文 [Gamma]）
FRAMES_DIR = "frames_gamma"

FFMPEG_PATH = "ffmpeg"


# ============================================================
# === 参数合并工具（与 Alpha/Beta 一致）
# ============================================================
def _merge_params(params_dict):
    """用传入的 params_dict 覆盖默认参数，返回新 dict（不修改 DEFAULT_PARAMS）"""
    params = dict(DEFAULT_PARAMS)
    if params_dict:
        params.update(params_dict)
    return params


# ============================================================
# === 核心入口（与 Alpha/Beta 签名约定对齐）
# ============================================================
def generate_gamma_metrics_video(
    fit_path,
    lap_start=None,               # None → 自动取数据起点
    lap_end=None,                 # None → 自动取数据终点
    generate_gamma=True,          # 保留开关，与 Alpha/Beta 风格一致
    fps=None,                     # 覆盖 params 中的 fps
    cleanup=False,                # False=保留帧目录(GUI 统一清理)；True=自清理并记录 cleanup_time
    params_dict=None,             # 覆盖 DEFAULT_PARAMS
    ffmpeg_path=None,             # 覆盖全局 FFmpeg 路径
    output_dir=None,              # 自定义帧目录（避免冲突）
    output_file=None,             # 自定义输出视频文件名
    selected_nums=None,           # CLI 用：选中的 Lap 编号（仅日志）
    covered_nums=None,            # CLI 用：覆盖区间编号（仅日志）
):
    """
    生成 Gamma 训练指标视频。

    参数:
        fit_path, lap_start, lap_end : FIT 路径与绝对时间范围
        generate_gamma              : 是否生成（保留开关）
        fps                         : 帧率；为 None 时取 params['fps']
        cleanup                     : True=合成后自清理(CLI)；False=保留帧目录(API/GUI)
        params_dict                 : 覆盖默认参数（ftp/width/height/font_size 等）
        ffmpeg_path                 : 覆盖 FFmpeg 路径
        output_dir                  : 帧目录（默认 "frames_gamma"）
        output_file                 : 输出视频路径

    返回 dict:
        success, gamma_video, frame_count,
        frames_dir, warnings, total_time, cleanup_time
    """
    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path

    # 合并参数 + FPS 覆盖
    params = _merge_params(params_dict)
    if fps is not None:
        params["fps"] = fps
    metrics_fps = params["fps"]

    frame_dir = output_dir or FRAMES_DIR

    result = {
        "success": False,
        "gamma_video": None,
        "frame_count": 0,
        "frames_dir": frame_dir,
        "warnings": [],
        "total_time": 0.0,
        "cleanup_time": None,
    }
    t_program = time.time()

    try:
        if not fit_path:
            raise RuntimeError("fit_path 不能为空")

        # 未指定时间范围 → 从数据自动推导（独立运行兜底）
        if lap_start is None or lap_end is None:
            print("[Gamma] 自动推导时间范围...")
            tmp = FitFile(fit_path)
            all_ts = [m.get_values().get('timestamp') for m in tmp.get_messages('record')]
            all_ts = [t for t in all_ts if t is not None]
            if not all_ts:
                raise RuntimeError("FIT 文件中没有有效的时间戳数据")
            if lap_start is None: lap_start = min(all_ts)
            if lap_end is None:   lap_end = max(all_ts)
            print(f"[Gamma] 推导结果: {lap_start} ~ {lap_end} ({(lap_end-lap_start).total_seconds():.1f}s)")

        if not generate_gamma:
            print("[Gamma] generate_gamma=False，跳过")
            return result

        duration = (lap_end - lap_start).total_seconds()
        if duration <= 0:
            raise ValueError(f"无效的 Lap 时长: {duration}秒")

        # 输出文件名
        if output_file is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = os.path.join(os.getcwd(), f"gamma_metrics_{ts}.mov")

        ftp = params["ftp"]
        print("\n=== Gamma 训练指标视频配置 ===")
        if selected_nums and covered_nums:
            print(f"选中 Lap: {', '.join(map(str, selected_nums))}")
            print(f"覆盖区间: {covered_nums[0]} → {covered_nums[-1]} ({len(covered_nums)} 个 Lap)")
        print(f"时间范围: {lap_start.strftime('%H:%M:%S')} → {lap_end.strftime('%H:%M:%S')}")
        print(f"时长: {duration:.1f}s | 帧率: {metrics_fps}Hz | 预期帧数: {int(duration*metrics_fps)+1}")
        print(f"FTP: {ftp}W | 停车阈值: <{params['speed_min_kmh']} km/h 冻结指标")
        print(f"输出: {output_file}")
        print("===============================\n")

        print("[Gamma 1/4] 加载并过滤 FIT 数据...")
        raw = load_and_filter(fit_path, lap_start, lap_end, params)

        print("[Gamma 2/4] 计算指标 (AP/NP/HR/TSS/IF/VI/Speed)...")
        metrics = interpolate_metrics(raw, duration, metrics_fps, ftp, params)

        print("[Gamma 3/4] 渲染帧...")
        frame_count = render_gamma_frames(metrics, duration, metrics_fps, frame_dir, params)
        result["frame_count"] = frame_count
        if frame_count == 0:
            print("❌ 未生成任何帧")
            return result

        print("[Gamma 4/4] 合成视频...")
        ok = assemble_gamma_mov(frame_dir, output_file, frame_count, metrics_fps)
        if ok:
            result["gamma_video"] = output_file
            result["success"] = True
            print(f"✅ Gamma 指标视频生成成功: {output_file}")
        else:
            result["warnings"].append("ffmpeg 合成失败")

    except Exception as e:
        print(f"[Gamma] ❌ 错误: {e}")
        traceback.print_exc()
        result["warnings"].append(str(e))
    finally:
        result["total_time"] = time.time() - t_program
        if cleanup and result.get("success"):
            t0 = time.time()
            if os.path.isdir(frame_dir):
                shutil.rmtree(frame_dir)
                print(f"[Gamma] 🧹 已清理帧目录: {frame_dir}")
            result["cleanup_time"] = time.time() - t0

    return result


# ============================================================
# === 数据处理
# ============================================================
def load_and_filter(fit_path, start_abs_time, end_abs_time, params):
    speed_min_kmh = params["speed_min_kmh"]
    fit = FitFile(fit_path)
    offsets, power, hr, speed, is_stopped = [], [], [], [], []

    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None or not (start_abs_time <= ts <= end_abs_time):
            continue

        offsets.append((ts - start_abs_time).total_seconds())

        p = vals.get('power', np.nan)
        power.append(p if (p is not None and not np.isnan(float(p))) else np.nan)

        h = vals.get('heart_rate', np.nan)
        hr.append(h if (h is not None and not np.isnan(float(h))) else np.nan)

        s = vals.get('enhanced_speed', vals.get('speed', np.nan))
        if s is not None and not np.isnan(float(s)):
            speed_kmh = float(s) * 3.6
            if speed_kmh < speed_min_kmh:
                speed.append(0.0)
                is_stopped.append(True)
            else:
                speed.append(speed_kmh)
                is_stopped.append(False)
        else:
            speed.append(np.nan)
            is_stopped.append(True)

    if not offsets:
        raise RuntimeError("指定时间范围内无有效数据")

    return {
        'offsets': np.array(offsets, dtype=float),
        'power': np.array(power, dtype=float),
        'hr': np.array(hr, dtype=float),
        'speed': np.array(speed, dtype=float),
        'is_stopped': np.array(is_stopped, dtype=bool),
    }


def _safe_interp1d(x, y, x_new):
    if len(x) == 0:
        return np.full_like(x_new, np.nan)
    sort_idx = np.argsort(x)
    x = x[sort_idx]
    y = y[sort_idx]
    f = interp1d(x, y, kind='linear', bounds_error=False, fill_value=np.nan)
    return f(x_new)


def _expanding_mean_with_freeze(values, is_moving):
    result = np.full_like(values, np.nan)
    seg_sum, seg_count = 0.0, 0
    for i in range(len(values)):
        if is_moving[i] and not np.isnan(values[i]):
            seg_sum += values[i]
            seg_count += 1
            result[i] = seg_sum / seg_count
        elif seg_count > 0:
            result[i] = seg_sum / seg_count
    return result


def _calculate_np_cum(power_series, is_moving, ema_span):
    ps = pd.Series(power_series)
    ema = ps.where(is_moving).ewm(span=ema_span, adjust=False, min_periods=1).mean()
    ema_4th = ema ** 4
    result = np.full(len(ps), np.nan)
    seg_sum_4th, seg_count = 0.0, 0
    for i in range(len(ps)):
        if is_moving[i] and not np.isnan(ema_4th[i]):
            seg_sum_4th += ema_4th[i]
            seg_count += 1
            result[i] = (seg_sum_4th / seg_count) ** 0.25
        elif seg_count > 0:
            result[i] = (seg_sum_4th / seg_count) ** 0.25
    lap_np = 0
    if np.any(is_moving):
        valid = result[is_moving]
        if len(valid) > 0:
            lap_np = valid[-1]
    return result, lap_np


def interpolate_metrics(data, duration_sec, metrics_fps, ftp, params):
    ema_span = params["ema_span"]
    offsets = data['offsets']
    num_1hz = int(np.ceil(duration_sec)) + 1
    t_1hz = np.linspace(0, duration_sec, num_1hz)

    valid_speed = ~np.isnan(data['speed'])
    speed_1hz = _safe_interp1d(offsets[valid_speed], data['speed'][valid_speed], t_1hz)

    is_moving_1hz = np.ones_like(t_1hz, dtype=bool)
    for i, t in enumerate(t_1hz):
        idx = np.searchsorted(offsets, t, side='right') - 1
        if 0 <= idx < len(data['is_stopped']) and data['is_stopped'][idx]:
            is_moving_1hz[i] = False

    valid_power = ~np.isnan(data['power'])
    power_1hz = _safe_interp1d(offsets[valid_power], data['power'][valid_power], t_1hz)

    ap_1hz = _expanding_mean_with_freeze(power_1hz, is_moving_1hz)
    np_cum_1hz, lap_np = _calculate_np_cum(power_1hz, is_moving_1hz, ema_span)

    if lap_np <= 0:
        lap_np = ap_1hz[is_moving_1hz][-1] if np.any(is_moving_1hz) else 0

    np_s = pd.Series(np_cum_1hz)
    ap_s = pd.Series(ap_1hz)

    if_series = (np_s / ftp).where(np_s > 0, other=np.nan)
    vi_series = (np_s / ap_s.replace(0, np.nan)).where((np_s > 0) & (ap_s > 0), other=np.nan)

    hr_cum = np.full_like(t_1hz, np.nan)
    valid_hr = (~np.isnan(data['hr'])) & (data['hr'] > 30) & (data['hr'] < 250)
    if np.any(valid_hr):
        hr_1hz = _safe_interp1d(offsets[valid_hr], data['hr'][valid_hr], t_1hz)
        hr_cum = _expanding_mean_with_freeze(hr_1hz, is_moving_1hz)

    avg_speed_1hz = _expanding_mean_with_freeze(speed_1hz, is_moving_1hz)

    tss_vals = np.zeros_like(t_1hz, dtype=float)
    if ftp > 0 and lap_np > 0:
        dt = 1.0 / 3600.0
        tss_rate = (np_s.fillna(0).values / ftp) ** 2 * dt * 100.0 * is_moving_1hz
        tss_vals = np.cumsum(tss_rate)

    num_frames = int(duration_sec * metrics_fps) + 1
    video_time = np.arange(num_frames) / metrics_fps

    def _sample(values_1hz):
        if np.all(np.isnan(values_1hz)):
            return np.full_like(video_time, np.nan)
        indices = np.clip(np.round(video_time).astype(int), 0, len(values_1hz) - 1)
        return values_1hz[indices]

    return {
        'time': video_time,
        'ap': _sample(ap_1hz),
        'np': _sample(np_cum_1hz),
        'hr': _sample(hr_cum),
        'tss': _sample(tss_vals),
        'ftp': ftp,
        'if': _sample(if_series.fillna(0).values),
        'vi': _sample(vi_series.fillna(0).values),
        'avg_speed': _sample(avg_speed_1hz),
        'lap_np': lap_np,
    }


# ============================================================
# === 渲染
# ============================================================
def render_gamma_frames(metrics, duration, metrics_fps, frame_dir, params):
    plt.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.weight"] = "normal"
    plt.rcParams["font.size"] = params.get('font_size', 22)
    width, height = params["width"], params["height"]
    font_size = params["font_size"]
    font_color = params["font_color"]
    bg_color = params["bg_color"]
    bg_alpha = params["bg_alpha"]
    print_interval = params["print_interval"]

    os.makedirs(frame_dir, exist_ok=True)
    for f in os.listdir(frame_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frame_dir, f))

    plt.ioff()
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0.05, 1, 0.9])
    ax.axis('off')

    ftp_val = metrics.get('ftp', 250)
    text_obj = ax.text(
        0.05, 0.40, "",
        fontsize=params.get('font_size', 22),
        fontweight='normal',   # ★ 显式指定
        color='white',
        bbox=dict(facecolor=bg_color, alpha=bg_alpha, boxstyle='round,pad=0.25'),
        transform=ax.transAxes, linespacing=1.5,
    )

    num_frames = len(metrics['time'])
    t_start = time.time()
    last_print = t_start

    for idx in range(num_frames):
        now = time.time()
        if now - last_print >= print_interval:
            elapsed = now - t_start
            processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (num_frames - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Gamma] {processed}/{num_frames}帧 | 已用 {elapsed:.1f}s | "
                  f"剩余 {remaining:.1f}s | {fps_actual:.1f}帧/s")
            last_print = now

        def _fmt(val, fmt, na="--"):
            return fmt.format(val) if not np.isnan(val) else na

        display = (
            f"FTP:{ftp_val:.0f}W  AP:{_fmt(metrics['ap'][idx], '{:.0f}W')}  "
            f"NP:{_fmt(metrics['np'][idx], '{:.0f}W')}\n"
            f"IF:{_fmt(metrics['if'][idx], '{:.2f}')}    "
            f"VI:{_fmt(metrics['vi'][idx], '{:.2f}')}  "
            f"TSS:{_fmt(metrics['tss'][idx], '{:.0f}', '0')}\n"
            f"AvgHR:{_fmt(metrics['hr'][idx], '{:.0f}')}  "
            f"AvgSPD:{_fmt(metrics['avg_speed'][idx], '{:.1f}')}km/h"
        )
        text_obj.set_text(display)
        fig.savefig(
            os.path.join(frame_dir, f"frame_{idx:06d}.png"),
            dpi=100, pad_inches=0, transparent=True,
        )

    plt.close(fig)
    elapsed = time.time() - t_start
    print(f"[Gamma] ✅ 渲染完成 {num_frames} 帧, 耗时 {elapsed:.1f}s")
    return num_frames


def assemble_gamma_mov(frame_dir, output_file, frame_count, fps):
    global FFMPEG_PATH
    if frame_count == 0:
        return False
    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, check=True)
    except Exception:
        print(f"[Gamma] ❌ ffmpeg 不可用: {FFMPEG_PATH}")
        return False

    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-vf", f"scale={DEFAULT_PARAMS['width']}:{DEFAULT_PARAMS['height']},setsar=1",
        "-c:v", "prores_ks", "-profile:v", "4", "-vendor", "apl0",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file,
    ]
    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        print(f"[Gamma] ❌ ffmpeg 合成失败: {r.stderr[:500]}")
        return False
    return True


# ============================================================
# === CLI 交互（与 Beta 一致：全程可 q 退出，FPS=0 跳过）
# ============================================================
def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(os.path.join(p, f) for f in os.listdir(p)
                         if f.lower().endswith(".fit"))
    return sorted(set(files))


def _input_or_quit(prompt, default, cast=int):
    """回车=默认, q=退出(SystemExit), 非法=默认"""
    raw = input(prompt).strip().lower()
    if raw == "q":
        print("👋 已取消")
        raise SystemExit(0)
    if raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        print(f"⚠️ 输入无效，使用默认值 {default}")
        return default


def select_laps(fit_path):
    """选择 Lap（可多选逗号分隔）。返回 (lap_start, lap_end, selected_nums, covered_nums)"""
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
        return None, None, None, None

    tz = DEFAULT_PARAMS.get("timezone_offset", 8)
    for num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{num}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")

    choice = input("选择 Lap (q退出，支持多选逗号分隔，如 1,3): ").strip().lower()
    if choice == "q":
        print("👋 已取消"); return None, None, None, None
    try:
        nums = sorted({int(x.strip()) for x in choice.split(',') if x.strip()})
    except ValueError:
        print("❌ 输入无效，请重新输入")
        return select_laps(fit_path)
    if not (1 <= min(nums) <= max(nums) <= len(laps)):
        print(f"❌ 请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)

    idxs = [n - 1 for n in nums]
    covered = list(range(min(idxs), max(idxs) + 1))
    return laps[min(idxs)][1], laps[max(idxs)][2], nums, covered


def main():
    print("=" * 56)
    print("Gamma 模块 - 训练指标视频生成器 (独立模式)")
    print("提示: 通过 generate_gamma_metrics_video(**kwargs) 编程调用可跳过交互")
    print("=" * 56 + "\n")

    # 1. 选文件
    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 FIT 文件（扫描了 . / ./data / ./fit / ./activities）")
        return
    for i, f in enumerate(fits, start=1):
        print(f"[{i}] {f}")
    choice = input("选择文件 (q退出): ").strip().lower()
    if choice == "q":
        print("👋 已取消"); return
    try:
        file_no = int(choice)
        if not (1 <= file_no <= len(fits)):
            raise ValueError
    except ValueError:
        print("❌ 无效选择"); return
    fit_path = fits[file_no - 1]

    # 2. 选 Lap
    lap_start, lap_end, selected_nums, covered_nums = select_laps(fit_path)
    if lap_start is None:
        return

    # 3. 参数（FTP / FPS；FPS=0 跳过；全程可 q）
    ftp = _input_or_quit(f"FTP (回车默认{DEFAULT_PARAMS['ftp']}): ", DEFAULT_PARAMS['ftp'])
    fps = _input_or_quit(f"帧率 (0=跳过, 回车默认{DEFAULT_PARAMS['fps']}): ", DEFAULT_PARAMS['fps'])

    if fps <= 0:
        print("ℹ️ 帧率为 0，无需生成")
        return

    # 4. CLI 模式：清理已存在的帧目录（避免脏数据）
    if os.path.exists(FRAMES_DIR):
        print(f"[Gamma] 检测到已存在帧目录 {FRAMES_DIR}，CLI 模式将覆盖清理")
        shutil.rmtree(FRAMES_DIR)

    # 5. 执行（cleanup=True：合成后自清理，并记录 cleanup_time）
    t0 = time.time()
    try:
        result = generate_gamma_metrics_video(
            fit_path, lap_start, lap_end,
            generate_gamma=True,
            fps=fps,
            cleanup=True,                  # CLI：自清理
            params_dict={"ftp": ftp},
            selected_nums=selected_nums,
            covered_nums=covered_nums,
        )
    except Exception as e:
        print(f"[Gamma] ❌ 运行失败: {e}")
        traceback.print_exc()
        return
    total = time.time() - t0

    # 6. 报告
    m, s = divmod(int(total), 60)
    if result.get("gamma_video") and os.path.exists(result["gamma_video"]):
        print(f"[Gamma] ✅ 视频: {result['gamma_video']}")
    print(f"[Gamma] ⏱️ 总用时: {m}分{s}秒 ({total:.2f}s)")
    if result.get("cleanup_time") is not None:
        print(f"[Gamma] 🧹 清理用时: {result['cleanup_time']:.2f}s")


if __name__ == "__main__":
    main()
