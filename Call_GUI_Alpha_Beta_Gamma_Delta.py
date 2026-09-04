# -*- coding: utf-8 -*-
"""
Call_GUI.py — FIT 数据视频生成器 GUI 入口 (V3.3 左右并排双页·翻开书式)
A页(左): 文件/目录/参数/控制栏（无滚动条，紧凑等宽）
B页(右): 进度条 + 运行日志（仅日志）
"""

import sys
import os
import io
import re
import time
import queue
import threading
import traceback
import importlib.util
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
from PIL import Image, ImageTk

# ============================================================
# 资源路径
# ============================================================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_ffmpeg_path():
    if getattr(sys, 'frozen', False):
        bundled = resource_path("resources/ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled
    import shutil
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.isfile(local_ffmpeg):
        return local_ffmpeg
    return None

# Logo 路径
LOGO_PATH1 = resource_path("resources/2025单车行logo_Tr.png")
LOGO_PATH2 = resource_path("resources/ZhengwenZENG_Bilibili.png")

# ============================================================
# 配置区
# ============================================================
MODULE_PATH_ALPHA_SPHC = resource_path("1_Alpha_SPHC.py")
MODULE_PATH_ALPHA_MAP_ELEV = resource_path("2_Alpha_map_elevation.py")
MODULE_PATH_BETA = resource_path("3_Beta_time_distance_elevation.py")
MODULE_PATH_GAMMA = resource_path("4_Gamma_metrics.py")
MODULE_PATH_DELTA = resource_path("5_Delta_elevation.py")

ALPHA_SPHC_FPS = 30
ALPHA_MAP_FPS = 5
ALPHA_ELEVATION_FPS = 5
BETA_TIME_FPS = 1
BETA_DISTANCE_FPS = 5
BETA_ELEVATION_FPS = 5
GAMMA_FPS = 1
DELTA_FPS = 5

SPHC_FRAMES_DIR = "frames_Alpha_SPHC"
MAP_FRAMES_DIR = "frames_Alpha_MAP"
ELEVATION_FRAMES_DIR = "frames_Alpha_ELEVATION"
BETA_TIME_FRAMES_DIR = "frames_Beta_TIME"
BETA_DISTANCE_FRAMES_DIR = "frames_Beta_DISTANCE"
BETA_ELEVATION_FRAMES_DIR = "frames_Beta_ELEVATION"
GAMMA_FRAMES_DIR = "frames_gamma"
DELTA_FRAMES_DIR = "frames_Delta"

# ============================================================

def load_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class StdoutRedirector(io.TextIOBase):
    def __init__(self, log_queue):
        self.log_queue = log_queue
    def write(self, text):
        if text:
            self.log_queue.put(text)
        return len(text)
    def flush(self):
        pass

def parse_color(raw, default=(255, 255, 255)):
    if raw is None:
        return default
    if isinstance(raw, (tuple, list)):
        return tuple(raw)
    s = str(raw).strip()
    if not s:
        return default
    if ',' in s:
        nums = re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', s)
        if len(nums) >= 3:
            vals = [float(n) for n in nums[:4]]
            if any(v > 1.0 for v in vals[:3]):
                rgb = [int(round(v)) for v in vals[:3]]
                a = int(round(vals[3])) if len(vals) >= 4 else 255
                return (rgb[0], rgb[1], rgb[2], a)
            else:
                a = vals[3] if len(vals) >= 4 else 1.0
                return (vals[0], vals[1], vals[2], a)
    return s


# ============================================================
# 通用参数对话框
# ============================================================
class DictParamsDialog(tk.Toplevel):
    def __init__(self, master, title, param_defs, initial=None, defaults=None):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.param_defs = []
        for item in param_defs:
            if len(item) == 3:
                self.param_defs.append((item[0], item[1], item[2], ""))
            elif len(item) == 4:
                self.param_defs.append(tuple(item))
            else:
                raise ValueError(f"无效参数定义: {item}")
        self.defaults = defaults or {}
        self.initial = dict(self.defaults)
        if initial:
            self.initial.update(initial)
        self.vars = {}
        self._build()
        self.result = None

    def _build(self):
        c = ttk.Frame(self, padding=10); c.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(c); sb = ttk.Scrollbar(c, orient=tk.VERTICAL, command=canvas.yview)
        sf = ttk.Frame(canvas)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        for label, key, ptype, tip in self.param_defs:
            row = ttk.Frame(sf); row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=26, anchor="w").pack(side=tk.LEFT)
            val = self.initial.get(key, "")
            if ptype == "bool":
                var = tk.BooleanVar(value=bool(val))
                ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            else:
                var = tk.StringVar(value="" if val is None else str(val))
                ttk.Entry(row, textvariable=var, width=16).pack(side=tk.LEFT)
            self.vars[key] = (var, ptype)
            if tip:
                ttk.Label(row, text=f"({tip})", foreground="gray").pack(side=tk.LEFT)
        btn = ttk.Frame(self, padding=10); btn.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn, text="恢复默认", command=self.reset_defaults).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn, text="确定", command=self.apply).pack(side=tk.RIGHT, padx=5)

    def _read(self):
        out = {}
        for label, key, ptype, _ in self.param_defs:
            var, _ = self.vars[key]
            raw = var.get() if ptype == "bool" else var.get().strip()
            try:
                if ptype == "color":
                    out[key] = parse_color(raw)
                elif ptype == "int":
                    out[key] = int(float(raw)) if raw != "" else 0
                elif ptype == "float":
                    out[key] = float(raw) if raw != "" else 0.0
                elif ptype == "bool":
                    out[key] = bool(raw)
                else:
                    out[key] = raw
            except ValueError:
                messagebox.showerror("错误", f"{label} 无效", parent=self); return None
        return out

    def apply(self):
        p = self._read()
        if p is None: return
        self.result = p; self.destroy()

    def reset_defaults(self):
        for _, key, ptype, _ in self.param_defs:
            var, _ = self.vars[key]
            val = self.defaults.get(key, "")
            (var.set(str(val)) if ptype != "bool" else var.set(bool(val)))

    def get_result(self):
        self.wait_window(); return self.result


