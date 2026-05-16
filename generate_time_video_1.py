import os
import sys
import glob
import time
import subprocess
import shutil
from datetime import datetime, timedelta
from fitparse import FitFile
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import time
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
# ==================== 用户可配置参数 ====================
# FIT文件路径（设置为None则自动查找最新文件）
FIT_PATH = None

# 输出视频参数
FPS = 1
OUTPUT_DIR = "frames_timestamp"  # 临时帧目录
OUTPUT_VIDEO = f"timestamp_overlay_{timestamp}.mov"  # 输出视频文件名

# 时区设置（北京时间 = UTC+8）
TIMEZONE_OFFSET = 8  # 小时

# 字体样式设置
# FONT_SIZE = 60
# FONT_COLOR = (255, 255, 255)  # 白色
# OUTLINE_WIDTH = 3
# OUTLINE_COLOR = (0, 0, 0)  # 黑色

FONT_SIZE = 60
FONT_COLOR = (255, 165, 0)  # 橙色 (RGB: 255, 165, 0)
OUTLINE_WIDTH = 3
OUTLINE_COLOR = (0, 0, 0)  # 黑色 OUTLINE_COLOR = (255, 255, 255)  # 白色

# 视频尺寸设置（设置为None则自动计算）
VIDEO_WIDTH = None
VIDEO_HEIGHT = None
VIDEO_PADDING = 20  # 像素，文本周围的边距

# 字体文件路径（如果使用自定义字体）
# 如果设置为None，将使用PIL的默认字体
FONT_PATH = None
# =====================================================

def find_latest_fit_file():
    """查找当前目录下最新的.fit文件"""
    fit_files = glob.glob("*.fit")
    
    if not fit_files:
        # 如果没有找到，尝试在子目录中查找
        fit_files = glob.glob("**/*.fit", recursive=True)
    
    if not fit_files:
        return None
    
    # 按修改时间排序，获取最新的文件
    fit_files.sort(key=os.path.getmtime, reverse=True)
    latest_fit = os.path.abspath(fit_files[0])
    print(f"找到最新的FIT文件: {latest_fit}")
    return latest_fit

def get_all_laps(fit_path):
    """获取fit文件中的所有lap信息"""
    print(f"正在读取FIT文件: {fit_path}")
    fit = FitFile(fit_path)
    
    laps = []
    print("\n=== FIT文件中的Lap信息 ===")
    
    for i, lap in enumerate(fit.get_messages("lap")):
        vals = lap.get_values()
        start_time = vals.get("start_time")
        elapsed = vals.get("total_elapsed_time")
        trigger = vals.get("lap_trigger")
        total_distance = vals.get("total_distance", 0.0)
        
        if start_time is not None and elapsed is not None:
            end_time = start_time + timedelta(seconds=elapsed)
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
            
            lap_info = {
                "index": i + 1,
                "start_time": start_time,  # UTC时间
                "end_time": end_time,      # UTC时间
                "elapsed_seconds": elapsed,
                "total_distance": total_distance,
                "trigger": trigger
            }
            laps.append(lap_info)
            
            # 转换为北京时间显示
            start_beijing = start_time + timedelta(hours=TIMEZONE_OFFSET)
            end_beijing = end_time + timedelta(hours=TIMEZONE_OFFSET)
            
            print(f"[Lap {i+1}]")
            print(f"  开始时间(UTC): {start_time}")
            print(f"  开始时间(北京): {start_beijing}")
            print(f"  结束时间(北京): {end_beijing.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  持续时间: {elapsed:.1f}秒 ({elapsed//60}分{elapsed%60:.0f}秒)")
            print(f"  总距离: {total_distance/1000:.2f}km")
            print(f"  触发类型: {trigger}")
            print(f"  {'-'*40}")
    
    if not laps:
        print("未找到Lap信息")
    
    return laps

def select_laps_for_generation(laps):
    """让用户选择要生成的lap"""
    if not laps:
        print("没有可用的Lap信息")
        return None
    
    print("\n请选择要生成视频的Lap（输入序号，多个用逗号分隔，q退出）:")
    for lap in laps:
        start_beijing = lap['start_time'] + timedelta(hours=TIMEZONE_OFFSET)
        print(f"{lap['index']}. Lap {lap['index']} ({lap['elapsed_seconds']:.1f}秒, {start_beijing.strftime('%H:%M:%S')})")
    
    while True:
        choice = input("请输入选择: ").strip()
        
        if choice.lower() == 'q':
            return None
        
        if choice:
            try:
                selected_indices = [int(idx.strip()) for idx in choice.split(',')]
                selected_laps = []
                selected_start = None
                selected_end = None
                
                for idx in selected_indices:
                    if 1 <= idx <= len(laps):
                        lap = laps[idx-1]
                        selected_laps.append(lap)
                        
                        if selected_start is None or lap['start_time'] < selected_start:
                            selected_start = lap['start_time']
                        if selected_end is None or lap['end_time'] > selected_end:
                            selected_end = lap['end_time']
                    else:
                        print(f"警告: Lap {idx} 不存在，跳过")
                
                if selected_laps:
                    # 转换为北京时间显示
                    start_beijing = selected_start + timedelta(hours=TIMEZONE_OFFSET)
                    end_beijing = selected_end + timedelta(hours=TIMEZONE_OFFSET)
                    
                    print(f"\n已选择 {len(selected_laps)} 个Lap:")
                    for lap in selected_laps:
                        lap_start_beijing = lap['start_time'] + timedelta(hours=TIMEZONE_OFFSET)
                        lap_end_beijing = lap['end_time'] + timedelta(hours=TIMEZONE_OFFSET)
                        print(f"  Lap {lap['index']}: {lap_start_beijing} 到 {lap_end_beijing}")
                    print(f"合并时间范围: {start_beijing} 到 {end_beijing}")
                    return selected_start, selected_end, selected_laps
                else:
                    print("没有有效的选择")
            except ValueError:
                print("输入无效，请重新输入")

