
import os
import sys
import glob
import shutil
import subprocess
import time
import math
from datetime import datetime, timedelta
from fitparse import FitFile
import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# 可配置参数（已针对长坡优化）
# ============================================================
DELTA_FPS = 5
DELTA_WIDTH, DELTA_HEIGHT = 720, 80
DELTA_FONT_SIZE = 28
DELTA_PADDING = 12

# ---- 平滑（作用于原始 1Hz 数据）----
ELEV_WEAK_SMOOTH_SEC = 2.0     # 显示海拔弱平滑窗口（秒）
GRAD_STRONG_SMOOTH_SEC = 3.0   # 坡度用强平滑窗口（秒）
GRAD_COMPENSATION_SEC = 1.5    # 相位补偿（秒）≈ 强平滑窗口/2
GRAD_MIN_SPEED_KMH = 3.0       # 低于此速度不显示坡度

# ---- 累计爬升（长坡修复核心参数）----
GAIN_SMOOTH_SEC = 7.0          # 累计爬升用强平滑窗口（秒）
# 移除GAIN_STEP_NOISE：不再对逐点差分做阈值过滤，靠强平滑去噪
GAIN_MIN_HEIGHT_M = 5.0        # 整体最小有效爬升段高度（米）
GAIN_MIN_DIST_M = 50.0         # 整体最小有效爬升段距离（米）

# ---- 字体 / ffmpeg ----
FONT_PATH = None
FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR_DELTA = "frames_delta"
OUTPUT_MOV_DELTA = None
PRINT_INTERVAL = 5.0

# ---- 显示配置（新增）----
GRAD_DISPLAY_DECIMALS = 1  # 坡度显示小数位数：0=整数，1=1位小数，2=2位小数

