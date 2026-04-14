import os
import numpy as np
from fitparse import FitFile
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import time
from datetime import datetime, timedelta
import shutil   # 用于删除目录

# —— 配置区域 —— 
FIT_PATH        = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-11-06-15-17.fit"   # 替换为您的FIT文件路径
OUTPUT_DIR      = "frames_hud"                # 临时帧目录
FPS             = 30                          # 帧率
WIDTH, HEIGHT   = 480, 270                    # 分辨率
FONT_SIZE       = 25                          # 字体大小
PRINT_INTERVAL  = 10                          # 进度打印间隔（秒）

# —— 在这里输入你要截取的绝对时间 —— 
lap_start = datetime(2026, 4, 10, 22, 15, 17)
lap_end   = datetime(2026, 4, 10, 22, 18, 17)

# 自动生成输出文件名
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_MOV_A = f"hud_overlay_alpha_{timestamp}.mov"

# 常量定义
POWER_INVALID = -2147483648
CADENCE_INVALID = -2147483648
CADENCE_MAX_VALID = 200
CADENCE_MIN_VALID = 0
CADENCE_SPIKE_THRESHOLD = 50
SPEED_STOP_THRESHOLD = 1.0
POWER_STOP_THRESHOLD = 10
SPEED_SMOOTH_WINDOW = 0.5  # 秒，速度平滑窗口（可选）


def debug_print_config():
    """打印所有关键配置参数"""
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
    print(f"速度显示模式: 实时显示（最近邻插值）")
    print(f"踏频显示模式: 实时显示（最近邻插值）")
    print(f"停车速度阈值: {SPEED_STOP_THRESHOLD} km/h")
    print("==================\n")


def validate_frames(frame_count, output_dir):
    """检查生成的帧是否连续且完整"""
    existing_frames = len([f for f in os.listdir(output_dir) if f.startswith("frame_")])
    if existing_frames != frame_count:
        raise RuntimeError(
            f"帧数不匹配！预期 {frame_count} 帧，实际生成 {existing_frames} 帧\n"
            "可能原因：渲染过程中断或文件名冲突"
        )
    print(f"[验证] 帧连续性检查通过: 共{existing_frames}帧")


# —— STEP1：加载并严格过滤 FIT 数据 ——
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
        spd.append(s * 3.6)
        
        raw_pwr = r.get('power')
        if raw_pwr is None or abs(raw_pwr - POWER_INVALID) < 1000:
            pwr.append(np.nan)
        else:
            pwr.append(float(raw_pwr))
        
        raw_hr = r.get('heart_rate')
        hr.append(np.nan if raw_hr is None else float(raw_hr))
        
        raw_cad = r.get('cadence')
        if raw_cad is None or abs(raw_cad - CADENCE_INVALID) < 1000:
            cad.append(np.nan)
        elif raw_cad < CADENCE_MIN_VALID or raw_cad > CADENCE_MAX_VALID:
            cad.append(np.nan)
        else:
            cad.append(float(raw_cad))

    if not offs:
        raise RuntimeError("指定时间范围内没有数据")

    print(f"[DEBUG] 过滤后有效记录数: {len(offs)}条")
    print(f"[DEBUG] 实际数据时间范围: {min(offs):.1f}-{max(offs):.1f}秒")
    
    valid_pwr = sum(1 for v in pwr if not np.isnan(v))
    valid_cad = sum(1 for v in cad if not np.isnan(v))
    print(f"[DEBUG] 有效功率数据点: {valid_pwr}/{len(pwr)} ({valid_pwr/len(pwr)*100:.1f}%)")
    print(f"[DEBUG] 有效踏频数据点: {valid_cad}/{len(cad)} ({valid_cad/len(cad)*100:.1f}%)")
    
    return {
        'offsets': np.array(offs),
        'speed':   np.array(spd),
        'power':   np.array(pwr),
        'hr':      np.array(hr),
        'cad':     np.array(cad),
    }


# —— STEP2：踏频数据清洗 ——
def clean_cadence_data(cadence_values, time_offsets):
    """清洗踏频数据的异常值和突变"""
    print(f"[DEBUG] 开始踏频数据清洗")
    
    if len(cadence_values) == 0:
        return cadence_values
    
    cleaned = cadence_values.copy()
    total_points = len(cleaned)
    
    valid_before = np.sum(~np.isnan(cleaned))
    print(f"[DEBUG] 清洗前有效踏频点: {valid_before}/{total_points}")
    
    spike_count = 0
    for i in range(1, len(cleaned)):
        if np.isnan(cleaned[i]) or np.isnan(cleaned[i-1]):
            continue
        
        delta = abs(cleaned[i] - cleaned[i-1])
        time_delta = time_offsets[i] - time_offsets[i-1] if i < len(time_offsets) else 1.0
        
        if time_delta > 0:
            rate = delta / time_delta
            if rate > CADENCE_SPIKE_THRESHOLD:
                cleaned[i] = np.nan
                spike_count += 1
    
    print(f"[DEBUG] 检测到突变点: {spike_count}个")
    
    last_valid = None
    for i in range(len(cleaned)):
        if np.isnan(cleaned[i]):
            if last_valid is not None:
                cleaned[i] = last_valid
        else:
            last_valid = cleaned[i]
    
    valid_after = np.sum(~np.isnan(cleaned))
    print(f"[DEBUG] 清洗后有效踏频点: {valid_after}/{total_points}")
    
    return cleaned


