import os
import numpy as np
import pandas as pd
from fitparse import FitFile
import matplotlib
matplotlib.use('Agg')
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

# ==================== 可配置参数 ====================
METRICS_FPS = 1
METRICS_FTP = 250
METRICS_WIDTH, METRICS_HEIGHT = 480, 270
METRICS_FONT_SIZE = 22

EMA_SPAN = 25
IF_MIN_VALID_SECONDS = 30
SPEED_MIN_KMH = 3.0
PRINT_INTERVAL = 5

FFMPEG_PATH = "ffmpeg"
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
    global OUTPUT_MOV_GAMMA

    if ftp is None:
        ftp = METRICS_FTP
    if metrics_fps is None:
        metrics_fps = METRICS_FPS

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长：{duration}秒")

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
    print(f"停车判定阈值: 速度 < {SPEED_MIN_KMH} km/h 时冻结所有指标")
    print(f"输出视频: {OUTPUT_MOV_GAMMA}")
    print("===============================\n")

    print("[步骤1/4] 加载 FIT 数据...")
    raw = load_and_filter(fit_path, lap_start, lap_end)

    print("[步骤2/4] 计算指标 (AP/NP/HR/TSS/IF/VI/Speed)...")
    metrics = interpolate_metrics(raw, duration, metrics_fps, ftp)

    print("[步骤3/4] 渲染帧...")
    frame_count = render_gamma_frames(metrics, duration, metrics_fps)

    if frame_count == 0:
        print("❌ 未生成任何帧")
        return {}

    print("[步骤4/4] 合成视频...")
    success = assemble_gamma_mov(
        OUTPUT_DIR_GAMMA, OUTPUT_MOV_GAMMA, frame_count, metrics_fps
    )

    if os.path.exists(OUTPUT_DIR_GAMMA):
        shutil.rmtree(OUTPUT_DIR_GAMMA)

    if success:
        print(f"✅ Gamma 指标视频生成成功: {OUTPUT_MOV_GAMMA}")
        return {'gamma_metrics_video': OUTPUT_MOV_GAMMA}
    else:
        return {}

# ==================== 数据处理（Alpha风格） ====================

def load_and_filter(fit_path, start_abs_time, end_abs_time):
    fit = FitFile(fit_path)
    offsets, power, hr, speed, is_stopped = [], [], [], [], []

    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None or not (start_abs_time <= ts <= end_abs_time):
            continue

        offsets.append((ts - start_abs_time).total_seconds())

        p = vals.get('power', np.nan)
        power.append(p if not (p is None or np.isnan(p)) else np.nan)

        h = vals.get('heart_rate', np.nan)
        hr.append(h if not (h is None or np.isnan(h)) else np.nan)

        s = vals.get('enhanced_speed', vals.get('speed', np.nan))
        if s is not None and not np.isnan(float(s)):
            speed_kmh = float(s) * 3.6
            if speed_kmh < SPEED_MIN_KMH:
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


def expanding_mean_with_freeze(values, is_moving):
    result = np.full_like(values, np.nan)
    seg_sum = 0.0
    seg_count = 0

    for i in range(len(values)):
        if is_moving[i] and not np.isnan(values[i]):
            seg_sum += values[i]
            seg_count += 1
            result[i] = seg_sum / seg_count
        elif seg_count > 0:
            result[i] = seg_sum / seg_count

    return result


def calculate_np_cum(power_series, is_moving, ema_span=EMA_SPAN):
    ps = pd.Series(power_series)

    ema = ps.where(is_moving).ewm(
        span=ema_span, adjust=False, min_periods=1
    ).mean()

    ema_4th = ema ** 4
    result = np.full(len(ps), np.nan)

    seg_sum_4th = 0.0
    seg_count = 0

    for i in range(len(ps)):
        if is_moving[i] and not np.isnan(ema_4th[i]):
            seg_sum_4th += ema_4th[i]
            seg_count += 1
            result[i] = (seg_sum_4th / seg_count) ** 0.25
        elif seg_count > 0:
            result[i] = (seg_sum_4th / seg_count) ** 0.25

    lap_np = 0
    if np.any(is_moving):
        valid_np = result[is_moving]
        if len(valid_np) > 0:
            lap_np = valid_np[-1]

    return result, lap_np


