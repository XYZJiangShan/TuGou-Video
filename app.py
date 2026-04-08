"""
🐟 泥鳅视频工具箱 - 视频下载 & 去重处理工具
GUI界面 - 基于 tkinter

功能:
1. 抖音/快手/B站 无水印视频下载
2. 12+种去重手段，5种预设模式
3. 批量处理支持
4. 实时进度显示
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.downloader import VideoDownloader
from core.deduplicator import (
    VideoDeduplicator, DedupConfig, PRESETS, PLATFORM_PRESETS,
    get_preset_names, get_preset_description,
    get_platform_names, get_platform_modes, get_platform_preset,
    get_mode_description
)


class VideoToolkitApp:
    """泥鳅视频工具箱主界面"""

    # ---- 主题配色 ----
    COLORS = {
        "bg_dark": "#1a1a2e",
        "bg_card": "#16213e",
        "bg_input": "#0f3460",
        "accent": "#e94560",
        "accent_hover": "#ff6b81",
        "text": "#eaeaea",
        "text_dim": "#8b8b8b",
        "success": "#2ed573",
        "warning": "#ffa502",
        "border": "#2a2a4a",
    }

    def __init__(self, root):
        self.root = root
        self.root.title("🐟 泥鳅视频工具箱 V1.0 - 下载 & 去重")
        self.root.geometry("2100x1425")
        self.root.minsize(1650, 1125)
        self.root.configure(bg=self.COLORS["bg_dark"])

        # 设置窗口图标
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        # 设置样式
        self._setup_styles()

        # 初始化组件
        self.downloader = None
        self.deduplicator = None
        self._init_tools()

        # 路径默认值
        self.download_dir = os.path.join(os.path.dirname(__file__), "downloads")
        self.output_dir = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # 构建UI
        self._build_ui()

    def _setup_styles(self):
        """配置ttk样式"""
        style = ttk.Style()
        style.theme_use("clam")

        # 自定义Notebook标签
        style.configure("TNotebook", background=self.COLORS["bg_dark"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text"],
            padding=[15, 6],
            font=("Microsoft YaHei UI", 7, "bold"),
        )
        style.map("TNotebook.Tab", background=[("selected", self.COLORS["accent"])])

        # 进度条样式
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=self.COLORS["bg_input"],
            background=self.COLORS["accent"],
            thickness=8,
        )

        # Label样式
        style.configure(
            "Card.TFrame",
            background=self.COLORS["bg_card"],
        )

    def _init_tools(self):
        """初始化工具组件"""
        try:
            self.downloader = VideoDownloader(save_dir=self.download_dir if hasattr(self, 'download_dir') else "downloads")
        except Exception as e:
            pass  # 稍后处理

        try:
            self.deduplicator = VideoDeduplicator()
        except RuntimeError as e:
            self.deduplicator = None
            self._ffmpeg_error = str(e)

    def _build_ui(self):
        """构建主UI"""
        # 顶部标题栏
        header = tk.Frame(self.root, bg=self.COLORS["bg_dark"], height=70)
        header.pack(fill="x", padx=15, pady=(15, 8))
        header.pack_propagate(False)

        title_label = tk.Label(
            header,
            text="🐟 泥鳅视频工具箱",
            font=("Microsoft YaHei UI", 13, "bold"),
            fg=self.COLORS["accent"],
            bg=self.COLORS["bg_dark"],
        )
        title_label.pack(side="left", padx=5)

        version_label = tk.Label(
            header,
            text="V1.0 | 下载 · 去重 · 发布",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_dark"],
        )
        version_label.pack(side="left", padx=15, pady=(10, 0))

        # Tab 页面
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=8)

        # Tab 1: 视频下载
        self.tab_download = tk.Frame(self.notebook, bg=self.COLORS["bg_dark"])
        self.notebook.add(self.tab_download, text="📥 视频下载")
        self._build_download_tab()

        # Tab 2: 视频去重
        self.tab_dedup = tk.Frame(self.notebook, bg=self.COLORS["bg_dark"])
        self.notebook.add(self.tab_dedup, text="🔄 视频去重")
        self._build_dedup_tab()

        # Tab 3: 批量处理
        self.tab_batch = tk.Frame(self.notebook, bg=self.COLORS["bg_dark"])
        self.notebook.add(self.tab_batch, text="📦 批量处理")
        self._build_batch_tab()

        # 底部状态栏
        status_bar = tk.Frame(self.root, bg=self.COLORS["bg_card"], height=42)
        status_bar.pack(fill="x", padx=15, pady=(0, 12))
        status_bar.pack_propagate(False)

        ffmpeg_status = "✅ FFmpeg就绪" if self.deduplicator else "❌ FFmpeg未找到"
        self.status_label = tk.Label(
            status_bar,
            text=f"  {ffmpeg_status} | 下载目录: {self.download_dir}",
            font=("Microsoft YaHei UI", 6),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=12, pady=8)

    # ==================== 下载Tab ====================

    def _build_download_tab(self):
        """构建下载页面"""
        tab = self.tab_download

        # URL输入区域
        url_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=20, pady=20)
        url_frame.pack(fill="x", padx=15, pady=12)

        tk.Label(
            url_frame,
            text="🔗 视频链接",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        tk.Label(
            url_frame,
            text="粘贴抖音分享链接（支持短链接和完整链接）",
            font=("Microsoft YaHei UI", 6),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w", pady=(4, 10))

        self.url_entry = tk.Text(
            url_frame,
            height=3,
            font=("Consolas", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            padx=12, pady=10,
            wrap="word",
        )
        self.url_entry.pack(fill="x")

        # 监听粘贴事件：自动清空旧内容，只保留新粘贴的链接
        self.url_entry.bind("<<Paste>>", self._on_url_paste)
        # 记录上次已下载的URL，防止重复
        self._last_downloaded_url = None

        # 保存目录
        dir_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=20, pady=20)
        dir_frame.pack(fill="x", padx=15, pady=(0, 12))

        tk.Label(
            dir_frame,
            text="📁 保存目录",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        path_row = tk.Frame(dir_frame, bg=self.COLORS["bg_card"])
        path_row.pack(fill="x", pady=(10, 0))

        self.download_dir_var = tk.StringVar(value=self.download_dir)
        self.download_dir_entry = tk.Entry(
            path_row,
            textvariable=self.download_dir_var,
            font=("Consolas", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
        )
        self.download_dir_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 10))

        browse_btn = tk.Button(
            path_row,
            text="浏览...",
            font=("Microsoft YaHei UI", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            relief="flat",
            cursor="hand2",
            padx=12, pady=4,
            command=self._browse_download_dir,
        )
        browse_btn.pack(side="right")

        # 下载按钮 & 进度
        action_frame = tk.Frame(tab, bg=self.COLORS["bg_dark"], padx=15)
        action_frame.pack(fill="x", padx=15)

        self.download_btn = tk.Button(
            action_frame,
            text="⬇️  开始下载",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLORS["accent"],
            fg="white",
            activebackground=self.COLORS["accent_hover"],
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=40, pady=10,
            command=self._start_download,
        )
        self.download_btn.pack(pady=12)

        # 进度条
        self.dl_progress = ttk.Progressbar(
            action_frame,
            style="Accent.Horizontal.TProgressbar",
            mode="determinate",
            length=500,
        )
        self.dl_progress.pack(fill="x", pady=(0, 8))

        self.dl_status_label = tk.Label(
            action_frame,
            text="就绪",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_dark"],
        )
        self.dl_status_label.pack()

        # 日志
        log_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=15, pady=12)
        log_frame.pack(fill="both", expand=True, padx=15, pady=12)

        tk.Label(
            log_frame,
            text="📋 日志",
            font=("Microsoft YaHei UI", 7, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        self.dl_log = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Consolas", 6),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            state="disabled",
        )
        self.dl_log.pack(fill="both", expand=True, pady=(8, 0))

    # ==================== 去重Tab ====================

    def _build_dedup_tab(self):
        """构建去重页面"""
        tab = self.tab_dedup

        # 文件选择区域
        file_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=20, pady=20)
        file_frame.pack(fill="x", padx=15, pady=12)

        tk.Label(
            file_frame,
            text="🎥 输入视频",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        input_row = tk.Frame(file_frame, bg=self.COLORS["bg_card"])
        input_row.pack(fill="x", pady=(10, 0))

        self.dedup_input_var = tk.StringVar()
        tk.Entry(
            input_row,
            textvariable=self.dedup_input_var,
            font=("Consolas", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
        ).pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 10))

        tk.Button(
            input_row,
            text="选择文件",
            font=("Microsoft YaHei UI", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            relief="flat",
            cursor="hand2",
            padx=12, pady=4,
            command=self._browse_dedup_input,
        ).pack(side="right")

        # 输出目录
        output_row_frame = tk.Frame(file_frame, bg=self.COLORS["bg_card"])
        output_row_frame.pack(fill="x", pady=(12, 0))

        tk.Label(
            output_row_frame,
            text="输出目录:",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left")

        self.dedup_output_var = tk.StringVar(value=self.output_dir)
        tk.Entry(
            output_row_frame,
            textvariable=self.dedup_output_var,
            font=("Consolas", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
        ).pack(side="left", fill="x", expand=True, ipady=6, padx=10)

        tk.Button(
            output_row_frame,
            text="浏览",
            font=("Microsoft YaHei UI", 6),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            relief="flat",
            cursor="hand2",
            padx=10, pady=3,
            command=self._browse_dedup_output,
        ).pack(side="right")

        # 预设模式选择 — 按平台分组
        preset_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=20, pady=20)
        preset_frame.pack(fill="x", padx=15, pady=(0, 12))

        tk.Label(
            preset_frame,
            text="⚡ 去重模式（选择目标平台 → 选择模式）",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        # 平台选择行
        platform_row = tk.Frame(preset_frame, bg=self.COLORS["bg_card"])
        platform_row.pack(fill="x", pady=(10, 8))

        tk.Label(
            platform_row,
            text="目标平台:",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left")

        self.platform_var = tk.StringVar(value="抖音")
        platform_names = get_platform_names()

        # 平台按钮：用 Radiobutton 横排
        for pname in platform_names:
            # 平台图标
            icons = {"抖音": "🎵", "快手": "🎬", "小红书": "📕", "B站": "📺", "通用": "⚙️"}
            icon = icons.get(pname, "📌")
            rb = tk.Radiobutton(
                platform_row,
                text=f" {icon} {pname}",
                variable=self.platform_var,
                value=pname,
                font=("Microsoft YaHei UI", 7, "bold"),
                fg=self.COLORS["text"],
                bg=self.COLORS["bg_card"],
                selectcolor=self.COLORS["accent"],
                activebackground=self.COLORS["bg_card"],
                activeforeground=self.COLORS["accent"],
                indicatoron=0,  # 按钮样式
                padx=12, pady=4,
                relief="flat",
                borderwidth=2,
                cursor="hand2",
                command=self._on_platform_changed,
            )
            rb.pack(side="left", padx=4)

        # 模式选择区域（动态更新）
        self.mode_container = tk.Frame(preset_frame, bg=self.COLORS["bg_card"])
        self.mode_container.pack(fill="x", pady=(4, 0))

        self.preset_var = tk.StringVar()
        self._refresh_mode_list()

        # 生成数量
        count_frame = tk.Frame(preset_frame, bg=self.COLORS["bg_card"])
        count_frame.pack(fill="x", pady=(12, 0))

        tk.Label(
            count_frame,
            text="生成数量:",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left")

        self.gen_count_var = tk.IntVar(value=1)
        count_spin = tk.Spinbox(
            count_frame,
            from_=1, to=20,
            textvariable=self.gen_count_var,
            width=5,
            font=("Microsoft YaHei UI", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            buttonbackground=self.COLORS["bg_input"],
        )
        count_spin.pack(side="left", padx=12)

        tk.Label(
            count_frame,
            text="（同一视频生成多个不同版本）",
            font=("Microsoft YaHei UI", 6),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left")

        # 处理按钮 & 进度
        action_frame = tk.Frame(tab, bg=self.COLORS["bg_dark"], padx=15)
        action_frame.pack(fill="x", padx=15)

        self.dedup_btn = tk.Button(
            action_frame,
            text="🔄  开始去重处理",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg=self.COLORS["accent"],
            fg="white",
            activebackground=self.COLORS["accent_hover"],
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=40, pady=10,
            command=self._start_dedup,
        )
        self.dedup_btn.pack(pady=12)

        self.dedup_progress = ttk.Progressbar(
            action_frame,
            style="Accent.Horizontal.TProgressbar",
            mode="determinate",
        )
        self.dedup_progress.pack(fill="x", pady=(0, 8))

        self.dedup_status_label = tk.Label(
            action_frame,
            text="就绪" if self.deduplicator else "⚠️ FFmpeg未找到，去重功能不可用",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"] if self.deduplicator else self.COLORS["warning"],
            bg=self.COLORS["bg_dark"],
        )
        self.dedup_status_label.pack()

        # 日志
        log_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=15, pady=12)
        log_frame.pack(fill="both", expand=True, padx=15, pady=12)

        self.dedup_log = scrolledtext.ScrolledText(
            log_frame,
            height=6,
            font=("Consolas", 6),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            state="disabled",
        )
        self.dedup_log.pack(fill="both", expand=True)

    # ==================== 批量处理Tab ====================

    def _build_batch_tab(self):
        """构建批量处理页面"""
        tab = self.tab_batch

        # 批量下载区域
        batch_dl_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=20, pady=20)
        batch_dl_frame.pack(fill="x", padx=15, pady=12)

        tk.Label(
            batch_dl_frame,
            text="📥 批量下载",
            font=("Microsoft YaHei UI", 8, "bold"),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w")

        tk.Label(
            batch_dl_frame,
            text="每行输入一个视频链接：",
            font=("Microsoft YaHei UI", 6),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(anchor="w", pady=(4, 8))

        self.batch_urls_text = tk.Text(
            batch_dl_frame,
            height=6,
            font=("Consolas", 7),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            padx=12, pady=10,
        )
        self.batch_urls_text.pack(fill="x")

        # 选项行
        opts_row = tk.Frame(batch_dl_frame, bg=self.COLORS["bg_card"])
        opts_row.pack(fill="x", pady=(12, 0))

        self.batch_auto_dedup = tk.BooleanVar(value=True)
        tk.Checkbutton(
            opts_row,
            text="下载后自动去重",
            variable=self.batch_auto_dedup,
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text"],
            bg=self.COLORS["bg_card"],
            selectcolor=self.COLORS["bg_input"],
            activebackground=self.COLORS["bg_card"],
        ).pack(side="left")

        tk.Label(
            opts_row,
            text="去重平台:",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left", padx=(25, 8))

        self.batch_platform_var = tk.StringVar(value="抖音")
        batch_platform_combo = ttk.Combobox(
            opts_row,
            textvariable=self.batch_platform_var,
            values=get_platform_names(),
            state="readonly",
            width=8,
            font=("Microsoft YaHei UI", 7),
        )
        batch_platform_combo.pack(side="left")
        batch_platform_combo.bind("<<ComboboxSelected>>", self._on_batch_platform_changed)

        tk.Label(
            opts_row,
            text="模式:",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        ).pack(side="left", padx=(12, 4))

        self.batch_preset_var = tk.StringVar()
        self.batch_mode_combo = ttk.Combobox(
            opts_row,
            textvariable=self.batch_preset_var,
            state="readonly",
            width=28,
            font=("Microsoft YaHei UI", 7),
        )
        self.batch_mode_combo.pack(side="left")
        # 初始化模式列表
        self._on_batch_platform_changed()

        # 批量执行按钮
        self.batch_btn = tk.Button(
            batch_dl_frame,
            text="🚀  开始批量处理",
            font=("Microsoft YaHei UI", 8, "bold"),
            bg=self.COLORS["accent"],
            fg="white",
            activebackground=self.COLORS["accent_hover"],
            relief="flat",
            cursor="hand2",
            padx=30, pady=8,
            command=self._start_batch,
        )
        self.batch_btn.pack(pady=(18, 8))

        # 批量进度
        self.batch_progress = ttk.Progressbar(
            batch_dl_frame,
            style="Accent.Horizontal.TProgressbar",
            mode="determinate",
        )
        self.batch_progress.pack(fill="x", pady=(5, 0))

        self.batch_status = tk.Label(
            batch_dl_frame,
            text="就绪",
            font=("Microsoft YaHei UI", 7),
            fg=self.COLORS["text_dim"],
            bg=self.COLORS["bg_card"],
        )
        self.batch_status.pack(pady=(8, 0))

        # 批量日志
        log_frame = tk.Frame(tab, bg=self.COLORS["bg_card"], padx=15, pady=12)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(0, 12))

        self.batch_log = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            font=("Consolas", 6),
            bg=self.COLORS["bg_input"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            state="disabled",
        )
        self.batch_log.pack(fill="both", expand=True)

    # ==================== 事件处理 ====================

    def _on_url_paste(self, event=None):
        """粘贴时自动清空旧内容，只保留新粘贴的链接"""
        try:
            clipboard = self.root.clipboard_get()
            if not clipboard or not clipboard.strip():
                return

            # 检查剪贴板里有没有URL
            import re
            urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', clipboard)
            if urls:
                # 有链接 → 清空输入框，填入新链接
                self.url_entry.delete("1.0", "end")
                self.url_entry.insert("1.0", clipboard.strip())
                return "break"  # 阻止默认粘贴行为（避免重复插入）
        except tk.TclError:
            pass  # 剪贴板为空或不可访问
        return None

    def _extract_latest_url(self, text):
        """从文本中提取最新的（最后一个）有效链接"""
        import re
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
        if urls:
            return urls[-1]  # 取最后一个（最新粘贴的）
        return text.strip()

    def _browse_download_dir(self):
        path = filedialog.askdirectory(title="选择下载保存目录")
        if path:
            self.download_dir_var.set(path)
            self.download_dir = path

    def _browse_dedup_input(self):
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm"),
                ("所有文件", "*.*"),
            ]
        )
        if path:
            self.dedup_input_var.set(path)

    def _browse_dedup_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.dedup_output_var.set(path)

    def _on_platform_changed(self):
        """平台切换时刷新模式列表"""
        self._refresh_mode_list()

    def _refresh_mode_list(self):
        """刷新模式选择列表"""
        # 清空旧内容
        for widget in self.mode_container.winfo_children():
            widget.destroy()

        platform = self.platform_var.get()
        modes = get_platform_modes(platform)

        if not modes:
            return

        # 默认选第一个模式
        if platform == "通用":
            default_mode = "中度去重"
        else:
            default_mode = modes[0]
        self.preset_var.set(default_mode)

        for mode_name in modes:
            desc = get_mode_description(platform, mode_name)
            row = tk.Frame(self.mode_container, bg=self.COLORS["bg_card"])
            row.pack(fill="x", pady=2)

            rb = tk.Radiobutton(
                row,
                text=f"  {mode_name}",
                variable=self.preset_var,
                value=mode_name,
                font=("Microsoft YaHei UI", 7),
                fg=self.COLORS["text"],
                bg=self.COLORS["bg_card"],
                selectcolor=self.COLORS["bg_input"],
                activebackground=self.COLORS["bg_card"],
                activeforeground=self.COLORS["accent"],
                cursor="hand2",
            )
            rb.pack(side="left")

            if desc:
                tk.Label(
                    row,
                    text=f"  {desc}",
                    font=("Microsoft YaHei UI", 6),
                    fg=self.COLORS["text_dim"],
                    bg=self.COLORS["bg_card"],
                ).pack(side="left")

    def _get_current_preset_key(self):
        """获取当前选择的预设key（用于PRESETS字典查找）"""
        platform = self.platform_var.get()
        mode = self.preset_var.get()
        if platform == "通用":
            return mode
        else:
            return f"{platform}/{mode}"

    def _log(self, widget, message):
        """向日志控件追加消息"""
        def _append():
            widget.configure(state="normal")
            widget.insert("end", message + "\n")
            widget.see("end")
            widget.configure(state="disabled")
        self.root.after(0, _append)

    def _start_download(self):
        """开始下载"""
        raw_text = self.url_entry.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("提示", "请输入视频链接！")
            return

        # 提取最新的有效链接
        url = self._extract_latest_url(raw_text)
        if not url:
            messagebox.showwarning("提示", "未识别到有效链接，请检查输入！")
            return

        # 检查是否跟上次一样
        if url == self._last_downloaded_url:
            if not messagebox.askyesno("提示", "该链接已下载过，确认再次下载？"):
                return

        save_dir = self.download_dir_var.get()
        self.download_btn.configure(state="disabled", text="⏳ 下载中...")

        def do_download():
            try:
                downloader = VideoDownloader(save_dir=save_dir)

                def callback(downloaded, total, percent, msg):
                    self.root.after(0, lambda: self.dl_progress.configure(value=percent))
                    self.root.after(0, lambda: self.dl_status_label.configure(
                        text=msg, fg=self.COLORS["text"]
                    ))

                self._log(self.dl_log, f"[开始] 正在下载: {url[:80]}...")
                path = downloader.download(url, callback=callback)
                self._log(self.dl_log, f"[完成] ✅ 保存至: {path}")

                # 记录已下载URL
                self._last_downloaded_url = url

                # 下载成功后清空输入框，方便粘贴下一个
                self.root.after(0, lambda: self.url_entry.delete("1.0", "end"))

                self.root.after(0, lambda: self.dl_status_label.configure(
                    text=f"✅ 下载完成! {path}", fg=self.COLORS["success"]
                ))
                self.root.after(0, lambda: messagebox.showinfo("下载完成", f"视频已保存至:\n{path}"))

            except Exception as e:
                self._log(self.dl_log, f"[错误] ❌ {e}")
                self.root.after(0, lambda: self.dl_status_label.configure(
                    text=f"❌ 下载失败: {e}", fg=self.COLORS["accent"]
                ))
            finally:
                self.root.after(0, lambda: self.download_btn.configure(
                    state="normal", text="⬇️  开始下载"
                ))

        threading.Thread(target=do_download, daemon=True).start()

    def _start_dedup(self):
        """开始去重处理"""
        if not self.deduplicator:
            messagebox.showerror("错误", "FFmpeg未找到，请安装FFmpeg后重试！\n下载地址: https://ffmpeg.org/download.html")
            return

        input_path = self.dedup_input_var.get()
        if not input_path or not os.path.exists(input_path):
            messagebox.showwarning("提示", "请选择有效的视频文件！")
            return

        output_dir = self.dedup_output_var.get()
        preset_name = self._get_current_preset_key()
        gen_count = self.gen_count_var.get()

        self.dedup_btn.configure(state="disabled", text="⏳ 处理中...")

        def do_dedup():
            try:
                os.makedirs(output_dir, exist_ok=True)
                basename = Path(input_path).stem

                for i in range(gen_count):
                    suffix = f"_v{i+1}" if gen_count > 1 else ""
                    output_path = os.path.join(
                        output_dir, f"dedup_{basename}{suffix}.mp4"
                    )

                    self._log(
                        self.dedup_log,
                        f"[{i+1}/{gen_count}] 预设: {preset_name} | 输出: {Path(output_path).name}"
                    )

                    def callback(percent, msg):
                        overall = int(((i + percent / 100) / gen_count) * 100)
                        self.root.after(0, lambda p=overall: self.dedup_progress.configure(value=p))
                        self.root.after(0, lambda m=msg: self.dedup_status_label.configure(
                            text=m, fg=self.COLORS["text"]
                        ))

                    self.deduplicator.process(
                        input_path, output_path,
                        preset=preset_name, callback=callback
                    )
                    self._log(self.dedup_log, f"  ✅ 完成: {output_path}")

                self.root.after(0, lambda: self.dedup_status_label.configure(
                    text=f"✅ 全部完成! 生成 {gen_count} 个去重视频", fg=self.COLORS["success"]
                ))
                self.root.after(0, lambda: messagebox.showinfo(
                    "处理完成", f"已生成 {gen_count} 个去重版本\n输出目录: {output_dir}"
                ))

            except Exception as e:
                self._log(self.dedup_log, f"[错误] ❌ {e}")
                self.root.after(0, lambda: self.dedup_status_label.configure(
                    text=f"❌ 处理失败: {e}", fg=self.COLORS["accent"]
                ))
            finally:
                self.root.after(0, lambda: self.dedup_btn.configure(
                    state="normal", text="🔄  开始去重处理"
                ))

        threading.Thread(target=do_dedup, daemon=True).start()

    def _on_batch_platform_changed(self, event=None):
        """批量处理平台切换时更新模式列表"""
        platform = self.batch_platform_var.get()
        modes = get_platform_modes(platform)
        self.batch_mode_combo["values"] = modes
        if modes:
            if platform == "通用":
                self.batch_preset_var.set("中度去重")
            else:
                self.batch_preset_var.set(modes[0])

    def _get_batch_preset_key(self):
        """获取批量处理当前选择的预设key"""
        platform = self.batch_platform_var.get()
        mode = self.batch_preset_var.get()
        if platform == "通用":
            return mode
        else:
            return f"{platform}/{mode}"

    def _start_batch(self):
        """开始批量处理"""
        urls_text = self.batch_urls_text.get("1.0", "end").strip()
        if not urls_text:
            messagebox.showwarning("提示", "请输入视频链接！")
            return

        urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
        if not urls:
            messagebox.showwarning("提示", "未检测到有效链接！")
            return

        auto_dedup = self.batch_auto_dedup.get()
        preset = self._get_batch_preset_key()
        self.batch_btn.configure(state="disabled", text="⏳ 批量处理中...")

        def do_batch():
            total = len(urls)
            success = 0

            for idx, url in enumerate(urls):
                try:
                    # 更新进度
                    progress = int((idx / total) * 100)
                    self.root.after(0, lambda p=progress: self.batch_progress.configure(value=p))
                    self.root.after(0, lambda m=f"[{idx+1}/{total}] 下载中...": self.batch_status.configure(text=m))

                    self._log(self.batch_log, f"\n[{idx+1}/{total}] 下载: {url[:60]}...")

                    # 下载
                    downloader = VideoDownloader(save_dir=self.download_dir)

                    def dl_callback(downloaded, total_size, percent, msg):
                        pass  # 批量模式简化进度

                    dl_path = downloader.download(url, callback=dl_callback)
                    self._log(self.batch_log, f"  ✅ 下载完成: {dl_path}")

                    # 自动去重
                    if auto_dedup and self.deduplicator:
                        self.root.after(0, lambda: self.batch_status.configure(
                            text=f"[{idx+1}/{total}] 去重中..."
                        ))
                        basename = Path(dl_path).stem
                        dedup_path = os.path.join(self.output_dir, f"dedup_{basename}.mp4")

                        self.deduplicator.process(
                            dl_path, dedup_path, preset=preset
                        )
                        self._log(self.batch_log, f"  ✅ 去重完成: {dedup_path}")

                    success += 1

                except Exception as e:
                    self._log(self.batch_log, f"  ❌ 失败: {e}")

            self.root.after(0, lambda: self.batch_progress.configure(value=100))
            self.root.after(0, lambda: self.batch_status.configure(
                text=f"✅ 批量完成! 成功 {success}/{total}",
                fg=self.COLORS["success"]
            ))
            self.root.after(0, lambda: self.batch_btn.configure(
                state="normal", text="🚀  开始批量处理"
            ))

        threading.Thread(target=do_batch, daemon=True).start()


def main():
    # 设置DPI感知（必须在Tk()之前）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    app = VideoToolkitApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