def get_fit_path():
    """获取FIT文件路径，如果未指定则自动查找最新文件"""
    if FIT_PATH is None:
        print("未指定FIT_PATH，正在查找当前目录下最新的.fit文件...")
        fit_path = find_latest_fit_file()
        if fit_path is None:
            print("❌ 未找到任何.fit文件")
            print("请在代码开头设置FIT_PATH，或在当前目录下放置.fit文件")
            return None
        return fit_path
    else:
        if not os.path.exists(FIT_PATH):
            print(f"❌ 找不到指定的FIT文件: {FIT_PATH}")
            return None
        return os.path.abspath(FIT_PATH)

def load_font(font_size):
    """加载字体"""
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            font = ImageFont.truetype(FONT_PATH, font_size)
            print(f"使用自定义字体: {FONT_PATH}")
        else:
            # 尝试加载系统字体
            try:
                # 在Windows上
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    # 在Linux/Mac上
                    font = ImageFont.truetype("DejaVuSans.ttf", font_size)
                except:
                    # 使用PIL的默认字体
                    font = ImageFont.load_default()
                    print("⚠️ 使用PIL默认字体（可能不支持中文）")
    except Exception as e:
        print(f"⚠️ 字体加载失败: {e}，使用默认字体")
        font = ImageFont.load_default()
    
    return font

def calculate_text_size(text, font):
    """计算文本尺寸"""
    # 创建一个临时图像来测量文本大小
    temp_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    
    # 获取文本边界框
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    
    return width, height

def calculate_video_dimensions(font, max_text="2026-12-31 23:59:59"):
    """计算视频尺寸，确保文本能完全显示"""
    # 计算最大文本的尺寸
    text_width, text_height = calculate_text_size(max_text, font)
    
    # 加上描边宽度
    text_width += OUTLINE_WIDTH * 2
    text_height += OUTLINE_WIDTH * 2
    
    # 加上边距
    if VIDEO_WIDTH is None or VIDEO_HEIGHT is None:
        # 自动计算尺寸
        width = text_width + VIDEO_PADDING * 2
        height = text_height + VIDEO_PADDING * 2
        
        # 确保宽高是偶数（视频编码要求）
        if width % 2 != 0:
            width += 1
        if height % 2 != 0:
            height += 1
            
        print(f"自动计算视频尺寸: {width}x{height} (文本尺寸: {text_width}x{text_height})")
        return width, height
    else:
        # 使用用户指定的尺寸
        print(f"使用指定视频尺寸: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
        return VIDEO_WIDTH, VIDEO_HEIGHT

def create_timestamp_frame(timestamp_str, width, height, font):
    """创建时间戳帧"""
    # 创建透明背景图像
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 计算文本尺寸
    text_width, text_height = calculate_text_size(timestamp_str, font)
    
    # 计算文本位置（居中）
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    
    # 如果有描边，先绘制描边
    if OUTLINE_WIDTH > 0:
        # 在8个方向绘制描边
        for dx in [-OUTLINE_WIDTH, 0, OUTLINE_WIDTH]:
            for dy in [-OUTLINE_WIDTH, 0, OUTLINE_WIDTH]:
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), timestamp_str, font=font, fill=OUTLINE_COLOR)
    
    # 绘制主文本
    draw.text((x, y), timestamp_str, font=font, fill=FONT_COLOR)
    
    return image

