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
from PIL import Image, ImageTk  # 需要 pip install Pillow

# ==================== 用户可修改的配置 ====================
MODULE_PATH_ALPHA = r"Gamin_Generate_Hud_Video_From_Fit\Alpha_hud_map_elevation.py"
MODULE_PATH_BETA  = r"Gamin_Generate_Hud_Video_From_Fit\Beta_time_distance_elevation.py"

LOGO_PATH = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\2025单车行logo_Tr.png"

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
        self.title("FIT 视频生成器")
        self.geometry("800x780")
        self.resizable(True, True)

        # 数据存储
        self.fit_path = None
        self.laps = []
        self.selected_lap_indices = []

        # 日志队列（用于跨线程传递 stdout 输出）
        self.log_queue = queue.Queue()
        self.after(100, self.process_log_queue)  # 定期刷新日志

        # 创建主容器
        self.main_frame = ttk.Frame(self, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # ========== 修改点：将图片区域移至最上方 ==========
        # ---------- 第0行：赞助商标识（原品牌标识） ----------
        image_frame = ttk.LabelFrame(self.main_frame, text="赞助商标识", padding=5)
        image_frame.pack(fill=tk.X, pady=5)

        self.image_label = ttk.Label(image_frame)
        self.image_label.pack(pady=5)
        self.load_logo()  # 加载并显示图片

        # ---------- 第1行：FIT 文件选择 ----------
        file_frame = ttk.LabelFrame(self.main_frame, text="FIT 文件", padding=5)
        file_frame.pack(fill=tk.X, pady=5)

        self.file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_var, width=70).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.select_fit_file).pack(side=tk.RIGHT)

        # ---------- 第2行：Lap 选择 ----------
        lap_frame = ttk.LabelFrame(self.main_frame, text="选择 Lap（可多选）", padding=5)
        lap_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        listbox_frame = ttk.Frame(lap_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        self.lap_listbox = tk.Listbox(listbox_frame, selectmode=tk.MULTIPLE,
                                      yscrollcommand=scrollbar.set, height=6)
        scrollbar.config(command=self.lap_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lap_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(lap_frame)
        btn_frame.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="全选", command=self.select_all_laps).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消全选", command=self.deselect_all_laps).pack(side=tk.LEFT, padx=5)

        # ---------- 第3行：Alpha 模块设置 ----------
        alpha_frame = ttk.LabelFrame(self.main_frame, text="Alpha 模块（HUD / 地图 / 海拔）", padding=5)
        alpha_frame.pack(fill=tk.X, pady=5)

        self.alpha_hud_var = tk.BooleanVar(value=False)
        self.alpha_map_var = tk.BooleanVar(value=False)
        self.alpha_elev_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(alpha_frame, text="HUD 视频", variable=self.alpha_hud_var).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(alpha_frame, text="地图视频", variable=self.alpha_map_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(alpha_frame, text="海拔视频", variable=self.alpha_elev_var).grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(alpha_frame, text="HUD FPS:").grid(row=1, column=0, sticky=tk.E, padx=2)
        self.alpha_hud_fps = tk.IntVar(value=ALPHA_HUD_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_hud_fps, width=5).grid(row=1, column=0, sticky=tk.W, padx=(55,5))

        ttk.Label(alpha_frame, text="地图 FPS:").grid(row=1, column=1, sticky=tk.E, padx=2)
        self.alpha_map_fps = tk.IntVar(value=ALPHA_MAP_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_map_fps, width=5).grid(row=1, column=1, sticky=tk.W, padx=(62,5))

        ttk.Label(alpha_frame, text="海拔 FPS:").grid(row=1, column=2, sticky=tk.E, padx=2)
        self.alpha_elev_fps = tk.IntVar(value=ALPHA_ELEVATION_FPS)
        ttk.Spinbox(alpha_frame, from_=1, to=120, textvariable=self.alpha_elev_fps, width=5).grid(row=1, column=2, sticky=tk.W, padx=(78,5))

        # ---------- 第4行：Beta 模块设置 ----------
        beta_frame = ttk.LabelFrame(self.main_frame, text="Beta 模块（时间 / 距离 / 海拔）", padding=5)
        beta_frame.pack(fill=tk.X, pady=5)

        self.beta_time_var = tk.BooleanVar(value=False)
        self.beta_dist_var = tk.BooleanVar(value=False)
        self.beta_elev_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(beta_frame, text="时间视频", variable=self.beta_time_var).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(beta_frame, text="距离视频", variable=self.beta_dist_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(beta_frame, text="海拔视频", variable=self.beta_elev_var).grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(beta_frame, text="时间 FPS:").grid(row=1, column=0, sticky=tk.E, padx=2)
        self.beta_time_fps = tk.IntVar(value=BETA_TIME_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_time_fps, width=5).grid(row=1, column=0, sticky=tk.W, padx=(68,5))

        ttk.Label(beta_frame, text="距离 FPS:").grid(row=1, column=1, sticky=tk.E, padx=2)
        self.beta_dist_fps = tk.IntVar(value=BETA_DISTANCE_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_dist_fps, width=5).grid(row=1, column=1, sticky=tk.W, padx=(76,5))

        ttk.Label(beta_frame, text="海拔 FPS:").grid(row=1, column=2, sticky=tk.E, padx=2)
        self.beta_elev_fps = tk.IntVar(value=BETA_ELEVATION_FPS)
        ttk.Spinbox(beta_frame, from_=1, to=120, textvariable=self.beta_elev_fps, width=5).grid(row=1, column=2, sticky=tk.W, padx=(88,5))

        # ---------- 第5行：运行按钮 + 进度条 ----------
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=10)

        self.run_button = ttk.Button(control_frame, text="开始生成", command=self.start_generation)
        self.run_button.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(control_frame, mode='indeterminate', length=400)
        self.progress.pack(side=tk.LEFT, padx=20, fill=tk.X, expand=True)

        # ---------- 第6行：输出日志区域 ----------
        log_frame = ttk.LabelFrame(self.main_frame, text="运行日志（包含模块内部输出）", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD, state=tk.DISABLED)
        scroll_log = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll_log.set)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定事件：当选择 FIT 文件后自动读取 lap
        self.file_var.trace_add("write", lambda *args: self.on_fit_file_changed())

    # -------------------- 图片加载 --------------------
    def load_logo(self):
        try:
            img_pil = Image.open(LOGO_PATH)
            # 保持宽高比，高度固定为 40 像素
            base_height = 45
            ratio = base_height / img_pil.height
            new_width = int(img_pil.width * ratio)
            img_resized = img_pil.resize((new_width, base_height), Image.LANCZOS)
            self.logo_image = ImageTk.PhotoImage(img_resized)
            self.image_label.config(image=self.logo_image)
        except Exception as e:
            self.image_label.config(text=f"Logo 加载失败: {e}", foreground="gray")
            print(f"Logo 加载失败: {e}")  # 保留控制台输出以便调试

    # -------------------- 日志处理 --------------------
    def process_log_queue(self):
        """定时从队列中取出 stdout 内容并显示到日志框"""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self.process_log_queue)

    def _append_log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.update_idletasks()

    def log(self, msg):
        """手动添加日志（主线程调用）"""
        self._append_log(msg + "\n")

    # -------------------- 辅助方法 --------------------
    def select_fit_file(self):
        path = filedialog.askopenfilename(
            title="选择 FIT 文件",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )
        if path:
            self.file_var.set(path)

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
                if start_time is not None and elapsed is not None:
                    end_time = start_time + timedelta(seconds=elapsed)
                    laps.append({
                        "index": len(laps) + 1,
                        "start_time": start_time,
                        "end_time": end_time,
                        "elapsed_seconds": elapsed,
                        "total_distance": total_distance
                    })
            self.laps = laps
            self.lap_listbox.delete(0, tk.END)
            for lap in laps:
                dur_str = self._seconds_to_hms(lap["elapsed_seconds"])
                dist_str = f"{lap['total_distance']/1000:.2f} km"
                display = f"Lap {lap['index']}: {dur_str} | {dist_str}"
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

        self.run_button.config(state=tk.DISABLED)
        self.progress.start(10)
        self.log("开始生成任务...")

        thread = threading.Thread(target=self._run_generation, daemon=True)
        thread.start()

    def _run_generation(self):
        # 重定向标准输出到 GUI 日志队列
        old_stdout = sys.stdout
        redirector = StdoutRedirector(self.log_queue)
        sys.stdout = redirector

        try:
            selected_indices = [self.lap_listbox.curselection()[i] for i in range(len(self.lap_listbox.curselection()))]
            selected_laps = [self.laps[i] for i in selected_indices]

            lap_start = min(lap['start_time'] for lap in selected_laps)
            lap_end = max(lap['end_time'] for lap in selected_laps)

            # 以下 print 会被重定向到 GUI
            print(f"时间范围: {lap_start} ~ {lap_end}")
            print(f"总时长: {(lap_end - lap_start).total_seconds():.1f} 秒")

            # Alpha 模块
            if self.alpha_hud_var.get() or self.alpha_map_var.get() or self.alpha_elev_var.get():
                print("--- 开始 Alpha 模块 ---")
                if not os.path.exists(MODULE_PATH_ALPHA):
                    raise FileNotFoundError(f"找不到 Alpha 模块文件: {MODULE_PATH_ALPHA}")
                mod_alpha = load_module_from_path("mod_alpha", MODULE_PATH_ALPHA)
                print("Alpha 模块加载成功")

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
                print("跳过 Alpha 模块")

            # Beta 模块
            if self.beta_time_var.get() or self.beta_dist_var.get() or self.beta_elev_var.get():
                print("--- 开始 Beta 模块 ---")
                if not os.path.exists(MODULE_PATH_BETA):
                    raise FileNotFoundError(f"找不到 Beta 模块文件: {MODULE_PATH_BETA}")
                mod_beta = load_module_from_path("mod_beta", MODULE_PATH_BETA)
                print("Beta 模块加载成功")

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
                print("跳过 Beta 模块")

            print("✅ 所有任务已完成！")
        except Exception as e:
            print(f"❌ 错误: {e}")
            traceback.print_exc(file=sys.stdout)  # 也会被重定向
            messagebox.showerror("运行错误", str(e))
        finally:
            sys.stdout = old_stdout  # 恢复标准输出
            self.after(0, self._finish_ui)

    def _finish_ui(self):
        self.progress.stop()
        self.run_button.config(state=tk.NORMAL)
        self.log("--- 结束 ---\n")


if __name__ == "__main__":
    app = FitVideoGeneratorApp()
    app.mainloop()