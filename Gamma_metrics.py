import os
import numpy as np
import pandas as pd
from fitparse import FitFile
import matplotlib
matplotlib.use('Agg')  # 必须在 import pyplot 之前设置，确保无显示环境下正常工作
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import time
from datetime import datetime, timedelta
import shutil
import sys
import subprocess

# ============================================================
# === gamma: training metrics video (Strava-like NP/AP/IF/VI/TSS)
# ============================================================

# ==================== 字体初始化 ====================
plt.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ==================== 可配置参数（call 代码会通过模块对象覆盖这些） ====================
METRICS_FPS = 1
METRICS_FTP = 250
METRICS_WIDTH, METRICS_HEIGHT = 480, 270
METRICS_FONT_SIZE = 22

# Strava-like NP：25s EMA（核心参数）
EMA_SPAN = 25

IF_MIN_VALID_SECONDS = 30
SPEED_MIN_KMH = 3.0
PRINT_INTERVAL = 5

# call 代码会覆盖这个路径（指向打包内或系统 PATH 的 ffmpeg）
FFMPEG_PATH = "ffmpeg"

# call 代码会覆盖这些路径，确保输出受控于 GUI 的输出目录
OUTPUT_DIR_GAMMA = "frames_gamma"
OUTPUT_MOV_GAMMA = None

# ==================== 核心函数 ====================

def generate_gamma_metrics_video(
    fit_path,
    lap_start,
    lap_end,
    selected_nums=None,
    covered_nums=None,
    ftp=None,
    metrics_fps=None
):
    """
    从 FIT 文件生成训练指标视频（AP/NP/HR/TSS/IF/VI/Speed）
    
    参数:
    ----------
    fit_path : str
        FIT 文件路径
    lap_start : datetime
        起始时间（多个 Lap 合并后的最早时间）
    lap_end : datetime
        结束时间（多个 Lap 合并后的最晚时间）
    selected_nums : list of int, 可选
        用户选中的 Lap 编号（1-based），用于日志显示
    covered_nums : list of int, 可选
        覆盖的 Lap 编号区间，用于日志显示
    ftp : int, 可选
        功能阈值功率，None 则使用模块级 METRICS_FTP
    metrics_fps : int, 可选
        视频帧率，None 则使用模块级 METRICS_FPS
        
    返回值:
    ----------
    dict : {'gamma_metrics_video': 输出文件路径} 或 {}
    """
    global OUTPUT_MOV_GAMMA

    if ftp is None:
        ftp = METRICS_FTP
    if metrics_fps is None:
        metrics_fps = METRICS_FPS

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长：{duration}秒")

    # 如果 call 代码没有显式设置 OUTPUT_MOV_GAMMA，则使用默认命名
    if OUTPUT_MOV_GAMMA is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        OUTPUT_MOV_GAMMA = f"gamma_metrics_{timestamp}.mov"

    print("\n=== Gamma 训练指标视频配置 ===")
    if selected_nums and covered_nums:
        print(f"选中 Lap: {', '.join(map(str, selected_nums))}")
        print(f"覆盖 Lap 区间: {covered_nums[0]} → {covered_nums[-1]} ({len(covered_nums)} 个 Lap)")
    print(f"时间范围: {lap_start.strftime('%H:%M:%S')} → {lap_end.strftime('%H:%M:%S')}")
    print(f"Lap时长: {duration:.1f}秒")
    print(f"帧率: {metrics_fps} Hz")
    print(f"预期帧数: {int(duration * metrics_fps) + 1}")
    print(f"FTP: {ftp} W")
    print(f"输出视频: {OUTPUT_MOV_GAMMA}")
    print(f"FFMPEG_PATH: {FFMPEG_PATH}")
    print("===============================\n")

    print("[步骤1/4] 加载 FIT 数据...")
    raw = load_and_filter(fit_path, lap_start, lap_end)

    print("[步骤2/4] 计算指标 (AP/NP/HR/TSS/IF/VI/Speed)...")
    metrics = interpolate_metrics(raw, duration, metrics_fps, ftp)

    print(f"[DEBUG] lap_np (Strava-like) = {metrics.get('lap_np', float('nan')):.1f} W")
    print(f"[DEBUG] TSS[-1] = {metrics['tss'][-1]:.1f}")
    print(f"[DEBUG] AP[-1] = {metrics['ap'][-1]:.0f} W")
    print(f"[DEBUG] HR[-1] = {metrics['hr'][-1]:.0f} bpm")
    print(f"[DEBUG] AvgSpeed[-1] = {metrics['avg_speed'][-1]:.1f} km/h")

    print("[步骤3/4] 渲染帧...")
    frame_count = render_gamma_frames(metrics, duration, metrics_fps)

    if frame_count == 0:
        print("❌ 未生成任何帧")
        return {}

    print("[步骤4/4] 合成视频...")
    success = assemble_gamma_mov(
        OUTPUT_DIR_GAMMA, OUTPUT_MOV_GAMMA, frame_count, metrics_fps
    )

    # 清理临时帧目录
    if os.path.exists(OUTPUT_DIR_GAMMA):
        shutil.rmtree(OUTPUT_DIR_GAMMA)

    if success:
        print(f"✅ Gamma 指标视频生成成功: {OUTPUT_MOV_GAMMA}")
        return {'gamma_metrics_video': OUTPUT_MOV_GAMMA}
    else:
        return {}