# ============================================================
# 各模块参数对话框
# ============================================================
class SPHCParamsDialog(DictParamsDialog):
    DEFS = [
        ("画布宽度 width", "width", "int", "像素"),
        ("画布高度 height", "height", "int", "像素"),
        ("字号 font_size", "font_size", "int", "pt"),
        ("字体颜色 font_color", "font_color", "color", "white 或 255,255,255"),
        ("背景透明度 bg_alpha", "bg_alpha", "float", "0.0~1.0"),
        ("背景框可见 bg_visible", "bg_visible", "bool", "False=去背景"),
        ("行间距 linespacing", "linespacing", "float", "默认1.2"),
        ("停车阈值 speed_threshold", "speed_threshold", "float", "km/h"),
        ("打印间隔 print_interval", "print_interval", "int", "秒"),
        ("文字锚点X text_x", "text_x", "float", "0.0~1.0"),
        ("文字锚点Y text_y", "text_y", "float", "0.0~1.0"),
    ]
    def __init__(self, master, initial_params=None):
        defaults = self._load_defaults()
        super().__init__(master, "SPHC 详细属性设定", self.DEFS, initial_params, defaults)
        self.geometry("460x500")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_sphc", MODULE_PATH_ALPHA_SPHC)
            return dict(mod.DEFAULT_PARAMS)
        except Exception:
            return {'width':480,'height':270,'font_size':25,'font_color':'white',
                    'bg_alpha':0.4,'bg_visible':True,'linespacing':1.2,
                    'speed_threshold':3.0,'print_interval':10,'text_x':0.05,'text_y':0.92}

class MAPParamsDialog(DictParamsDialog):
    DEFS = [
        ("画布宽度 width", "width", "int"),
        ("画布高度 height", "height", "int"),
        ("地图线宽 map_line_width", "map_line_width", "int"),
        ("已完成颜色 map_completed_color", "map_completed_color", "color"),
        ("标记大小 map_marker_size", "map_marker_size", "int"),
        ("打印间隔 print_interval", "print_interval", "int"),
    ]
    def __init__(self, master, initial=None):
        defaults = self._load_defaults()
        super().__init__(master, "MAP 属性设定", self.DEFS, initial, defaults)
        self.geometry("440x340")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_me", MODULE_PATH_ALPHA_MAP_ELEV)
            return dict(mod.DEFAULT_PARAMS_MAP)
        except: return {}

class ElevationParamsDialog(DictParamsDialog):
    DEFS = [
        ("海拔宽度 elevation_width", "elevation_width", "int"),
        ("宽高比 elevation_aspect_ratio", "elevation_aspect_ratio", "float"),
        ("线宽 elevation_line_width", "elevation_line_width", "int"),
        ("已完成颜色 elevation_completed_color", "elevation_completed_color", "color"),
        ("标记大小 elevation_marker_size", "elevation_marker_size", "int"),
        ("打印间隔 print_interval", "print_interval", "int"),
    ]
    def __init__(self, master, initial=None):
        defaults = self._load_defaults()
        super().__init__(master, "ELEVATION 属性设定", self.DEFS, initial, defaults)
        self.geometry("440x340")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_me", MODULE_PATH_ALPHA_MAP_ELEV)
            return dict(mod.DEFAULT_PARAMS_ELEVATION)
        except: return {}

class BetaTimeParamsDialog(DictParamsDialog):
    DEFS = [
        ("字号 font_size", "font_size", "int", "pt"),
        ("字体颜色 font_color", "font_color", "color", "white 或 255,255,255"),
        ("描边宽度 outline_width", "outline_width", "int", "像素"),
        ("描边颜色 outline_color", "outline_color", "color", "0,0,0"),
        ("视频宽度 video_width", "video_width", "int", "0=自动"),
        ("视频高度 video_height", "video_height", "int", "0=自动"),
        ("边距 padding", "padding", "int", "像素"),
        ("时区偏移 timezone_offset", "timezone_offset", "int", "小时"),
    ]
    def __init__(self, master, initial=None, current_fps=None):
        defaults = self._load_defaults()
        if current_fps is not None:
            defaults = dict(defaults); defaults['fps'] = current_fps
        super().__init__(master, "Beta 时间视频 属性", self.DEFS, initial, defaults)
        self.geometry("440x400")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_beta", MODULE_PATH_BETA)
            return dict(mod.DEFAULT_PARAMS_TIME)
        except: return {'font_size':60,'font_color':'white','outline_width':3,
                        'outline_color':(0,0,0),'video_width':None,'video_height':None,
                        'padding':30,'timezone_offset':8}

class BetaDistanceParamsDialog(DictParamsDialog):
    DEFS = [
        ("字号 font_size", "font_size", "int", "pt"),
        ("字体颜色 font_color", "font_color", "color", "white"),
        ("描边宽度 outline_width", "outline_width", "int", "像素"),
        ("描边颜色 outline_color", "outline_color", "color", "0,0,0"),
        ("前缀文本 prefix", "prefix", "str", "如  Dist: "),
        ("后缀文本 suffix", "suffix", "str", "如  km"),
    ]
    def __init__(self, master, initial=None):
        defaults = self._load_defaults()
        super().__init__(master, "Beta 距离视频 属性", self.DEFS, initial, defaults)
        self.geometry("440x360")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_beta", MODULE_PATH_BETA)
            return dict(mod.DEFAULT_PARAMS_DISTANCE)
        except: return {'font_size':50,'font_color':'white','outline_width':3,
                        'outline_color':(0,0,0),'prefix':' Dist: ','suffix':' km'}