# —— STEP3：速度数据预处理（可选平滑）——
def preprocess_speed_data(speed_values, time_offsets):
    """预处理速度数据，可选的轻微平滑"""
    print(f"[DEBUG] 预处理速度数据")
    
    if len(speed_values) == 0:
        return speed_values
    
    # 简单中值滤波去除小抖动
    smoothed = speed_values.copy()
    
    # 可选：对速度进行轻微平滑（如果原始数据噪声大）
    # 这里使用简单的移动平均，窗口大小为3个点
    if len(smoothed) >= 3:
        for i in range(1, len(smoothed)-1):
            if not np.isnan(smoothed[i-1]) and not np.isnan(smoothed[i]) and not np.isnan(smoothed[i+1]):
                smoothed[i] = np.mean([smoothed[i-1], smoothed[i], smoothed[i+1]])
    
    # 检测停车段
    stop_segments = []
    in_stop = False
    stop_start = 0
    
    for i in range(len(smoothed)):
        if smoothed[i] < SPEED_STOP_THRESHOLD:
            if not in_stop:
                in_stop = True
                stop_start = i
        else:
            if in_stop:
                stop_segments.append((stop_start, i-1))
                in_stop = False
    
    if in_stop:
        stop_segments.append((stop_start, len(smoothed)-1))
    
    print(f"[DEBUG] 检测到 {len(stop_segments)} 个停车段")
    for start_idx, end_idx in stop_segments[:3]:  # 显示前3个
        start_time = time_offsets[start_idx] if start_idx < len(time_offsets) else 0
        end_time = time_offsets[end_idx] if end_idx < len(time_offsets) else 0
        print(f"[DEBUG]  停车段 {start_idx}-{end_idx}: {start_time:.1f}-{end_time:.1f}s")
    
    return smoothed


# —— STEP4：完全实时插值（速度和踏频都用最近邻）——
def real_time_interpolate(data, duration_sec):
    print(f"\n[DEBUG] 开始完全实时数据插值，目标时长: {duration_sec}秒")
    x = data['offsets']
    time_points = np.linspace(0, duration_sec, int(duration_sec * FPS) + 1)
    print(f"[DEBUG] 生成{len(time_points)}个时间点")
    print(f"[DEBUG] 插值策略: 速度=最近邻, 踏频=最近邻, 功率=线性, 心率=线性")
    
    # 1. 速度：最近邻插值（实时显示）
    print("[DEBUG] 处理速度数据（最近邻插值，实时显示）")
    processed_speed = preprocess_speed_data(data['speed'], data['offsets'])
    
    if np.any(~np.isnan(processed_speed)):
        speed_interp = interp1d(x, processed_speed, kind='nearest', fill_value="extrapolate", bounds_error=False)
        speed_values = speed_interp(time_points)
    else:
        speed_values = np.full_like(time_points, 0.0)
    
    # 应用停车阈值
    speed_values[np.abs(speed_values) < SPEED_STOP_THRESHOLD] = 0.0
    
    # 2. 功率：线性插值
    print("[DEBUG] 处理功率数据（线性插值）")
    power_valid = ~np.isnan(data['power'])
    if np.any(power_valid):
        x_valid = x[power_valid]
        pwr_valid = data['power'][power_valid]
        pwr_interp = interp1d(x_valid, pwr_valid, kind='linear', fill_value=np.nan, bounds_error=False)
        power_values = pwr_interp(time_points)
    else:
        power_values = np.full_like(time_points, np.nan)
    
    # 3. 心率：线性插值
    print("[DEBUG] 处理心率数据（线性插值）")
    hr_valid = ~np.isnan(data['hr'])
    if np.any(hr_valid):
        x_hr_valid = x[hr_valid]
        hr_valid_data = data['hr'][hr_valid]
        hr_interp = interp1d(x_hr_valid, hr_valid_data, kind='linear', fill_value=np.nan, bounds_error=False)
        hr_values = hr_interp(time_points)
    else:
        hr_values = np.full_like(time_points, np.nan)
    
    # 4. 踏频：最近邻插值（实时显示）
    print("[DEBUG] 处理踏频数据（清洗+最近邻插值，实时显示）")
    cleaned_cadence = clean_cadence_data(data['cad'], data['offsets'])
    
    if np.any(~np.isnan(cleaned_cadence)):
        cad_interp = interp1d(x, cleaned_cadence, kind='nearest', fill_value=np.nan, bounds_error=False)
        cad_values = cad_interp(time_points)
    else:
        cad_values = np.full_like(time_points, np.nan)
    
    result = {
        'speed': speed_values,
        'power': power_values,
        'hr': hr_values,
        'cad': cad_values,
    }
    
    # 统计分析
    print("[DEBUG] 插值结果统计:")
    print(f"  速度: 有效{np.sum(~np.isnan(speed_values))}/{len(speed_values)}帧, "
          f"停车{np.sum(speed_values < 0.1)}帧")
    print(f"  功率: 有效{np.sum(~np.isnan(power_values))}/{len(power_values)}帧")
    print(f"  踏频: 有效{np.sum(~np.isnan(cad_values))}/{len(cad_values)}帧")
    
    # 检测停车段的速度行为
    stop_frames = speed_values < 0.1
    if np.any(stop_frames):
        cad_in_stop = cad_values[stop_frames]
        non_zero_cad = np.sum(cad_in_stop > 0)
        print(f"[DEBUG] 停车段检测: {np.sum(stop_frames)}帧, "
              f"其中踏频>0: {non_zero_cad}帧")
    
    print("[DEBUG] 实时插值完成")
    return result


