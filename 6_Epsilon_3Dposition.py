# -*- coding: utf-8 -*-
"""
Epsilon_3d_map_v5.py
2.5D 位置/海拔 透明地图视频生成器（伪3D 墙体挤出）

相比 v4 的新增/改动:
  1) PRINT_INTERVAL、video_width/height 纳入 DEFAULT_PARAMS，可通过 params_dict 修改
  2) 新增 line_width（路线粗细度），同时影响墙体上方已走/未走路线

特点:
  - 透明背景 (RGBA) + ProRes 4444，可直接叠加到骑行视频
  - 已走路线橙色高亮，未走路线灰色，墙体颜色随路线自动一致（半透明）
  - 可调节俯仰角 (pitch_deg)、墙体透明度 (wall_alpha)、路线粗细 (line_width)
  - 可自定义输出分辨率 (video_width / video_height)
  - 不指定分辨率时自动选择最优尺寸并居中

用法:
  1) 单独运行 (CLI):  python Epsilon_3d_map_v5.py
  2) 被 GUI 调用:    generate_epsilon_video(**kwargs)
"""

import os
import sys
import math
import shutil
import subprocess
import traceback
from datetime import datetime, timedelta
import time
import numpy as np
from scipy.interpolate import interp1d
from fitparse import FitFile
from PIL import Image, ImageDraw

# ==================== 全局可覆盖 ====================
FFMPEG_PATH = "ffmpeg"

DEFAULT_PARAMS = {
    "fps": 5,
    "pitch_deg": 65,            # 俯仰角：0=完全俯视，90=水平
    "z_scale": 3.0,             # 海拔高度放大倍数
    "video_width": None,         # 不指定则自动计算 (16:9, 1280x720 基准)
    "video_height": None,
    "padding": 50,              # 画布内边距（像素）
    "transparent": True,         # True -> ProRes 4444 (RGBA), False -> H264
    "wall_alpha": 110,          # 墙体透明度 (0-255)
    "color_passed": (0, 153, 255),      # 已走路线颜色
    "color_not_passed": (255, 120, 0),# 未走路线颜色
    "marker_radius": 10,
    "marker_outline": 3,
    "print_interval": 5.0,       # 帧生成进度打印间隔（秒）
    "line_width": 6,             # 路线粗细度（同时影响已走/未走路线 & 自适应基准值）
}

# 帧目录名
EPS_FRAMES = "frames_Epsilon"

FONT_PATH = None

# ============================================================
# 数据加载与插值
# ============================================================
def load_fit_data(fit_path, lap_start, lap_end):
    """加载 FIT 数据 (time, lat, lon, elev)，只保留三者都完整的点"""
    fit = FitFile(fit_path)
    times, lats, lons, elevs = [], [], [], []
    for m in fit.get_messages('record'):
        vals = m.get_values()
        ts = vals.get('timestamp')
        if ts is None:
            continue
        if lap_start is not None and ts < lap_start:
            continue
        if lap_end is not None and ts > lap_end:
            continue

        lat = vals.get('position_lat')
        lon = vals.get('position_long')
        elev = vals.get('enhanced_altitude') or vals.get('altitude')
        if lat is None or lon is None or elev is None:
            continue

        times.append(ts)
        lats.append(lat / 2**31 * 180)   # semicircles -> degrees
        lons.append(lon / 2**31 * 180)
        elevs.append(elev)

    print(f"[Epsilon_加载] 有效轨迹点 {len(times)} 个 (要求 position + altitude 齐全)")
    return times, lats, lons, elevs


def interpolate_on_timeline(times, values, start_time, end_time, fps):
    """在统一时间轴上插值 (线性外推)"""
    if len(times) < 2:
        return None
    t_offsets = np.array([(t - start_time).total_seconds() for t in times], dtype=float)
    duration = (end_time - start_time).total_seconds()
    interp_times = np.linspace(0, duration, int(duration * fps) + 1)
    f = interp1d(t_offsets, values, kind='linear',
                 fill_value='extrapolate', bounds_error=False)
    return f(interp_times)