def interpolate_metrics(data, duration_sec, metrics_fps, ftp):
    offsets = data['offsets']
    num_1hz_points = int(np.ceil(duration_sec)) + 1
    high_res_time_1hz = np.linspace(0, duration_sec, num_1hz_points)

    valid_speed_mask = ~np.isnan(data['speed'])
    speed_1hz = safe_interp1d(
        offsets[valid_speed_mask],
        data['speed'][valid_speed_mask],
        high_res_time_1hz
    )

    is_stopped_original = data['is_stopped']
    is_moving_1hz = np.ones_like(high_res_time_1hz, dtype=bool)

    for i, t in enumerate(high_res_time_1hz):
        idx = np.searchsorted(offsets, t, side='right') - 1
        if idx >= 0 and idx < len(is_stopped_original):
            if is_stopped_original[idx]:
                is_moving_1hz[i] = False

    valid_power_mask = ~np.isnan(data['power'])
    power_1hz = safe_interp1d(
        offsets[valid_power_mask],
        data['power'][valid_power_mask],
        high_res_time_1hz
    )

    ap_series_1hz = expanding_mean_with_freeze(power_1hz, is_moving_1hz)
    np_cum_1hz, lap_np = calculate_np_cum(power_1hz, is_moving_1hz)

    if lap_np <= 0:
        lap_np = ap_series_1hz[is_moving_1hz][-1] if np.any(is_moving_1hz) else 0

    np_s = pd.Series(np_cum_1hz)
    ap_s = pd.Series(ap_series_1hz)

    if_series = (np_s / ftp).where(np_s > 0, other=np.nan)
    vi_series = (np_s / ap_s.replace(0, np.nan)).where(
        (np_s > 0) & (ap_s > 0), other=np.nan
    )

    valid_hr_mask = (~np.isnan(data['hr'])) & (data['hr'] > 30) & (data['hr'] < 250)
    hr_cum = np.full_like(high_res_time_1hz, np.nan)
    if np.any(valid_hr_mask):
        hr_1hz = safe_interp1d(
            offsets[valid_hr_mask], data['hr'][valid_hr_mask], high_res_time_1hz
        )
        hr_cum = expanding_mean_with_freeze(hr_1hz, is_moving_1hz)

    avg_speed_1hz = expanding_mean_with_freeze(speed_1hz, is_moving_1hz)

    tss_vals = np.zeros_like(high_res_time_1hz, dtype=float)
    if ftp > 0 and lap_np > 0:
        np_safe = np_s.fillna(0).values
        dt_hours = 1.0 / 3600.0
        tss_rate = (np_safe / ftp) ** 2 * dt_hours * 100.0
        tss_rate = tss_rate * is_moving_1hz
        tss_vals = np.cumsum(tss_rate)

    num_video_frames = int(duration_sec * metrics_fps) + 1
    video_time = np.arange(num_video_frames) / metrics_fps

    def sample_to_video(values_1hz):
        if np.all(np.isnan(values_1hz)):
            return np.full_like(video_time, np.nan)
        indices = np.round(video_time).astype(int)
        indices = np.clip(indices, 0, len(values_1hz) - 1)
        return values_1hz[indices]

    return {
        'time': video_time,
        'ap': sample_to_video(ap_series_1hz),
        'np': sample_to_video(np_cum_1hz),
        'hr': sample_to_video(hr_cum),
        'tss': sample_to_video(tss_vals),
        'ftp': ftp,
        'if': sample_to_video(if_series.fillna(0).values),
        'vi': sample_to_video(vi_series.fillna(0).values),
        'avg_speed': sample_to_video(avg_speed_1hz),
        'lap_np': lap_np
    }


# ==================== 渲染 ====================

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

        ftp_text = f"{ftp_val:.0f}W"
        ap_val = metrics['ap'][idx]
        ap_text = f"{ap_val:.0f}W" if not np.isnan(ap_val) else "--"
        np_val = metrics['np'][idx]
        np_text = f"{np_val:.0f}W" if not np.isnan(np_val) else "--"

        if_val = metrics['if'][idx]
        if_text = f"{if_val:.2f}" if not np.isnan(if_val) else "--"
        vi_val = metrics['vi'][idx]
        vi_text = f"{vi_val:.2f}" if not np.isnan(vi_val) else "--"
        tss_val = metrics['tss'][idx]
        tss_text = f"{tss_val:.0f}" if not np.isnan(tss_val) else "0"

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
    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-vf", f"scale={METRICS_WIDTH}:{METRICS_HEIGHT},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4",
        "-vendor", "apl0",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        output_file
    ]

    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        print(f"❌ ffmpeg 合成失败: {result.stderr[:500]}")
        return False
    return True


# ==================== CLI ====================

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