# —— STEP5：增强型停车逻辑修正 ——
def enhanced_stop_logic(data_intp, time_points):
    """增强型停车逻辑，考虑前后时间关系"""
    print(f"\n[DEBUG] 应用增强型停车逻辑")
    
    speed_values = data_intp['speed']
    power_values = data_intp['power']
    cad_values = data_intp['cad']
    
    # 1. 停车检测：速度和功率都低
    speed_stop_mask = speed_values < SPEED_STOP_THRESHOLD
    power_stop_mask = np.abs(np.nan_to_num(power_values, nan=0.0)) < POWER_STOP_THRESHOLD
    stop_mask = speed_stop_mask & power_stop_mask
    
    # 2. 扩展停车段：前后各0.5秒也视为停车
    expanded_stop_mask = stop_mask.copy()
    frame_window = int(FPS * 0.5)  # 0.5秒对应的帧数
    
    for i in range(len(stop_mask)):
        if stop_mask[i]:
            start_idx = max(0, i - frame_window)
            end_idx = min(len(stop_mask), i + frame_window + 1)
            expanded_stop_mask[start_idx:end_idx] = True
    
    # 3. 在停车段强制归零
    original_cad = cad_values.copy()
    cad_values[expanded_stop_mask] = 0
    
    # 处理NaN
    cad_nan_mask = np.isnan(cad_values)
    cad_values[cad_nan_mask & expanded_stop_mask] = 0
    
    # 4. 功率在停车段强制归零
    power_values[expanded_stop_mask] = 0
    pwr_nan_mask = np.isnan(power_values)
    power_values[pwr_nan_mask & expanded_stop_mask] = 0
    
    # 5. 速度在停车段确保为0
    speed_values[expanded_stop_mask] = 0.0
    
    # 统计
    stop_frames = np.sum(stop_mask)
    expanded_frames = np.sum(expanded_stop_mask)
    cad_corrected = np.sum((original_cad != cad_values) & (~np.isnan(original_cad)))
    
    print(f"[DEBUG] 停车逻辑统计:")
    print(f"  核心停车帧: {stop_frames}/{len(stop_mask)}")
    print(f"  扩展停车帧: {expanded_frames}/{len(stop_mask)} (+{expanded_frames-stop_frames}帧)")
    print(f"  踏频修正帧: {cad_corrected}帧")
    print(f"  最终停车率: {expanded_frames/len(stop_mask)*100:.1f}%")
    
    data_intp['speed'] = speed_values
    data_intp['power'] = power_values
    data_intp['cad'] = cad_values
    
    return data_intp


# —— STEP6：渲染所有帧 ——
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
        
        speed_val = data_intp['speed'][idx]
        power_val = data_intp['power'][idx]
        hr_val = data_intp['hr'][idx]
        cad_val = data_intp['cad'][idx]
        
        # 格式化显示
        speed_text = f"{speed_val:.1f} km/h"
        
        if np.isnan(power_val):
            power_text = "0 W" if speed_val < 0.1 else "--"
        else:
            power_text = f"{int(power_val)} W"
        
        hr_text = f"{int(hr_val)} bpm" if not np.isnan(hr_val) else "--"
        cad_text = f"{int(cad_val)} rpm" if not np.isnan(cad_val) else "--"
        
        text_obj.set_text(
            f"Speed: {speed_text}\n"
            f"Power: {power_text}\n"
            f"Heart Rate: {hr_text}\n"
            f"Cadence: {cad_text}"
        )
        
        path = os.path.join(OUTPUT_DIR, f"frame_{idx:06d}.png")
        fig.savefig(path, dpi=100, pad_inches=0, transparent=True)

    plt.close(fig)
    validate_frames(frame_count, OUTPUT_DIR)
    return frame_count


# —— STEP7：FFmpeg合成 ——
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


# —— 主程序 ——
if __name__ == "__main__":
    start_time = time.time()
    debug_print_config()

    duration = (lap_end - lap_start).total_seconds()

    try:
        raw = load_and_filter(FIT_PATH, lap_start, lap_end)
        time_points = np.linspace(0, duration, int(duration * FPS) + 1)
        data_intp = real_time_interpolate(raw, duration)
        data_intp = enhanced_stop_logic(data_intp, time_points)
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