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
# === Delta: elevation / gradient / cumulative gain HUD video
# ============================================================

# ==================== 可配置参数 ====================
DELTA_FPS = 5
DELTA_WIDTH, DELTA_HEIGHT = 720, 80  # 横向长条，足够放下三组数据
DELTA_FONT_SIZE = 28
DELTA_PADDING = 12

# 平滑参数
ELEV_WEAK_SMOOTH_SEC = 2.0        # 实时海拔弱平滑窗口（秒）
GRAD_STRONG_SMOOTH_SEC = 3.0      # 坡度计算用强平滑窗口（秒）
GRAD_COMPENSATION_SEC = 1.5       # 相位补偿（秒）≈ 强平滑窗口/2
GRAD_MIN_SPEED_KMH = 3.0          # 低于此速度不显示坡度

# 累计爬升分段检测阈值
GAIN_MIN_HEIGHT = 5.0             # 最小爬升段高度（米）
GAIN_MIN_DIST = 50.0              # 最小爬升段距离（米）
GAIN_DROP_TOLERANCE = 2.0         # 下坡容忍（米），小于此不算坡结束

# 字体
FONT_PATH = None  # None = 自动查找

# ffmpeg
FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR_DELTA = "frames_delta"
OUTPUT_MOV_DELTA = None

PRINT_INTERVAL = 5.0

# ==================== 字体 ====================
def load_font(size):
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            return ImageFont.truetype(FONT_PATH, size)
        try:
            return ImageFont.truetype("arial.ttf", size)
        except:
            try:
                return ImageFont.truetype("DejaVuSans.ttf", size)
            except:
                return ImageFont.load_default()
    except:
        return ImageFont.load_default()


# ==================== 交互 ====================
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
    except:
        return DELTA_FPS


# ==================== 数据加载 ====================
def load_fit_data(fit_path, lap_start, lap_end):
    print("\n[步骤1/5] 加载 FIT 数据...")
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
        if s is not None:
            speeds.append(float(s) * 3.6)  # m/s → km/h
        else:
            speeds.append(np.nan)

    if not offsets:
        raise RuntimeError("指定时间范围内无有效数据")

    print(f"  有效记录数: {len(offsets)}")
    print(f"  海拔有效: {sum(~np.isnan(alts))}/{len(alts)}")
    print(f"  距离有效: {sum(~np.isnan(dists))}/{len(dists)}")

    return {
        'offsets': np.array(offsets),
        'alts': np.array(alts),
        'dists': np.array(dists),
        'speeds': np.array(speeds),
    }


# ==================== 插值 ====================
def interpolate_to_fps(data, duration_sec, fps):
    """线性插值到目标 FPS"""
    time_points = np.linspace(0, duration_sec, int(duration_sec * fps) + 1)
    x = data['offsets']

    def interp(arr, fill=np.nan):
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full_like(time_points, np.nan)
        f = interp1d(x[valid], arr[valid], kind='linear', fill_value="extrapolate")
        return f(time_points)

    return {
        'time': time_points,
        'alts': interp(data['alts']),
        'dists': interp(data['dists']),
        'speeds': interp(data['speeds']),
    }


# ==================== 平滑 ====================
def apply_smooth(values, fps, window_sec, polyorder=2):
    """Savitzky-Golay 平滑，窗口自动对齐为奇数"""
    window = int(window_sec * fps)
    if window % 2 == 0:
        window += 1
    if window < 5 or len(values) < window:
        return values
    return savgol_filter(values, window, polyorder)


