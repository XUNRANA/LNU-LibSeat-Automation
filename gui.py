"""
LNU-LibSeat-Automation GUI
===========================
双击 EXE 即可使用的图形界面抢座系统。
所有配置通过界面填写，无需编辑任何文件。

UI: CustomTkinter — Apple 风格毛玻璃设计
"""
import sys
import os
import types
import threading
import tkinter as tk
import ctypes
from tkinter import scrolledtext, messagebox
from PIL import Image, ImageDraw

import customtkinter as ctk

# Windows 防休眠 API 常量
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


def _base_dir():
    """exe 或脚本所在目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ════════════════════════════════════════════════════════════
#  配色方案 — Apple 风格毛玻璃效果
# ════════════════════════════════════════════════════════════
C = {
    # 渐变背景色
    "bg_grad_start": "#667eea",  # 紫蓝色
    "bg_grad_end":   "#764ba2",  # 紫色
    "bg_solid":      "#f5f7fa",  # 纯色备选
    
    # 毛玻璃卡片
    "card":          "#ffffff",
    "card_alpha":    0.85,       # 卡片透明度
    "card_border":   "#ffffff40", # 白色半透明边框
    
    # 主题色
    "primary":       "#6366f1",  # Indigo
    "pri_hov":       "#4f46e5",
    "pri_light":     "#eef2ff",
    "pri_gradient":  ["#6366f1", "#8b5cf6"],  # 渐变按钮
    
    # 辅助色
    "success":       "#10b981",  # Emerald
    "success_light": "#d1fae5",
    "warning":       "#f59e0b",  # Amber
    "danger":        "#ef4444",  # Red
    "dng_hov":       "#dc2626",
    
    # 文字
    "text":          "#1e293b",
    "text2":         "#64748b",
    "text3":         "#94a3b8",
    "text_white":    "#ffffff",
    
    # 输入框
    "input_bg":      "#f8fafc",
    "input_border":  "#e2e8f0",
    "input_focus":   "#6366f1",
    
    # 日志
    "log_bg":        "#1e293b",
    "log_fg":        "#e2e8f0",
    "log_time":      "#64748b",
    
    # 阴影
    "shadow":        "#00000015",
}

FONT_FAMILY = "微软雅黑"
FONT_MONO = "Cascadia Code"

# 校区 → 自习室
ROOM_DATA = {
    "蒲河校区图书馆": [
        "三楼走廊", "4楼阅览室", "四楼走廊", "5楼阅览室", "五楼走廊",
        "6楼阅览室", "六楼走廊", "704", "706", "707", "708", "七楼走廊",
    ],
    "崇山校区图书馆": [
        "二楼书库北", "二楼书库南", "二楼背诵长廊", "三楼智慧研修空间",
        "三楼理科书库", "四楼北自习室", "四楼南自习室", "四楼自习室406",
    ],
}


# ════════════════════════════════════════════════════════════
#  基础字体大小 (1400x900 基准)
# ════════════════════════════════════════════════════════════
BASE_W = 1400
FS = {
    "title":       24,   # 顶部标题
    "subtitle":    13,   # 副标题
    "status":      13,   # 状态文字
    "status_dot":  10,   # 状态点
    "card_title":  15,   # 卡片标题
    "card_desc":   12,   # 卡片描述
    "label":       13,   # 标签
    "entry":       13,   # 输入框
    "combo":       13,   # 下拉框
    "seat":        15,   # 座位号
    "time":        14,   # 时间输入
    "time_sep":    18,   # 时间冒号
    "hint":        11,   # 提示文字
    "radio":       13,   # 单选
    "switch":      13,   # 开关
    "btn":         14,   # 按钮
    "btn_small":   12,   # 小按钮
    "log_title":   14,   # 日志标题
    "log":         12,   # 日志正文
    "sched":       20,   # 定时数字
}


def _scaled(base_size, scale=1.0):
    """按缩放系数返回整数字号"""
    return max(9, int(base_size * scale))


class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("LNU-LibSeat 图书馆智能抢座系统")
        self.geometry("1400x980")
        self.minsize(1200, 880)
        
        # 设置渐变背景
        self.configure(fg_color=C["bg_solid"])

        self.running = False
        self.stop_event = None
        self.worker_thread = None
        self._font_scale = 1.0
        self._last_width = 1400

        # ── 变量 ──
        self.var_campus = tk.StringVar(value="崇山校区图书馆")
        self.var_room = tk.StringVar(value="三楼智慧研修空间")
        self.seat_vars = [tk.StringVar() for _ in range(10)]
        self.var_email = tk.StringVar()
        self.var_mode = tk.StringVar(value="scheduled")
        self.var_sched_hour = tk.StringVar(value="06")
        self.var_sched_min = tk.StringVar(value="30")

        self.var_account1 = tk.StringVar()
        self.var_password1 = tk.StringVar()
        self.var_start1 = tk.StringVar(value="9:00")
        self.var_end1 = tk.StringVar(value="15:00")

        self.var_use_account2 = tk.BooleanVar(value=False)
        self.var_account2 = tk.StringVar()
        self.var_password2 = tk.StringVar()
        self.var_start2 = tk.StringVar(value="15:00")
        self.var_end2 = tk.StringVar(value="21:00")

        self.var_headless = tk.BooleanVar(value=True)

        # 收集所有需要缩放字体的 widget
        self._scalable_widgets = []  # [(widget, font_key, bold?, family_override)]

        self._build_ui()
        self._load_config()

        # 绑定窗口大小变化
        self.bind("<Configure>", self._on_resize)

        # 查找 logo
        icon_path = os.path.join(_base_dir(), "logo.ico")
        if not os.path.exists(icon_path):
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                icon_path = os.path.join(meipass, "logo.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # 居中
        win_w, win_h = 1400, 980
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - win_w) // 2)
        y = max(0, (sh - win_h) // 2)
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # ────────────── 布局 ──────────────

    def _build_ui(self):
        # 预加载 Logo 图片
        self._logo_image = None
        logo_path = os.path.join(_base_dir(), "logo.png")
        if not os.path.exists(logo_path):
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                logo_path = os.path.join(meipass, "logo.png")
        if os.path.exists(logo_path):
            try:
                pil_img = Image.open(logo_path)
                self._logo_image = ctk.CTkImage(light_image=pil_img,
                                                 dark_image=pil_img,
                                                 size=(58, 58))  # Logo 1.2倍
            except Exception:
                pass

        # ═══ 创建渐变背景 ═══
        self._bg_frame = ctk.CTkFrame(self, fg_color=C["bg_solid"], corner_radius=0)
        self._bg_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        # ═══ 主容器 ═══
        main_container = ctk.CTkFrame(self._bg_frame, fg_color="transparent")
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        # ═══ 顶部标题栏 ═══
        self._build_header(main_container)

        # ═══ 主体区域 ═══
        body = ctk.CTkFrame(main_container, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        body.grid_columnconfigure(0, weight=55, minsize=560)  # 左侧配置 - 更宽
        body.grid_columnconfigure(1, weight=45, minsize=400)  # 右侧日志
        body.grid_rowconfigure(0, weight=1)

        # ── 左栏（配置表单） ──
        left_frame = ctk.CTkFrame(body, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self._build_left_panel(left_frame)

        # ── 右栏（日志 + 操作） ──
        right_frame = ctk.CTkFrame(body, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="nsew")
        self._build_right_panel(right_frame)

    def _build_header(self, parent):
        """构建顶部标题栏 - 居中布局"""
        hdr = ctk.CTkFrame(parent, fg_color="transparent", height=56)
        hdr.pack(fill=tk.X, pady=(4, 0))
        hdr.pack_propagate(False)

        # 居中容器
        center = ctk.CTkFrame(hdr, fg_color="transparent")
        center.place(relx=0.5, rely=0.5, anchor="center")
        
        if self._logo_image:
            logo_lbl = ctk.CTkLabel(center, image=self._logo_image, text="")
            logo_lbl.pack(side=tk.LEFT, padx=(0, 16))

        # 单行标题
        lbl_title = ctk.CTkLabel(
            center, 
            text="LNU-LibSeat  辽宁大学图书馆智能抢座系统",
            font=(FONT_FAMILY, FS["title"], "bold"),
            text_color=C["primary"]
        )
        lbl_title.pack(side=tk.LEFT)
        self._scalable_widgets.append((lbl_title, "title", True, None))

        # 右侧：状态指示器
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side=tk.RIGHT, fill=tk.Y)
        
        status_card = ctk.CTkFrame(
            right, 
            fg_color=C["success_light"],
            corner_radius=20,
            height=36
        )
        status_card.pack(side=tk.RIGHT, pady=12)
        status_card.pack_propagate(False)
        
        status_inner = ctk.CTkFrame(status_card, fg_color="transparent")
        status_inner.pack(expand=True, padx=16)
        
        self.status_dot = ctk.CTkLabel(
            status_inner, 
            text="●",
            font=(FONT_FAMILY, FS["status_dot"]),
            text_color=C["success"]
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 6))
        self._scalable_widgets.append((self.status_dot, "status_dot", False, None))
        
        self.lbl_status = ctk.CTkLabel(
            status_inner,
            text="就绪",
            font=(FONT_FAMILY, FS["status"], "bold"),
            text_color=C["success"]
        )
        self.lbl_status.pack(side=tk.LEFT)
        self._scalable_widgets.append((self.lbl_status, "status", True, None))
        self._status_card = status_card

    def _build_left_panel(self, parent):
        """构建左侧配置面板 - 紧凑布局，无滚动"""
        # 直接使用普通 Frame，不用滚动
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        self._left_scroll = container  # 保持引用名称兼容

        # ── 目标设置卡片 ──
        self._build_target_card(container)
        
        # ── 账号设置卡片 ──
        self._build_account_card(container)
        
        # ── 执行设置卡片 ──
        self._build_execution_card(container)

    def _build_target_card(self, parent):
        """目标设置卡片"""
        card = self._create_card_compact(parent, "🎯", "目标设置")
        content = card.content
        
        # 统一字体大小 14px
        LABEL_FONT = (FONT_FAMILY, 14)
        
        # 第一行：校区
        row1 = ctk.CTkFrame(content, fg_color="transparent")
        row1.pack(fill=tk.X, pady=(0, 8))
        
        ctk.CTkLabel(row1, text="校区", font=LABEL_FONT, text_color=C["text"],
                     width=80, anchor="w").pack(side=tk.LEFT)
        campus_combo = self._create_combo(row1, self.var_campus, 
                                          list(ROOM_DATA.keys()), command=self._on_campus_change)
        campus_combo.configure(width=200, height=34)  # 加宽显示完整"崇山校区图书馆"
        campus_combo.pack(side=tk.LEFT)
        
        # 第二行：自习室
        row2 = ctk.CTkFrame(content, fg_color="transparent")
        row2.pack(fill=tk.X, pady=(0, 8))
        
        ctk.CTkLabel(row2, text="自习室", font=LABEL_FONT, text_color=C["text"],
                     width=80, anchor="w").pack(side=tk.LEFT)
        self.room_combo = self._create_combo(row2, self.var_room, 
                                              ROOM_DATA.get(self.var_campus.get(), []))
        self.room_combo.configure(width=200, height=34)
        self.room_combo.pack(side=tk.LEFT)
        
        # 第三行：优先座位 (10 个，分两行显示)
        row3 = ctk.CTkFrame(content, fg_color="transparent")
        row3.pack(fill=tk.X)
        ctk.CTkLabel(row3, text="优先座位", font=LABEL_FONT, text_color=C["text"],
                     width=80, anchor="w").pack(side=tk.LEFT)
        for i in range(5):
            sv = self.seat_vars[i]
            seat_entry = ctk.CTkEntry(
                row3, textvariable=sv, width=54, height=34,
                font=(FONT_MONO, 14), corner_radius=6,
                fg_color="#ffffff", border_color=C["input_border"],
                text_color=C["text"], justify="center", border_width=1,
                placeholder_text=f"{i+1:03d}"
            )
            seat_entry.pack(side=tk.LEFT, padx=(0, 6))

        row3b = ctk.CTkFrame(content, fg_color="transparent")
        row3b.pack(fill=tk.X, pady=(6, 0))
        ctk.CTkLabel(row3b, text="", font=LABEL_FONT, width=80, anchor="w").pack(side=tk.LEFT)
        for i in range(5, 10):
            sv = self.seat_vars[i]
            seat_entry = ctk.CTkEntry(
                row3b, textvariable=sv, width=54, height=34,
                font=(FONT_MONO, 14), corner_radius=6,
                fg_color="#ffffff", border_color=C["input_border"],
                text_color=C["text"], justify="center", border_width=1,
                placeholder_text=f"{i+1:03d}"
            )
            seat_entry.pack(side=tk.LEFT, padx=(0, 6))

    def _build_account_card(self, parent):
        """账号设置卡片 - 三行布局"""
        card = self._create_card_compact(parent, "👤", "账号设置")
        content = card.content
        
        # 统一字体大小
        LABEL_FONT = (FONT_FAMILY, 14)
        INPUT_FONT = (FONT_FAMILY, 14)
        MONO_FONT = (FONT_MONO, 14)
        LABEL_W = 80  # 标签宽度对齐
        
        # ══════ 主账号区域 ══════
        acc1_frame = ctk.CTkFrame(content, fg_color=C["input_bg"], corner_radius=10)
        acc1_frame.pack(fill=tk.X, pady=(0, 8))
        acc1_inner = ctk.CTkFrame(acc1_frame, fg_color="transparent")
        acc1_inner.pack(fill=tk.X, padx=16, pady=12)
        
        # 主账号标题
        ctk.CTkLabel(acc1_inner, text="主账号", font=(FONT_FAMILY, 14, "bold"),
                     text_color=C["primary"]).pack(anchor="w", pady=(0, 8))
        
        # 第一行：学号
        row1 = ctk.CTkFrame(acc1_inner, fg_color="transparent")
        row1.pack(fill=tk.X, pady=(0, 6))
        ctk.CTkLabel(row1, text="学号", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row1, textvariable=self.var_account1, height=34,
                     font=INPUT_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 第二行：密码
        row2 = ctk.CTkFrame(acc1_inner, fg_color="transparent")
        row2.pack(fill=tk.X, pady=(0, 6))
        ctk.CTkLabel(row2, text="密码", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row2, textvariable=self.var_password1, height=34,
                     font=INPUT_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, show="●").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 第三行：时段
        row3 = ctk.CTkFrame(acc1_inner, fg_color="transparent")
        row3.pack(fill=tk.X)
        ctk.CTkLabel(row3, text="时段", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row3, textvariable=self.var_start1, width=70, height=34,
                     font=MONO_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, justify="center").pack(side=tk.LEFT)
        ctk.CTkLabel(row3, text="  →  ", text_color=C["text2"], 
                     font=LABEL_FONT).pack(side=tk.LEFT)
        ctk.CTkEntry(row3, textvariable=self.var_end1, width=70, height=34,
                     font=MONO_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, justify="center").pack(side=tk.LEFT)
        
        # 添加第二账号开关
        self.switch_account2 = ctk.CTkSwitch(
            content, text="启用副账号", font=LABEL_FONT,
            text_color=C["text2"], variable=self.var_use_account2,
            command=self._toggle_account2, progress_color=C["primary"],
            button_color=C["primary"], fg_color=C["input_border"], height=24
        )
        self.switch_account2.pack(anchor="w", pady=(6, 6))
        
        # ══════ 副账号区域（默认隐藏）══════
        self.account2_frame = ctk.CTkFrame(content, fg_color=C["input_bg"], corner_radius=10)
        acc2_inner = ctk.CTkFrame(self.account2_frame, fg_color="transparent")
        acc2_inner.pack(fill=tk.X, padx=16, pady=12)
        
        # 副账号标题
        ctk.CTkLabel(acc2_inner, text="副账号", font=(FONT_FAMILY, 14, "bold"),
                     text_color=C["primary"]).pack(anchor="w", pady=(0, 8))
        
        # 第一行：学号
        row1b = ctk.CTkFrame(acc2_inner, fg_color="transparent")
        row1b.pack(fill=tk.X, pady=(0, 6))
        ctk.CTkLabel(row1b, text="学号", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row1b, textvariable=self.var_account2, height=34,
                     font=INPUT_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 第二行：密码
        row2b = ctk.CTkFrame(acc2_inner, fg_color="transparent")
        row2b.pack(fill=tk.X, pady=(0, 6))
        ctk.CTkLabel(row2b, text="密码", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row2b, textvariable=self.var_password2, height=34,
                     font=INPUT_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, show="●").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 第三行：时段
        row3b = ctk.CTkFrame(acc2_inner, fg_color="transparent")
        row3b.pack(fill=tk.X)
        ctk.CTkLabel(row3b, text="时段", font=LABEL_FONT, text_color=C["text"],
                     width=LABEL_W, anchor="w").pack(side=tk.LEFT)
        ctk.CTkEntry(row3b, textvariable=self.var_start2, width=70, height=34,
                     font=MONO_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, justify="center").pack(side=tk.LEFT)
        ctk.CTkLabel(row3b, text="  →  ", text_color=C["text2"],
                     font=LABEL_FONT).pack(side=tk.LEFT)
        ctk.CTkEntry(row3b, textvariable=self.var_end2, width=70, height=34,
                     font=MONO_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1, justify="center").pack(side=tk.LEFT)
        
        # ══════ 邮件通知 ══════
        email_row = ctk.CTkFrame(content, fg_color="transparent")
        email_row.pack(fill=tk.X, pady=(8, 0))
        ctk.CTkLabel(email_row, text="成功后通知邮箱", font=LABEL_FONT,
                     text_color=C["text"]).pack(side=tk.LEFT, padx=(0, 12))
        ctk.CTkEntry(email_row, textvariable=self.var_email, height=34,
                     font=INPUT_FONT, corner_radius=6,
                     fg_color="#ffffff", border_color=C["input_border"],
                     text_color=C["text"], border_width=1,
                     placeholder_text="example@email.com").pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_execution_card(self, parent):
        """执行设置卡片"""
        card = self._create_card_compact(parent, "⚡", "执行设置")
        content = card.content
        
        # 统一字体大小 14px
        LABEL_FONT = (FONT_FAMILY, 14)
        
        # 第一行：模式按钮 + 静默开关
        row1 = ctk.CTkFrame(content, fg_color="transparent")
        row1.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_mode_now = ctk.CTkButton(
            row1, text="⚡ 立即执行", font=(FONT_FAMILY, 14, "bold"),
            height=36, width=100, corner_radius=18,
            fg_color=C["input_bg"], hover_color=C["pri_light"],
            text_color=C["text2"], border_width=1, border_color=C["input_border"],
            command=lambda: self._set_mode("now")
        )
        self.btn_mode_now.pack(side=tk.LEFT, padx=(0, 10))
        
        self.btn_mode_sched = ctk.CTkButton(
            row1, text="⏰ 定时执行", font=(FONT_FAMILY, 14, "bold"),
            height=36, width=100, corner_radius=18,
            fg_color=C["primary"], hover_color=C["pri_hov"],
            text_color=C["text_white"], border_width=1, border_color=C["primary"],
            command=lambda: self._set_mode("scheduled")
        )
        self.btn_mode_sched.pack(side=tk.LEFT, padx=(0, 20))
        
        self.switch_headless = ctk.CTkSwitch(
            row1, text="静默运行（隐藏浏览器）", variable=self.var_headless,
            font=LABEL_FONT, text_color=C["text"],
            progress_color=C["primary"], button_color=C["card"],
            fg_color=C["input_border"], height=26
        )
        self.switch_headless.pack(side=tk.LEFT)
        
        # 定时时间设置
        self.sched_frame = ctk.CTkFrame(content, fg_color=C["pri_light"], corner_radius=10)
        sched_inner = ctk.CTkFrame(self.sched_frame, fg_color="transparent")
        sched_inner.pack(fill=tk.X, padx=16, pady=12)
        
        ctk.CTkLabel(sched_inner, text="抢座时间", font=(FONT_FAMILY, 14),
                     text_color=C["text"], width=80, anchor="w").pack(side=tk.LEFT)
        
        ctk.CTkEntry(sched_inner, textvariable=self.var_sched_hour, width=55, height=36,
                     font=(FONT_MONO, 14), corner_radius=6,
                     fg_color="#ffffff", border_color=C["primary"],
                     text_color=C["primary"], justify="center", border_width=2).pack(side=tk.LEFT)
        
        ctk.CTkLabel(sched_inner, text=":", font=(FONT_MONO, 14),
                     text_color=C["primary"]).pack(side=tk.LEFT, padx=6)
        
        ctk.CTkEntry(sched_inner, textvariable=self.var_sched_min, width=55, height=36,
                     font=(FONT_MONO, 14), corner_radius=6,
                     fg_color="#ffffff", border_color=C["primary"],
                     text_color=C["primary"], justify="center", border_width=2).pack(side=tk.LEFT)
        
        ctk.CTkLabel(sched_inner, text="（北京时间）", font=LABEL_FONT,
                     text_color=C["text2"]).pack(side=tk.LEFT, padx=(16, 0))
        
        # 初始化显示
        self._on_mode_change()

    def _build_right_panel(self, parent):
        """构建右侧面板（日志+按钮）"""
        # 日志卡片
        log_card = ctk.CTkFrame(
            parent,
            fg_color=C["card"],
            corner_radius=16,
            border_width=1,
            border_color=C["input_border"]
        )
        log_card.pack(fill=tk.BOTH, expand=True)
        
        # 日志标题
        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill=tk.X, padx=20, pady=(16, 12))
        
        log_title = ctk.CTkLabel(
            log_header,
            text="📋 运行日志",
            font=(FONT_FAMILY, FS["log_title"], "bold"),
            text_color=C["text"]
        )
        log_title.pack(side=tk.LEFT)
        self._scalable_widgets.append((log_title, "log_title", True, None))
        
        # 清空按钮
        clear_btn = ctk.CTkButton(
            log_header,
            text="清空",
            font=(FONT_FAMILY, FS["hint"]),
            width=50,
            height=26,
            corner_radius=13,
            fg_color=C["input_bg"],
            hover_color=C["input_border"],
            text_color=C["text3"],
            command=self._clear_log
        )
        clear_btn.pack(side=tk.RIGHT)
        self._scalable_widgets.append((clear_btn, "hint", False, None))
        
        # 日志文本区域 - 深色背景
        log_container = ctk.CTkFrame(
            log_card, 
            fg_color=C["log_bg"], 
            corner_radius=12
        )
        log_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        
        self.log_text = scrolledtext.ScrolledText(
            log_container,
            font=(FONT_MONO, FS["log"]),
            state=tk.DISABLED,
            wrap=tk.WORD,
            bg=C["log_bg"],
            fg=C["log_fg"],
            insertbackground=C["primary"],
            relief="flat",
            selectbackground=C["primary"],
            selectforeground=C["text_white"],
            borderwidth=0,
            padx=16,
            pady=12
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        
        # 日志颜色标签
        for tag, color in [
            ("green", C["success"]), 
            ("yellow", C["warning"]),
            ("red", C["danger"]), 
            ("blue", "#60a5fa"),
            ("dim", C["text3"]),
            ("time", C["log_time"])
        ]:
            self.log_text.tag_configure(tag, foreground=color)
        
        # 操作按钮区域
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent", height=60)
        btn_frame.pack(fill=tk.X, pady=(16, 0))
        btn_frame.pack_propagate(False)
        
        # 开始按钮 - 渐变效果
        self.btn_start = ctk.CTkButton(
            btn_frame,
            text="🚀  开始抢座",
            font=(FONT_FAMILY, FS["btn"], "bold"),
            height=50,
            corner_radius=25,
            fg_color=C["primary"],
            hover_color=C["pri_hov"],
            text_color=C["text_white"],
            command=self._start
        )
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._scalable_widgets.append((self.btn_start, "btn", True, None))
        
        # 停止按钮
        self.btn_stop = ctk.CTkButton(
            btn_frame,
            text="■  停止",
            font=(FONT_FAMILY, FS["btn"]),
            height=50,
            width=100,
            corner_radius=25,
            fg_color=C["danger"],
            hover_color=C["dng_hov"],
            text_color=C["text_white"],
            command=self._stop,
            state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT)
        self._scalable_widgets.append((self.btn_stop, "btn", False, None))

    # ────────────── 组件工厂 ──────────────

    def _create_card_compact(self, parent, icon, title):
        """创建卡片"""
        card = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["input_border"]
        )
        card.pack(fill=tk.X, pady=(0, 8))
        
        # 标题行
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill=tk.X, padx=14, pady=(10, 6))
        
        ctk.CTkLabel(header, text=icon, font=(FONT_FAMILY, 16)).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkLabel(header, text=title, font=(FONT_FAMILY, FS["card_title"], "bold"),
                     text_color=C["text"]).pack(side=tk.LEFT)
        
        # 内容区域
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill=tk.X, padx=14, pady=(0, 10))
        
        card.content = content
        return card

    def _create_card(self, parent, icon, title, description):
        """创建带描述的卡片（保留兼容）"""
        return self._create_card_compact(parent, icon, title)

    def _create_combo(self, parent, var, values, command=None):
        """创建下拉框 - 统一14px字体"""
        cb = ctk.CTkComboBox(
            parent, variable=var, values=values, height=34,
            font=(FONT_FAMILY, 14), corner_radius=8,
            fg_color="#ffffff", border_color=C["input_border"],
            button_color=C["text3"], button_hover_color=C["text2"],
            dropdown_fg_color="#ffffff", dropdown_hover_color=C["pri_light"],
            dropdown_text_color=C["text"], text_color=C["text"],
            dropdown_font=(FONT_FAMILY, 14),
            state="readonly", border_width=1
        )
        if command:
            cb.configure(command=lambda _: command())
        return cb

    # ────────────── 字体缩放 ──────────────

    def _on_resize(self, event):
        """窗口大小变化时，按宽度比例缩放所有字体"""
        if event.widget is not self:
            return
        w = event.width
        if abs(w - self._last_width) < 50:
            return
        self._last_width = w
        self._font_scale = max(0.85, w / BASE_W)
        self._apply_font_scale()

    def _apply_font_scale(self):
        """对所有注册的 widget 应用当前缩放系数"""
        s = self._font_scale
        for widget, key, bold, family_override in self._scalable_widgets:
            try:
                if not widget.winfo_exists():
                    continue
            except Exception:
                continue
            fam = family_override or FONT_FAMILY
            size = _scaled(FS[key], s)
            if bold:
                widget.configure(font=(fam, size, "bold"))
            else:
                widget.configure(font=(fam, size))
        # 日志区域
        try:
            log_size = _scaled(FS["log"], s)
            self.log_text.configure(font=(FONT_MONO, log_size))
        except Exception:
            pass

    # ────────────── 交互 ──────────────

    def _toggle_account2(self):
        if self.var_use_account2.get():
            self.account2_frame.pack(fill=tk.X, pady=(4, 0),
                                     after=self.switch_account2)
        else:
            self.account2_frame.pack_forget()

    def _on_campus_change(self):
        campus = self.var_campus.get()
        rooms = ROOM_DATA.get(campus, [])
        self.room_combo.configure(values=rooms)
        self.var_room.set(rooms[0] if rooms else "")

    def _set_mode(self, mode):
        """切换执行模式"""
        self.var_mode.set(mode)
        self._on_mode_change()
        
        # 更新按钮样式
        if mode == "now":
            self.btn_mode_now.configure(
                fg_color=C["primary"],
                text_color=C["text_white"]
            )
            self.btn_mode_sched.configure(
                fg_color=C["input_bg"],
                text_color=C["text2"]
            )
        else:
            self.btn_mode_now.configure(
                fg_color=C["input_bg"],
                text_color=C["text2"]
            )
            self.btn_mode_sched.configure(
                fg_color=C["primary"],
                text_color=C["text_white"]
            )

    def _on_mode_change(self):
        if self.var_mode.get() == "scheduled":
            self.sched_frame.pack(fill=tk.X, pady=(8, 0))
        else:
            self.sched_frame.pack_forget()

    def _clear_log(self):
        """清空日志"""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ────────────── Config I/O ──────────────

    def _config_path(self):
        return os.path.join(_base_dir(), "config.py")

    def _load_config(self):
        path = self._config_path()
        if not os.path.exists(path):
            return
        try:
            ns = {}
            with open(path, "r", encoding="utf-8") as f:
                exec(compile(f.read(), path, "exec"), ns)

            users = ns.get("USERS", {})
            accounts = list(users.items())
            if accounts:
                a, i = accounts[0]
                if a not in ("你的学号", ""):
                    self.var_account1.set(a)
                    self.var_password1.set(i.get("password", ""))
                tc = i.get("time", {})
                self.var_start1.set(tc.get("start", "9:00"))
                self.var_end1.set(tc.get("end", "15:00"))

            if len(accounts) >= 2:
                a2, i2 = accounts[1]
                if a2 not in ("第二个学号", ""):
                    self.var_use_account2.set(True)
                    self.var_account2.set(a2)
                    self.var_password2.set(i2.get("password", ""))
                    tc2 = i2.get("time", {})
                    self.var_start2.set(tc2.get("start", "15:00"))
                    self.var_end2.set(tc2.get("end", "21:00"))
                    self._toggle_account2()

            for attr, var in [("TARGET_CAMPUS", self.var_campus),
                              ("TARGET_ROOM", self.var_room),
                              ("RECEIVER_EMAIL", self.var_email)]:
                v = ns.get(attr, "")
                if v:
                    var.set(v)

            seats = ns.get("PREFER_SEATS", [])
            for i, sv in enumerate(self.seat_vars):
                sv.set(seats[i] if i < len(seats) else "")

            self.var_headless.set(ns.get("HEADLESS", True))

            wait = ns.get("WAIT_FOR_0630", True)
            self.var_mode.set("scheduled" if wait else "now")
            self._set_mode("scheduled" if wait else "now")
        except Exception:
            pass

    def _inject_config(self):
        seats = [sv.get().strip() for sv in self.seat_vars if sv.get().strip()]
        is_sched = self.var_mode.get() == "scheduled"

        users = {
            self.var_account1.get().strip(): {
                "password": self.var_password1.get(),
                "time": {"start": self.var_start1.get().strip(),
                         "end": self.var_end1.get().strip()},
            }
        }
        if self.var_use_account2.get() and self.var_account2.get().strip():
            users[self.var_account2.get().strip()] = {
                "password": self.var_password2.get(),
                "time": {"start": self.var_start2.get().strip(),
                         "end": self.var_end2.get().strip()},
            }

        cfg = types.ModuleType("config")
        cfg.USERS = users
        cfg.TARGET_CAMPUS = self.var_campus.get()
        cfg.TARGET_ROOM = self.var_room.get().strip()
        cfg.PREFER_SEATS = seats
        cfg.WAIT_FOR_0630 = is_sched
        cfg.HEADLESS = self.var_headless.get()
        cfg.BROWSER = "edge"
        cfg.DRIVER_PATH = ""
        cfg.WEBDRIVER_CACHE = ""
        cfg.RECEIVER_EMAIL = self.var_email.get().strip()
        cfg.SMTP_USER = ""
        cfg.SMTP_PASS = ""
        cfg.LOG_LEVEL = "INFO"
        cfg.LOG_DIR = os.path.join(_base_dir(), "logs")

        if is_sched:
            try:
                cfg.SCHEDULE_MODE = "custom"
                cfg.SCHEDULE_HOUR = int(self.var_sched_hour.get().strip())
                cfg.SCHEDULE_MINUTE = int(self.var_sched_min.get().strip())
            except ValueError:
                cfg.SCHEDULE_MODE = "strict"
                cfg.SCHEDULE_HOUR = 6
                cfg.SCHEDULE_MINUTE = 30

        sys.modules["config"] = cfg

    def _save_config_file(self):
        seats = [sv.get().strip() for sv in self.seat_vars if sv.get().strip()]
        seats_str = ", ".join(f'"{s}"' for s in seats)
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        is_sched = self.var_mode.get() == "scheduled"

        ub = (f'    "{esc(self.var_account1.get())}": {{\n'
              f'        "password": "{esc(self.var_password1.get())}",\n'
              f'        "time": {{"start": "{esc(self.var_start1.get())}", '
              f'"end": "{esc(self.var_end1.get())}"}}\n    }},\n')
        if self.var_use_account2.get() and self.var_account2.get().strip():
            ub += (f'    "{esc(self.var_account2.get())}": {{\n'
                   f'        "password": "{esc(self.var_password2.get())}",\n'
                   f'        "time": {{"start": "{esc(self.var_start2.get())}", '
                   f'"end": "{esc(self.var_end2.get())}"}}\n    }},\n')

        content = (
            "# ===================================================================\n"
            "# LNU-LibSeat-Automation 配置文件 (由 GUI 自动保存)\n"
            "# ===================================================================\n\n"
            f"USERS = {{\n{ub}}}\n\n"
            f'TARGET_CAMPUS = "{esc(self.var_campus.get())}"\n'
            f'TARGET_ROOM = "{esc(self.var_room.get())}"\n'
            f"PREFER_SEATS = [{seats_str}]\n\n"
            f"WAIT_FOR_0630 = {is_sched}\n"
            f"HEADLESS = {self.var_headless.get()}\n"
            'BROWSER = "edge"\nDRIVER_PATH = ""\nWEBDRIVER_CACHE = ""\n\n'
            f'RECEIVER_EMAIL = "{esc(self.var_email.get())}"\n'
            'SMTP_USER = ""\nSMTP_PASS = ""\n\n'
            'LOG_LEVEL = "INFO"\nLOG_DIR = "logs"\n')
        try:
            with open(self._config_path(), "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    # ────────────── 校验 ──────────────

    def _validate(self):
        if not self.var_account1.get().strip():
            messagebox.showwarning("提示", "请填写账号1的学号！"); return False
        if not self.var_password1.get().strip():
            messagebox.showwarning("提示", "请填写账号1的密码！"); return False
        if not self.var_room.get().strip():
            messagebox.showwarning("提示", "请选择自习室！"); return False
        if not any(sv.get().strip() for sv in self.seat_vars):
            messagebox.showwarning("提示", "请至少填写一个优先座位号！"); return False
        if self.var_use_account2.get():
            if not self.var_account2.get().strip():
                messagebox.showwarning("提示", "请填写账号2的学号！"); return False
            if not self.var_password2.get().strip():
                messagebox.showwarning("提示", "请填写账号2的密码！"); return False
        if self.var_mode.get() == "scheduled":
            try:
                h, m = int(self.var_sched_hour.get()), int(self.var_sched_min.get())
                if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
            except ValueError:
                messagebox.showwarning("提示", "定时时间格式不正确！"); return False
        return True

    # ────────────── 日志 ──────────────

    def _log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        tag = None
        if "🎉" in text or "成功" in text or "✅" in text: tag = "green"
        elif "⚠️" in text or "WARNING" in text or "😭" in text or "💔" in text: tag = "yellow"
        elif "❌" in text or "ERROR" in text or "崩溃" in text: tag = "red"
        elif "🚀" in text or "🎯" in text or "🔒" in text or "📧" in text: tag = "blue"
        self.log_text.insert(tk.END, text, tag) if tag else self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _gui_log_callback(self, msg):
        try: self.after(0, self._log, msg)
        except Exception: pass

    # ────────────── 运行控制 ──────────────

    def _start(self):
        if not self._validate(): return
        self._save_config_file()
        self._inject_config()

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

        n = "2 个账号" if self.var_use_account2.get() else "1 个账号"
        m = "立即执行" if self.var_mode.get() == "now" else \
            f"定时 {self.var_sched_hour.get()}:{self.var_sched_min.get()}"
        self._log(f">>> {n} | {m} | 启动中...\n\n")

        from core.logger import attach_gui_handler
        attach_gui_handler(self._gui_log_callback)

        self.stop_event = threading.Event()
        self.running = True
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self._status_card.configure(fg_color=C["success_light"])
        self.status_dot.configure(text_color=C["success"])
        self.lbl_status.configure(text="运行中", text_color=C["success"])
        self._set_form_state(False)

        # 开启防休眠
        try:
            if sys.platform.startswith("win"):
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
                self._log("\n>>> 🟢 已开启防休眠模式，确保定时器正常工作...\n")
        except Exception:
            pass

        def worker():
            try:
                from main import main as run_main
                run_main(stop_event=self.stop_event)
            except Exception as e:
                self.after(0, self._log, f"\n❌ 异常退出: {e}\n")
            finally:
                self.after(0, self._done)

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _done(self):
        self.running = False
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)
        self._set_form_state(True)
        self._status_card.configure(fg_color=C["pri_light"])
        self.status_dot.configure(text_color=C["primary"])
        self.lbl_status.configure(text="已完成", text_color=C["primary"])
        self._log("\n>>> 程序已结束。\n")
        
        # 恢复正常休眠
        try:
            if sys.platform.startswith("win"):
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                self._log(">>> 🔴 已恢复系统常规休眠策略。\n")
        except Exception:
            pass
            
        from core.logger import detach_gui_handler
        detach_gui_handler()

    def _stop(self):
        if self.stop_event:
            self.stop_event.set()
            self._log("\n>>> 正在停止...\n")
            self._status_card.configure(fg_color="#fef2f2")
            self.status_dot.configure(text_color=C["danger"])
            self.lbl_status.configure(text="停止中", text_color=C["danger"])

    def _set_form_state(self, enabled):
        st = "normal" if enabled else "disabled"
        for child in self._left_scroll.winfo_children():
            self._recursive_state(child, st)
        self.btn_start.configure(state="normal" if enabled else "disabled")
        self.btn_stop.configure(state="disabled" if enabled else "normal")

    def _recursive_state(self, w, st):
        try:
            widget_class = w.winfo_class()
            if hasattr(w, 'configure'):
                if isinstance(w, (ctk.CTkEntry, ctk.CTkComboBox, ctk.CTkRadioButton,
                                  ctk.CTkCheckBox, ctk.CTkSwitch, ctk.CTkButton)):
                    w.configure(state=st)
        except Exception:
            pass
        for child in w.winfo_children():
            self._recursive_state(child, st)

    def _on_close(self):
        if self.running:
            if messagebox.askokcancel("确认退出", "正在运行，确定退出？"):
                self._stop()
                self.after(1500, self.destroy)
        else:
            self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