def build_track_points(times, lats, lons, elevs, lap_start, lap_end, fps):
    """转换为平面局部坐标并插值，返回 frame_count 和 points3d (Nx3)"""
    if len(times) < 2:
        raise ValueError("有效数据点少于 2 个")

    lat0, lon0 = lats[0], lons[0]

    # 局部平面坐标 (等距圆柱近似)，海拔以全程最低点为基准
    x_m = [(lon - lon0) * 111320.0 * math.cos(math.radians(lat0)) for lon in lons]
    y_m = [(lat - lat0) * 110540.0 for lat in lats]
    z_min = min(elevs)
    z_m = [e - z_min for e in elevs]

    # 插值
    x_int = interpolate_on_timeline(times, x_m, lap_start, lap_end, fps)
    y_int = interpolate_on_timeline(times, y_m, lap_start, lap_end, fps)
    z_int = interpolate_on_timeline(times, z_m, lap_start, lap_end, fps)
    if x_int is None or y_int is None or z_int is None:
        raise ValueError("插值失败：检查时间范围")

    points3d = np.column_stack([x_int, y_int, z_int])
    return len(x_int), points3d


# ============================================================
# 2.5D 投影与画布计算
# ============================================================
def _project_all(points3d, pitch_rad, z_scale, scale=1.0, cx=0.0, cy=0.0):
    """对所有轨迹点（含底面墙体投影）计算屏幕坐标，返回 (sx[], sy[])"""
    sxs, sys_ = [], []
    cos_p = math.cos(pitch_rad)
    for x, y, z in points3d:
        sxs.append(cx + x * scale)
        sys_.append(cy + (-y * cos_p - z * z_scale) * scale)
        # 底面点 (z=0)，对应墙体落地点
        sys_.append(cy + (-y * cos_p) * scale)
    return sxs, sys_


def calc_canvas_and_origin(points3d, canvas_w, canvas_h, pitch_rad, z_scale, padding):
    """计算 scale / cx / cy，使轨迹+墙体完整居中

    先用 scale=1 求投影包围盒，再由画布可用区反推真实 scale，最后居中。
    """
    # 第一步：scale=1 下的原始包围盒
    sxs, sys_ = _project_all(points3d, pitch_rad, z_scale, scale=1.0, cx=0.0, cy=0.0)
    min_sx, max_sx = min(sxs), max(sxs)
    min_sy, max_sy = min(sys_), max(sys_)

    range_x = max_sx - min_sx
    range_y = max_sy - min_sy
    usable_w = canvas_w - 2 * padding
    usable_h = canvas_h - 2 * padding
    scale = min(usable_w / (range_x if range_x > 0 else 1),
                usable_h / (range_y if range_y > 0 else 1))
    # 防止 scale 异常
    if scale <= 0 or not math.isfinite(scale):
        scale = 1.0

    # 第二步：用真实 scale 重新计算包围盒中心，平移居中
    cx = canvas_w / 2 - (min_sx + max_sx) / 2 * scale
    cy = canvas_h / 2 - (min_sy + max_sy) / 2 * scale
    return scale, cx, cy


# ============================================================
# 帧渲染
# ============================================================
def make_frame(points3d, i, canvas_w, canvas_h, scale, cx, cy,
               pitch_deg, z_scale, params):
    """生成单帧 RGBA 透明图"""
    pitch_rad = math.radians(pitch_deg)

    # 创建透明画布
    img = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 预计算所有投影点（包括底面）
    n = len(points3d)
    top_pts = []
    bot_pts = []
    cos_p = math.cos(pitch_rad)
    for x, y, z in points3d:
        sx = cx + x * scale
        sy = cy + (-y * cos_p - z * z_scale) * scale
        top_pts.append((sx, sy))
        syb = cy + (-y * cos_p) * scale   # 底面 (z=0)，墙体落地点
        bot_pts.append((sx, syb))

    # --- 墙体挤出 ---
    color_passed = params["color_passed"]
    color_not_passed = params["color_not_passed"]
    wall_alpha = params["wall_alpha"]

    # 构建墙体四边形，记录排序键 (底面最小Y，即远处先画)
    wall_polys = []
    for k in range(n - 1):
        x0_t, y0_t = top_pts[k]
        x1_t, y1_t = top_pts[k + 1]
        x0_b, y0_b = bot_pts[k]
        x1_b, y1_b = bot_pts[k + 1]

        # 判断该段是否已被走过
        base_color = color_passed if k < i else color_not_passed
        wall_color = (base_color[0], base_color[1], base_color[2], wall_alpha)

        polygon = [(x0_b, y0_b), (x1_b, y1_b), (x1_t, y1_t), (x0_t, y0_t)]
        sort_key = min(y0_b, y1_b)
        wall_polys.append((polygon, sort_key, wall_color))

    # 从远到近绘制
    wall_polys.sort(key=lambda item: item[1])
    for polygon, _, wall_color in wall_polys:
        draw.polygon(polygon, fill=wall_color)

    # --- 路线折线 ---
    # ★ v5：以 params["line_width"] 为基准，按当前画布宽度自适应
    #   基准参考尺寸取 1280，画布越宽线越粗，保证不同分辨率下视觉粗细一致
    base_lw = float(params.get("line_width", 6))
    line_width = max(1, int(round(base_lw * canvas_w / 1280.0)))

    # 未走过：从当前点开始画到终点（灰色，不透明）
    if i < n - 1:
        draw.line(top_pts[i:], fill=color_not_passed, width=line_width, joint="curve")

    # 已走过：从起点画到当前点（亮色，不透明）
    if i > 0:
        draw.line(top_pts[:i + 1], fill=color_passed, width=line_width, joint="curve")

    # --- 当前位置标记 ---
    cx_m, cy_m = top_pts[i]
    radius = params["marker_radius"]
    outline = params["marker_outline"]
    # 外圈白色
    draw.ellipse([cx_m - radius, cy_m - radius, cx_m + radius, cy_m + radius],
                 fill=(255, 255, 255, 255))
    # 内圈主题色
    draw.ellipse([cx_m - radius + outline, cy_m - radius + outline,
                  cx_m + radius - outline, cy_m + radius - outline],
                 fill=color_passed + (255,))

    return img


