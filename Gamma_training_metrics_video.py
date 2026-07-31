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

# ==================== 字体初始化 ====================
plt.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ==================== 可配置参数 ====================
METRICS_FPS = 1
METRICS_FTP = 250
METRICS_WIDTH, METRICS_HEIGHT = 480, 270
METRICS_FONT_SIZE = 25
NP_WINDOW_SECONDS = 30
PRINT_INTERVAL = 5

FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR_METRICS = "frames_metrics"
OUTPUT_MOV_METRICS = None

# ==================== 核心函数 ====================

def generate_training_metrics_video(fit_path, lap_start, lap_end, ftp=None, metrics_fps=None):
    global OUTPUT_MOV_METRICS

    if ftp is None:
        ftp = METRICS_FTP
    if metrics_fps is None:
        metrics_fps = METRICS_FPS

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError(f"无效的 Lap 时长：{duration}秒")

    if OUTPUT_MOV_METRICS is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        OUTPUT_MOV_METRICS = f"alpha_metrics_{timestamp}.mov"

    print("\n=== 训练指标视频配置 ===")
    print(f"Lap时段: {lap_start.strftime('%H:%M:%S')} → {lap_end.strftime('%H:%M:%S')}")
    print(f"Lap时长: {duration:.1f}秒")
    print(f"帧率: {metrics_fps} Hz")
    print(f"预期帧数: {int(duration * metrics_fps) + 1}")
    print(f"FTP: {ftp} W")
    print("=========================\n")

    print("[步骤1/4] 加载 FIT 数据...")
    raw = load_and_filter(fit_path, lap_start, lap_end)

    print("[步骤2/4] 计算指标 (AP/NP/HR/TSS)...")
    metrics = interpolate_metrics(raw, duration, metrics_fps, ftp)

    # 调试：打印关键值
    print(f"[DEBUG] lap_np = {metrics.get('lap_np', 'N/A')}")
    print(f"[DEBUG] TSS[0]={metrics['tss'][0]:.1f}, TSS[-1]={metrics['tss'][-1]:.1f}")
    print(f"[DEBUG] AP[-1]={metrics['ap'][-1]:.0f}, HR[-1]={metrics['hr'][-1]:.0f}")

    print("[步骤3/4] 渲染帧...")
    frame_count = render_metrics_frames(metrics, duration, metrics_fps)

    if frame_count == 0:
        print("❌ 未生成任何帧")
        return {}

    print("[步骤4/4] 合成视频...")
    success = assemble_alpha_mov(OUTPUT_DIR_METRICS, OUTPUT_MOV_METRICS, frame_count, metrics_fps)

    if os.path.exists(OUTPUT_DIR_METRICS):
        shutil.rmtree(OUTPUT_DIR_METRICS)

    if success:
        print(f"✅ 训练指标视频生成成功: {OUTPUT_MOV_METRICS}")
        return {'metrics_video': OUTPUT_MOV_METRICS}
    else:
        return {}

# ==================== 数据处理 ====================

def load_and_filter(fit_path, start_abs_time, end_abs_time):
    fit = FitFile(fit_path)
    offsets, power, hr = [], [], []

    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None or not (start_abs_time <= ts <= end_abs_time):
            continue
        offsets.append((ts - start_abs_time).total_seconds())
        power.append(vals.get('power', 0) or 0)
        hr.append(vals.get('heart_rate', np.nan))

    if not offsets:
        raise RuntimeError("指定 Lap 内无有效数据")

    print(f"[DEBUG] 加载完成: {len(offsets)}条记录, 时间范围: {offsets[0]:.1f}s → {offsets[-1]:.1f}s")
    print(f"[DEBUG] 功率范围: {min(power)} → {max(power)} W")
    
    return {
        'offsets': np.array(offsets),
        'power': np.array(power),
        'hr': np.array(hr)
    }

def safe_interp1d(x, y, x_new):
    if len(x) == 0:
        return np.full_like(x_new, np.nan)
    interp_func = interp1d(x, y, kind='linear', bounds_error=False, fill_value=np.nan)
    return interp_func(x_new)

