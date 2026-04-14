import os
import numpy as np
from fitparse import FitFile
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import time
from datetime import datetime, timedelta
import shutil

# —— 配置区域 —— 
FIT_PATH        = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-11-06-15-17.fit"   # 替换为您的FIT文件路径
OUTPUT_DIR      = "frames_hud"                # 临时帧目录
FPS             = 30                          # 帧率
WIDTH, HEIGHT   = 480, 270                    # 分辨率
FONT_SIZE       = 25                          # 字体大小
PRINT_INTERVAL  = 10                          # 进度打印间隔（秒）
SPEED_THRESHOLD = 3.0                         # 速度阈值，低于此值视为停车

# —— 在这里输入你要截取的绝对时间 —— 
lap_start = datetime(2026, 4, 10, 22, 15, 17)
lap_end   = datetime(2026, 4, 10, 22, 18, 17)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_MOV_A = f"hud_overlay_alpha_{timestamp}.mov"


def debug_print_config():
    duration = (lap_end - lap_start).total_seconds()
    print("\n=== 配置参数检查 ===")
    print(f"FIT文件路径: {FIT_PATH}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"输出视频: {OUTPUT_MOV_A}")
    print(f"帧率(FPS): {FPS}")
    print(f"分辨率: {WIDTH}x{HEIGHT}")
    print(f"开始时间: {lap_start} (UTC)")
    print(f"结束时间: {lap_end} (UTC)")
    print(f"计算时长: {duration}秒 ({duration//60}分{duration%60}秒)")
    print(f"预期总帧数: {int(duration*FPS)}帧")
    print(f"速度显示阈值: {SPEED_THRESHOLD} km/h")
    print("==================\n")


def validate_frames(frame_count, output_dir):
    existing_frames = len([f for f in os.listdir(output_dir) if f.startswith("frame_")])
    if existing_frames != frame_count:
        raise RuntimeError(
            f"帧数不匹配！预期 {frame_count} 帧，实际生成 {existing_frames} 帧\n"
            "可能原因：渲染过程中断或文件名冲突"
        )
    print(f"[验证] 帧连续性检查通过: 共{existing_frames}帧")


def load_and_filter(fit_path, start_abs_time, end_abs_time):
    print(f"\n[DEBUG] 正在加载FIT数据，绝对时间范围: {start_abs_time} - {end_abs_time}")
    fit = FitFile(fit_path)
    recs = []
    for m in fit.get_messages('record'):
        vals = m.get_values()
        if 'timestamp' in vals:
            recs.append(vals)

    if not recs:
        raise RuntimeError("FIT文件中没有数据")

    print(f"[DEBUG] 第一条记录时间: {recs[0]['timestamp']} (UTC)")

    offs, spd, pwr, hr, cad = [], [], [], [], []
    for r in recs:
        ts = r['timestamp']
        if not (start_abs_time <= ts <= end_abs_time):
            continue
        offset = (ts - start_abs_time).total_seconds()
        offs.append(offset)
        s = r.get('speed') or r.get('enhanced_speed', 0.0)
        
        # 在加载阶段就进行速度过滤
        raw_speed = s * 3.6
        if raw_speed < SPEED_THRESHOLD:
            speed_value = 0.0
        else:
            speed_value = raw_speed
            
        spd.append(speed_value)
        pwr.append(r.get('power', np.nan))
        hr.append(r.get('heart_rate', np.nan))
        cad.append(r.get('cadence', np.nan))

    if not offs:
        raise RuntimeError("指定时间范围内没有数据")

    # 统计速度过滤结果
    zero_count = sum(1 for s in spd if s == 0.0)
    print(f"[DEBUG] 过滤后有效记录数: {len(offs)}条")
    print(f"[DEBUG] 实际数据时间范围: {min(offs):.1f}-{max(offs):.1f}秒")
    print(f"[速度过滤] 加载阶段将{zero_count}个低速点(<{SPEED_THRESHOLD}km/h)设为0")
    print(f"[速度过滤] 零速点比例: {zero_count}/{len(spd)} ({(zero_count/len(spd))*100:.1f}%)")

    return {
        'offsets': np.array(offs),
        'speed':   np.array(spd),
        'power':   np.array(pwr),
        'hr':      np.array(hr),
        'cad':     np.array(cad),
    }


def interpolate(data, duration_sec):
    print(f"\n[DEBUG] 开始数据插值，目标时长: {duration_sec}秒")
    x = data['offsets']
    time_points = np.linspace(0, duration_sec, int(duration_sec * FPS) + 1)
    print(f"[DEBUG] 生成{len(time_points)}个时间点")
    
    # 第一步：识别停车时间段
    # 在原始数据中，标记哪些点速度<阈值
    is_stopped_original = data['speed'] < SPEED_THRESHOLD
    
    # 第二步：为每个插值点确定原始状态
    # 通过插值确定每个时间点的"停车状态"
    # 使用最近邻插值，确保时间连续性
    
    # 插值速度
    interp_speed = interp1d(x, data['speed'], kind='linear', fill_value="extrapolate")(time_points)
    
    # 关键修改：在原始数据中识别停车段
    # 构建一个"停车状态"的插值，使用阶跃函数（最近邻）
    # 每个插值点的状态由前一个原始数据点决定
    stop_flags = np.zeros_like(time_points, dtype=bool)
    
    for i, t in enumerate(time_points):
        # 找到最后一个原始数据点的时间 <= 当前插值时间
        idx = np.searchsorted(x, t, side='right') - 1
        
        if idx >= 0 and idx < len(is_stopped_original):
            # 如果前一个原始数据点是停车状态，那么这个插值点也是停车状态
            stop_flags[i] = is_stopped_original[idx]
        else:
            # 边界情况处理
            stop_flags[i] = False
    
    # 第三步：应用停车状态
    interp_speed_clean = interp_speed.copy()
    interp_speed_clean[stop_flags] = 0.0
    
    # 第四步：应用阈值过滤（作为双重保障）
    interp_speed_clean = np.where(interp_speed_clean < SPEED_THRESHOLD, 0.0, interp_speed_clean)
    
    # 其他数据的插值保持不变
    interp = lambda arr: interp1d(x, arr, kind='linear', fill_value="extrapolate")(time_points)
    
    result = {
        'speed': interp_speed_clean,
        'power': interp(data['power']).astype(int),
        'hr':    interp(data['hr']).astype(int),
        'cad':   interp(data['cad']).astype(int),
    }
    
    # 统计
    zero_count = np.sum(result['speed'] < 0.1)
    non_zero_count = len(result['speed']) - zero_count
    print(f"[停车段识别] 识别出{np.sum(stop_flags)}个插值点处于停车状态")
    print(f"[最终过滤] 零速点比例: {zero_count}/{len(result['speed'])} ({(zero_count/len(result['speed']))*100:.1f}%)")
    
    return result


def format_value(value, value_type):
    """
    格式化数据值用于显示
    
    参数:
        value: 数值
        value_type: 数据类型 ('speed', 'power', 'hr', 'cad')
    
    返回:
        格式化后的字符串
    """
    if value_type == 'speed':
        if value < SPEED_THRESHOLD:
            return f"<{SPEED_THRESHOLD}km/h"
        return f"{value:.1f} km/h"
    elif value_type in ['power', 'cad']:
        if value == -2147483648:  # 无效值标记
            return "--"
        if value_type == 'power':
            return f"{value} W"
        else:
            return f"{value} rpm"
    elif value_type == 'hr':
        return f"{value} bpm"
    return str(value)


def render_frames(data_intp, duration_sec):
    print("\n[DEBUG] 开始渲染帧")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    frame_count = int(duration_sec * FPS)

    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("frame_"):
            os.remove(os.path.join(OUTPUT_DIR, f))

    plt.ioff()
    fig, ax = plt.subplots(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_position([0, 0.05, 1, 0.9])
    ax.axis('off')

    text_obj = ax.text(
        0.05, 0.4, "",
        fontsize=FONT_SIZE,
        color='white',
        bbox=dict(facecolor='black', alpha=0.4, boxstyle='round,pad=0.25'),
        transform=ax.transAxes
    )

    last_print_time = time.time()
    start_time = time.time()

    for idx in range(frame_count):
        current_time = time.time()
        if current_time - last_print_time >= PRINT_INTERVAL:
            elapsed = current_time - start_time
            remaining = (frame_count - idx) * (elapsed / (idx + 1))
            print(
                f"[进度] {idx+1}/{frame_count}帧 | "
                f"已用: {elapsed:.1f}s | "
                f"剩余: {remaining:.1f}s | "
                f"速度: {idx/elapsed:.1f}帧/s"
            )
            last_print_time = current_time

        speed_display = format_value(data_intp['speed'][idx], 'speed')
        power_display = format_value(data_intp['power'][idx], 'power')
        hr_display = format_value(data_intp['hr'][idx], 'hr')
        cad_display = format_value(data_intp['cad'][idx], 'cad')

        text_obj.set_text(
            f"Speed: {speed_display}\n"
            f"Power: {power_display}\n"
            f"Heart Rate: {hr_display}\n"
            f"Cadence: {cad_display}"
        )
        
        path = os.path.join(OUTPUT_DIR, f"frame_{idx:06d}.png")
        fig.savefig(path, dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    validate_frames(frame_count, OUTPUT_DIR)
    return frame_count


def assemble_alpha_mov(frame_count):
    print(f"\n[DEBUG] 合成视频")

    cmd = (
        f'ffmpeg -y -framerate {FPS} -start_number 0 -i "{OUTPUT_DIR}/frame_%06d.png" '
        f'-vf "scale={WIDTH}:{HEIGHT},setsar=1" '
        f'-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le '
        f'-frames:v {frame_count} "{OUTPUT_MOV_A}"'
    )
    print(f"[DEBUG] FFmpeg命令:\n{cmd}")

    ffmpeg_start = time.time()
    os.system(cmd)
    ffmpeg_time = time.time() - ffmpeg_start
    print(f"[DEBUG] FFmpeg合成耗时: {ffmpeg_time:.1f}秒")


if __name__ == "__main__":
    start_time = time.time()
    debug_print_config()

    duration = (lap_end - lap_start).total_seconds()

    try:
        raw = load_and_filter(FIT_PATH, lap_start, lap_end)
        data_intp = interpolate(raw, duration)
        total_frames = render_frames(data_intp, duration)
        assemble_alpha_mov(total_frames)

        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
            print(f"\n[清理] 已删除临时帧目录: {OUTPUT_DIR}")

    except Exception as e:
        print(f"❌ 发生错误: {str(e)}")

    end_time = time.time()
    elapsed = end_time - start_time
    minutes, seconds = divmod(int(elapsed), 60)
    print(f"\n✅ 总耗时：{minutes}分{seconds}秒（{elapsed:.2f}秒）")