def generate_frames(points3d, frame_count, canvas_w, canvas_h, scale, cx, cy,
                    pitch_deg, z_scale, params, frame_dir, print_tag, stop_event=None):
    """逐帧渲染 PNG"""
    # ★ v5：从 params 读取打印间隔，不再依赖全局 PRINT_INTERVAL
    print_interval = float(params.get("print_interval", 5.0))

    os.makedirs(frame_dir, exist_ok=True)
    for f in os.listdir(frame_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frame_dir, f))

    if frame_count == 0:
        print(f"[{print_tag}] 时长为0，无帧可生成")
        return 0

    if stop_event and stop_event.is_set():
        print(f"[{print_tag}] 检测到停止信号，取消本段生成")
        return 0

    t0 = time.time()
    last = t0
    for i in range(frame_count):
        if stop_event and stop_event.is_set():
            print(f"[{print_tag}] 检测到停止信号，帧生成中断于 {i}/{frame_count}")
            return i

        now = time.time()
        if now - last >= print_interval:
            el = now - t0
            fa = (i + 1) / el if el > 0 else 0
            rem = (frame_count - i - 1) / fa if fa > 0 else 0
            print(f"[{print_tag}] {i+1}/{frame_count} | {el:.1f}s | 剩余 {rem:.1f}s | {fa:.1f}帧/s")
            last = now

        frame = make_frame(points3d, i, canvas_w, canvas_h, scale, cx, cy,
                           pitch_deg, z_scale, params)
        frame.save(os.path.join(frame_dir, f"frame_{i:06d}.png"), 'PNG')

    print(f"[{print_tag}] 完成 {frame_count} 帧")
    return frame_count


