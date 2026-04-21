import os
import numpy as np
from fitparse import FitFile
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import time
from datetime import datetime, timedelta
import shutil

def generate_hud_video(fit_path, lap_start, lap_end, 
                       output_dir="frames_hud", 
                       fps=30, 
                       width=480, height=270, 
                       font_size=25, 
                       print_interval=10, 
                       speed_threshold=3.0):
    
    # 内部配置变量
    OUTPUT_DIR = output_dir
    FPS = fps
    WIDTH, HEIGHT = width, height
    FONT_SIZE = font_size
    PRINT_INTERVAL = print_interval
    SPEED_THRESHOLD = speed_threshold
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    OUTPUT_MOV_A = f"hud_overlay_alpha_{timestamp}.mov"
    
    def debug_print_config():
        duration = (lap_end - lap_start).total_seconds()
        print("\n=== 配置参数检查 ===")
        print(f"FIT文件路径: {fit_path}")
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
        
        is_stopped_original = data['speed'] < SPEED_THRESHOLD
        
        interp_speed = interp1d(x, data['speed'], kind='linear', fill_value="extrapolate")(time_points)
        
        stop_flags = np.zeros_like(time_points, dtype=bool)
        
        for i, t in enumerate(time_points):
            idx = np.searchsorted(x, t, side='right') - 1
            if idx >= 0 and idx < len(is_stopped_original):
                stop_flags[i] = is_stopped_original[idx]
            else:
                stop_flags[i] = False
        
        interp_speed_clean = interp_speed.copy()
        interp_speed_clean[stop_flags] = 0.0
        interp_speed_clean = np.where(interp_speed_clean < SPEED_THRESHOLD, 0.0, interp_speed_clean)
        
        interp = lambda arr: interp1d(x, arr, kind='linear', fill_value="extrapolate")(time_points)
        
        result = {
            'speed': interp_speed_clean,
            'power': interp(data['power']).astype(int),
            'hr':    interp(data['hr']).astype(int),
            'cad':   interp(data['cad']).astype(int),
        }
        
        zero_count = np.sum(result['speed'] < 0.1)
        print(f"[停车段识别] 识别出{np.sum(stop_flags)}个插值点处于停车状态")
        print(f"[最终过滤] 零速点比例: {zero_count}/{len(result['speed'])} ({(zero_count/len(result['speed']))*100:.1f}%)")
        return result
    
    def format_value(value, value_type):
        if value_type == 'speed':
            if value < SPEED_THRESHOLD:
                return f"<{SPEED_THRESHOLD}km/h"
            return f"{value:.1f} km/h"
        elif value_type in ['power', 'cad']:
            if value == -2147483648:
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
    
    start_time_total = time.time()
    debug_print_config()
    duration = (lap_end - lap_start).total_seconds()
    try:
        raw = load_and_filter(fit_path, lap_start, lap_end)
        data_intp = interpolate(raw, duration)
        total_frames = render_frames(data_intp, duration)
        assemble_alpha_mov(total_frames)
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
            print(f"\n[清理] 已删除临时帧目录: {OUTPUT_DIR}")
    except Exception as e:
        print(f"❌ 发生错误: {str(e)}")
    end_time_total = time.time()
    elapsed = end_time_total - start_time_total
    minutes, seconds = divmod(int(elapsed), 60)
    print(f"\n✅ 总耗时：{minutes}分{seconds}秒（{elapsed:.2f}秒）")

if __name__ == "__main__":
    FIT_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2026-04-19-10-56-52.fit"
    OUTPUT_DIR = "frames_hud"
    FPS = 30
    WIDTH, HEIGHT = 480, 270
    FONT_SIZE = 25
    PRINT_INTERVAL = 10
    SPEED_THRESHOLD = 3.0
    lap_start = datetime(2026, 4, 19, 2, 56, 52)
    lap_end   = datetime(2026, 4, 19, 2, 57, 22)
    
    generate_hud_video(
        fit_path=FIT_PATH,
        lap_start=lap_start,
        lap_end=lap_end,
        output_dir=OUTPUT_DIR,
        fps=FPS,
        width=WIDTH, height=HEIGHT,
        font_size=FONT_SIZE,
        print_interval=PRINT_INTERVAL,
        speed_threshold=SPEED_THRESHOLD
    )