# ==================== 数据处理 ====================

def load_and_filter(fit_path, start_abs_time, end_abs_time):
    fit = FitFile(fit_path)
    offsets, power, hr, speed = [], [], [], []

    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None or not (start_abs_time <= ts <= end_abs_time):
            continue

        offsets.append((ts - start_abs_time).total_seconds())
        power.append(vals.get('power', 0) or 0)
        hr.append(vals.get('heart_rate', np.nan))

        s = vals.get('enhanced_speed', vals.get('speed', np.nan))
        if s is not None and not np.isnan(float(s)):
            speed.append(float(s) * 3.6)
        else:
            speed.append(np.nan)

    if not offsets:
        raise RuntimeError("指定时间范围内无有效数据")

    print(f"[DEBUG] 加载完成: {len(offsets)} 条记录")
    valid_speeds = [s for s in speed if not np.isnan(s)]
    if valid_speeds:
        print(f"[DEBUG] 速度范围: {min(valid_speeds):.1f} → {max(valid_speeds):.1f} km/h")

    return {
        'offsets': np.array(offsets),
        'power': np.array(power),
        'hr': np.array(hr),
        'speed': np.array(speed)
    }


def safe_interp1d(x, y, x_new):
    if len(x) == 0:
        return np.full_like(x_new, np.nan)
    sort_idx = np.argsort(x)
    x = x[sort_idx]
    y = y[sort_idx]
    interp_func = interp1d(
        x, y, kind='linear', bounds_error=False, fill_value=np.nan
    )
    return interp_func(x_new)


def calculate_np_cum(power_series, ema_span=EMA_SPAN):
    """
    Strava-like Weighted Average Power
    - 25s EMA
    - 不过滤 0W
    - 不人为置 NaN
    """
    power_series = pd.Series(power_series).fillna(0)

    ema = power_series.ewm(
        span=ema_span,
        adjust=False,
        min_periods=1
    ).mean()

    ema_4th = ema ** 4
    cum_mean_4th = ema_4th.expanding(min_periods=1).mean()
    np_cum = np.power(cum_mean_4th, 0.25)

    lap_np = np_cum.iloc[-1]
    return np_cum, lap_np