class BetaElevationParamsDialog(DictParamsDialog):
    DEFS = [
        ("字号 font_size", "font_size", "int", "pt"),
        ("字体颜色 font_color", "font_color", "color", "white"),
        ("描边宽度 outline_width", "outline_width", "int", "像素"),
        ("描边颜色 outline_color", "outline_color", "color", "0,0,0"),
        ("前缀文本 prefix", "prefix", "str", "如  Elev: "),
        ("后缀文本 suffix", "suffix", "str", "如  m"),
    ]
    def __init__(self, master, initial=None):
        defaults = self._load_defaults()
        super().__init__(master, "Beta 海拔视频 属性", self.DEFS, initial, defaults)
        self.geometry("440x360")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_beta", MODULE_PATH_BETA)
            return dict(mod.DEFAULT_PARAMS_ELEVATION)
        except: return {'font_size':50,'font_color':'white','outline_width':3,
                        'outline_color':(0,0,0),'prefix':' Elev: ','suffix':' m'}

class GammaParamsDialog(DictParamsDialog):
    DEFS = [
        ("画布宽度 width", "width", "int", "像素"),
        ("画布高度 height", "height", "int", "像素"),
        ("字号 font_size", "font_size", "int", "pt"),
        ("字体颜色 font_color", "font_color", "str", "white/red/#FFFFFF"),
        ("FTP 功率 ftp", "ftp", "int", "W"),
        ("停车阈值 speed_min_kmh", "speed_min_kmh", "float", "km/h"),
        ("EMA 跨度 ema_span", "ema_span", "int", "默认25"),
        ("打印间隔 print_interval", "print_interval", "int", "秒"),
        ("DPI dpi", "dpi", "int", "默认100"),
    ]
    def __init__(self, master, initial=None, current_fps=None):
        defaults = self._load_defaults()
        if current_fps is not None:
            defaults = dict(defaults); defaults['fps'] = current_fps
        super().__init__(master, "Gamma 训练指标视频 属性", self.DEFS, initial, defaults)
        self.geometry("460x420")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_gamma", MODULE_PATH_GAMMA)
            return dict(mod.DEFAULT_PARAMS)
        except Exception:
            return {
                'width': 480, 'height': 270, 'font_size': 22,
                'font_color': 'white', 'ftp': 250,
                'speed_min_kmh': 3.0, 'ema_span': 25,
                'print_interval': 5, 'dpi': 100, 'fps': 1,
            }

class DeltaParamsDialog(DictParamsDialog):
    DEFS = [
        ("画布宽度 width", "width", "int", "像素"),
        ("画布高度 height", "height", "int", "像素"),
        ("字号 font_size", "font_size", "int", "pt"),
        ("内边距 padding", "padding", "int", "像素"),
        ("海拔弱平滑 elev_weak_smooth_sec", "elev_weak_smooth_sec", "float", "秒"),
        ("坡度强平滑 grad_strong_smooth_sec", "grad_strong_smooth_sec", "float", "秒"),
        ("爬升平滑 gain_smooth_sec", "gain_smooth_sec", "float", "秒"),
        ("相位补偿 grad_compensation_sec", "grad_compensation_sec", "float", "秒"),
        ("坡度小数位 grad_display_decimals", "grad_display_decimals", "int", "0/1/2"),
        ("最低显示速度 grad_min_speed_kmh", "grad_min_speed_kmh", "float", "km/h"),
        ("最小爬升高度 gain_min_height_m", "gain_min_height_m", "float", "米"),
        ("最小爬升距离 gain_min_dist_m", "gain_min_dist_m", "float", "米"),
        ("打印间隔 print_interval", "print_interval", "float", "秒"),
    ]
    def __init__(self, master, initial=None):
        defaults = self._load_defaults()
        super().__init__(master, "Delta 海拔/坡度/爬升 属性", self.DEFS, initial, defaults)
        self.geometry("460x520")
    @staticmethod
    def _load_defaults():
        try:
            mod = load_module_from_path("mod_delta", MODULE_PATH_DELTA)
            d = dict(mod.DEFAULT_PARAMS)
            d.pop('fps', None)
            return d
        except Exception:
            return {
                'width': 720, 'height': 80, 'font_size': 28, 'padding': 12,
                'elev_weak_smooth_sec': 2.0,
                'grad_strong_smooth_sec': 3.0,
                'gain_smooth_sec': 7.0,
                'grad_compensation_sec': 1.5,
                'grad_display_decimals': 1,
                'grad_min_speed_kmh': 3.0,
                'gain_min_height_m': 5.0,
                'gain_min_dist_m': 50.0,
                'print_interval': 5.0,
            }