def calculate_lap_np(power, offsets, duration):
    """计算整个 Lap 的 NP，带多重降级策略"""
    if len(power) == 0:
        print("[WARN] 无功率数据")
        return np.nan
    
    # 过滤零功率
    valid_mask = power > 0
    if not np.any(valid_mask):
        print("[WARN] 所有功率值都为0")
        return np.nan
    
    valid_power = power[valid_mask]
    valid_offsets = offsets[valid_mask]
    
    # 方法1：用1Hz重采样 + 30秒滚动窗口
    high_res_time = np.linspace(0, duration, int(duration) + 1)
    high_res_pow = safe_interp1d(valid_offsets, valid_power, high_res_time)
    
    valid_pow = ~np.isnan(high_res_pow) & (high_res_pow > 0)
    valid_count = np.sum(valid_pow)
    
    print(f"[DEBUG] NP计算: 有效功率点 {valid_count}/{len(high_res_pow)}")
    
    if valid_count < NP_WINDOW_SECONDS:
        # 数据太少，退化为直接用平均功率
        avg_pow = np.mean(valid_power)
        print(f"[WARN] 数据不足30秒，NP退化为平均功率: {avg_pow:.0f}W")
        return avg_pow
    
    pow_series = pd.Series(high_res_pow[valid_pow])
    rolling = pow_series.rolling(window=NP_WINDOW_SECONDS, min_periods=NP_WINDOW_SECONDS//2)
    
    def calc_np(win):
        win = win.dropna()
        if len(win) < NP_WINDOW_SECONDS // 2:
            return np.nan
        return (np.mean(win ** 4)) ** 0.25
    
    np_series = rolling.apply(calc_np)
    result = np.nanmean(np_series)
    
    print(f"[DEBUG] NP计算结果: {result:.0f}W")
    return result

def interpolate_metrics(data, duration_sec, metrics_fps, ftp):
    offsets = data['offsets']
    time_points = np.linspace(0, duration_sec, int(duration_sec * metrics_fps) + 1)

    # --- 计算整个 Lap 的 NP ---
    lap_np = calculate_lap_np(data['power'], offsets, duration_sec)
    
    # 如果 NP 失败，用 AP 替代
    if np.isnan(lap_np) or lap_np <= 0:
        valid_pow = data['power'][data['power'] > 0]
        if len(valid_pow) > 0:
            lap_np = np.mean(valid_pow)
            print(f"[WARN] NP不可用，使用AP替代: {lap_np:.0f}W")
        else:
            lap_np = ftp * 0.5  # 最后兜底
            print(f"[WARN] 无有效功率，使用FTP*0.5: {lap_np:.0f}W")

    # --- AP（过滤零功率）---
    valid_pow = data['power'] > 0
    ap_raw = safe_interp1d(offsets[valid_pow], data['power'][valid_pow], time_points)

    ap_cum = np.full_like(time_points, np.nan)
    s, c = 0.0, 0
    for i, v in enumerate(ap_raw):
        if not np.isnan(v) and v > 0:
            s += v
            c += 1
            ap_cum[i] = s / c
        else:
            ap_cum[i] = ap_cum[i-1] if i > 0 and not np.isnan(ap_cum[i-1]) else np.nan

    # --- NP（瞬时，用于显示）---
    np_vals = np.full_like(time_points, np.nan)
    if np.any(valid_pow):
        high_res_t = np.linspace(0, duration_sec, int(duration_sec * 10) + 1)
        high_res_pow = safe_interp1d(offsets[valid_pow], data['power'][valid_pow], high_res_t)

        series = pd.Series(high_res_pow)
        rolled = series.rolling(NP_WINDOW_SECONDS * 10, min_periods=NP_WINDOW_SECONDS * 5)

        def calc_np_inst(win):
            win = win.dropna()
            if len(win) < NP_WINDOW_SECONDS * 5:
                return np.nan
            return (np.mean(win ** 4)) ** 0.25

        np_high_res = rolled.apply(calc_np_inst).values
        np_vals = safe_interp1d(high_res_t, np_high_res, time_points)

    # --- HRavg ---
    valid_hr = ~np.isnan(data['hr'])
    hr_cum = np.full_like(time_points, np.nan)
    if np.any(valid_hr):
        hr_raw = safe_interp1d(offsets[valid_hr], data['hr'][valid_hr], time_points)
        s, c = 0.0, 0
        for i, v in enumerate(hr_raw):
            if not np.isnan(v) and v > 0:
                s += v
                c += 1
                hr_cum[i] = s / c
            else:
                hr_cum[i] = hr_cum[i-1] if i > 0 and not np.isnan(hr_cum[i-1]) else np.nan

    # --- TSS（修正：确保一定会有值）---
    tss_vals = np.zeros_like(time_points)
    if ftp > 0 and not np.isnan(lap_np) and lap_np > 0:
        if_val = lap_np / ftp
        tss_total = (duration_sec * lap_np * if_val) / (ftp * 3600) * 100
        
        print(f"[DEBUG] TSS总计算: duration={duration_sec}s, lap_np={lap_np:.0f}W, "
              f"IF={if_val:.2f}, TSS_total={tss_total:.1f}")
        
        for i in range(len(time_points)):
            t = time_points[i]
            tss_vals[i] = (t / duration_sec) * tss_total
    else:
        print(f"[ERROR] TSS计算条件不满足: ftp={ftp}, lap_np={lap_np}")

    return {
        'time': time_points,
        'ap': ap_cum,
        'np': np_vals,
        'hr': hr_cum,
        'tss': tss_vals,
        'lap_np': lap_np
    }

# ==================== 渲染（HUD 风格）====================

def render_metrics_frames(metrics, duration, metrics_fps):
    os.makedirs(OUTPUT_DIR_METRICS, exist_ok=True)
    
    # 清理旧帧
    for f in os.listdir(OUTPUT_DIR_METRICS):
        if f.startswith("frame_"):
            os.remove(os.path.join(OUTPUT_DIR_METRICS, f))

    plt.ioff()
    fig, ax = plt.subplots(figsize=(METRICS_WIDTH/100, METRICS_HEIGHT/100), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')
    ax.set_position([0, 0.05, 1, 0.9])
    ax.axis('off')

    text_obj = ax.text(
        0.05, 0.4,
        "",
        fontsize=METRICS_FONT_SIZE,
        color='white',
        bbox=dict(facecolor='black', alpha=0.4, boxstyle='round,pad=0.25'),
        transform=ax.transAxes
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
            print(f"[Alpha_Metrics] {processed}/{num_frames}帧 | "
                  f"已用: {elapsed:.1f}s | "
                  f"剩余: {remaining:.1f}s | "
                  f"速度: {fps_actual:.1f}帧/s")
            last_print_time = current_time

        # AP
        ap_val = metrics['ap'][idx]
        ap_text = f"{ap_val:.0f} W" if not np.isnan(ap_val) else "--"
        
        # NP
        np_val = metrics['np'][idx]
        np_text = f"{np_val:.0f} W" if not np.isnan(np_val) else "Calculating..."
        
        # HR
        hr_val = metrics['hr'][idx]
        hr_text = f"{hr_val:.0f} bpm" if not np.isnan(hr_val) else "--"
        
        # TSS
        tss_val = metrics['tss'][idx]

        display_text = (
            f"AP: {ap_text}\n"
            f"NP: {np_text}\n"
            f"HRavg: {hr_text}\n"
            f"TSS: {tss_val:.0f}"
        )

        text_obj.set_text(display_text)

        path = os.path.join(OUTPUT_DIR_METRICS, f"frame_{idx:06d}.png")
        fig.savefig(path, dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    print(f"✅ 渲染完成，总耗时 {time.time() - start_time:.1f} 秒")
    return num_frames

def assemble_alpha_mov(frame_dir, output_file, frame_count, fps):
    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-vf", f"scale={METRICS_WIDTH}:{METRICS_HEIGHT},setsar=1",
        "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", "-frames:v", str(frame_count), output_file
    ]
    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    subprocess.run(cmd, creationflags=CREATE_NO_WINDOW)
    return True

# ==================== CLI ====================

def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend([os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".fit")])
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

    for idx, st, et in laps:
        print(f"[{idx}] {st.strftime('%H:%M:%S')} → {et.strftime('%H:%M:%S')}")

    choice = input("选择 Lap (q退出): ").strip().lower()
    if choice == "q":
        return None, None
    idx = int(choice)
    return laps[idx][1], laps[idx][2]

def main():
    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 FIT 文件")
        return

    for i, f in enumerate(fits):
        print(f"[{i}] {f}")
    choice = input("选择文件 (q退出): ").strip().lower()
    if choice == "q":
        return
    fit_path = fits[int(choice)]

    lap_start, lap_end = select_laps(fit_path)
    if lap_start is None:
        return

    ftp = int(input("FTP (回车默认250): ") or 250)
    fps = int(input("帧率 (回车默认1): ") or 1)

    generate_training_metrics_video(fit_path, lap_start, lap_end, ftp, fps)

if __name__ == "__main__":
    main()

generate_metrics_video = generate_training_metrics_video