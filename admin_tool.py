# -*- coding: utf-8 -*-
"""
泥鳅管理员 - 子管理员工具
用账号密码登录，按权限操作：
  - 生成充值Key（必须填写客户微信号/手机号/备注）
  - 查看用户列表（只显示自己Key关联的用户 + 归档状态）
  - 封禁/解封用户
  - 查看自己生成的Key记录（含客户信息和归档状态）
"""

import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ─── 配置 ──────────────────────────────────────────────
DEFAULT_SERVER = "http://170.106.188.41:5000"

# ─── 主题色 ─────────────────────────────────────────────
C = {
    "bg":          "#0d1117",
    "bg2":         "#161b22",
    "bg3":         "#21262d",
    "card":        "#1c2333",
    "border":      "#30363d",
    "accent":      "#58a6ff",
    "accent_h":    "#79c0ff",
    "green":       "#3fb950",
    "green_bg":    "#0d2818",
    "red":         "#f85149",
    "red_bg":      "#2d0a0a",
    "orange":      "#d29922",
    "text":        "#e6edf3",
    "text2":       "#8b949e",
    "text3":       "#484f58",
    "white":       "#ffffff",
    "input_bg":    "#0d1117",
    "input_bd":    "#30363d",
    "btn_primary": "#238636",
    "btn_primary_h": "#2ea043",
    "btn_danger":  "#da3633",
    "btn_danger_h": "#f85149",
    "btn_default": "#21262d",
    "btn_default_h": "#30363d",
    "purple":      "#bc8cff",
}


# ─── API 客户端 ─────────────────────────────────────────