def interpolate_metrics(data, duration_sec, metrics_fps, ftp):
    offsets = data['offsets']
    high_res_time_1hz = np.linspace(0, duration_sec, int(duration_sec) + 1)

    valid_power_mask = ~np.isnan(data['power'])
    if not np.any(valid_power_mask):
        raise ValueError("无有效功率数据")

    power_1hz = safe_interp1d(
        offsets[valid_power_mask],
        data['power'][valid_power_mask],
        high_res_time_1hz
    )
    power_series_1hz = pd.Series(power_1hz)

    # AP
    ap_series_1hz = power_series_1hz.expanding(min_periods=1).mean()

    # NP（Strava-like）
    np_cum_1hz, lap_np = calculate_np_cum(power_series_1hz)
    if np.isnan(lap_np) or lap_np <= 0:
        lap_np = ap_series_1hz.iloc[-1]
        print(f"[WARN] NP不可用，使用AP替代: {lap_np:.0f}W")

    # IF / VI
    if_series = (np_cum_1hz / ftp).where(np_cum_1hz.notna(), other=np.nan)
    ap_safe = ap_series_1hz.replace(0, np.nan)
    vi_series = (np_cum_1hz / ap_safe).where(
        (np_cum_1hz.notna()) & (ap_safe.notna()), other=np.nan
    )

    valid_count_for_if = np_cum_1hz.notna().cumsum()
    if_mask = valid_count_for_if >= IF_MIN_VALID_SECONDS
    if_series = if_series.where(if_mask, other=np.nan)
    vi_series = vi_series.where(if_mask, other=np.nan)

    # HRavg
    valid_hr_mask = (~np.isnan(data['hr'])) & (data['hr'] > 30) & (data['hr'] < 250)
    hr_cum = pd.Series(np.full_like(high_res_time_1hz, np.nan))
    if np.any(valid_hr_mask):
        hr_1hz = safe_interp1d(
            offsets[valid_hr_mask], data['hr'][valid_hr_mask], high_res_time_1hz
        )
        hr_cum = pd.Series(hr_1hz).expanding(min_periods=1).mean()

    # Avg Speed
    valid_speed_mask = (~np.isnan(data['speed'])) & (data['speed'] >= SPEED_MIN_KMH)
    avg_speed_1hz = pd.Series(np.full_like(high_res_time_1hz, np.nan))
    if np.any(valid_speed_mask):
        speed_1hz = safe_interp1d(
            offsets[valid_speed_mask],
            data['speed'][valid_speed_mask],
            high_res_time_1hz
        )
        speed_series_1hz = pd.Series(speed_1hz)
        speed_valid = speed_series_1hz.where(speed_series_1hz >= SPEED_MIN_KMH)
        avg_speed_1hz = speed_valid.expanding(min_periods=1).mean()

    # TSS（微分累计）
    tss_vals = np.zeros_like(high_res_time_1hz, dtype=float)
    if ftp > 0 and not np.all(np.isnan(np_cum_1hz)):
        np_safe = np_cum_1hz.fillna(0)
        dt_hours = 1.0 / 3600.0
        tss_rate = (np_safe / ftp) ** 2 * dt_hours * 100.0
        tss_vals = np.cumsum(tss_rate.values)
        tss_vals[np_cum_1hz.isna()] = 0

    # 插值到视频帧率
    video_time = np.linspace(0, duration_sec, int(duration_sec * metrics_fps) + 1)

    def interp_to_video(values):
        if np.all(np.isnan(values)):
            return np.full_like(video_time, np.nan)
        f = interp1d(
            high_res_time_1hz, values,
            kind='linear', bounds_error=False, fill_value=np.nan
        )
        return f(video_time)

    return {
        'time': video_time,
        'ap': interp_to_video(ap_series_1hz.values),
        'np': interp_to_video(np_cum_1hz.values),
        'hr': interp_to_video(hr_cum.values),
        'tss': interp_to_video(tss_vals),
        'ftp': ftp,
        'if': interp_to_video(if_series.values),
        'vi': interp_to_video(vi_series.values),
        'avg_speed': interp_to_video(avg_speed_1hz.values),
        'lap_np': lap_np
    }


# ==================== 渲染（单 bbox · 三排 HUD） ====================