# ==================== 坡度计算 ====================
def compute_gradient(alts_smooth, dists, speeds, fps):
    """
    坡度 = Δh / Δd × 100%
    使用强平滑后的海拔 + 相位补偿
    """
    n = len(alts_smooth)
    gradient = np.full(n, np.nan)

    # 计算距离差分
    dist_diff = np.diff(dists)
    alt_diff = np.diff(alts_smooth)

    for i in range(1, n):
        if np.isnan(dist_diff[i-1]) or dist_diff[i-1] <= 0:
            continue
        if np.isnan(alt_diff[i-1]):
            continue

        grad = alt_diff[i-1] / dist_diff[i-1] * 100.0

        # 速度过低时不显示
        spd = speeds[i] if not np.isnan(speeds[i]) else 0
        if spd < GRAD_MIN_SPEED_KMH:
            continue

        gradient[i] = grad

    # 相位补偿：往前移
    shift = int(GRAD_COMPENSATION_SEC * fps)
    if shift > 0 and shift < n:
        gradient = np.roll(gradient, -shift)
        gradient[-shift:] = np.nan

    return gradient


# ==================== 累计爬升（分段检测） ====================
def compute_cumulative_gain(alts_smooth, dists):
    n = len(alts_smooth)
    gain = np.zeros(n)
    acc = 0.0  # 已结算的累计爬升（基线）
    i = 0

    while i < n:
        # NaN：gain 冻结为已结算值，不推进 acc
        if np.isnan(alts_smooth[i]) or np.isnan(dists[i]):
            gain[i] = acc
            i += 1
            continue

        start_i = i
        start_alt = alts_smooth[i]
        start_dist = dists[i]
        seg_max_alt = start_alt
        seg_max_i = i

        j = i + 1
        segment_ended = False

        while j < n:
            if np.isnan(alts_smooth[j]) or np.isnan(dists[j]):
                j += 1
                continue

            if alts_smooth[j] > seg_max_alt:
                seg_max_alt = alts_smooth[j]
                seg_max_i = j

            drop = seg_max_alt - alts_smooth[j]
            if drop >= GAIN_DROP_TOLERANCE:
                # ---- 段结束 ----
                segment_ended = True
                total_rise = seg_max_alt - start_alt
                total_dist = dists[seg_max_i] - start_dist

                if total_rise >= GAIN_MIN_HEIGHT and total_dist >= GAIN_MIN_DIST:
                    # 有效段：逐帧累加正差分
                    for k in range(start_i, seg_max_i + 1):
                        if np.isnan(alts_smooth[k]):
                            gain[k] = acc
                        else:
                            added = (max(0.0, alts_smooth[k] - alts_smooth[k - 1])
                                     if k > start_i else 0.0)
                            acc += added
                            gain[k] = acc
                else:
                    # 无效段：gain 冻结
                    for k in range(start_i, seg_max_i + 1):
                        gain[k] = acc

                # 段结束探测点 j 及其之前的段尾下坡帧：填充为已结算值
                for k in range(seg_max_i + 1, j + 1):
                    if k < n:
                        gain[k] = acc

                i = j
                break
            j += 1

        if not segment_ended:
            # ---- 到达数据末尾 ----
            total_rise = seg_max_alt - start_alt
            total_dist = dists[seg_max_i] - start_dist
            if total_rise >= GAIN_MIN_HEIGHT and total_dist >= GAIN_MIN_DIST:
                for k in range(start_i, seg_max_i + 1):
                    if np.isnan(alts_smooth[k]):
                        gain[k] = acc
                    else:
                        added = (max(0.0, alts_smooth[k] - alts_smooth[k - 1])
                                 if k > start_i else 0.0)
                        acc += added
                        gain[k] = acc
            else:
                for k in range(start_i, n):
                    gain[k] = acc
            i = n

    return gain



# ==================== 格式化 ====================
def format_elevation(val):
    """Elev:  9999.9m（固定宽度，右对齐数值）"""
    if np.isnan(val):
        return "Elev:    ---- m"
    return f"Elev: {val:>6.1f} m"