class AdminAPI:
    """子管理员 HTTP 客户端（用 JWT token 认证）"""

    def __init__(self, server_url: str):
        self.server = server_url.rstrip("/")
        self.token = ""
        self.permissions = {}

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.server}{path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
        except URLError as e:
            return {"ok": False, "error": f"连接失败: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def login(self, username: str, password: str) -> dict:
        result = self._request("POST", "/api/admin/login", {
            "username": username, "password": password,
        })
        if result.get("ok"):
            self.token = result["token"]
            self.permissions = result.get("permissions", {})
        return result

    def get_profile(self) -> dict:
        return self._request("GET", "/api/admin/me")

    def list_users(self) -> dict:
        return self._request("GET", "/api/admin/users")

    def generate_key(self, days: float, count: int = 1, note: str = "",
                     wechat: str = "", phone: str = "", remark: str = "") -> dict:
        return self._request("POST", "/api/admin/generate_key", {
            "days": days, "count": count, "note": note,
            "wechat": wechat, "phone": phone, "remark": remark,
        })

    def list_keys(self, status: str = "all") -> dict:
        return self._request("GET", f"/api/admin/keys?status={status}")

    def ban(self, username: str, is_banned: bool = True) -> dict:
        return self._request("POST", "/api/admin/ban", {
            "username": username, "is_banned": is_banned,
        })

    def health(self) -> dict:
        return self._request("GET", "/api/health")


# ─── 管理界面 ───────────────────────────────────────────

class AdminTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🐟 泥鳅管理员")
        self.geometry("1080x720")
        self.minsize(960, 620)
        self.configure(bg=C["bg"])
        # 设置泥鳅图标
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

        self.api = AdminAPI(DEFAULT_SERVER)
        self._users_data = []
        self._keys_data = []
        self._logged_in = False

        self._build_login_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ═══════════════════════════════════════════════════
    #  登录界面
    # ═══════════════════════════════════════════════════

    def _build_login_ui(self):
        self._login_frame = tk.Frame(self, bg=C["bg"])
        self._login_frame.pack(fill="both", expand=True)

        center = tk.Frame(self._login_frame, bg=C["card"], padx=40, pady=30,
                          highlightthickness=1, highlightbackground=C["border"])
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text="🐟 泥鳅管理员",
                 font=("Microsoft YaHei UI", 18, "bold"),
                 bg=C["card"], fg=C["accent"]).pack(pady=(0, 5))

        tk.Label(center, text="子管理员登录",
                 font=("Microsoft YaHei UI", 10),
                 bg=C["card"], fg=C["text2"]).pack(pady=(0, 20))

        # 服务器
        srv_row = tk.Frame(center, bg=C["card"])
        srv_row.pack(fill="x", pady=3)
        tk.Label(srv_row, text="服务器:", font=("Microsoft YaHei UI", 9),
                 bg=C["card"], fg=C["text2"], width=6, anchor="e").pack(side="left")
        self.login_server_var = tk.StringVar(value=DEFAULT_SERVER)
        tk.Entry(srv_row, textvariable=self.login_server_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Consolas", 9), relief="flat", width=30,
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=5)

        # 用户名
        usr_row = tk.Frame(center, bg=C["card"])
        usr_row.pack(fill="x", pady=3)
        tk.Label(usr_row, text="用户名:", font=("Microsoft YaHei UI", 9),
                 bg=C["card"], fg=C["text2"], width=6, anchor="e").pack(side="left")
        self.login_user_var = tk.StringVar()
        tk.Entry(usr_row, textvariable=self.login_user_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 10), relief="flat", width=25,
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=5)

        # 密码
        pwd_row = tk.Frame(center, bg=C["card"])
        pwd_row.pack(fill="x", pady=3)
        tk.Label(pwd_row, text="密  码:", font=("Microsoft YaHei UI", 9),
                 bg=C["card"], fg=C["text2"], width=6, anchor="e").pack(side="left")
        self.login_pass_var = tk.StringVar()
        pwd_entry = tk.Entry(pwd_row, textvariable=self.login_pass_var, show="●",
                             bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                             font=("Microsoft YaHei UI", 10), relief="flat", width=25,
                             highlightthickness=1, highlightbackground=C["input_bd"],
                             highlightcolor=C["accent"])
        pwd_entry.pack(side="left", padx=5)
        pwd_entry.bind("<Return>", lambda e: self._do_login())

        # 登录按钮
        self.login_btn = tk.Button(center, text="登 录",
                                   font=("Microsoft YaHei UI", 11, "bold"),
                                   bg=C["btn_primary"], fg=C["white"], relief="flat",
                                   activebackground=C["btn_primary_h"], cursor="hand2",
                                   padx=30, pady=4, command=self._do_login)
        self.login_btn.pack(pady=(15, 5))

        self.login_status = tk.Label(center, text="",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=C["card"], fg=C["red"])
        self.login_status.pack()

    def _do_login(self):
        server = self.login_server_var.get().strip().rstrip("/")
        username = self.login_user_var.get().strip()
        password = self.login_pass_var.get()

        if not username or not password:
            self.login_status.configure(text="请输入用户名和密码", fg=C["red"])
            return

        self.api = AdminAPI(server)
        self.login_btn.configure(state="disabled", text="登录中...")
        self.login_status.configure(text="正在连接...", fg=C["text2"])

        def _do():
            result = self.api.login(username, password)
            self.after(0, lambda: self._on_login_result(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_login_result(self, result):
        self.login_btn.configure(state="normal", text="登 录")
        if result.get("ok"):
            self._logged_in = True
            self._display_name = result.get("display_name", "")
            self._login_frame.destroy()
            self._build_main_ui()
        else:
            self.login_status.configure(text=result.get("error", "登录失败"), fg=C["red"])

    # ═══════════════════════════════════════════════════
    #  主界面（登录后）
    # ═══════════════════════════════════════════════════

    def _build_main_ui(self):
        # 顶栏
        header = tk.Frame(self, bg=C["bg2"], padx=15, pady=8)
        header.pack(fill="x")

        tk.Label(header, text="🐟 泥鳅管理员",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 bg=C["bg2"], fg=C["accent"]).pack(side="left")

        tk.Label(header, text=f"👤 {self._display_name}",
                 font=("Microsoft YaHei UI", 10),
                 bg=C["bg2"], fg=C["green"]).pack(side="right", padx=10)

        # 权限提示
        perms = self.api.permissions
        perm_texts = []
        if perms.get("can_generate_key"):
            perm_texts.append("生成Key")
        if perms.get("can_ban"):
            perm_texts.append("封禁")
        if perms.get("can_view_users"):
            perm_texts.append("查看用户")
        perm_str = " | ".join(perm_texts) if perm_texts else "无权限"

        tk.Label(header, text=f"权限: {perm_str}",
                 font=("Microsoft YaHei UI", 9),
                 bg=C["bg2"], fg=C["text2"]).pack(side="right", padx=10)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # 标签页
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview",
                        background=C["bg"], foreground=C["text"],
                        fieldbackground=C["bg"], borderwidth=0,
                        font=("Microsoft YaHei UI", 9), rowheight=28)
        style.configure("Treeview.Heading",
                        background=C["bg2"], foreground=C["text2"],
                        borderwidth=0, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview",
                  background=[("selected", C["bg3"])],
                  foreground=[("selected", C["accent"])])
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=C["bg2"], foreground=C["text2"],
                        padding=[15, 6], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", C["bg3"])],
                  foreground=[("selected", C["accent"])])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        # Tab: 生成充值Key
        self.tab_keys = tk.Frame(self.notebook, bg=C["bg"])
        self.notebook.add(self.tab_keys, text="  🔑 生成充值Key  ")
        self._build_keys_tab()

        # Tab: 用户列表（按权限）
        if perms.get("can_view_users"):
            self.tab_users = tk.Frame(self.notebook, bg=C["bg"])
            self.notebook.add(self.tab_users, text="  📋 我的用户  ")
            self._build_users_tab()

        # 底部状态栏
        status_bar = tk.Frame(self, bg=C["bg2"], height=28)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        self.status_label = tk.Label(status_bar, text="就绪",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=C["bg2"], fg=C["text2"])
        self.status_label.pack(side="left", padx=10)

        self.time_label = tk.Label(status_bar, text="",
                                   font=("Microsoft YaHei UI", 9),
                                   bg=C["bg2"], fg=C["text3"])
        self.time_label.pack(side="right", padx=10)
        self._tick_clock()

        # 自动加载
        self._refresh_my_keys()
        if perms.get("can_view_users"):
            self._refresh_users()

    # ═══════════════════════════════════════════════════
    #  Tab: 生成充值Key
    # ═══════════════════════════════════════════════════

    def _build_keys_tab(self):
        tab = self.tab_keys

        # 生成区域
        gen_frame = tk.LabelFrame(tab, text=" 生成充值Key ",
                                   font=("Microsoft YaHei UI", 11, "bold"),
                                   bg=C["bg"], fg=C["accent"], relief="groove")
        gen_frame.pack(fill="x", padx=10, pady=(10, 5))

        # 第一行：天数 + 数量
        row1 = tk.Frame(gen_frame, bg=C["bg"])
        row1.pack(fill="x", padx=10, pady=5)

        tk.Label(row1, text="天数:", font=("Microsoft YaHei UI", 10),
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        self.gen_days_var = tk.StringVar(value="30")
        tk.Entry(row1, textvariable=self.gen_days_var, width=8,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 10), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=5)

        for text, days in [("1天", 1), ("7天", 7), ("30天", 30), ("90天", 90), ("365天", 365)]:
            tk.Button(row1, text=text, font=("Microsoft YaHei UI", 8),
                      bg=C["btn_default"], fg=C["text"], relief="flat",
                      activebackground=C["btn_default_h"], cursor="hand2",
                      padx=4, command=lambda d=days: self.gen_days_var.set(str(d))
                      ).pack(side="left", padx=2)

        tk.Label(row1, text="数量:", font=("Microsoft YaHei UI", 10),
                 bg=C["bg"], fg=C["text"]).pack(side="left", padx=(15, 0))
        self.gen_count_var = tk.StringVar(value="1")
        tk.Entry(row1, textvariable=self.gen_count_var, width=5,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 10), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=5)

        # 第二行：客户信息（必填）
        info_frame = tk.LabelFrame(gen_frame, text=" 客户信息（必填）",
                                    font=("Microsoft YaHei UI", 9),
                                    bg=C["bg"], fg=C["orange"], relief="groove")
        info_frame.pack(fill="x", padx=10, pady=(0, 5))

        row_wx = tk.Frame(info_frame, bg=C["bg"])
        row_wx.pack(fill="x", padx=8, pady=2)
        tk.Label(row_wx, text="微信号:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text"], width=7, anchor="e").pack(side="left")
        self.gen_wechat_var = tk.StringVar()
        tk.Entry(row_wx, textvariable=self.gen_wechat_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", fill="x", expand=True, padx=5)

        row_phone = tk.Frame(info_frame, bg=C["bg"])
        row_phone.pack(fill="x", padx=8, pady=2)
        tk.Label(row_phone, text="手机号:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text"], width=7, anchor="e").pack(side="left")
        self.gen_phone_var = tk.StringVar()
        tk.Entry(row_phone, textvariable=self.gen_phone_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", fill="x", expand=True, padx=5)

        row_remark = tk.Frame(info_frame, bg=C["bg"])
        row_remark.pack(fill="x", padx=8, pady=(2, 5))
        tk.Label(row_remark, text="备  注:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text"], width=7, anchor="e").pack(side="left")
        self.gen_remark_var = tk.StringVar()
        tk.Entry(row_remark, textvariable=self.gen_remark_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", fill="x", expand=True, padx=5)

        # 生成按钮
        btn_row = tk.Frame(gen_frame, bg=C["bg"])
        btn_row.pack(fill="x", padx=10, pady=(0, 5))
        self.gen_btn = tk.Button(btn_row, text="🔑 生成充值Key",
                                  font=("Microsoft YaHei UI", 10, "bold"),
                                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                                  activebackground=C["btn_primary_h"], cursor="hand2",
                                  padx=15, command=self._do_generate_key)
        self.gen_btn.pack(side="left")

        # 生成结果（大文本框，方便复制）
        self.gen_result_frame = tk.Frame(gen_frame, bg=C["bg"])
        self.gen_result_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.gen_result_text = tk.Text(self.gen_result_frame, height=3,
                                        bg=C["input_bg"], fg=C["green"],
                                        insertbackground=C["text"],
                                        font=("Consolas", 11), relief="flat",
                                        highlightthickness=1, highlightbackground=C["input_bd"])
        self.gen_result_text.pack(fill="x")
        self.gen_result_text.insert("1.0", "生成的充值Key会显示在这里，可直接复制发给用户")
        self.gen_result_text.configure(state="disabled")

        # 复制按钮
        tk.Button(self.gen_result_frame, text="📋 一键复制",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._copy_keys).pack(anchor="e", pady=3)

        # 我的Key记录
        record_frame = tk.LabelFrame(tab, text=" 我生成的Key记录 ",
                                      font=("Microsoft YaHei UI", 10),
                                      bg=C["bg"], fg=C["text2"], relief="groove")
        record_frame.pack(fill="both", expand=True, padx=10, pady=5)

        toolbar = tk.Frame(record_frame, bg=C["bg"])
        toolbar.pack(fill="x", padx=5, pady=5)

        tk.Button(toolbar, text="刷新", font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_my_keys).pack(side="left")

        self.mykey_filter_var = tk.StringVar(value="all")
        for val, text in [("all", "全部"), ("unused", "未使用"), ("used", "已使用")]:
            tk.Radiobutton(toolbar, text=text, variable=self.mykey_filter_var, value=val,
                           font=("Microsoft YaHei UI", 9),
                           bg=C["bg"], fg=C["text2"], selectcolor=C["bg3"],
                           activebackground=C["bg"], indicatoron=0,
                           relief="flat", padx=8, pady=2,
                           command=self._refresh_my_keys).pack(side="left", padx=2)

        self.mykeys_count = tk.Label(toolbar, text="",
                                      font=("Microsoft YaHei UI", 9),
                                      bg=C["bg"], fg=C["text3"])
        self.mykeys_count.pack(side="right")

        tree_frame = tk.Frame(record_frame, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        cols = ("key_code", "days", "status", "used_by", "wechat", "phone", "archive", "created_at")
        self.mykeys_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                         selectmode="browse", height=6)

        self.mykeys_tree.heading("key_code", text="充值Key")
        self.mykeys_tree.heading("days", text="天数", anchor="center")
        self.mykeys_tree.heading("status", text="状态", anchor="center")
        self.mykeys_tree.heading("used_by", text="使用者")
        self.mykeys_tree.heading("wechat", text="微信号")
        self.mykeys_tree.heading("phone", text="手机号")
        self.mykeys_tree.heading("archive", text="归档", anchor="center")
        self.mykeys_tree.heading("created_at", text="创建时间")

        self.mykeys_tree.column("key_code", width=160)
        self.mykeys_tree.column("days", width=50, anchor="center")
        self.mykeys_tree.column("status", width=60, anchor="center")
        self.mykeys_tree.column("used_by", width=80)
        self.mykeys_tree.column("wechat", width=100)
        self.mykeys_tree.column("phone", width=100)
        self.mykeys_tree.column("archive", width=60, anchor="center")
        self.mykeys_tree.column("created_at", width=120)

        self.mykeys_tree.tag_configure("unused", foreground=C["green"])
        self.mykeys_tree.tag_configure("used", foreground=C["text3"])
        self.mykeys_tree.tag_configure("archived", foreground=C["purple"])

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.mykeys_tree.yview)
        self.mykeys_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.mykeys_tree.pack(fill="both", expand=True)

        # 右键菜单
        self.mykeys_ctx_menu = tk.Menu(self, tearoff=0,
                                        bg=C["bg2"], fg=C["text"], activebackground=C["bg3"],
                                        activeforeground=C["accent"], font=("Microsoft YaHei UI", 9))
        self.mykeys_ctx_menu.add_command(label="📋 复制Key", command=self._copy_selected_key)

        self.mykeys_tree.bind("<Button-3>", self._on_mykeys_right_click)
        self.mykeys_tree.bind("<Double-1>", lambda e: self._copy_selected_key())

    def _do_generate_key(self):
        if not self.api.permissions.get("can_generate_key"):
            messagebox.showwarning("权限不足", "没有生成充值Key的权限")
            return

        try:
            days = float(self.gen_days_var.get().strip())
            if days <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "请输入有效天数")
            return

        try:
            count = int(self.gen_count_var.get().strip())
            count = max(1, min(count, 50))
        except ValueError:
            count = 1

        wechat = self.gen_wechat_var.get().strip()
        phone = self.gen_phone_var.get().strip()
        remark = self.gen_remark_var.get().strip()

        if not wechat:
            messagebox.showwarning("提示", "请填写客户微信号")
            return
        if not phone:
            messagebox.showwarning("提示", "请填写客户手机号")
            return
        if not remark:
            messagebox.showwarning("提示", "请填写备注信息")
            return

        self.gen_btn.configure(state="disabled", text="生成中...")

        def _do():
            result = self.api.generate_key(days, count, wechat=wechat, phone=phone, remark=remark)
            self.after(0, lambda: self._on_keys_generated(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_keys_generated(self, result):
        self.gen_btn.configure(state="normal", text="🔑 生成充值Key")
        if result.get("ok"):
            keys = result.get("keys", [])
            key_text = "\n".join(keys)

            self.gen_result_text.configure(state="normal")
            self.gen_result_text.delete("1.0", "end")
            self.gen_result_text.insert("1.0", key_text)
            self.gen_result_text.configure(state="disabled")

            self._set_status(f"✅ {result.get('message', '生成成功')}")
            self._refresh_my_keys()
        else:
            messagebox.showerror("生成失败", result.get("error", "未知错误"))

    def _copy_keys(self):
        self.gen_result_text.configure(state="normal")
        text = self.gen_result_text.get("1.0", "end").strip()
        self.gen_result_text.configure(state="disabled")

        if text and "显示在这里" not in text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status("📋 已复制到剪贴板")
        else:
            self._set_status("没有可复制的Key")

    def _on_mykeys_right_click(self, event):
        """右键选中行并弹出菜单"""
        item = self.mykeys_tree.identify_row(event.y)
        if item:
            self.mykeys_tree.selection_set(item)
            self.mykeys_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected_key(self):
        """复制选中的Key到剪贴板"""
        sel = self.mykeys_tree.selection()
        if not sel:
            self._set_status("请先选择一条Key记录")
            return
        key_id = int(sel[0])
        key = next((k for k in self._keys_data if k["id"] == key_id), None)
        if key:
            self.clipboard_clear()
            self.clipboard_append(key["key_code"])
            self._set_status(f"📋 已复制: {key['key_code']}")

    def _refresh_my_keys(self):
        if not self.api.token:
            return
        status = self.mykey_filter_var.get() if hasattr(self, "mykey_filter_var") else "all"

        def _do():
            result = self.api.list_keys(status=status)
            self.after(0, lambda: self._on_my_keys_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_my_keys_loaded(self, result):
        if not result.get("ok"):
            return

        self._keys_data = result.get("keys", [])
        for item in self.mykeys_tree.get_children():
            self.mykeys_tree.delete(item)

        for k in self._keys_data:
            if k["is_archived"]:
                status = "📦 归档"
                tag = "archived"
            elif k["is_used"]:
                status = "✅ 已用"
                tag = "used"
            else:
                status = "🟢 可用"
                tag = "unused"

            archive_text = "✅" if k.get("is_archived") else "—"

            self.mykeys_tree.insert("", "end", iid=str(k["id"]),
                                     values=(k["key_code"], k["days_text"],
                                             status, k["used_by"] or "—",
                                             k.get("wechat", ""),
                                             k.get("phone", ""),
                                             archive_text,
                                             self._fmt_time(k["created_at"])),
                                     tags=(tag,))

        self.mykeys_count.configure(text=f"共 {len(self._keys_data)} 个")

    # ═══════════════════════════════════════════════════
    #  Tab: 用户列表（只显示自己Key关联的用户）
    # ═══════════════════════════════════════════════════

    def _build_users_tab(self):
        tab = self.tab_users

        toolbar = tk.Frame(tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(toolbar, text="仅显示使用了你生成的Key的用户",
                 font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["orange"]).pack(side="left")

        tk.Button(toolbar, text="刷新", font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_users).pack(side="right")

        self.users_count_label = tk.Label(toolbar, text="",
                                           font=("Microsoft YaHei UI", 9),
                                           bg=C["bg"], fg=C["text3"])
        self.users_count_label.pack(side="right", padx=10)

        tree_frame = tk.Frame(tab, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("username", "status", "remaining", "created", "heartbeat", "archive")
        self.users_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                        selectmode="browse", height=15)

        self.users_tree.heading("username", text="用户名")
        self.users_tree.heading("status", text="状态", anchor="center")
        self.users_tree.heading("remaining", text="剩余时长")
        self.users_tree.heading("created", text="注册时间")
        self.users_tree.heading("heartbeat", text="最后活跃")
        self.users_tree.heading("archive", text="归档状态", anchor="center")

        self.users_tree.column("username", width=110)
        self.users_tree.column("status", width=70, anchor="center")
        self.users_tree.column("remaining", width=120)
        self.users_tree.column("created", width=130)
        self.users_tree.column("heartbeat", width=130)
        self.users_tree.column("archive", width=120, anchor="center")

        self.users_tree.tag_configure("active", foreground=C["green"])
        self.users_tree.tag_configure("expired", foreground=C["red"])
        self.users_tree.tag_configure("banned", foreground=C["text3"])
        self.users_tree.tag_configure("warning", foreground=C["orange"])

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.users_tree.yview)
        self.users_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.users_tree.pack(fill="both", expand=True)

        # 封禁按钮（按权限）
        if self.api.permissions.get("can_ban"):
            btn_bar = tk.Frame(tab, bg=C["bg"])
            btn_bar.pack(fill="x", padx=10, pady=(0, 10))

            tk.Button(btn_bar, text="⛔ 封禁",
                      font=("Microsoft YaHei UI", 9, "bold"),
                      bg=C["btn_danger"], fg=C["white"], relief="flat",
                      activebackground=C["btn_danger_h"], cursor="hand2",
                      padx=8, command=self._do_ban).pack(side="left", padx=(0, 5))

            tk.Button(btn_bar, text="✅ 解封",
                      font=("Microsoft YaHei UI", 9, "bold"),
                      bg=C["btn_default"], fg=C["green"], relief="flat",
                      activebackground=C["btn_default_h"], cursor="hand2",
                      padx=8, command=self._do_unban).pack(side="left")

    def _refresh_users(self):
        if not self.api.token:
            return

        def _do():
            result = self.api.list_users()
            self.after(0, lambda: self._on_users_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_users_loaded(self, result):
        if not result.get("ok"):
            self._set_status(f"加载用户失败: {result.get('error', '')}")
            return
        self._users_data = result.get("users", [])
        self._display_users()
        total = len(self._users_data)
        active = sum(1 for u in self._users_data if not u["is_expired"] and not u["is_banned"])
        self.users_count_label.configure(text=f"共 {total} | 正常 {active}")

    def _display_users(self):
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)

        for u in self._users_data:
            if u["is_banned"]:
                status_text, tag = "⛔ 封禁", "banned"
            elif u["is_expired"]:
                status_text, tag = "🔴 过期", "expired"
            elif u.get("remaining_seconds", 0) < 86400:
                status_text, tag = "🟡 即将", "warning"
            else:
                status_text, tag = "🟢 正常", "active"

            archive_status = u.get("archive_status", "—")

            self.users_tree.insert("", "end", iid=str(u["id"]),
                                    values=(u["username"], status_text,
                                            u.get("remaining_text", "—"),
                                            self._fmt_time(u.get("created_at", 0)),
                                            self._fmt_time(u.get("last_heartbeat", 0)),
                                            archive_status),
                                    tags=(tag,))

    def _get_selected_username(self) -> str | None:
        sel = self.users_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个用户")
            return None
        user_id = int(sel[0])
        user = next((u for u in self._users_data if u["id"] == user_id), None)
        return user["username"] if user else None

    def _do_ban(self):
        username = self._get_selected_username()
        if not username:
            return
        if not messagebox.askyesno("确认封禁", f"确定要封禁 [{username}]？"):
            return

        def _do():
            result = self.api.ban(username, True)
            self.after(0, lambda: self._on_ban_result(result, "封禁"))

        threading.Thread(target=_do, daemon=True).start()

    def _do_unban(self):
        username = self._get_selected_username()
        if not username:
            return

        def _do():
            result = self.api.ban(username, False)
            self.after(0, lambda: self._on_ban_result(result, "解封"))

        threading.Thread(target=_do, daemon=True).start()

    def _on_ban_result(self, result, action):
        if result.get("ok"):
            self._set_status(f"✅ {action}成功")
            self._refresh_users()
        else:
            messagebox.showerror(f"{action}失败", result.get("error", ""))

    # ═══════════════════════════════════════════════════
    #  工具
    # ═══════════════════════════════════════════════════

    def _fmt_time(self, ts: float) -> str:
        if not ts or ts <= 0:
            return "—"
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "—"

    def _set_status(self, text: str):
        if hasattr(self, "status_label"):
            self.status_label.configure(text=text)

    def _tick_clock(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.configure(text=now)
        self.after(1000, self._tick_clock)


# ─── 入口 ────────────────────────────────────────────────

if __name__ == "__main__":
    app = AdminTool()
    app.mainloop()