# ============================================================
# 主应用 —— 左右并排双页（翻开书式）
# ============================================================
class FitVideoGeneratorApp(tk.Tk):
    PADX = 10
    GAP = 2

    def __init__(self):
        super().__init__()
        self.title("FIT数据视频生成器 V3.0.0")
        self.geometry("1500x760")
        self.fit_path = None
        self.laps = []
        self.output_dir = ""
        self._entry_widgets = []    
        self._action_buttons = []   
        self.sphc_params = {}
        self.map_params = {}
        self.elev_params = {}
        self.beta_time_params = {}
        self.beta_dist_params = {}
        self.beta_elev_params = {}
        self.gamma_params = {}
        self.delta_params = {}
        self.generation_thread = None
        self.stop_flag = threading.Event()
        self.log_queue = queue.Queue()
        self.after(80, self.process_log_queue)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.page_a = ttk.Frame(paned)
        paned.add(self.page_a, weight=1)
        self._build_page_a()

        self.page_b = ttk.Frame(paned)
        paned.add(self.page_b, weight=1)
        self._build_page_b()

    # ---------------- A 页 ----------------
    def _build_page_a(self):
        px = self.PADX
        mf = ttk.Frame(self.page_a, padding=(px, 6, px, 6))
        mf.pack(fill=tk.BOTH, expand=True)

        # ---- FIT 文件 ----
        ff = ttk.LabelFrame(mf, text="FIT 文件", padding=5)
        ff.pack(fill=tk.X, pady=self.GAP)
        self.file_var = tk.StringVar()
        file_entry = ttk.Entry(ff, textvariable=self.file_var)
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self._entry_widgets.append(file_entry)
        ttk.Button(ff, text="浏览...", command=self.select_fit_file).pack(side=tk.RIGHT, padx=5)
        self.file_var.trace_add("write", lambda *a: self.on_fit_changed())

        # ---- 输出目录 ----
        of = ttk.LabelFrame(mf, text="输出目录", padding=5)
        of.pack(fill=tk.X, pady=self.GAP)
        self.out_dir_var = tk.StringVar(value=os.getcwd())
        out_entry = ttk.Entry(of, textvariable=self.out_dir_var)
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self._entry_widgets.append(out_entry)
        ttk.Button(of, text="浏览...", command=self.select_output_dir).pack(side=tk.RIGHT, padx=5)

        # ---- Lap 选择（固定5行，超出滚动）----
        lapf = ttk.LabelFrame(mf, text="选择 Lap（所有模块共用。按 Ctrl/Shift 可多选，合成为一整个连续时间轴）", padding=5)
        lapf.pack(fill=tk.X, pady=self.GAP)
        lbf = ttk.Frame(lapf); lbf.pack(fill=tk.X)
        lap_sb = ttk.Scrollbar(lbf, orient=tk.VERTICAL)
       
        self.lap_listbox = tk.Listbox(lbf, selectmode=tk.EXTENDED, yscrollcommand=lap_sb.set, height=5)
        lap_sb.config(command=self.lap_listbox.yview)
        lap_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lap_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bf = ttk.Frame(lapf); bf.pack(fill=tk.X, pady=(2,0))
        ttk.Button(bf, text="全选 Lap", command=lambda: self.lap_listbox.selection_set(0,tk.END)).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="取消全选 Lap", command=lambda: self.lap_listbox.selection_clear(0,tk.END)).pack(side=tk.LEFT, padx=5)

        # 收集每个模块行的「可锁定控件」
        self._module_rows = []

        # ---- 模块行构造：复选框 + FPS + [属性]（属性按钮统一右对齐）----
        def add_module(parent, name, var_fps, fps_default, open_cmd, var_store):
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=1)
            # 复选框（固定宽度，保证各行对齐；注意 ttk.Checkbutton 不支持 anchor）
            cb = ttk.Checkbutton(row, text=name, variable=var_store, width=40)
            cb.grid(row=0, column=0, sticky=tk.W, padx=(0, 0))
            # FPS 标签 + 输入框
            ttk.Label(row, text="FPS:").grid(row=0, column=1, padx=(8,2))
            spin = ttk.Spinbox(row, from_=1, to=120, textvariable=var_fps, width=6)
            spin.grid(row=0, column=2, padx=(0,8))
            # 占位弹簧，把「属性」按钮推到最右 → 属性按钮同一竖线
            row.columnconfigure(3, weight=1)
            lbl = ttk.Label(row, text="（默认参数）", foreground="gray")
            lbl.grid(row=0, column=4, sticky=tk.W, padx=(0,8))
            attr_btn = ttk.Button(row, text="属性...", command=open_cmd, width=10)
            attr_btn.grid(row=0, column=5, sticky=tk.E)
            self._action_buttons.append(attr_btn)   
            self._module_rows.append((cb, spin))     
            return lbl

        # ---- Alpha 模块 ----
        af = ttk.LabelFrame(mf, text="Alpha 模块", padding=5)
        af.pack(fill=tk.X, pady=self.GAP)
        self.sphc_var = tk.BooleanVar(value=False)
        self.sphc_fps = tk.IntVar(value=ALPHA_SPHC_FPS)
        self.sphc_lbl = add_module(af, "SPHC 速度/功率/心率/踏频", self.sphc_fps, ALPHA_SPHC_FPS, self.open_sphc, self.sphc_var)
        self.sphc_fps.trace_add("write", lambda *a: self._update_label(self.sphc_lbl, "SPHC", self.sphc_fps))
        self.map_var = tk.BooleanVar(value=False)
        self.map_fps = tk.IntVar(value=ALPHA_MAP_FPS)
        self.map_lbl = add_module(af, "Map 地图轨迹", self.map_fps, ALPHA_MAP_FPS, self.open_map, self.map_var)
        self.map_fps.trace_add("write", lambda *a: self._update_label(self.map_lbl, "MAP", self.map_fps))
        self.elev_var = tk.BooleanVar(value=False)
        self.elev_fps = tk.IntVar(value=ALPHA_ELEVATION_FPS)
        self.elev_lbl = add_module(af, "Elevation 海拔剖面轨迹", self.elev_fps, ALPHA_ELEVATION_FPS, self.open_elev, self.elev_var)
        self.elev_fps.trace_add("write", lambda *a: self._update_label(self.elev_lbl, "ELEV", self.elev_fps))

        # ---- Beta 模块 ----
        bf2 = ttk.LabelFrame(mf, text="Beta 模块", padding=5)
        bf2.pack(fill=tk.X, pady=self.GAP)
        self.beta_time_var = tk.BooleanVar(value=False)
        self.beta_time_fps = tk.IntVar(value=BETA_TIME_FPS)
        self.beta_time_lbl = add_module(bf2, "Time 时间轴", self.beta_time_fps, BETA_TIME_FPS, self.open_beta_time, self.beta_time_var)
        self.beta_time_fps.trace_add("write", lambda *a: self._update_label(self.beta_time_lbl, "Time", self.beta_time_fps))
        self.beta_dist_var = tk.BooleanVar(value=False)
        self.beta_dist_fps = tk.IntVar(value=BETA_DISTANCE_FPS)
        self.beta_dist_lbl = add_module(bf2, "Distance 累计距离", self.beta_dist_fps, BETA_DISTANCE_FPS, self.open_beta_dist, self.beta_dist_var)
        self.beta_dist_fps.trace_add("write", lambda *a: self._update_label(self.beta_dist_lbl, "Dist", self.beta_dist_fps))
        self.beta_elev_var = tk.BooleanVar(value=False)
        self.beta_elev_fps = tk.IntVar(value=BETA_ELEVATION_FPS)
        self.beta_elev_lbl = add_module(bf2, "Elevation 当前海拔高度", self.beta_elev_fps, BETA_ELEVATION_FPS, self.open_beta_elev, self.beta_elev_var)
        self.beta_elev_fps.trace_add("write", lambda *a: self._update_label(self.beta_elev_lbl, "Elev", self.beta_elev_fps))

        # ---- Gamma 模块 ----
        gf = ttk.LabelFrame(mf, text="Gamma 模块", padding=5)
        gf.pack(fill=tk.X, pady=self.GAP)
        self.gamma_var = tk.BooleanVar(value=False)
        self.gamma_fps = tk.IntVar(value=GAMMA_FPS)
        self.gamma_lbl = add_module(gf, "训练指标 NP/AP/IF/VI/TSS（默认FTP 250W）", self.gamma_fps, GAMMA_FPS, self.open_gamma, self.gamma_var)
        self.gamma_fps.trace_add("write", lambda *a: self._update_label(self.gamma_lbl, "Gamma", self.gamma_fps))

        # ---- Delta 模块 ----
        df2 = ttk.LabelFrame(mf, text="Delta 模块", padding=5)
        df2.pack(fill=tk.X, pady=self.GAP)
        self.delta_var = tk.BooleanVar(value=False)
        self.delta_fps = tk.IntVar(value=DELTA_FPS)
        self.delta_lbl = add_module(df2, "当前海拔高度 / 当前坡度 / 累计爬升", self.delta_fps, DELTA_FPS, self.open_delta, self.delta_var)
        self.delta_fps.trace_add("write", lambda *a: self._update_label(self.delta_lbl, "Delta", self.delta_fps))

        # ---- 控制栏 ----
        ctrl = ttk.LabelFrame(mf, text="运行控制", padding=6)
        ctrl.pack(fill=tk.X, pady=(8, 2))
        # 第一行：开始/停止/清空日志
        row1 = ttk.Frame(ctrl); row1.pack(fill=tk.X)
        self.run_btn = tk.Button(row1, text="▶ 开始生成", command=self.start,
                                bg="#4CAF50", fg="white", font=("Arial",10,"bold"), padx=12)
        self.run_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(row1, text="■ 强制结束", command=self.stop,
                                  bg="#F44336", fg="white", font=("Arial",10,"bold"), padx=12, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.clear_log_btn = tk.Button(row1, text="🗑 清空日志", command=self.clear_log,
                                       bg="#607D8B", fg="white", font=("Arial",10,"bold"), padx=12)
        self.clear_log_btn.pack(side=tk.LEFT, padx=5)
       
        row2 = ttk.Frame(ctrl); row2.pack(fill=tk.X, pady=(6,0))
        sel_all = ttk.Button(row2, text="☑ 全选所有视频 (8个)", command=self.select_all_modules)
        sel_all.pack(side=tk.LEFT, padx=5)
        sel_none = ttk.Button(row2, text="☐ 取消全选", command=self.deselect_all_modules)
        sel_none.pack(side=tk.LEFT, padx=5)
        self._action_buttons.extend([sel_all, sel_none])  
        
    # ---------------- 赞助商标识区域（放在 B 页最顶部） ----------------
    def _build_sponsor_area(self, parent):
        image_frame = ttk.LabelFrame(parent, text="赞助商", padding=5)
        image_frame.pack(fill=tk.X, pady=(8, 2))

        self.sponsor_left_margin = 250
        self.sponsor_spacing = 100

        inner_frame = ttk.Frame(image_frame)
        inner_frame.pack(side=tk.LEFT, padx=(self.sponsor_left_margin, 0), fill=tk.X, expand=True)

        self.image_label1 = ttk.Label(inner_frame)
        self.image_label1.pack(side=tk.LEFT, padx=(0, self.sponsor_spacing // 2))
        self.image_label2 = ttk.Label(inner_frame)
        self.image_label2.pack(side=tk.LEFT, padx=(self.sponsor_spacing // 2, 0))
        self.load_logos()

    def _set_controls_state(self, locked):
        """
        locked=True  : 禁用（运行中，禁止修改参数）
        locked=False : 恢复（运行结束，可再次修改）
        """
        state = tk.DISABLED if locked else tk.NORMAL
        # 文件 / 输出目录 Entry
        for entry in getattr(self, '_entry_widgets', []):
            try: entry.config(state=state)
            except tk.TclError: pass
        # 各模块行的 Checkbutton + Spinbox
        for cb, spin in getattr(self, '_module_rows', []):
            try: cb.config(state=state)
            except tk.TclError: pass
            try: spin.config(state=state)
            except tk.TclError: pass
        # 属性按钮 / 全选 / 取消全选按钮
        for btn in getattr(self, '_action_buttons', []):
            try: btn.config(state=state)
            except tk.TclError: pass
        # Lap 列表（多选框）
        try: self.lap_listbox.config(state=state)
        except tk.TclError: pass

    def load_logos(self):
        base_height = 26
        try:
            img_pil1 = Image.open(LOGO_PATH1)
            ratio1 = base_height / img_pil1.height
            new_width1 = int(img_pil1.width * ratio1)
            img_resized1 = img_pil1.resize((new_width1, base_height), Image.LANCZOS)
            self.logo_image1 = ImageTk.PhotoImage(img_resized1)
            self.image_label1.config(image=self.logo_image1)
        except Exception as e:
            self.image_label1.config(text="Logo1 加载失败", foreground="gray")
            print(f"Logo1 加载失败: {e}")

        try:
            img_pil2 = Image.open(LOGO_PATH2)
            ratio2 = base_height / img_pil2.height
            new_width2 = int(img_pil2.width * ratio2)
            img_resized2 = img_pil2.resize((new_width2, base_height), Image.LANCZOS)
            self.logo_image2 = ImageTk.PhotoImage(img_resized2)
            self.image_label2.config(image=self.logo_image2)
        except Exception as e:
            self.image_label2.config(text="Logo2 加载失败", foreground="gray")
            print(f"Logo2 加载失败: {e}")

    # ---------------- B 页：赞助商 + 进度条 + 运行日志 ----------------
    def _build_page_b(self):
        px = self.PADX      
        self._build_sponsor_area(self.page_b)

        prog_frame = ttk.Frame(self.page_b, padding=(px, 8, px, 0))
        prog_frame.pack(fill=tk.X)
        self.progress = ttk.Progressbar(prog_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X)

        lf = ttk.LabelFrame(self.page_b, text="运行日志（实时输出，自动滚动到底部）", padding=5)
        lf.pack(fill=tk.BOTH, expand=True, padx=px, pady=5)

        self.log_text = tk.Text(lf, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        log_sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_status = ttk.Label(self.page_b, text="就绪 | 0 行", relief=tk.SUNKEN, anchor=tk.W)
        self.log_status.pack(fill=tk.X, padx=px, pady=(0,6))

    # -------------------- 全选/取消全选模块 --------------------
    def select_all_modules(self):
        for v in [self.sphc_var, self.map_var, self.elev_var,
                  self.beta_time_var, self.beta_dist_var, self.beta_elev_var,
                  self.gamma_var, self.delta_var]:
            v.set(True)

    def deselect_all_modules(self):
        for v in [self.sphc_var, self.map_var, self.elev_var,
                  self.beta_time_var, self.beta_dist_var, self.beta_elev_var,
                  self.gamma_var, self.delta_var]:
            v.set(False)

    # -------------------- 清空日志 --------------------
    def clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log_status.config(text="日志已清空 | 0 行")

    # -------------------- 日志队列 --------------------
    def process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
                line_count = int(self.log_text.index('end-1c').split('.')[0])
                frac = self.log_text.yview()[1]
                pos = "底部(最新)" if frac >= 0.999 else f"约 {int(frac*100)}%"
                self.log_status.config(text=f"位置: {pos} | 共 {line_count} 行")
        except queue.Empty:
            pass
        self.after(80, self.process_log_queue)

    # -------------------- 属性对话框 --------------------
    def _update_label(self, label, name, var):
        try:
            label.config(text=f"{name} FPS={var.get()}")
        except: pass

    def open_sphc(self):
        d = SPHCParamsDialog(self, self.sphc_params); r = d.get_result()
        if r: self.sphc_params = r; self._update_label(self.sphc_lbl, "SPHC", self.sphc_fps)
    def open_map(self):
        d = MAPParamsDialog(self, self.map_params); r = d.get_result()
        if r: self.map_params = r; self._update_label(self.map_lbl, "MAP", self.map_fps)
    def open_elev(self):
        d = ElevationParamsDialog(self, self.elev_params); r = d.get_result()
        if r: self.elev_params = r; self._update_label(self.elev_lbl, "ELEV", self.elev_fps)
    def open_beta_time(self):
        d = BetaTimeParamsDialog(self, self.beta_time_params, current_fps=self.beta_time_fps.get()); r = d.get_result()
        if r: self.beta_time_params = r; self._update_label(self.beta_time_lbl, "Time", self.beta_time_fps)
    def open_beta_dist(self):
        d = BetaDistanceParamsDialog(self, self.beta_dist_params); r = d.get_result()
        if r: self.beta_dist_params = r; self._update_label(self.beta_dist_lbl, "Dist", self.beta_dist_fps)
    def open_beta_elev(self):
        d = BetaElevationParamsDialog(self, self.beta_elev_params); r = d.get_result()
        if r: self.beta_elev_params = r; self._update_label(self.beta_elev_lbl, "Elev", self.beta_elev_fps)
    def open_gamma(self):
        d = GammaParamsDialog(self, self.gamma_params, current_fps=self.gamma_fps.get()); r = d.get_result()
        if r: self.gamma_params = r; self._update_label(self.gamma_lbl, "Gamma", self.gamma_fps)
    def open_delta(self):
        d = DeltaParamsDialog(self, self.delta_params); r = d.get_result()
        if r: self.delta_params = r; self._update_label(self.delta_lbl, "Delta", self.delta_fps)

    # -------------------- 运行控制 --------------------
    def start(self):
        if not self.lap_listbox.curselection():
            messagebox.showwarning("警告","请选择 Lap"); return
        any_sel = (self.sphc_var.get() or self.map_var.get() or self.elev_var.get()
                   or self.beta_time_var.get() or self.beta_dist_var.get() or self.beta_elev_var.get()
                   or self.gamma_var.get() or self.delta_var.get())
        if not any_sel:
            messagebox.showwarning("警告","请至少勾选一个模块"); return
        self.stop_flag.clear()
        self.run_btn.config(state=tk.DISABLED); self.stop_btn.config(state=tk.NORMAL)
        self._set_controls_state(locked=True)   
        self.progress.start(10)
        self.generation_thread = threading.Thread(target=self._run, daemon=True)
        self.generation_thread.start()

    def stop(self):
        self.stop_flag.set(); self.stop_btn.config(state=tk.DISABLED)
        self.log("⚠️ 请求停止...")

    # -------------------- 参数规范化 --------------------
    def _normalize_delta_params(self, params, fps):
        p = dict(params or {})
        p['fps'] = fps
        for k, v in list(p.items()):
            if v is None: continue
            if k in ('width', 'height', 'font_size', 'padding', 'grad_display_decimals', 'print_interval'):
                try: p[k] = int(float(v))
                except: pass
            elif k in ('elev_weak_smooth_sec', 'grad_strong_smooth_sec', 'gain_smooth_sec', 'grad_compensation_sec', 'grad_min_speed_kmh', 'gain_min_height_m', 'gain_min_dist_m'):
                try: p[k] = float(v)
                except: pass
        return p

    def _normalize_beta_params(self, params, fps):
        p = dict(params or {})
        p['fps'] = fps
        for color_key in ('font_color', 'outline_color', 'bg_color', 'bar_color', 'line_color'):
            if color_key in p and p[color_key] is not None:
                val = p[color_key]
                val = parse_color(val)
                if isinstance(val, (tuple, list)) and len(val) >= 3:
                    if all(isinstance(v, float) and v <= 1.0 for v in val[:3]):
                        val = tuple(int(round(v * 255)) for v in val[:3])
                    else:
                        val = tuple(int(round(v)) for v in val[:3])
                p[color_key] = val
        for k in ('outline_width', 'video_width', 'video_height', 'padding', 'font_size'):
            if k in p and p[k] is not None:
                try: p[k] = int(float(p[k]))
                except: p[k] = None if k in ('video_width', 'video_height') else 0
        return p

    def _normalize_gamma_params(self, params, fps):
        p = dict(params or {})
        p['fps'] = fps
        return p

    # -------------------- 主运行逻辑 --------------------
    def _run(self):
        old = sys.stdout; sys.stdout = StdoutRedirector(self.log_queue)
        total_start = time.time()
        try:
            idxs = self.lap_listbox.curselection()
            laps = [self.laps[i] for i in idxs]
            t0 = min(l['start_time'] for l in laps); t1 = max(l['end_time'] for l in laps)
            ts = time.strftime('%Y%m%d_%H%M%S')
            ffmp = get_ffmpeg_path()
            print(f"时间范围: {t0}~{t1}, FFmpeg: {ffmp}")

            if not self.stop_flag.is_set() and self.sphc_var.get():
                print("--- SPHC ---")
                mod = load_module_from_path("m", MODULE_PATH_ALPHA_SPHC)
                r = mod.generate_sphc_video(
                    fit_path=self.fit_path, lap_start=t0, lap_end=t1,
                    fps=self.sphc_fps.get(), cleanup=False,
                    params_dict=self.sphc_params or None, ffmpeg_path=ffmp,
                    output_dir=os.path.join(self.out_dir_var.get(), SPHC_FRAMES_DIR),
                    output_file=os.path.join(self.out_dir_var.get(), f"alpha_SPHC_{ts}.mov"),
                )
                print(f"SPHC 完成: {r}")

            if not self.stop_flag.is_set() and (self.map_var.get() or self.elev_var.get()):
                print("--- MAP / ELEVATION ---")
                mod = load_module_from_path("m2", MODULE_PATH_ALPHA_MAP_ELEV)
                r = mod.generate_map_elevation_video(
                    fit_path=self.fit_path, lap_start=t0, lap_end=t1,
                    generate_map=self.map_var.get(), generate_elevation=self.elev_var.get(),
                    map_fps=self.map_fps.get(), elevation_fps=self.elev_fps.get(), cleanup=False,
                    map_params_dict=self.map_params or None, elevation_params_dict=self.elev_params or None,
                    ffmpeg_path=ffmp,
                    map_output_dir=os.path.join(self.out_dir_var.get(), MAP_FRAMES_DIR),
                    map_output_file=os.path.join(self.out_dir_var.get(), f"alpha_map_{ts}.mov"),
                    elevation_output_dir=os.path.join(self.out_dir_var.get(), ELEVATION_FRAMES_DIR),
                    elevation_output_file=os.path.join(self.out_dir_var.get(), f"alpha_elevation_{ts}.mov"),
                )
                print(f"MAP/ELEV 完成: {r}")

            beta_any = (self.beta_time_var.get() or self.beta_dist_var.get() or self.beta_elev_var.get())
            if not self.stop_flag.is_set() and beta_any:
                print("--- BETA ---")
                mod_beta = load_module_from_path("m3", MODULE_PATH_BETA)
                if self.beta_time_var.get():
                    bt = self._normalize_beta_params(self.beta_time_params, self.beta_time_fps.get())
                    r = mod_beta.generate_beta_video(
                        fit_path=self.fit_path, lap_start=t0, lap_end=t1,
                        generate_time=True, generate_distance=False, generate_elevation=False,
                        time_fps=self.beta_time_fps.get(), params_dict_time=bt or None,
                        ffmpeg_path=ffmp, output_dir=os.path.join(self.out_dir_var.get(), BETA_TIME_FRAMES_DIR),
                        output_file_time=os.path.join(self.out_dir_var.get(), f"beta_time_{ts}.mov"), cleanup=False,
                    )
                    print(f"Beta Time 完成: {r}")
                if self.beta_dist_var.get():
                    bd = self._normalize_beta_params(self.beta_dist_params, self.beta_dist_fps.get())
                    r = mod_beta.generate_beta_video(
                        fit_path=self.fit_path, lap_start=t0, lap_end=t1,
                        generate_time=False, generate_distance=True, generate_elevation=False,
                        distance_fps=self.beta_dist_fps.get(), params_dict_distance=bd or None,
                        ffmpeg_path=ffmp, output_dir=os.path.join(self.out_dir_var.get(), BETA_DISTANCE_FRAMES_DIR),
                        output_file_distance=os.path.join(self.out_dir_var.get(), f"beta_dist_{ts}.mov"), cleanup=False,
                    )
                    print(f"Beta Distance 完成: {r}")
                if self.beta_elev_var.get():
                    be = self._normalize_beta_params(self.beta_elev_params, self.beta_elev_fps.get())
                    r = mod_beta.generate_beta_video(
                        fit_path=self.fit_path, lap_start=t0, lap_end=t1,
                        generate_time=False, generate_distance=False, generate_elevation=True,
                        elevation_fps=self.beta_elev_fps.get(), params_dict_elevation=be or None,
                        ffmpeg_path=ffmp, output_dir=os.path.join(self.out_dir_var.get(), BETA_ELEVATION_FRAMES_DIR),
                        output_file_elevation=os.path.join(self.out_dir_var.get(), f"beta_elev_{ts}.mov"), cleanup=False,
                    )
                    print(f"Beta Elevation 完成: {r}")

            if not self.stop_flag.is_set() and self.gamma_var.get():
                print("--- GAMMA ---")
                mod_gamma = load_module_from_path("m4", MODULE_PATH_GAMMA)
                gp = self._normalize_gamma_params(self.gamma_params, self.gamma_fps.get())
                selected_nums = [i + 1 for i in idxs]
                covered_nums = list(range(min(selected_nums), max(selected_nums) + 1))
                r = mod_gamma.generate_gamma_metrics_video(
                    fit_path=self.fit_path, lap_start=t0, lap_end=t1, generate_gamma=True,
                    fps=gp.pop('fps', self.gamma_fps.get()), cleanup=False, params_dict=gp or None,
                    ffmpeg_path=ffmp, output_dir=os.path.join(self.out_dir_var.get(), GAMMA_FRAMES_DIR),
                    output_file=os.path.join(self.out_dir_var.get(), f"gamma_metrics_{ts}.mov"),
                    selected_nums=selected_nums, covered_nums=covered_nums,
                )
                print(f"Gamma 完成: {r}")

            if not self.stop_flag.is_set() and self.delta_var.get():
                print("--- DELTA ---")
                mod_delta = load_module_from_path("m5", MODULE_PATH_DELTA)
                dp = self._normalize_delta_params(self.delta_params, self.delta_fps.get())
                r = mod_delta.generate_delta_elevation_video(
                    fit_path=self.fit_path, lap_start=t0, lap_end=t1, generate_delta=True,
                    fps=self.delta_fps.get(), cleanup=False, params_dict=dp or None,
                    ffmpeg_path=ffmp, output_dir=os.path.join(self.out_dir_var.get(), DELTA_FRAMES_DIR),
                    output_file=os.path.join(self.out_dir_var.get(), f"delta_elevation_{ts}.mov"),
                )
                print(f"Delta 完成: {r}")

            total_elapsed = time.time() - total_start
            print("✅ 全部完成")
            print(f"⏱️ 生成总用时: {total_elapsed:.2f}s")
        except Exception as e:
            print(f"❌ {e}")
            traceback.print_exc()
        finally:
            sys.stdout = old
            cleanup_elapsed = self._cleanup()
            print(f"🧹 清理总用时: {cleanup_elapsed:.2f}s")
            self.after(0, self._finish)

    def _selected_frame_dirs(self):
        """返回当前勾选模块对应的帧目录名列表。"""
        dirs = []
        if self.sphc_var.get(): dirs.append(SPHC_FRAMES_DIR)
        if self.map_var.get() or self.elev_var.get():
            # MAP / ELEVATION 共用 generate_map_elevation_video，各自独立目录
            if self.map_var.get(): dirs.append(MAP_FRAMES_DIR)
            if self.elev_var.get(): dirs.append(ELEVATION_FRAMES_DIR)
        if self.beta_time_var.get(): dirs.append(BETA_TIME_FRAMES_DIR)
        if self.beta_dist_var.get(): dirs.append(BETA_DISTANCE_FRAMES_DIR)
        if self.beta_elev_var.get(): dirs.append(BETA_ELEVATION_FRAMES_DIR)
        if self.gamma_var.get(): dirs.append(GAMMA_FRAMES_DIR)
        if self.delta_var.get(): dirs.append(DELTA_FRAMES_DIR)
        return dirs

    def _cleanup(self):
        import shutil
        t0 = time.time(); cleaned = 0
        expected = self._selected_frame_dirs()
        total = len(expected)
        for d in expected:
            p = os.path.join(self.out_dir_var.get(), d)
            if os.path.isdir(p):
                try: shutil.rmtree(p); self.log(f"🧹 清理: {d}"); cleaned += 1
                except Exception as e: self.log(f"🧹 清理失败 {d}: {e}")
        elapsed = time.time() - t0
        self.log(f"🧹 共清理 {cleaned}/{total} 个目录, 合计 {elapsed:.2f}s")
        return elapsed

    def _finish(self):
        self.progress.stop()
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_controls_state(locked=False)  

    # -------------------- Lap 加载--------------------
    def select_fit_file(self):
        p = filedialog.askopenfilename(filetypes=[("FIT","*.fit")])
        if p: self.file_var.set(p)

    def select_output_dir(self):
        d = filedialog.askdirectory()
        if d: self.out_dir_var.set(d)

    def on_fit_changed(self):
        p = self.file_var.get()
        if os.path.isfile(p):
            self.fit_path = p
            try:
                from fitparse import FitFile
                fit = FitFile(p)
                self.laps = []
                for i, lap in enumerate(fit.get_messages("lap")):
                    vals = lap.get_values()
                    start_time = vals.get("start_time")
                    elapsed = vals.get("total_elapsed_time")
                    trigger = vals.get("lap_trigger")
                    if start_time is not None and elapsed is not None:
                        end_time = start_time + timedelta(seconds=elapsed)
                        end_str = end_time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(end_time.microsecond/100000)}"
                        self.laps.append({
                            'start_time': start_time,
                            'end_time': end_time,
                            'elapsed': elapsed,
                            'trigger': trigger,
                        })
                self.lap_listbox.delete(0, tk.END)
                for i, l in enumerate(self.laps):
                    text = (f"[Lap {i+1}] start={l['start_time']:%Y-%m-%d %H:%M:%S}, "
                            f"end={l['end_time']:%Y-%m-%d %H:%M:%S}."
                            f"{int(l['end_time'].microsecond/100000)}, "
                            f"elapsed={l['elapsed']:.1f}s, trigger={l['trigger']}")
                    self.lap_listbox.insert(tk.END, text)
            except Exception as e:
                self.log(f"读取 Lap 失败: {e}")

    def log(self, m): self.log_queue.put(m+"\n")

    def on_closing(self):
        if self.generation_thread and self.generation_thread.is_alive():
            if messagebox.askyesno("确认","任务进行中，退出？"): self.destroy()
        else: self.destroy()

if __name__ == "__main__":
    FitVideoGeneratorApp().mainloop()