def format_gradient(val):
    """Grade:  +1.0% （符号固定宽度，小数点绝对对齐）"""
    if np.isnan(val):
        return "Grade:     -- %"

    # 符号：+ / - / 空格，统一占 1 字符
    sign = "+" if val > 0 else "-" if val < 0 else " "

    # 数值右对齐到小数点（固定 4 字符：x.xx）
    return f"Grade: {sign}{abs(val):>4.1f}%"


def format_gain(val):
    """Gain:  9999.9m"""
    if np.isnan(val):
        return "Gain:    ---- m"
    return f"Gain: {val:>6.1f} m"


# ==================== 渲染 ====================
def render_delta_frames(alts_weak, gradients, gains, fps):
    print(f"\n[步骤4/5] 渲染帧 (FPS={fps})...")
    os.makedirs(OUTPUT_DIR_DELTA, exist_ok=True)
    for f in os.listdir(OUTPUT_DIR_DELTA):
        if f.startswith("frame_"):
            os.remove(os.path.join(OUTPUT_DIR_DELTA, f))

    font = load_font(DELTA_FONT_SIZE)
    n = len(alts_weak)

    # 预计算每段文本的固定宽度（用最大值测量）
    dummy_img = Image.new('RGBA', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    sample_elev = format_elevation(9999.9)
    sample_grad = format_gradient(99.9)
    sample_gain = format_gain(9999.9)

    w_elev = dummy_draw.textbbox((0, 0), sample_elev, font=font)[2]
    w_grad = dummy_draw.textbbox((0, 0), sample_grad, font=font)[2]
    w_gain = dummy_draw.textbbox((0, 0), sample_gain, font=font)[2]

    gap = 40  # 三组之间的间距
    total_w = w_elev + gap + w_grad + gap + w_gain
    # 如果超过宽度则等比缩小字体（保险）
    if total_w > DELTA_WIDTH - 2 * DELTA_PADDING:
        print(f"  ⚠️ 文本总宽 {total_w}px 超过画布 {DELTA_WIDTH}px，建议增大 DELTA_WIDTH")

    start_x = (DELTA_WIDTH - total_w) // 2
    y = (DELTA_HEIGHT - dummy_draw.textbbox((0, 0), "Ay", font=font)[3]) // 2

    start_time = time.time()
    last_print = start_time

    for idx in range(n):
        current = time.time()
        if current - last_print >= PRINT_INTERVAL:
            elapsed = current - start_time
            processed = idx + 1
            fps_actual = processed / elapsed
            remaining = (n - processed) / fps_actual if fps_actual > 0 else 0
            print(f"[Delta] {processed}/{n}帧 | 已用:{elapsed:.1f}s | 剩余:{remaining:.1f}s | {fps_actual:.1f}帧/s")
            last_print = current

        img = Image.new('RGBA', (DELTA_WIDTH, DELTA_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 黑色半透明背景条
        draw.rounded_rectangle(
            [0, 0, DELTA_WIDTH, DELTA_HEIGHT],
            radius=10,
            fill=(0, 0, 0, 140)
        )

        x = start_x
        draw.text((x, y), format_elevation(alts_weak[idx]), font=font, fill=(255, 255, 255))
        x += w_elev + gap
        draw.text((x, y), format_gradient(gradients[idx]), font=font, fill=(255, 255, 255))
        x += w_grad + gap
        draw.text((x, y), format_gain(gains[idx]), font=font, fill=(255, 255, 255))

        path = os.path.join(OUTPUT_DIR_DELTA, f"frame_{idx:06d}.png")
        img.save(path, 'PNG')

    print(f"✅ 渲染完成，总耗时 {time.time() - start_time:.1f}s")
    return n


# ==================== 合成 ====================
def assemble_delta_mov(frame_count, fps):
    global OUTPUT_MOV_DELTA
    if OUTPUT_MOV_DELTA is None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        OUTPUT_MOV_DELTA = f"delta_elevation_{ts}.mov"

    print(f"\n[步骤5/5] 合成视频: {OUTPUT_MOV_DELTA}")
    cmd = [
        FFMPEG_PATH, "-y", "-framerate", str(fps), "-start_number", "0",
        "-i", os.path.join(OUTPUT_DIR_DELTA, "frame_%06d.png"),
        "-vf", f"scale={DELTA_WIDTH}:{DELTA_HEIGHT},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        OUTPUT_MOV_DELTA
    ]

    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        print(f"❌ ffmpeg 失败: {result.stderr[:500]}")
        return False

    print(f"✅ 视频生成成功: {OUTPUT_MOV_DELTA}")
    if os.path.exists(OUTPUT_MOV_DELTA):
        size = os.path.getsize(OUTPUT_MOV_DELTA) / (1024 * 1024)
        print(f"   文件大小: {size:.2f} MB")
    return True


# ==================== 主流程 ====================
def generate_delta_elevation_video(fit_path, lap_start, lap_end, fps=None):
    if fps is None:
        fps = DELTA_FPS

    duration = (lap_end - lap_start).total_seconds()
    if duration <= 0:
        raise ValueError("无效的 Lap 时长")

    print("\n=== Delta 海拔/坡度/爬升视频配置 ===")
    print(f"时间范围: {lap_start.strftime('%H:%M:%S')} → {lap_end.strftime('%H:%M:%S')}")
    print(f"时长: {duration:.1f}秒")
    print(f"FPS: {fps}")
    print(f"预期帧数: {int(duration * fps) + 1}")
    print(f"实时海拔平滑窗口: {ELEV_WEAK_SMOOTH_SEC}s (弱平滑)")
    print(f"坡度计算平滑窗口: {GRAD_STRONG_SMOOTH_SEC}s (强平滑)")
    print(f"坡度相位补偿: {GRAD_COMPENSATION_SEC}s")
    print(f"累计爬升阈值: ≥{GAIN_MIN_HEIGHT}m / ≥{GAIN_MIN_DIST}m")
    print("===============================\n")

    # 1. 加载
    raw = load_fit_data(fit_path, lap_start, lap_end)

    # 2. 插值
    print("[步骤2/5] 插值数据...")
    intp = interpolate_to_fps(raw, duration, fps)
    print(f"  插值后帧数: {len(intp['time'])}")

    # 3. 平滑（双轨）
    print("[步骤3/5] 平滑处理...")
    alts_weak = apply_smooth(intp['alts'], fps, ELEV_WEAK_SMOOTH_SEC)
    alts_strong = apply_smooth(intp['alts'], fps, GRAD_STRONG_SMOOTH_SEC)

    # 坡度
    gradients = compute_gradient(alts_strong, intp['dists'], intp['speeds'], fps)

    # 累计爬升
    gains = compute_cumulative_gain(alts_strong, intp['dists'])

    print(f"  坡度范围: {np.nanmin(gradients):.1f}% ~ {np.nanmax(gradients):.1f}%")
    print(f"  累计爬升: {gains[-1]:.1f} m")

    # 4. 渲染
    frame_count = render_delta_frames(alts_weak, gradients, gains, fps)

    # 5. 合成
    success = assemble_delta_mov(frame_count, fps)

    # 清理
    if os.path.exists(OUTPUT_DIR_DELTA):
        shutil.rmtree(OUTPUT_DIR_DELTA)

    if success:
        return {'delta_elevation_video': OUTPUT_MOV_DELTA}
    return {}


# ==================== CLI ====================
def main():
    print("=" * 55)
    print("Delta: 海拔 / 坡度 / 累计爬升 HUD 视频生成器")
    print("=" * 55)

    fits = find_fit_files()
    if not fits:
        print("❌ 未找到 .fit 文件")
        return

    for i, f in enumerate(fits, 1):
        print(f"[{i}] {f}")
    choice = input("选择文件 (q退出): ").strip()
    if choice.lower() == 'q':
        return

    try:
        fit_path = fits[int(choice) - 1]
    except:
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