# ============================================================
# 视频合成
# ============================================================
def compile_video(frame_dir, output_file, frame_count, width, height, fps,
                  transparent, stop_event=None):
    """ffmpeg 合成视频，透明用 ProRes 4444，非透明用 H264"""
    global FFMPEG_PATH
    if frame_count == 0:
        return False

    if stop_event and stop_event.is_set():
        print("[Epsilon_合成] 检测到停止信号，跳过视频合成")
        return False

    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, check=True)
    except Exception:
        print(f"[Epsilon_合成] ffmpeg 不可用: {FFMPEG_PATH}")
        return False

    # 日志文件（避免管道阻塞导致卡死）
    log_file = os.path.join(frame_dir, "ffmpeg_progress.log")
    with open(log_file, "w") as log_fp:
        cmd = [
            FFMPEG_PATH, "-y",
            "-framerate", str(fps),
            "-start_number", "0",
            "-i", os.path.join(frame_dir, "frame_%06d.png"),
            "-vf", f"scale={width}:{height},setsar=1",
        ]
        if transparent:
            cmd += ["-c:v", "prores_ks", "-profile:v", "4444",
                    "-pix_fmt", "yuva444p10le"]
        else:
            cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]

        cmd += ["-frames:v", str(frame_count), output_file]

        CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen(
                cmd, stdout=log_fp, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            print(f"[Epsilon_合成] 启动 ffmpeg 失败: {e}")
            return False

        last_print = time.time()
        while proc.poll() is None:
            if stop_event and stop_event.is_set():
                print("[Epsilon_合成] 检测到停止信号，终止 ffmpeg 进程...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                if os.path.exists(output_file):
                    os.remove(output_file)
                print(f"[Epsilon_合成] 已删除半成品视频: {output_file}")
                return False

            # 定期输出进度
            now = time.time()
            if now - last_print >= 3.0:
                last_print = now
                if os.path.exists(log_file):
                    with open(log_file, "r") as lf:
                        lines = [ln for ln in lf.readlines() if "frame=" in ln]
                        if lines:
                            print(f"[Epsilon_合成] 最近进度: {lines[-1].strip()}")
            time.sleep(0.1)

        # 进程结束
        if proc.returncode == 0:
            print(f"[Epsilon_合成] 成功: {output_file}")
            return True
        else:
            print(f"[Epsilon_合成] 失败，日志末尾:")
            with open(log_file, "r") as lf:
                tail = lf.read().strip().splitlines()[-10:]
                for line in tail:
                    print(f"    {line}")
            return False


# ============================================================
# 可编程入口
# ============================================================
def generate_epsilon_video(fit_path, lap_start=None, lap_end=None,
                           fps=None, params_dict=None,
                           ffmpeg_path=None, output_dir=None,
                           output_file=None, cleanup=False, stop_event=None):
    """生成 Epsilon 3D 位置/海拔视频

    可通过 params_dict 覆盖 DEFAULT_PARAMS 中的任意参数，例如:
        params_dict = {
            "print_interval": 2.0,       # 进度打印间隔
            "line_width": 10,            # 路线粗细
            "video_width": 1920,         # 自定义分辨率
            "video_height": 1080,
            "pitch_deg": 45,
            "wall_alpha": 130,
        }
    """
    global FFMPEG_PATH
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path

    # 合并参数（用户传入优先）
    params = {**DEFAULT_PARAMS, **(params_dict or {})}
    if fps is not None:
        params["fps"] = fps

    out_dir = output_dir or os.getcwd()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    ext = ".mov" if params["transparent"] else ".mp4"
    out_file = output_file or os.path.join(out_dir, f"epsilon_3d_{ts}{ext}")

    result = {
        "success": False,
        "video": None,
        "cleanup_time": 0.0,
        "total_time": 0.0,
        "stopped": False,
    }
    t0_all = time.time()

    try:
        if lap_start is None or lap_end is None:
            print("[Epsilon] 自动推导时间范围...")
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
        print(f"[Epsilon] 时间范围: {lap_start} -> {lap_end} ({duration:.1f}秒)")

        # 加载并构建轨迹
        times, lats, lons, elevs = load_fit_data(fit_path, lap_start, lap_end)
        if len(times) < 2:
            raise ValueError("指定范围内有效数据点不足")
        frame_count, points3d = build_track_points(
            times, lats, lons, elevs, lap_start, lap_end, params["fps"])
        print(f"[Epsilon] 插值后帧数: {frame_count} (fps={params['fps']})")

        # 分辨率：用户指定或自动计算
        canvas_w = int(params["video_width"]) if params.get("video_width") else None
        canvas_h = int(params["video_height"]) if params.get("video_height") else None
        if canvas_w is None or canvas_h is None:
            # 自动根据轨迹范围选择合适尺寸 (16:9)
            calc_canvas_and_origin(
                points3d, 1280, 720, math.radians(params["pitch_deg"]),
                params["z_scale"], params["padding"])
            canvas_w = 1280
            canvas_h = 720

        # 偶数化（编码器要求）
        if canvas_w % 2:
            canvas_w += 1
        if canvas_h % 2:
            canvas_h += 1

        # 计算 scale / cx / cy
        scale, cx, cy = calc_canvas_and_origin(
            points3d, canvas_w, canvas_h, math.radians(params["pitch_deg"]),
            params["z_scale"], params["padding"])
        print(f"[Epsilon] 画布: {canvas_w}x{canvas_h}, scale={scale:.2f}, "
              f"z_scale={params['z_scale']}, line_width={params['line_width']}")

        # 生成帧
        frame_dir = os.path.join(out_dir, EPS_FRAMES)
        cnt = generate_frames(
            points3d, frame_count, canvas_w, canvas_h, scale, cx, cy,
            params["pitch_deg"], params["z_scale"], params,
            frame_dir, "Epsilon_3D", stop_event)

        if stop_event and stop_event.is_set():
            result["stopped"] = True
            if os.path.isdir(frame_dir):
                shutil.rmtree(frame_dir)
            print("[Epsilon] 已清理中断的帧目录")
        elif cnt > 0:
            ok = compile_video(frame_dir, out_file, cnt, canvas_w, canvas_h,
                               params["fps"], params["transparent"], stop_event)
            if ok:
                result["video"] = out_file
                result["success"] = True
            elif stop_event and stop_event.is_set():
                result["stopped"] = True
                if os.path.isdir(frame_dir):
                    shutil.rmtree(frame_dir)

    except Exception as e:
        print(f"[Epsilon] 错误: {e}")
        traceback.print_exc()
        result["success"] = False

    finally:
        if cleanup and result.get("success") and not result.get("stopped"):
            t0_cl = time.time()
            full = os.path.join(out_dir, EPS_FRAMES)
            if os.path.isdir(full):
                shutil.rmtree(full)
                result["cleanup_time"] = time.time() - t0_cl
                print(f"[Epsilon_清理] 已清理帧目录，耗时 {result['cleanup_time']:.2f}s")

    result["total_time"] = time.time() - t0_all
    return result


# ============================================================
# CLI 交互
# ============================================================
def find_fit_files():
    paths = [".", "./data", "./fit", "./activities"]
    files = []
    for p in paths:
        if os.path.exists(p):
            files.extend(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".fit"))
    return sorted(set(files))


def _check_quit(choice):
    if choice.strip().lower() == 'q':
        print("用户取消，退出程序。")
        sys.exit(0)


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
        print("[Epsilon] 无有效 Lap")
        return None, None, None, None
    tz = DEFAULT_PARAMS.get("timezone_offset", 0)
    for num, (idx, st, et) in enumerate(laps, start=1):
        print(f"[{num}] {(st+timedelta(hours=tz)).strftime('%H:%M:%S')} -> "
              f"{(et+timedelta(hours=tz)).strftime('%H:%M:%S')}")
    choice = input("请选择 Lap (q 退出, 可多选逗号分隔, 如 1,3): ").strip().lower()
    _check_quit(choice)
    try:
        nums = sorted({int(x.strip()) for x in choice.split(',') if x.strip()})
    except ValueError:
        print("[Epsilon] 输入无效，请重新输入")
        return select_laps(fit_path)
    if not (1 <= min(nums) <= max(nums) <= len(laps)):
        print(f"[Epsilon] 请输入 1 ~ {len(laps)} 之间的数字")
        return select_laps(fit_path)
    idxs = [n - 1 for n in nums]
    return laps[min(idxs)][1], laps[max(idxs)][2], nums, list(range(min(idxs)+1, max(idxs)+2))


def _input_with_quit(prompt, default):
    raw = input(prompt).strip()
    if raw.lower() == 'q':
        print("用户取消，退出程序。")
        sys.exit(0)
    if raw == '':
        return default
    try:
        return int(raw)
    except ValueError:
        print("[Epsilon] 输入无效，使用默认值")
        return default


def main():
    print("=== Epsilon 2.5D 位置/海拔 透明地图视频生成器 ===\n")

    # 1. 选文件
    fits = find_fit_files()
    if not fits:
        print("[Epsilon] 未找到 FIT 文件（已扫描 . / ./data / ./fit / ./activities）")
        return
    for i, f in enumerate(fits, start=1):
        print(f"[{i}] {f}")
    c = input("请选择文件 (q 退出): ").strip().lower()
    _check_quit(c)
    try:
        fit_path = fits[int(c) - 1]
    except (ValueError, IndexError):
        print("[Epsilon] 无效选择")
        return

    # 2. 选 Lap
    lap_start, lap_end, _, _ = select_laps(fit_path)
    if lap_start is None:
        return

    # 3. FPS
    print("\n请设置帧率（直接回车使用默认，输入 q 退出）:")
    fps = _input_with_quit(f"  FPS (默认 {DEFAULT_PARAMS['fps']}): ", DEFAULT_PARAMS['fps'])

    # 4. 清理旧帧
    if os.path.exists(EPS_FRAMES):
        print(f"[Epsilon_清理] 检测到已存在目录 {EPS_FRAMES}，CLI 模式将覆盖清理")
        shutil.rmtree(EPS_FRAMES)

    # 5. 执行
    t0 = time.time()
    try:
        result = generate_epsilon_video(
            fit_path=fit_path, lap_start=lap_start, lap_end=lap_end,
            fps=fps, cleanup=True)
    except Exception as e:
        print(f"[Epsilon] 运行失败: {e}")
        traceback.print_exc()
        return

    # 6. 报告
    total = time.time() - t0
    m, s = divmod(int(total), 60)
    if result.get("video") and os.path.exists(result["video"]):
        print(f"[Epsilon] ✅ 视频: {result['video']}")
    else:
        print("[Epsilon] ❌ 未生成视频")
    print(f"[Epsilon] ⏱️ 总用时: {m}分{s}秒 ({total:.2f}s)")
    if result.get("cleanup_time"):
        print(f"[Epsilon_清理] 清理用时: {result['cleanup_time']:.2f}s")


if __name__ == "__main__":
    main()