# ============================================================
# 字体加载
# ============================================================
def load_font(size):
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            return ImageFont.truetype(FONT_PATH, size)
        for name in ("arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# ============================================================
# 交互工具：查找FIT/选择Lap/设置帧率
# ============================================================
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
        return select_laps(fit_path)
    if not (1 <= min(selected_nums) <= max(selected_nums) <= len(laps)):
        print(f"❌ 请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)
    selected_indices = [n - 1 for n in selected_nums]
    return laps[min(selected_indices)][1], laps[max(selected_indices)][2]

def get_fps():
    try:
        val = input(f"帧率 (回车默认{DELTA_FPS}): ").strip()
        return int(val) if val else DELTA_FPS
    except Exception:
        return DELTA_FPS


# ============================================================
# 1) 加载原始1Hz FIT数据（不做插值）
# ============================================================
def load_fit_data(fit_path, lap_start, lap_end):
    print("\n[步骤1/6] 加载 FIT 数据（原始 1Hz record）...")
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

    print(f"  有效记录数: {len(offsets)}")
    print(f"  海拔有效: {sum(~np.isnan(alts))}/{len(alts)}")
    print(f"  距离有效: {sum(~np.isnan(dists))}/{len(dists)}")
    
    offsets = np.array(offsets, dtype=float)
    dt = np.diff(offsets)
    if len(dt) > 0:
        print(f"  采样间隔: min={dt.min():.3f}s mean={dt.mean():.3f}s max={dt.max():.3f}s")
    
    return {
        'offsets': offsets,
        'alts': np.array(alts, dtype=float),
        'dists': np.array(dists, dtype=float),
        'speeds': np.array(speeds, dtype=float),
    }


# ============================================================
# 2) 1Hz网格平滑（核心：先平滑再插值，支持NaN填充）
# ============================================================
def apply_smooth_1hz(values, dt_sec, window_sec, polyorder=2):
    """Savitzky-Golay平滑，窗口按1Hz样本数对齐为奇数，自动处理NaN"""
    window = int(round(window_sec / dt_sec))
    if window % 2 == 0:
        window += 1
    if window < 5 or len(values) < window:
        return values.copy()
    
    # 复制数据，避免修改原数组
    v = values.copy()
    # 填充NaN（线性插值，避免滤波错误）
    valid = ~np.isnan(v)
    if not np.all(valid):
        # 用非NaN的索引和值做插值
        f = interp1d(np.where(valid)[0], v[valid], kind='linear', fill_value="extrapolate")
        v[~valid] = f(np.where(~valid)[0])
    
    return savgol_filter(v, window, polyorder)


# ============================================================
# 3) 坡度计算（速度法，1Hz稳定版）
# ============================================================
def compute_gradient_1hz(alts_smooth, speeds, dt):
    """
    坡度 = dz / (v*dt) * 100%
    使用强平滑后的海拔 + 速度法，对1Hz气压计噪声稳定
    """
    n = len(alts_smooth)
    gradient = np.full(n, np.nan)
    dz = np.diff(alts_smooth)

    v_avg = (speeds[:-1] + speeds[1:]) / 2 #v = speeds[1:].copy()
    v_ms = v_avg / 3.6 #v_ms = v / 3.6  # km/h -> m/s
    denom = v_ms * dt
    with np.errstate(divide='ignore', invalid='ignore'):
        g = dz / denom * 100.0
    
    # 限幅：坡度有效范围±60%，离群置nan
    g = np.where(np.abs(g) > 60, np.nan, g)
    # 低速/无效速度置nan
    valid = (v_ms >= GRAD_MIN_SPEED_KMH / 3.6) & (~np.isnan(v_ms)) & (~np.isnan(g))
    g_out = np.full_like(g, np.nan)
    g_out[valid] = g[valid]
    gradient[1:] = g_out

    # 相位补偿：强平滑带来约window/2的滞后，向前对齐
    shift = int(round(GRAD_COMPENSATION_SEC / dt))
    if shift > 0 and shift < n:
        gradient_shifted = np.full(n, np.nan)
        gradient_shifted[:-shift] = gradient[shift:]
        gradient = gradient_shifted
    return gradient


# ============================================================
# 4) 累计爬升（长坡修复核心：强平滑+无逐点过滤）
# ============================================================
def compute_cumulative_gain_strava(alts_smooth, dists):
    """
    长坡修复版累计爬升（与Strava逻辑对齐）：
    1. 7s强平滑已完全消除气压计逐点噪声，无需再过滤小差分
    2. 仅对差分做3点滑动平均，进一步平滑剩余噪声，不影响缓坡真实上升
    3. 累计所有正差分，不抵消长坡微小回落
    """
    n = len(alts_smooth)
    if n < 2:
        return np.zeros(n)
    
    # 1. 计算平滑后海拔的逐点差分
    dh = np.diff(alts_smooth)
    
    # 2. 对差分做3点滑动平均（仅平滑噪声，不削减真实缓坡上升）
    if len(dh) >= 3:
        dh = np.convolve(dh, np.ones(3)/3, mode='same')
    
    # 3. 累计所有正差分（无阈值过滤，强平滑已去噪）
    gain = np.cumsum(np.maximum(0.0, dh))
    # 对齐长度（cumsum后少1个元素，开头补0）
    gain = np.concatenate(([0.0], gain))
    
    # 4. 诊断信息（关键：对比原始总差和累计爬升）
    raw_alt_diff = alts_smooth[-1] - alts_smooth[0] if n > 1 else 0.0
    total_rise = gain[-1]
    print(f"  [累计爬升诊断] 原始海拔总差: {raw_alt_diff:.1f}m | 算法累计爬升: {total_rise:.1f}m")
    print(f"  [长坡修复] 使用{GAIN_SMOOTH_SEC}s强平滑，无逐点差分过滤")
    
    # 5. 整体有效性判断（仅过滤无意义的小活动）
    total_dist = 0.0
    if n > 1 and not np.isnan(dists[0]) and not np.isnan(dists[-1]):
        total_dist = dists[-1] - dists[0]
    if total_dist < 0:
        total_dist = 0.0
    
    if total_rise < GAIN_MIN_HEIGHT_M or total_dist < GAIN_MIN_DIST_M:
        print(f"  [有效性过滤] 总爬升{total_rise:.1f}m < {GAIN_MIN_HEIGHT_M}m 或 总距离{total_dist:.1f}m < {GAIN_MIN_DIST_M}m，累计置0")
        return np.zeros(n)
    return gain


# ============================================================
# 5) 坡度显示裁剪（修复原NumPy赋值错误）
# ============================================================
def clip_gradient_display(gradients, lo=0.1, hi=40.0):
    """仅用于HUD显示裁剪，极小/极端坡度置NaN"""
    out = gradients.copy()
    # 绝对值小于lo的极小坡度，直接赋值为0.0
    out[np.abs(out) < lo] = 0.0 
    # 超出合理范围的极端坡度，仍置为NaN，显示--%
    out[np.abs(out) > hi] = np.nan
    return out


# ============================================================
# 6) 插值到FPS（仅用于显示，不影响计算结果）
# ============================================================
def interpolate_to_fps(arrays_dict, duration_sec, fps):
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
# 格式化 / 渲染 / 视频合成
# ============================================================
def format_elevation(val):
    return "Elev:    ---- m" if np.isnan(val) else f"Elev: {val:>6.1f} m"

def format_gradient(val):
    if np.isnan(val):
        return "Grade:     -- %"
    # 按配置的小数位数四舍五入
    grad_val = round(val, GRAD_DISPLAY_DECIMALS)
    sign = "+" if grad_val >= 0 else "-"
    # 根据小数位数自动调整格式化规则
    if GRAD_DISPLAY_DECIMALS == 0:
        return f"Grade: {sign}{abs(int(grad_val)):>3d}%"
    else:
        return f"Grade: {sign}{abs(grad_val):>4.{GRAD_DISPLAY_DECIMALS}f}%"

def format_gain(val):
    return "Gain:    ---- m" if np.isnan(val) else f"Gain: {val:>6.1f} m"

def render_delta_frames(alts_weak, gradients, gains, fps):
    print(f"\n[步骤5/6] 渲染帧 (FPS={fps})...")
    os.makedirs(OUTPUT_DIR_DELTA, exist_ok=True)
    for f in os.listdir(OUTPUT_DIR_DELTA):
        if f.startswith("frame_"):
            os.remove(os.path.join(OUTPUT_DIR_DELTA, f))

    font = load_font(DELTA_FONT_SIZE)
    n = len(alts_weak)
    
    dummy_img = Image.new('RGBA', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    sample_elev = format_elevation(9999.9)
    sample_grad = format_gradient(99.9)
    sample_gain = format_gain(9999.9)

    w_elev = dummy_draw.textbbox((0, 0), sample_elev, font=font)[2]
    w_grad = dummy_draw.textbbox((0, 0), sample_grad, font=font)[2]
    w_gain = dummy_draw.textbbox((0, 0), sample_gain, font=font)[2]
    
    gap = 40
    total_w = w_elev + gap + w_grad + gap + w_gain
    if total_w > DELTA_WIDTH - 2 * DELTA_PADDING:
        print(f"  ⚠️ 文本总宽 {total_w}px 超过画布 {DELTA_WIDTH}px，建议增大DELTA_WIDTH")

    start_x = (DELTA_WIDTH - total_w) // 2
    text_height = dummy_draw.textbbox((0, 0), "Ay", font=font)[3]
    y = (DELTA_HEIGHT - text_height) // 2

    start_time = time.time()
    last_print = start_time
    
    for idx in range(n):
        current = time.time()
        if current - last_print >= PRINT_INTERVAL:
            elapsed = current - start_time
            processed = idx + 1
            fps_actual = processed / elapsed if elapsed > 0 else 0
            remaining = (n - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Delta] {processed}/{n}帧 | 已用:{elapsed:.1f}s | 剩余:{remaining:.1f}s | {fps_actual:.1f}帧/s")
            last_print = current

        img = Image.new('RGBA', (DELTA_WIDTH, DELTA_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        #draw.rounded_rectangle([0, 0, DELTA_WIDTH, DELTA_HEIGHT], radius=10, fill=(0, 0, 0, 140)) 绘制背景矩形

        x = start_x
        draw.text((x, y), format_elevation(alts_weak[idx]), font=font, fill=(255, 255, 255))
        x += w_elev + gap
        draw.text((x, y), format_gradient(gradients[idx]), font=font, fill=(255, 255, 255))
        x += w_grad + gap
        draw.text((x, y), format_gain(gains[idx]), font=font, fill=(255, 255, 255))

        frame_path = os.path.join(OUTPUT_DIR_DELTA, f"frame_{idx:06d}.png")
        img.save(frame_path, 'PNG')

    print(f"✅ 渲染完成，总耗时 {time.time() - start_time:.1f}s")
    return n

def assemble_delta_mov(frame_count, fps):
    global OUTPUT_MOV_DELTA
    if OUTPUT_MOV_DELTA is None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        OUTPUT_MOV_DELTA = f"delta_elevation_{ts}.mov"
    print(f"\n[步骤6/6] 合成视频: {OUTPUT_MOV_DELTA}")
    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(OUTPUT_DIR_DELTA, "frame_%06d.png"),
        "-vf", f"scale={DELTA_WIDTH}:{DELTA_HEIGHT},setsar=1",
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count), OUTPUT_MOV_DELTA,
    ]
    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        print(f"❌ ffmpeg 失败: {result.stderr[:500]}")
        return False
    print(f"✅ 视频生成成功: {OUTPUT_MOV_DELTA}")
    if os.path.exists(OUTPUT_MOV_DELTA):
        print(f"   文件大小: {os.path.getsize(OUTPUT_MOV_DELTA)/(1024 * 1024):.2f} MB")
    return True


# ============================================================
# 主流程
# ============================================================
def generate_delta_elevation_video(fit_path, lap_start, lap_end, fps=None):
    if fps is None:
        fps = DELTA_FPS
    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError("无效的 Lap 时长")

    print("\n=== Delta 海拔/坡度/爬升视频配置 (1Hz FIT · 长坡修复版) ===")
    print(f"时间范围: {lap_start.strftime('%H:%M:%S')} → {lap_end.strftime('%H:%M:%S')}")
    print(f"时长: {duration:.1f}秒 | FPS: {fps} | 预期帧数: {int(duration*fps)+1}")
    print(f"流程: 原始1Hz强平滑 -> 坡度(速度法) -> 累计爬升(强平滑无过滤) -> 插值{fps}Hz -> 渲染")
    print(f"  海拔弱平滑: {ELEV_WEAK_SMOOTH_SEC}s | 坡度强平滑: {GRAD_STRONG_SMOOTH_SEC}s")
    print(f"  累计爬升平滑: {GAIN_SMOOTH_SEC}s（关键：增强平滑替代逐点过滤）")
    print("============================================================\n")

    raw = load_fit_data(fit_path, lap_start, lap_end)
    
    # 关键：填充海拔NaN，避免Savitzky-Golay滤波错误
    alts = raw['alts']
    valid = ~np.isnan(alts)
    if not np.all(valid):
        nan_count = np.sum(~valid)
        print(f"[预处理] 填充 {nan_count} 个海拔NaN值...")
        f_interp = interp1d(raw['offsets'][valid], alts[valid], kind='linear', fill_value="extrapolate")
        raw['alts'] = f_interp(raw['offsets'])

    # 原始1Hz采样间隔（用于平滑窗口换算）
    dt = np.median(np.diff(raw['offsets'])) if len(raw['offsets']) > 1 else 1.0
    print(f"[步骤2/6] 原始网格 dt={dt:.3f}s -> 平滑窗口按1Hz样本数计算")

    print("[步骤3/6] 平滑处理（先平滑，后插值）...")
    alts_weak = apply_smooth_1hz(raw['alts'], dt, ELEV_WEAK_SMOOTH_SEC)
    alts_strong = apply_smooth_1hz(raw['alts'], dt, GRAD_STRONG_SMOOTH_SEC)
    alts_gain = apply_smooth_1hz(raw['alts'], dt, GAIN_SMOOTH_SEC)

    print("[步骤4/6] 坡度计算（速度法）+ 累计爬升（长坡修复版）...")
    gradients_1hz = compute_gradient_1hz(alts_strong, raw['speeds'], dt)
    gains_1hz = compute_cumulative_gain_strava(alts_gain, raw['dists'])

    print(f"  坡度范围(1Hz): {np.nanmin(gradients_1hz):.1f}% ~ {np.nanmax(gradients_1hz):.1f}%")
    print(f"  累计爬升(长坡修复版,1Hz): {gains_1hz[-1]:.1f} m")

    print(f"[步骤5/6] 插值到 {fps}Hz（仅用于显示）...")
    interp_in = {
        'offsets': raw['offsets'],
        'alts_weak': alts_weak,
        'gradients': gradients_1hz,
        'gains': gains_1hz,
    }
    intp = interpolate_to_fps(interp_in, duration, fps)
    alts_weak_fps = intp['alts_weak']
    gradients_fps = clip_gradient_display(intp['gradients'])
    gains_fps = intp['gains']
    print(f"  插值后帧数: {len(alts_weak_fps)}")

    frame_count = render_delta_frames(alts_weak_fps, gradients_fps, gains_fps, fps)
    success = assemble_delta_mov(frame_count, fps)

    if os.path.exists(OUTPUT_DIR_DELTA):
        shutil.rmtree(OUTPUT_DIR_DELTA)
    return {'delta_elevation_video': OUTPUT_MOV_DELTA} if success else {}


# ============================================================
# CLI入口
# ============================================================
def main():
    print("=" * 60)
    print("Delta: 海拔/坡度/累计爬升 HUD (1Hz FIT · 长坡修复版)")
    print("=" * 60)
    fit_arg = sys.argv[1] if len(sys.argv) > 1 else None
    fits = [fit_arg] if fit_arg else find_fit_files()
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

    lap_start, lap_end = select_laps(fit_path)
    if lap_start is None:
        return
    fps = get_fps()
    result = generate_delta_elevation_video(fit_path, lap_start, lap_end, fps)
    if result:
        print(f"\n✅ 完成！输出: {result.get('delta_elevation_video')}")
    else:
        print("\n❌ 生成失败")

if __name__ == "__main__":
    main()