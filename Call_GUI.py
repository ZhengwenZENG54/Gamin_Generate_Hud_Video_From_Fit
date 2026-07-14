import sys
import os
import io
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
from fitparse import FitFile
import importlib.util
import glob
import time
import threading
import traceback
from PIL import Image, ImageTk
import scipy.special
import scipy.interpolate
import PIL.ImageDraw      
import PIL.ImageFont      
import matplotlib
matplotlib.use('Agg')            

# ==================== 资源路径辅助函数 ====================
def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后的 exe"""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_ffmpeg_path():
    """获取 ffmpeg 路径：打包后使用内部资源，开发时使用系统 PATH"""
    # 打包后
    if getattr(sys, 'frozen', False):
        bundled = resource_path("ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled
    # 开发环境：使用系统 PATH 中的 ffmpeg（conda 环境自带）
    import shutil
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    # 最后尝试项目根目录下的 ffmpeg.exe（兼容旧版）
    local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.isfile(local_ffmpeg):
        return local_ffmpeg
    return None

# ==================== 资源路径辅助函数 ====================
def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后的 exe"""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# ==================== 用户可修改的配置 ====================
# 模块文件路径（使用 resource_path）
MODULE_PATH_ALPHA = resource_path("Alpha_hud_map_elevation.py")
MODULE_PATH_BETA  = resource_path("Beta_time_distance_elevation.py")

# 资源文件路径（放在 resources 子目录下）
LOGO_PATH1 = resource_path("resources/2025单车行logo_Tr.png")
LOGO_PATH2 = resource_path("resources/ZhengwenZENG.png")
FFMPEG_PATH = resource_path("resources/ffmpeg.exe")  # 仅用于打包，开发时不用
SDL3_PATH = resource_path("resources/SDL3.dll")
TCL_DIR = resource_path("resources/tcl")

# 默认帧率
ALPHA_HUD_FPS = 30
ALPHA_MAP_FPS = 5
ALPHA_ELEVATION_FPS = 5
BETA_TIME_FPS = 1
BETA_DISTANCE_FPS = 5
BETA_ELEVATION_FPS = 5
# =========================================================

def load_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StdoutRedirector(io.TextIOBase):
    """将标准输出重定向到 GUI 日志的流"""
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        if text:
            self.log_queue.put(text)
        return len(text)

    def flush(self):
        pass


class FitVideoGeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FIT数据视频生成器V1.0.0")
        self.geometry("880x920")
        self.resizable(True, True)

        # 数据存储
        self.fit_path = None
        self.laps = []
        self.selected_lap_indices = []
        self.output_dir = ""

        # 线程控制
        self.generation_thread = None
        self.stop_flag = threading.Event()

        # 日志队列
        self.log_queue = queue.Queue()
        self.after(100, self.process_log_queue)

        # 创建主容器
        self.main_frame = ttk.Frame(self, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # ---------- 第0行：赞助商标识（双图片） ----------
        image_frame = ttk.LabelFrame(self.main_frame, text="赞助商标识", padding=5)
        image_frame.pack(fill=tk.X, pady=5)

        # ===== 可调参数 =====
        self.sponsor_left_margin = 250   # 图片组距离左侧的间距（单位：像素）
        self.sponsor_spacing = 100       # 两张图片之间的间距（单位：像素）
        # ===================

        # 内部水平容器，使两张图片从左到右排列
        inner_frame = ttk.Frame(image_frame)
        inner_frame.pack(side=tk.LEFT, padx=(self.sponsor_left_margin, 0), fill=tk.X, expand=True)

        # 左侧图片
        self.image_label1 = ttk.Label(inner_frame)
        self.image_label1.pack(side=tk.LEFT, padx=(0, self.sponsor_spacing // 2))

        # 右侧图片
        self.image_label2 = ttk.Label(inner_frame)
        self.image_label2.pack(side=tk.LEFT, padx=(self.sponsor_spacing // 2, 0))

        # 加载图片
        self.load_logos()

        # ---------- 第1行：FIT 文件选择 ----------
        file_frame = ttk.LabelFrame(self.main_frame, text="FIT 文件", padding=5)
        file_frame.pack(fill=tk.X, pady=5)

        self.file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_var, width=65).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.select_fit_file).pack(side=tk.RIGHT)

        # ---------- 第2行：输出目录选择 ----------
        out_frame = ttk.LabelFrame(self.main_frame, text="输出目录（视频存放位置）", padding=5)
        out_frame.pack(fill=tk.X, pady=5)

        self.out_dir_var = tk.StringVar(value=os.getcwd())
        ttk.Entry(out_frame, textvariable=self.out_dir_var, width=65).pack(side=tk.LEFT, padx=5)
        ttk.Button(out_frame, text="浏览...", command=self.select_output_dir).pack(side=tk.RIGHT)
        ttk.Label(out_frame, text="默认: 当前工作目录").pack(side=tk.LEFT, padx=5)

        # ---------- 第3行：Lap 选择 ----------
        lap_frame = ttk.LabelFrame(self.main_frame, text="选择 Lap（注意可多选，但合成为一整个连续时间轴）", padding=5)
        lap_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        listbox_frame = ttk.Frame(lap_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        self.lap_listbox = tk.Listbox(listbox_frame, selectmode=tk.MULTIPLE,
                                      yscrollcommand=scrollbar.set, height=5)
        scrollbar.config(command=self.lap_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lap_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(lap_frame)
        btn_frame.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="全选", command=self.select_all_laps).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消全选", command=self.deselect_all_laps).pack(side=tk.LEFT, padx=5)

        # ---------- 第4行：Alpha 模块设置 ----------
        alpha_frame = ttk.LabelFrame(self.main_frame, text="Alpha 模块（HUD / 地图 / 海拔剖面图）", padding=5)
        alpha_frame.pack(fill=tk.X, pady=5)

        self.alpha_hud_var = tk.BooleanVar(value=False)
        self.alpha_map_var = tk.BooleanVar(value=False)
        self.alpha_elev_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(alpha_frame, text="HUD 视频", variable=self.alpha_hud_var).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(alpha_frame, text="地图视频", variable=self.alpha_map_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(alpha_frame, text="海拔剖面图视频", variable=self.alpha_elev_var).grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(alpha_frame, text="HUD FPS:").grid(row=1, column=0, sticky=tk.E, padx=2)
        self.alpha_hud_fps = tk.IntVar(value=ALPHA_HUD_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_hud_fps, width=5).grid(row=1, column=0, sticky=tk.W, padx=(58,5))

        ttk.Label(alpha_frame, text="地图 FPS:").grid(row=1, column=1, sticky=tk.E, padx=2)
        self.alpha_map_fps = tk.IntVar(value=ALPHA_MAP_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_map_fps, width=5).grid(row=1, column=1, sticky=tk.W, padx=(67,5))

        ttk.Label(alpha_frame, text="海拔 FPS:").grid(row=1, column=2, sticky=tk.E, padx=2)
        self.alpha_elev_fps = tk.IntVar(value=ALPHA_ELEVATION_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_elev_fps, width=5).grid(row=1, column=2, sticky=tk.W, padx=(83,5))

        # ---------- 第5行：Beta 模块设置 ----------
        beta_frame = ttk.LabelFrame(self.main_frame, text="Beta 模块（时间 / 累积距离 / 当前海拔高度）", padding=5)
        beta_frame.pack(fill=tk.X, pady=5)

        self.beta_time_var = tk.BooleanVar(value=False)
        self.beta_dist_var = tk.BooleanVar(value=False)
        self.beta_elev_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(beta_frame, text="时间视频", variable=self.beta_time_var).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(beta_frame, text="累积距离视频", variable=self.beta_dist_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(beta_frame, text="当前海拔高度视频", variable=self.beta_elev_var).grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(beta_frame, text="时间 FPS:").grid(row=1, column=0, sticky=tk.E, padx=2)
        self.beta_time_fps = tk.IntVar(value=BETA_TIME_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_time_fps, width=5).grid(row=1, column=0, sticky=tk.W, padx=(73,5))

        ttk.Label(beta_frame, text="距离 FPS:").grid(row=1, column=1, sticky=tk.E, padx=2)
        self.beta_dist_fps = tk.IntVar(value=BETA_DISTANCE_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_dist_fps, width=5).grid(row=1, column=1, sticky=tk.W, padx=(81,5))

        ttk.Label(beta_frame, text="海拔 FPS:").grid(row=1, column=2, sticky=tk.E, padx=2)
        self.beta_elev_fps = tk.IntVar(value=BETA_ELEVATION_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_elev_fps, width=5).grid(row=1, column=2, sticky=tk.W, padx=(93,5))

        # ---------- 第6行：控制按钮 + 进度条 ----------
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=10)

        # 开始生成按钮（绿色）
        self.run_button = tk.Button(control_frame, text="开始生成", command=self.start_generation,
                                    bg="#4CAF50", fg="white", font=("Arial", 10, "bold"),
                                    activebackground="#66BB6A", relief=tk.RAISED, padx=10)
        self.run_button.pack(side=tk.LEFT, padx=5)

        # 结束生成按钮（红色）
        self.stop_button = tk.Button(control_frame, text="强制结束", command=self.stop_generation,
                                     bg="#F44336", fg="white", font=("Arial", 10, "bold"),
                                     activebackground="#EF5350", relief=tk.RAISED, padx=10, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # 清理日志按钮
        self.clear_log_button = tk.Button(control_frame, text="清理日志", command=self.clear_log,
                                          bg="#2196F3", fg="white", font=("Arial", 10, "bold"),
                                          activebackground="#42A5F5", relief=tk.RAISED, padx=10)
        self.clear_log_button.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(control_frame, mode='indeterminate', length=390)
        self.progress.pack(side=tk.LEFT, padx=20, fill=tk.X, expand=True)

        # ---------- 第7行：输出日志区域 ----------
        log_frame = ttk.LabelFrame(self.main_frame, text="运行日志（包含模块内部输出）", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = tk.Text(log_frame, height=12, wrap=tk.WORD, state=tk.DISABLED)
        scroll_log = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll_log.set)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定事件
        self.file_var.trace_add("write", lambda *args: self.on_fit_file_changed())

    # -------------------- 图片加载（双图片） --------------------
    def load_logos(self):
        """加载两张赞助商图片，自动缩放至合适高度"""
        base_height = 26  # 统一高度，可根据需要调整
        # 加载第一张图片
        try:
            img_pil1 = Image.open(LOGO_PATH1)
            ratio1 = base_height / img_pil1.height
            new_width1 = int(img_pil1.width * ratio1)
            img_resized1 = img_pil1.resize((new_width1, base_height), Image.LANCZOS)
            self.logo_image1 = ImageTk.PhotoImage(img_resized1)
            self.image_label1.config(image=self.logo_image1)
        except Exception as e:
            self.image_label1.config(text=f"Logo1 加载失败", foreground="gray")
            print(f"Logo1 加载失败: {e}")

        # 加载第二张图片
        try:
            img_pil2 = Image.open(LOGO_PATH2)
            ratio2 = base_height / img_pil2.height
            new_width2 = int(img_pil2.width * ratio2)
            img_resized2 = img_pil2.resize((new_width2, base_height), Image.LANCZOS)
            self.logo_image2 = ImageTk.PhotoImage(img_resized2)
            self.image_label2.config(image=self.logo_image2)
        except Exception as e:
            self.image_label2.config(text=f"Logo2 加载失败", foreground="gray")
            print(f"Logo2 加载失败: {e}")

    # -------------------- 日志处理 --------------------
    def process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self.process_log_queue)

    def _append_log(self, text):
        if not text.strip():
            return
        self.log_text.configure(state=tk.NORMAL)
        if not text.endswith('\n'):
            text += '\n'
        self.log_text.insert(tk.END, text)
        line_count = int(self.log_text.index('end-1c').split('.')[0])
        if line_count > 3000:
            self.log_text.delete('1.0', f'{line_count - 2900}.0')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.update_idletasks()

    def log(self, msg):
        self._append_log(msg + "\n")

    # -------------------- 辅助方法 --------------------
    def select_fit_file(self):
        path = filedialog.askopenfilename(
            title="选择 FIT 文件",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def select_output_dir(self):
        directory = filedialog.askdirectory(title="选择输出文件夹")
        if directory:
            self.out_dir_var.set(directory)

    def on_fit_file_changed(self):
        path = self.file_var.get()
        if not path or not os.path.isfile(path):
            return
        self.fit_path = path
        self.log(f"已选择 FIT 文件: {path}")
        self.load_laps()

    def load_laps(self):
        try:
            fit = FitFile(self.fit_path)
            laps = []
            for msg in fit.get_messages("lap"):
                vals = msg.get_values()
                start_time = vals.get("start_time")
                elapsed = vals.get("total_elapsed_time")
                total_distance = vals.get("total_distance", 0.0)
                trigger = vals.get("lap_trigger", "unknown")
                if start_time is not None and elapsed is not None:
                    end_time = start_time + timedelta(seconds=elapsed)
                    laps.append({
                        "index": len(laps) + 1,
                        "start_time": start_time,
                        "end_time": end_time,
                        "elapsed_seconds": elapsed,
                        "total_distance": total_distance,
                        "trigger": trigger
                    })
            self.laps = laps
            self.lap_listbox.delete(0, tk.END)
            for lap in laps:
                start_str = lap['start_time'].strftime('%Y-%m-%d %H:%M:%S')
                end_str = lap['end_time'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                elapsed_str = f"{lap['elapsed_seconds']:.1f}s"
                display = f"[Lap {lap['index']}] start={start_str}, end={end_str}, elapsed={elapsed_str}, trigger={lap['trigger']}"
                self.lap_listbox.insert(tk.END, display)
            self.log(f"共读取到 {len(laps)} 个 Lap")
        except Exception as e:
            messagebox.showerror("读取失败", f"无法解析 FIT 文件:\n{e}")
            self.log(f"错误: {e}")

    def _seconds_to_hms(self, sec):
        if sec is None:
            return "N/A"
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        else:
            return f"{m:02d}:{s:02d}"

    def select_all_laps(self):
        self.lap_listbox.selection_set(0, tk.END)

    def deselect_all_laps(self):
        self.lap_listbox.selection_clear(0, tk.END)

    # -------------------- 核心运行 --------------------
    def start_generation(self):
        if not self.fit_path:
            messagebox.showwarning("警告", "请先选择一个 FIT 文件")
            return
        if not self.laps:
            messagebox.showwarning("警告", "FIT 文件中没有 Lap 数据")
            return
        selected = self.lap_listbox.curselection()
        if not selected:
            messagebox.showwarning("警告", "请至少选择一个 Lap")
            return

        alpha_any = self.alpha_hud_var.get() or self.alpha_map_var.get() or self.alpha_elev_var.get()
        beta_any = self.beta_time_var.get() or self.beta_dist_var.get() or self.beta_elev_var.get()
        if not alpha_any and not beta_any:
            messagebox.showwarning("警告", "请至少选择一种视频类型（Alpha 或 Beta）")
            return

        self.output_dir = self.out_dir_var.get().strip()
        if not self.output_dir:
            self.output_dir = os.getcwd()
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir)
                self.log(f"创建输出目录: {self.output_dir}")
            except Exception as e:
                messagebox.showerror("错误", f"无法创建输出目录: {e}")
                return

        self.stop_flag.clear()
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.progress.start(10)
        self.log("开始生成任务...")

        self.generation_thread = threading.Thread(target=self._run_generation, daemon=True)
        self.generation_thread.start()

    def stop_generation(self):
        if self.generation_thread is None or not self.generation_thread.is_alive():
            self.log("当前没有正在运行的任务")
            return
        self.log("用户请求停止生成...")
        self.stop_flag.set()
        self.stop_button.config(state=tk.DISABLED)
        self.generation_thread.join(timeout=5)
        if self.generation_thread.is_alive():
            self.log("警告: 生成线程未能及时退出，可能仍有残留进程")
        else:
            self.log("生成线程已退出")
        self._cleanup_temp_files()
        self._finish_ui()
        self.log("生成已被用户中止")

    def _cleanup_temp_files(self):
        import shutil
        possible_dirs = [
            os.path.join(self.output_dir, "frames_hud"),
            os.path.join(self.output_dir, "frames_map"),
            os.path.join(self.output_dir, "frames_elevation"),
            os.path.join(self.output_dir, "frames_timestamp"),
            os.path.join(self.output_dir, "frames_distance"),
        ]
        for d in possible_dirs:
            if os.path.isdir(d):
                try:
                    shutil.rmtree(d)
                    self.log(f"已清理中间目录: {d}")
                except Exception as e:
                    self.log(f"清理目录 {d} 失败: {e}")

    def _run_generation(self):
        old_stdout = sys.stdout
        redirector = StdoutRedirector(self.log_queue)
        sys.stdout = redirector

        try:
            if self.stop_flag.is_set():
                print("检测到停止信号，退出生成")
                return

            selected_indices = [self.lap_listbox.curselection()[i] for i in range(len(self.lap_listbox.curselection()))]
            selected_laps = [self.laps[i] for i in selected_indices]

            lap_start = min(lap['start_time'] for lap in selected_laps)
            lap_end = max(lap['end_time'] for lap in selected_laps)

            print(f"时间范围: {lap_start} ~ {lap_end}")
            print(f"总时长: {(lap_end - lap_start).total_seconds():.1f} 秒")
            print(f"输出目录: {self.output_dir}")

            # ==================== Alpha 模块 ====================
            if not self.stop_flag.is_set() and (self.alpha_hud_var.get() or self.alpha_map_var.get() or self.alpha_elev_var.get()):
                print("--- 开始 Alpha 模块 ---")
                if not os.path.exists(MODULE_PATH_ALPHA):
                    raise FileNotFoundError(f"找不到 Alpha 模块文件: {MODULE_PATH_ALPHA}")
                mod_alpha = load_module_from_path("mod_alpha", MODULE_PATH_ALPHA)
                print("Alpha 模块加载成功")

                ffmpeg_path = get_ffmpeg_path()
                if ffmpeg_path is None:
                    raise RuntimeError("找不到 ffmpeg，请确保 ffmpeg.exe 与程序同在，或系统已安装 ffmpeg 并加入 PATH")
                print(f"FFmpeg 路径: {ffmpeg_path}")
                mod_alpha.FFMPEG_PATH = get_ffmpeg_path()

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

                mod_alpha.OUTPUT_DIR_HUD = os.path.join(self.output_dir, "frames_hud")
                mod_alpha.OUTPUT_DIR_MAP = os.path.join(self.output_dir, "frames_map")
                mod_alpha.OUTPUT_DIR_ELEVATION = os.path.join(self.output_dir, "frames_elevation")

                mod_alpha.OUTPUT_MOV_HUD = os.path.join(self.output_dir, f"alpha_hud__{timestamp}.mov")
                mod_alpha.OUTPUT_MOV_MAP = os.path.join(self.output_dir, f"alpha_map__{timestamp}.mov")
                mod_alpha.OUTPUT_MOV_ELEVATION = os.path.join(self.output_dir, f"alpha_elev_{timestamp}.mov")

                kwargs = {
                    "fit_path": self.fit_path,
                    "lap_start": lap_start,
                    "lap_end": lap_end,
                    "generate_hud": self.alpha_hud_var.get(),
                    "generate_map": self.alpha_map_var.get(),
                    "generate_elevation": self.alpha_elev_var.get(),
                    "hud_fps": self.alpha_hud_fps.get(),
                    "map_fps": self.alpha_map_fps.get(),
                    "elevation_fps": self.alpha_elev_fps.get()
                }
                print(f"参数: {kwargs}")
                result = mod_alpha.generate_hud_map_elevation_video(**kwargs)
                print(f"Alpha 完成: {result}")
            else:
                if not self.stop_flag.is_set():
                    print("跳过 Alpha 模块")

            # ==================== Beta 模块 ====================
            if not self.stop_flag.is_set() and (self.beta_time_var.get() or self.beta_dist_var.get() or self.beta_elev_var.get()):
                print("--- 开始 Beta 模块 ---")
                if not os.path.exists(MODULE_PATH_BETA):
                    raise FileNotFoundError(f"找不到 Beta 模块文件: {MODULE_PATH_BETA}")
                mod_beta = load_module_from_path("mod_beta", MODULE_PATH_BETA)
                print("Beta 模块加载成功")

                ffmpeg_path = get_ffmpeg_path()
                if ffmpeg_path is None:
                    raise RuntimeError("找不到 ffmpeg，请确保 ffmpeg.exe 与程序同在，或系统已安装 ffmpeg 并加入 PATH")
                print(f"FFmpeg 路径: {ffmpeg_path}")
                mod_beta.FFMPEG_PATH = get_ffmpeg_path()

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                mod_beta.OUTPUT_DIR_TIME = os.path.join(self.output_dir, "frames_timestamp")
                mod_beta.OUTPUT_DIR_DISTANCE = os.path.join(self.output_dir, "frames_distance")
                mod_beta.OUTPUT_DIR_ELEVATION = os.path.join(self.output_dir, "frames_elevation")
                mod_beta.OUTPUT_VIDEO_TIME = os.path.join(self.output_dir, f"beta_time_{timestamp}.mov")
                mod_beta.OUTPUT_VIDEO_DISTANCE = os.path.join(self.output_dir, f"beta_dist_{timestamp}.mov")
                mod_beta.OUTPUT_VIDEO_ELEVATION = os.path.join(self.output_dir, f"beta_elev_{timestamp}.mov")

                if hasattr(mod_beta, 'FPS_TIME'):
                    mod_beta.FPS_TIME = self.beta_time_fps.get()
                if hasattr(mod_beta, 'FPS_DISTANCE'):
                    mod_beta.FPS_DISTANCE = self.beta_dist_fps.get()
                if hasattr(mod_beta, 'FPS_ELEVATION'):
                    mod_beta.FPS_ELEVATION = self.beta_elev_fps.get()

                if hasattr(mod_beta, 'generate_videos_from_fit'):
                    result = mod_beta.generate_videos_from_fit(
                        fit_path=self.fit_path,
                        lap_start=lap_start,
                        lap_end=lap_end,
                        generate_time=self.beta_time_var.get(),
                        generate_distance=self.beta_dist_var.get(),
                        generate_elevation=self.beta_elev_var.get()
                    )
                    print(f"Beta 完成: {result}")
                else:
                    raise AttributeError("Beta 模块中没有 generate_videos_from_fit 函数")
            else:
                if not self.stop_flag.is_set():
                    print("跳过 Beta 模块")

            if not self.stop_flag.is_set():
                print("✅ 所有任务已完成！")
        except Exception as e:
            print(f"❌ 错误: {e}")
            traceback.print_exc(file=sys.stdout)
            self.after(0, lambda: messagebox.showerror("运行错误", str(e)))
        finally:
            sys.stdout = old_stdout
            self.after(0, self._finish_ui)

    def _finish_ui(self):
        self.progress.stop()
        self.run_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.log("--- 结束 ---\n")

    def clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.configure(state=tk.DISABLED)


if __name__ == "__main__":
    app = FitVideoGeneratorApp()
    app.mainloop()