def generate_timestamp_frames(lap_start, lap_end, width, height, font):
    """生成时间戳帧序列"""
    print(f"\n开始生成时间戳帧...")
    
    # 清理临时目录
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 计算总时长和总帧数
    duration = (lap_end - lap_start).total_seconds()
    total_frames = int(duration * FPS)
    
    print(f"时间范围: {lap_start} 到 {lap_end}")
    print(f"时长: {duration:.2f}秒")
    print(f"帧率: {FPS} FPS")
    print(f"总帧数: {total_frames}")
    print(f"视频尺寸: {width}x{height}")
    
    start_time = time.time()
    last_print_time = start_time
    frame_count = 0
    
    for i in range(total_frames):
        # 计算当前时间点
        current_time_utc = lap_start + timedelta(seconds=i / FPS)
        
        # 转换为北京时间
        current_time_beijing = current_time_utc + timedelta(hours=TIMEZONE_OFFSET)
        
        # 格式化时间字符串
        timestamp_str = current_time_beijing.strftime("%Y-%m-%d %H:%M:%S")
        
        # 创建帧
        frame = create_timestamp_frame(timestamp_str, width, height, font)
        
        # 保存帧
        frame_path = os.path.join(OUTPUT_DIR, f"frame_{i:06d}.png")
        frame.save(frame_path, 'PNG')
        
        frame_count += 1
        
        # 打印进度
        current_time = time.time()
        if current_time - last_print_time >= 5:  # 每5秒打印一次进度
            elapsed = current_time - start_time
            fps_actual = frame_count / elapsed if elapsed > 0 else 0
            remaining_frames = total_frames - frame_count
            remaining_time = remaining_frames / fps_actual if fps_actual > 0 else 0
            
            print(f"进度: {frame_count}/{total_frames}帧 "
                  f"({frame_count/total_frames*100:.1f}%) | "
                  f"速度: {fps_actual:.1f}帧/秒 | "
                  f"剩余: {remaining_time:.1f}秒")
            last_print_time = current_time
    
    print(f"✅ 帧生成完成: {frame_count}帧")
    return frame_count

def compile_video(frame_count, width, height):
    """将帧合成为视频"""
    print(f"\n开始合成视频...")
    
    if frame_count == 0:
        print("❌ 没有帧可合成")
        return False
    
    # 检查ffmpeg是否可用
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 未找到ffmpeg，请先安装ffmpeg")
        print("Windows: https://ffmpeg.org/download.html")
        print("macOS: brew install ffmpeg")
        print("Linux: sudo apt install ffmpeg")
        return False
    
    # 构建ffmpeg命令
    ffmpeg_cmd = [
        "ffmpeg", "-y",  # 覆盖输出文件
        "-framerate", str(FPS),
        "-start_number", "0",
        "-i", os.path.join(OUTPUT_DIR, "frame_%06d.png"),
        "-vf", f"scale={width}:{height},setsar=1",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-frames:v", str(frame_count),
        OUTPUT_VIDEO
    ]
    
    print("执行命令:", " ".join(ffmpeg_cmd))
    
    try:
        # 运行ffmpeg
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ 视频生成成功: {OUTPUT_VIDEO}")
            
            # 显示视频信息
            if os.path.exists(OUTPUT_VIDEO):
                file_size = os.path.getsize(OUTPUT_VIDEO) / (1024 * 1024)  # MB
                print(f"文件大小: {file_size:.2f} MB")
                return True
        else:
            print(f"❌ ffmpeg执行失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 视频合成失败: {e}")
        return False

def cleanup():
    """清理临时文件"""
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
        print(f"已清理临时帧目录: {OUTPUT_DIR}")

def main():
    """主函数"""
    print("=" * 60)
    print("FIT文件时间戳透明视频生成器")
    print("=" * 60)
    
    # 显示当前配置
    print(f"时区偏移: UTC+{TIMEZONE_OFFSET}")
    print(f"字体大小: {FONT_SIZE}")
    print(f"字体颜色: {FONT_COLOR}")
    print(f"描边宽度: {OUTLINE_WIDTH}")
    print(f"描边颜色: {OUTLINE_COLOR}")
    print(f"帧率: {FPS}")
    print()
    
    # 获取FIT文件路径
    fit_path = get_fit_path()
    if fit_path is None:
        return
    
    # 获取所有lap信息
    laps = get_all_laps(fit_path)
    if not laps:
        print("文件中没有Lap信息，无法生成视频")
        return
    
    # 让用户选择要生成的lap
    selection = select_laps_for_generation(laps)
    if selection is None:
        print("用户取消操作")
        return
    
    lap_start, lap_end, selected_laps = selection
    
    # 转换为北京时间显示
    lap_start_beijing = lap_start + timedelta(hours=TIMEZONE_OFFSET)
    lap_end_beijing = lap_end + timedelta(hours=TIMEZONE_OFFSET)
    
    print(f"\n生成时间范围:")
    print(f"UTC: {lap_start} 到 {lap_end}")
    print(f"北京时间: {lap_start_beijing} 到 {lap_end_beijing}")
    
    # 加载字体
    print("\n加载字体...")
    font = load_font(FONT_SIZE)
    
    # 计算视频尺寸
    print("计算视频尺寸...")
    width, height = calculate_video_dimensions(font)
    
    # 生成帧
    frame_count = generate_timestamp_frames(lap_start, lap_end, width, height, font)
    
    if frame_count > 0:
        # 合成视频
        success = compile_video(frame_count, width, height)
        
        if success:
            print(f"\n✅ 时间戳透明视频生成完成!")
            print(f"视频文件: {os.path.abspath(OUTPUT_VIDEO)}")
        else:
            print("\n❌ 视频生成失败")
    
    # 清理临时文件
    cleanup()
    
    print("\n程序结束")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
        cleanup()
    except Exception as e:
        print(f"\n❌ 程序发生错误: {e}")
        import traceback
        traceback.print_exc()
        cleanup()