def render_gamma_frames(metrics, duration, metrics_fps):
    os.makedirs(OUTPUT_DIR_GAMMA, exist_ok=True)
    for f in os.listdir(OUTPUT_DIR_GAMMA):
        if f.startswith("frame_"):
            os.remove(os.path.join(OUTPUT_DIR_GAMMA, f))

    plt.ioff()
    fig, ax = plt.subplots(
        figsize=(METRICS_WIDTH / 100, METRICS_HEIGHT / 100), dpi=100
    )
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0.05, 1, 0.9])
    ax.axis('off')

    ftp_val = metrics.get('ftp', 250)

    text_obj = ax.text(
        0.05, 0.40, "",
        fontsize=METRICS_FONT_SIZE,
        color='white',
        bbox=dict(facecolor='black', alpha=0.4, boxstyle='round,pad=0.25'),
        transform=ax.transAxes,
        linespacing=1.5
    )

    num_frames = len(metrics['time'])
    start_time = time.time()
    last_print_time = time.time()

    for idx in range(num_frames):
        current_time = time.time()
        if current_time - last_print_time >= PRINT_INTERVAL:
            elapsed = current_time - start_time
            processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (num_frames - processed) / fps_actual if fps_actual > 0 else 0
            print(
                f"[Gamma_Metrics] {processed}/{num_frames}帧 | "
                f"已用: {elapsed:.1f}s | 剩余: {remaining:.1f}s | "
                f"速度: {fps_actual:.1f}帧/s"
            )
            last_print_time = current_time

        # Row 1
        ftp_text = f"{ftp_val:.0f}W"
        ap_val = metrics['ap'][idx]
        ap_text = f"{ap_val:.0f}W" if not np.isnan(ap_val) else "--"
        np_val = metrics['np'][idx]
        np_text = f"{np_val:.0f}W" if not np.isnan(np_val) else "--"

        # Row 2
        if_val = metrics['if'][idx]
        if_text = f"{if_val:.2f}" if not np.isnan(if_val) else "--"
        vi_val = metrics['vi'][idx]
        vi_text = f"{vi_val:.2f}" if not np.isnan(vi_val) else "--"
        tss_val = metrics['tss'][idx]
        tss_text = f"{tss_val:.0f}" if not np.isnan(tss_val) else "0"

        # Row 3
        hr_val = metrics['hr'][idx]
        hr_text = f"{hr_val:.0f}" if not np.isnan(hr_val) else "--"
        spd_val = metrics['avg_speed'][idx]
        spd_text = f"{spd_val:.1f}" if not np.isnan(spd_val) else "--"

        display_text = (
            f"FTP:{ftp_text}  AP:{ap_text}  NP:{np_text}\n"
            f"IF:{if_text}    VI:{vi_text}  TSS:{tss_text}\n"
            f"AvgHR:{hr_text} AvgSPD:{spd_text}km/h"
        )

        text_obj.set_text(display_text)
        path = os.path.join(OUTPUT_DIR_GAMMA, f"frame_{idx:06d}.png")
        fig.savefig(path, dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    print(f"✅ Gamma 渲染完成，总耗时 {time.time() - start_time:.1f} 秒")
    return num_frames


def assemble_gamma_mov(frame_dir, output_file, frame_count, fps):
    """
    使用 ffmpeg 合成 ProRes 4444 透明视频
    注意：-profile:v 4 是 ffmpeg 对 ProRes 4444 的标准写法
    -vendor apl0 确保 QuickTime/Final Cut 兼容
    """
    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-vf", f"scale={METRICS_WIDTH}:{METRICS_HEIGHT},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4",               # ProRes 4444 标准写法
        "-vendor", "apl0",               # QuickTime 兼容标识
        "-pix_fmt", "yuva444p10le",      # 10bit YUV + Alpha 通道
        "-frames:v", str(frame_count),
        output_file
    ]

    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        print(f"❌ ffmpeg 合成失败: {result.stderr[:500]}")
        return False
    return True


# ==================== CLI（独立运行时的交互入口，被 import 时不执行） ====================

def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(
                [os.path.join(p, f) for f in os.listdir(p)
                 if f.lower().endswith(".fit")]
            )
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
        print("⚠️ 无有效 Lap")
        return None, None, None, None

    for display_num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{display_num}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")

    choice = input("选择 Lap (q退出，支持多选，逗号分隔，如1,3): ").strip().lower()
    if choice == "q":
        return None, None, None, None

    try:
        selected_nums = sorted({int(x.strip()) for x in choice.split(',')})
    except ValueError:
        print("❌ 输入无效，请输入数字并用逗号分隔（如1,3）")
        return select_laps(fit_path)

    if not (1 <= min(selected_nums) <= max(selected_nums) <= len(laps)):
        print(f"❌ 无效选择，请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)

    selected_indices = [num - 1 for num in selected_nums]
    min_idx = min(selected_indices)
    max_idx = max(selected_indices)
    covered_nums = list(range(min_idx + 1, max_idx + 2))

    return laps[min_idx][1], laps[max_idx][2], selected_nums, covered_nums


def main():
    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 FIT 文件")
        return

    for display_num, f in enumerate(fits, start=1):
        print(f"[{display_num}] {f}")
    choice = input("选择文件 (q退出): ").strip().lower()
    if choice == "q":
        return

    file_no = int(choice)
    if not (1 <= file_no <= len(fits)):
        print("❌ 无效选择")
        return
    fit_path = fits[file_no - 1]

    lap_start, lap_end, selected_nums, covered_nums = select_laps(fit_path)
    if lap_start is None:
        return

    ftp = int(input("FTP (回车默认250): ") or 250)
    fps = int(input("帧率 (回车默认1): ") or 1)

    generate_gamma_metrics_video(
        fit_path, lap_start, lap_end,
        selected_nums, covered_nums, ftp, fps
    )


if __name__ == "__main__":
    main()