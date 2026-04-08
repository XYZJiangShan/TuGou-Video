# -*- coding: utf-8 -*-
"""
土狗管理员总管理工具
超级管理员使用，功能：
  - 管理子管理员（创建/编辑权限/启禁/删除）
  - 查看所有用户 + 直接充值/封禁
  - 查看所有充值Key（含客户信息、归档操作）
  - 查看操作日志
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
    "accent":      "#f0883e",
    "accent_h":    "#ffa657",
    "green":       "#3fb950",
    "green_bg":    "#0d2818",
    "red":         "#f85149",
    "red_bg":      "#2d0a0a",
    "orange":      "#d29922",
    "orange_bg":   "#2a1e00",
    "purple":      "#bc8cff",
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
    "btn_orange":  "#9e6a03",
    "btn_orange_h": "#bb8009",
}


# ─── API 客户端 ─────────────────────────────────────────

class SuperAdminAPI:
    """超级管理员 HTTP 客户端"""

    def __init__(self, server_url: str, super_key: str):
        self.server = server_url.rstrip("/")
        self.super_key = super_key

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.server}{path}"
        headers = {
            "X-Super-Admin-Key": self.super_key,
            "Content-Type": "application/json",
        }
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

    def health(self) -> dict:
        return self._request("GET", "/api/health")

    # 管理员操作
    def list_admins(self) -> dict:
        return self._request("GET", "/api/super/admins")

    def create_admin(self, data: dict) -> dict:
        return self._request("POST", "/api/super/admins", data)

    def update_admin(self, username: str, data: dict) -> dict:
        return self._request("PUT", f"/api/super/admins/{username}", data)

    def delete_admin(self, username: str) -> dict:
        return self._request("DELETE", f"/api/super/admins/{username}")

    # 用户操作
    def list_users(self) -> dict:
        return self._request("GET", "/api/super/users")

    def recharge(self, username: str, seconds: int, description: str = "") -> dict:
        return self._request("POST", "/api/super/recharge", {
            "username": username, "seconds": seconds, "description": description,
        })

    def ban(self, username: str, is_banned: bool = True) -> dict:
        return self._request("POST", "/api/super/ban", {
            "username": username, "is_banned": is_banned,
        })

    # 充值Key
    def list_keys(self, status: str = "all", limit: int = 200) -> dict:
        return self._request("GET", f"/api/super/keys?status={status}&limit={limit}")

    def archive_key(self, key_id: int, is_archived: bool = True) -> dict:
        return self._request("POST", f"/api/super/keys/{key_id}/archive", {
            "is_archived": is_archived,
        })

    def revoke_key(self, key_id: int, reason: str = "") -> dict:
        return self._request("POST", f"/api/super/keys/{key_id}/revoke", {
            "reason": reason,
        })

    # 日志
    def get_logs(self, limit: int = 100) -> dict:
        return self._request("GET", f"/api/super/logs?limit={limit}")

    def get_user_ip_logs(self, user_id: int, limit: int = 50) -> dict:
        return self._request("GET", f"/api/super/users/{user_id}/ip_logs?limit={limit}")

    def get_admin_ip_logs(self, admin_username: str, limit: int = 50) -> dict:
        return self._request("GET", f"/api/super/admins/{admin_username}/ip_logs?limit={limit}")


# ─── 主界面 ────────────────────────────────────────────

class SuperAdminTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🐶 土狗管理员总管理工具")
        self.geometry("1350x750")
        self.minsize(1150, 650)
        self.configure(bg=C["bg"])
        # 去掉默认图标
        self._blank_icon = tk.PhotoImage(width=1, height=1)
        self.iconphoto(True, self._blank_icon)

        self.api = None
        self._admins_data = []
        self._users_data = []
        self._keys_data = []

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ═══════════════════════════════════════════════════
    #  UI 构建
    # ═══════════════════════════════════════════════════

    def _build_ui(self):
        # ── 顶部连接栏 ──
        conn_bar = tk.Frame(self, bg=C["bg2"], padx=15, pady=10)
        conn_bar.pack(fill="x")

        tk.Label(conn_bar, text="🐶 土狗管理员总管理工具",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 bg=C["bg2"], fg=C["accent"]).pack(side="left")

        right_conn = tk.Frame(conn_bar, bg=C["bg2"])
        right_conn.pack(side="right")

        tk.Label(right_conn, text="服务器:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg2"], fg=C["text2"]).pack(side="left")
        self.server_var = tk.StringVar(value=DEFAULT_SERVER)
        tk.Entry(right_conn, textvariable=self.server_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Consolas", 9), relief="flat", width=25,
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=(5, 10))

        tk.Label(right_conn, text="超级密钥:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg2"], fg=C["text2"]).pack(side="left")
        self.key_var = tk.StringVar()
        tk.Entry(right_conn, textvariable=self.key_var, show="●",
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Consolas", 9), relief="flat", width=22,
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=(5, 10))

        self.conn_btn = tk.Button(right_conn, text="连接",
                                  font=("Microsoft YaHei UI", 9, "bold"),
                                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                                  activebackground=C["btn_primary_h"], cursor="hand2",
                                  padx=12, command=self._connect)
        self.conn_btn.pack(side="left")

        self.conn_status = tk.Label(conn_bar, text="● 未连接",
                                    font=("Microsoft YaHei UI", 9),
                                    bg=C["bg2"], fg=C["red"])
        self.conn_status.pack(side="right", padx=15)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── 标签页 ──
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=C["bg2"], foreground=C["text2"],
                        padding=[15, 6], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", C["bg3"])],
                  foreground=[("selected", C["accent"])])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_admins = tk.Frame(self.notebook, bg=C["bg"])
        self.tab_users = tk.Frame(self.notebook, bg=C["bg"])
        self.tab_keys = tk.Frame(self.notebook, bg=C["bg"])
        self.tab_logs = tk.Frame(self.notebook, bg=C["bg"])

        self.notebook.add(self.tab_admins, text="  👥 子管理员  ")
        self.notebook.add(self.tab_users, text="  📋 用户管理  ")
        self.notebook.add(self.tab_keys, text="  🔑 充值Key  ")
        self.notebook.add(self.tab_logs, text="  📝 操作日志  ")

        self._build_admins_tab()
        self._build_users_tab()
        self._build_keys_tab()
        self._build_logs_tab()

        # ── 底部状态栏 ──
        status_bar = tk.Frame(self, bg=C["bg2"], height=28)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        self.status_label = tk.Label(status_bar, text="请输入服务器地址和超级管理员密钥，然后点击连接",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=C["bg2"], fg=C["text2"])
        self.status_label.pack(side="left", padx=10)

        self.time_label = tk.Label(status_bar, text="",
                                   font=("Microsoft YaHei UI", 9),
                                   bg=C["bg2"], fg=C["text3"])
        self.time_label.pack(side="right", padx=10)
        self._tick_clock()

    # ═══════════════════════════════════════════════════
    #  Tab 1: 子管理员管理
    # ═══════════════════════════════════════════════════

    def _build_admins_tab(self):
        tab = self.tab_admins

        toolbar = tk.Frame(tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(toolbar, text="➕ 创建管理员",
                  font=("Microsoft YaHei UI", 9, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  activebackground=C["btn_primary_h"], cursor="hand2",
                  padx=10, command=self._show_create_admin_dialog).pack(side="left", padx=(0, 5))

        tk.Button(toolbar, text="🔄 刷新",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_admins).pack(side="left")

        self.admins_count = tk.Label(toolbar, text="",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=C["bg"], fg=C["text3"])
        self.admins_count.pack(side="right")

        tree_frame = tk.Frame(tab, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("username", "display_name", "password", "permissions", "max_days",
                "status", "last_ip", "ip_changes", "last_login")
        self.admins_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                         selectmode="browse", height=12)

        self.admins_tree.heading("username", text="用户名")
        self.admins_tree.heading("display_name", text="显示名")
        self.admins_tree.heading("password", text="密码")
        self.admins_tree.heading("permissions", text="权限")
        self.admins_tree.heading("max_days", text="最大天数")
        self.admins_tree.heading("status", text="状态")
        self.admins_tree.heading("last_ip", text="当前IP")
        self.admins_tree.heading("ip_changes", text="月换IP", anchor="center")
        self.admins_tree.heading("last_login", text="最后登录")

        self.admins_tree.column("username", width=90)
        self.admins_tree.column("display_name", width=80)
        self.admins_tree.column("password", width=90)
        self.admins_tree.column("permissions", width=160)
        self.admins_tree.column("max_days", width=60, anchor="center")
        self.admins_tree.column("status", width=60, anchor="center")
        self.admins_tree.column("last_ip", width=110)
        self.admins_tree.column("ip_changes", width=60, anchor="center")
        self.admins_tree.column("last_login", width=115)

        self._apply_tree_style()

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.admins_tree.yview)
        self.admins_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.admins_tree.pack(fill="both", expand=True)

        self.admins_tree.tag_configure("active", foreground=C["green"])
        self.admins_tree.tag_configure("inactive", foreground=C["red"])

        # 右键菜单
        self.admins_ctx_menu = tk.Menu(self, tearoff=0,
                                        bg=C["bg2"], fg=C["text"], activebackground=C["bg3"],
                                        activeforeground=C["accent"], font=("Microsoft YaHei UI", 9))
        self.admins_ctx_menu.add_command(label="📋 查看IP登录记录", command=self._show_admin_ip_logs)
        self.admins_ctx_menu.add_command(label="📋 复制密码", command=self._copy_admin_password)

        self.admins_tree.bind("<Button-3>", self._on_admins_right_click)

        btn_bar = tk.Frame(tab, bg=C["bg"])
        btn_bar.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btn_bar, text="✏️ 编辑权限",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_orange"], fg=C["white"], relief="flat",
                  activebackground=C["btn_orange_h"], cursor="hand2",
                  padx=8, command=self._show_edit_admin_dialog).pack(side="left", padx=(0, 5))

        tk.Button(btn_bar, text="🔒 禁用/启用",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._toggle_admin_active).pack(side="left", padx=(0, 5))

        tk.Button(btn_bar, text="🔑 重置密码",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._reset_admin_password).pack(side="left", padx=(0, 5))

        tk.Button(btn_bar, text="🗑️ 删除",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_danger"], fg=C["white"], relief="flat",
                  activebackground=C["btn_danger_h"], cursor="hand2",
                  padx=8, command=self._delete_admin).pack(side="right")

    # ═══════════════════════════════════════════════════
    #  Tab 2: 用户管理
    # ═══════════════════════════════════════════════════

    def _build_users_tab(self):
        tab = self.tab_users

        top = tk.Frame(tab, bg=C["bg"])
        top.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        search_bar = tk.Frame(top, bg=C["bg"])
        search_bar.pack(fill="x", pady=(0, 5))

        tk.Label(search_bar, text="🔍", font=("Segoe UI Emoji", 12),
                 bg=C["bg"], fg=C["text2"]).pack(side="left")
        self.user_search_var = tk.StringVar()
        self.user_search_var.trace_add("write", lambda *_: self._filter_users())
        tk.Entry(search_bar, textvariable=self.user_search_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 10), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", fill="x", expand=True, padx=5)

        tk.Button(search_bar, text="刷新",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_users).pack(side="right")

        self.users_count = tk.Label(search_bar, text="",
                                     font=("Microsoft YaHei UI", 9),
                                     bg=C["bg"], fg=C["text3"])
        self.users_count.pack(side="right", padx=10)

        tree_frame = tk.Frame(top, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True)

        cols = ("username", "password", "status", "remaining", "last_ip", "ip_changes", "created", "heartbeat")
        self.users_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                        selectmode="browse", height=12)

        self.users_tree.heading("username", text="用户名")
        self.users_tree.heading("password", text="密码")
        self.users_tree.heading("status", text="状态", anchor="center")
        self.users_tree.heading("remaining", text="剩余时长")
        self.users_tree.heading("last_ip", text="当前IP")
        self.users_tree.heading("ip_changes", text="月换IP", anchor="center")
        self.users_tree.heading("created", text="注册时间")
        self.users_tree.heading("heartbeat", text="最后活跃")

        self.users_tree.column("username", width=90)
        self.users_tree.column("password", width=90)
        self.users_tree.column("status", width=60, anchor="center")
        self.users_tree.column("remaining", width=100)
        self.users_tree.column("last_ip", width=110)
        self.users_tree.column("ip_changes", width=60, anchor="center")
        self.users_tree.column("created", width=115)
        self.users_tree.column("heartbeat", width=115)

        self.users_tree.tag_configure("active", foreground=C["green"])
        self.users_tree.tag_configure("expired", foreground=C["red"])
        self.users_tree.tag_configure("banned", foreground=C["text3"])
        self.users_tree.tag_configure("warning", foreground=C["orange"])

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.users_tree.yview)
        self.users_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.users_tree.pack(fill="both", expand=True)

        # 右键菜单
        self.users_ctx_menu = tk.Menu(self, tearoff=0,
                                       bg=C["bg2"], fg=C["text"], activebackground=C["bg3"],
                                       activeforeground=C["accent"], font=("Microsoft YaHei UI", 9))
        self.users_ctx_menu.add_command(label="📋 查看IP登录记录", command=self._show_user_ip_logs)
        self.users_ctx_menu.add_command(label="📋 复制密码", command=self._copy_user_password)

        self.users_tree.bind("<Button-3>", self._on_users_right_click)

        btn_bar = tk.Frame(tab, bg=C["bg"])
        btn_bar.pack(fill="x", padx=10, pady=(0, 5))

        recharge_frame = tk.Frame(btn_bar, bg=C["bg"])
        recharge_frame.pack(side="left")

        tk.Label(recharge_frame, text="天数:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text2"]).pack(side="left")
        self.user_days_var = tk.StringVar(value="30")
        tk.Entry(recharge_frame, textvariable=self.user_days_var,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat", width=6,
                 highlightthickness=1, highlightbackground=C["input_bd"],
                 highlightcolor=C["accent"]).pack(side="left", padx=5)

        for text, days in [("1天", 1), ("7天", 7), ("30天", 30), ("90天", 90), ("365天", 365)]:
            tk.Button(recharge_frame, text=text,
                      font=("Microsoft YaHei UI", 8),
                      bg=C["btn_default"], fg=C["text"], relief="flat",
                      activebackground=C["btn_default_h"], cursor="hand2",
                      padx=4, command=lambda d=days: self.user_days_var.set(str(d))
                      ).pack(side="left", padx=1)

        tk.Button(recharge_frame, text="✅ 充值",
                  font=("Microsoft YaHei UI", 9, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  activebackground=C["btn_primary_h"], cursor="hand2",
                  padx=8, command=self._do_recharge).pack(side="left", padx=(8, 0))

        tk.Button(btn_bar, text="✅ 解封",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["green"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=6, command=self._do_unban).pack(side="right", padx=(3, 0))

        tk.Button(btn_bar, text="⛔ 封禁",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_danger"], fg=C["white"], relief="flat",
                  activebackground=C["btn_danger_h"], cursor="hand2",
                  padx=6, command=self._do_ban).pack(side="right", padx=(0, 3))

    # ═══════════════════════════════════════════════════
    #  Tab 3: 充值Key（含归档操作 + 客户信息）
    # ═══════════════════════════════════════════════════

    def _build_keys_tab(self):
        tab = self.tab_keys

        toolbar = tk.Frame(tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(toolbar, text="🔄 刷新",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_keys).pack(side="left")

        # 归档操作按钮
        tk.Button(toolbar, text="📦 归档（确认到账）",
                  font=("Microsoft YaHei UI", 9, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  activebackground=C["btn_primary_h"], cursor="hand2",
                  padx=8, command=self._do_archive_key).pack(side="left", padx=(10, 3))

        tk.Button(toolbar, text="↩️ 取消归档",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._do_unarchive_key).pack(side="left", padx=(0, 10))

        # 筛选
        self.key_filter_var = tk.StringVar(value="all")
        for val, text in [("all", "全部"), ("unused", "未使用"), ("used", "已使用"),
                          ("unarchived", "待归档"), ("archived", "已归档"), ("revoked", "已撤销")]:
            tk.Radiobutton(toolbar, text=text, variable=self.key_filter_var, value=val,
                           font=("Microsoft YaHei UI", 9),
                           bg=C["bg"], fg=C["text2"], selectcolor=C["bg3"],
                           activebackground=C["bg"], activeforeground=C["accent"],
                           indicatoron=0, relief="flat", padx=8, pady=2,
                           command=self._refresh_keys).pack(side="left", padx=2)

        self.keys_count = tk.Label(toolbar, text="",
                                    font=("Microsoft YaHei UI", 9),
                                    bg=C["bg"], fg=C["text3"])
        self.keys_count.pack(side="right")

        # Treeview（含客户信息 + 归档状态）
        tree_frame = tk.Frame(tab, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("key_code", "days", "created_by", "status", "used_by",
                "wechat", "phone", "remark", "archive", "created_at")
        self.keys_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                       selectmode="browse", height=15)

        self.keys_tree.heading("key_code", text="充值Key")
        self.keys_tree.heading("days", text="天数", anchor="center")
        self.keys_tree.heading("created_by", text="创建者")
        self.keys_tree.heading("status", text="状态", anchor="center")
        self.keys_tree.heading("used_by", text="使用者")
        self.keys_tree.heading("wechat", text="微信号")
        self.keys_tree.heading("phone", text="手机号")
        self.keys_tree.heading("remark", text="备注")
        self.keys_tree.heading("archive", text="归档", anchor="center")
        self.keys_tree.heading("created_at", text="创建时间")

        self.keys_tree.column("key_code", width=155)
        self.keys_tree.column("days", width=45, anchor="center")
        self.keys_tree.column("created_by", width=80)
        self.keys_tree.column("status", width=55, anchor="center")
        self.keys_tree.column("used_by", width=80)
        self.keys_tree.column("wechat", width=100)
        self.keys_tree.column("phone", width=100)
        self.keys_tree.column("remark", width=120)
        self.keys_tree.column("archive", width=55, anchor="center")
        self.keys_tree.column("created_at", width=115)

        self.keys_tree.tag_configure("unused", foreground=C["green"])
        self.keys_tree.tag_configure("used", foreground=C["text2"])
        self.keys_tree.tag_configure("archived", foreground=C["purple"])
        self.keys_tree.tag_configure("unarchived", foreground=C["orange"])
        self.keys_tree.tag_configure("revoked", foreground=C["red"])

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.keys_tree.yview)
        self.keys_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.keys_tree.pack(fill="both", expand=True)

        # 右键菜单
        self.keys_ctx_menu = tk.Menu(self, tearoff=0,
                                      bg=C["bg2"], fg=C["text"], activebackground=C["bg3"],
                                      activeforeground=C["accent"], font=("Microsoft YaHei UI", 9))
        self.keys_ctx_menu.add_command(label="🚫 撤销此Key（扣回时长）", command=self._do_revoke_key)
        self.keys_ctx_menu.add_separator()
        self.keys_ctx_menu.add_command(label="📦 归档（确认到账）", command=self._do_archive_key)
        self.keys_ctx_menu.add_command(label="↩️ 取消归档", command=self._do_unarchive_key)

        self.keys_tree.bind("<Button-3>", self._on_keys_right_click)

    # ═══════════════════════════════════════════════════
    #  Tab 4: 操作日志
    # ═══════════════════════════════════════════════════

    def _build_logs_tab(self):
        tab = self.tab_logs

        toolbar = tk.Frame(tab, bg=C["bg"])
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(toolbar, text="🔄 刷新",
                  font=("Microsoft YaHei UI", 9),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=8, command=self._refresh_logs).pack(side="left")

        tree_frame = tk.Frame(tab, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("time", "admin", "action", "target", "detail")
        self.logs_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                       selectmode="browse", height=18)

        self.logs_tree.heading("time", text="时间")
        self.logs_tree.heading("admin", text="操作者")
        self.logs_tree.heading("action", text="操作")
        self.logs_tree.heading("target", text="目标")
        self.logs_tree.heading("detail", text="详情")

        self.logs_tree.column("time", width=130)
        self.logs_tree.column("admin", width=100)
        self.logs_tree.column("action", width=100)
        self.logs_tree.column("target", width=100)
        self.logs_tree.column("detail", width=400)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.logs_tree.yview)
        self.logs_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.logs_tree.pack(fill="both", expand=True)

    # ═══════════════════════════════════════════════════
    #  Treeview 样式
    # ═══════════════════════════════════════════════════

    def _apply_tree_style(self):
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
        style.map("Treeview.Heading",
                  background=[("active", C["bg3"])])

    # ═══════════════════════════════════════════════════
    #  连接
    # ═══════════════════════════════════════════════════

    def _connect(self):
        server = self.server_var.get().strip().rstrip("/")
        key = self.key_var.get().strip()

        if not server:
            messagebox.showwarning("提示", "请输入服务器地址")
            return
        if not key:
            messagebox.showwarning("提示", "请输入超级管理员密钥")
            return

        self.api = SuperAdminAPI(server, key)
        self.conn_btn.configure(state="disabled", text="连接中...")
        self._set_status("正在连接服务器...")

        def _do():
            result = self.api.health()
            self.after(0, lambda: self._on_connect(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_connect(self, result):
        self.conn_btn.configure(state="normal", text="连接")
        if result.get("ok"):
            test = self.api.list_admins()
            if test.get("ok") or test.get("ok") is None:
                self.conn_status.configure(text="● 已连接", fg=C["green"])
                self._set_status("连接成功，正在加载数据...")
                self._refresh_all()
            else:
                self.conn_status.configure(text="● 密钥错误", fg=C["red"])
                self._set_status(f"密钥验证失败: {test.get('error', '')}")
                messagebox.showerror("连接失败", "超级管理员密钥不正确")
        else:
            self.conn_status.configure(text="● 连接失败", fg=C["red"])
            self._set_status(f"连接失败: {result.get('error', '')}")
            messagebox.showerror("连接失败", result.get("error", "无法连接服务器"))

    def _refresh_all(self):
        self._refresh_admins()
        self._refresh_users()
        self._refresh_keys()
        self._refresh_logs()

    # ═══════════════════════════════════════════════════
    #  管理员操作
    # ═══════════════════════════════════════════════════

    def _refresh_admins(self):
        if not self.api:
            return

        def _do():
            result = self.api.list_admins()
            self.after(0, lambda: self._on_admins_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_admins_loaded(self, result):
        if not result.get("ok"):
            self._set_status(f"加载管理员列表失败: {result.get('error', '')}")
            return

        self._admins_data = result.get("admins", [])
        for item in self.admins_tree.get_children():
            self.admins_tree.delete(item)

        for a in self._admins_data:
            perms = []
            if a["can_generate_key"]:
                perms.append("生成Key")
            if a["can_ban"]:
                perms.append("封禁")
            if a["can_view_users"]:
                perms.append("查看用户")
            perm_text = " / ".join(perms) if perms else "无权限"

            status = "🟢 启用" if a["is_active"] else "🔴 禁用"
            tag = "active" if a["is_active"] else "inactive"
            max_days = str(a["max_recharge_days"]) + "天" if a["max_recharge_days"] > 0 else "不限"
            last_login = self._fmt_time(a.get("last_login", 0))

            last_ip = a.get("last_ip", "") or "—"
            ip_changes = a.get("ip_change_count", 0)
            ip_text = str(ip_changes) if ip_changes > 0 else "0"

            self.admins_tree.insert("", "end", iid=str(a["id"]),
                                     values=(a["username"], a["display_name"],
                                             a.get("plain_password", "—"),
                                             perm_text, max_days, status,
                                             last_ip, ip_text, last_login),
                                     tags=(tag,))

        self.admins_count.configure(text=f"共 {len(self._admins_data)} 个管理员")

    def _get_selected_admin(self) -> dict | None:
        sel = self.admins_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个管理员")
            return None
        admin_id = int(sel[0])
        return next((a for a in self._admins_data if a["id"] == admin_id), None)

    def _show_create_admin_dialog(self):
        if not self.api:
            messagebox.showwarning("提示", "请先连接服务器")
            return

        dlg = tk.Toplevel(self)
        dlg.title("创建子管理员")
        dlg.geometry("400x420")
        dlg.configure(bg=C["bg"])
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="创建子管理员", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=C["bg"], fg=C["accent"]).pack(pady=(15, 10))

        fields_frame = tk.Frame(dlg, bg=C["bg"])
        fields_frame.pack(fill="x", padx=30)

        vars_ = {}
        for label, key, show in [("用户名:", "username", None), ("密码:", "password", "●"),
                                  ("显示名:", "display_name", None)]:
            row = tk.Frame(fields_frame, bg=C["bg"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=("Microsoft YaHei UI", 9),
                     bg=C["bg"], fg=C["text"], width=8, anchor="e").pack(side="left")
            v = tk.StringVar()
            vars_[key] = v
            kw = {"show": show} if show else {}
            tk.Entry(row, textvariable=v, bg=C["input_bg"], fg=C["text"],
                     insertbackground=C["text"], font=("Microsoft YaHei UI", 10),
                     relief="flat", highlightthickness=1, highlightbackground=C["input_bd"],
                     highlightcolor=C["accent"], **kw).pack(side="left", fill="x", expand=True, padx=5)

        perm_frame = tk.LabelFrame(dlg, text=" 权限 ", font=("Microsoft YaHei UI", 10),
                                    bg=C["bg"], fg=C["text"], relief="groove")
        perm_frame.pack(fill="x", padx=30, pady=10)

        perm_vars = {}
        for key, label in [("can_generate_key", "生成充值Key"),
                           ("can_ban", "封禁/解封用户"),
                           ("can_view_users", "查看用户列表")]:
            v = tk.BooleanVar(value=True)
            perm_vars[key] = v
            tk.Checkbutton(perm_frame, text=label, variable=v,
                           bg=C["bg"], fg=C["text"], selectcolor=C["bg3"],
                           activebackground=C["bg"], font=("Microsoft YaHei UI", 9)
                           ).pack(anchor="w", padx=10, pady=2)

        max_days_frame = tk.Frame(perm_frame, bg=C["bg"])
        max_days_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(max_days_frame, text="单Key最大天数 (0=不限):",
                 font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text2"]).pack(side="left")
        max_days_var = tk.StringVar(value="0")
        tk.Entry(max_days_frame, textvariable=max_days_var, width=6,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"]
                 ).pack(side="left", padx=5)

        def _create():
            data = {
                "username": vars_["username"].get().strip(),
                "password": vars_["password"].get(),
                "display_name": vars_["display_name"].get().strip(),
                "can_generate_key": perm_vars["can_generate_key"].get(),
                "can_ban": perm_vars["can_ban"].get(),
                "can_view_users": perm_vars["can_view_users"].get(),
                "max_recharge_days": int(max_days_var.get() or 0),
            }

            def _do():
                result = self.api.create_admin(data)
                self.after(0, lambda: self._on_admin_created(result, dlg))

            threading.Thread(target=_do, daemon=True).start()

        tk.Button(dlg, text="✅ 创建", font=("Microsoft YaHei UI", 11, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  activebackground=C["btn_primary_h"], cursor="hand2",
                  padx=20, pady=4, command=_create).pack(pady=10)

    def _on_admin_created(self, result, dlg):
        if result.get("ok"):
            messagebox.showinfo("成功", result.get("message", "创建成功"))
            dlg.destroy()
            self._refresh_admins()
        else:
            messagebox.showerror("失败", result.get("error", "创建失败"))

    def _show_edit_admin_dialog(self):
        admin = self._get_selected_admin()
        if not admin:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"编辑管理员: {admin['username']}")
        dlg.geometry("400x350")
        dlg.configure(bg=C["bg"])
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text=f"编辑 {admin['display_name']}",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 bg=C["bg"], fg=C["accent"]).pack(pady=(15, 10))

        name_frame = tk.Frame(dlg, bg=C["bg"])
        name_frame.pack(fill="x", padx=30, pady=3)
        tk.Label(name_frame, text="显示名:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text"], width=8, anchor="e").pack(side="left")
        display_var = tk.StringVar(value=admin["display_name"])
        tk.Entry(name_frame, textvariable=display_var, bg=C["input_bg"], fg=C["text"],
                 insertbackground=C["text"], font=("Microsoft YaHei UI", 10), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"]).pack(side="left", fill="x", expand=True, padx=5)

        perm_frame = tk.LabelFrame(dlg, text=" 权限 ", font=("Microsoft YaHei UI", 10),
                                    bg=C["bg"], fg=C["text"], relief="groove")
        perm_frame.pack(fill="x", padx=30, pady=10)

        perm_vars = {}
        for key, label in [("can_generate_key", "生成充值Key"),
                           ("can_ban", "封禁/解封用户"),
                           ("can_view_users", "查看用户列表")]:
            v = tk.BooleanVar(value=admin.get(key, True))
            perm_vars[key] = v
            tk.Checkbutton(perm_frame, text=label, variable=v,
                           bg=C["bg"], fg=C["text"], selectcolor=C["bg3"],
                           activebackground=C["bg"], font=("Microsoft YaHei UI", 9)
                           ).pack(anchor="w", padx=10, pady=2)

        max_frame = tk.Frame(perm_frame, bg=C["bg"])
        max_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(max_frame, text="单Key最大天数 (0=不限):",
                 font=("Microsoft YaHei UI", 9), bg=C["bg"], fg=C["text2"]).pack(side="left")
        max_var = tk.StringVar(value=str(admin["max_recharge_days"]))
        tk.Entry(max_frame, textvariable=max_var, width=6,
                 bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                 font=("Microsoft YaHei UI", 9), relief="flat").pack(side="left", padx=5)

        def _save():
            data = {
                "display_name": display_var.get().strip(),
                "can_generate_key": perm_vars["can_generate_key"].get(),
                "can_ban": perm_vars["can_ban"].get(),
                "can_view_users": perm_vars["can_view_users"].get(),
                "max_recharge_days": int(max_var.get() or 0),
            }

            def _do():
                result = self.api.update_admin(admin["username"], data)
                self.after(0, lambda: self._on_admin_updated(result, dlg))

            threading.Thread(target=_do, daemon=True).start()

        tk.Button(dlg, text="✅ 保存", font=("Microsoft YaHei UI", 11, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  activebackground=C["btn_primary_h"], cursor="hand2",
                  padx=20, pady=4, command=_save).pack(pady=10)

    def _on_admin_updated(self, result, dlg):
        if result.get("ok"):
            messagebox.showinfo("成功", result.get("message", "更新成功"))
            dlg.destroy()
            self._refresh_admins()
        else:
            messagebox.showerror("失败", result.get("error", "更新失败"))

    def _toggle_admin_active(self):
        admin = self._get_selected_admin()
        if not admin:
            return
        new_state = not admin["is_active"]
        action = "启用" if new_state else "禁用"
        if not messagebox.askyesno("确认", f"确定要{action}管理员 {admin['display_name']}？"):
            return

        def _do():
            result = self.api.update_admin(admin["username"], {"is_active": new_state})
            self.after(0, lambda: self._on_toggle_result(result, action))

        threading.Thread(target=_do, daemon=True).start()

    def _on_toggle_result(self, result, action):
        if result.get("ok"):
            self._set_status(f"✅ {action}成功")
            self._refresh_admins()
        else:
            messagebox.showerror("失败", result.get("error", "操作失败"))

    def _reset_admin_password(self):
        admin = self._get_selected_admin()
        if not admin:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"重置密码: {admin['username']}")
        dlg.geometry("350x150")
        dlg.configure(bg=C["bg"])
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="新密码:", font=("Microsoft YaHei UI", 10),
                 bg=C["bg"], fg=C["text"]).pack(pady=(20, 5))
        pw_var = tk.StringVar()
        tk.Entry(dlg, textvariable=pw_var, show="●", bg=C["input_bg"], fg=C["text"],
                 insertbackground=C["text"], font=("Microsoft YaHei UI", 10), relief="flat",
                 highlightthickness=1, highlightbackground=C["input_bd"]).pack(padx=30, fill="x")

        def _reset():
            pw = pw_var.get()
            if len(pw) < 6:
                messagebox.showwarning("提示", "密码至少6个字符")
                return

            def _do():
                result = self.api.update_admin(admin["username"], {"password": pw})
                self.after(0, lambda: (
                    messagebox.showinfo("成功", "密码已重置") if result.get("ok")
                    else messagebox.showerror("失败", result.get("error", "")),
                    dlg.destroy() if result.get("ok") else None,
                ))

            threading.Thread(target=_do, daemon=True).start()

        tk.Button(dlg, text="确认重置", font=("Microsoft YaHei UI", 10, "bold"),
                  bg=C["btn_primary"], fg=C["white"], relief="flat",
                  cursor="hand2", padx=15, command=_reset).pack(pady=10)

    def _delete_admin(self):
        admin = self._get_selected_admin()
        if not admin:
            return
        if not messagebox.askyesno("确认删除",
                                    f"确定要删除管理员 {admin['display_name']} ({admin['username']}) 吗？\n\n此操作不可撤销。"):
            return

        def _do():
            result = self.api.delete_admin(admin["username"])
            self.after(0, lambda: self._on_delete_result(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_delete_result(self, result):
        if result.get("ok"):
            self._set_status("✅ 管理员已删除")
            self._refresh_admins()
        else:
            messagebox.showerror("失败", result.get("error", "删除失败"))

    # ═══════════════════════════════════════════════════
    #  用户操作
    # ═══════════════════════════════════════════════════

    def _refresh_users(self):
        if not self.api:
            return

        def _do():
            result = self.api.list_users()
            self.after(0, lambda: self._on_users_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_users_loaded(self, result):
        if not result.get("ok"):
            return
        self._users_data = result.get("users", [])
        self._filter_users()
        total = len(self._users_data)
        active = sum(1 for u in self._users_data if not u["is_expired"] and not u["is_banned"])
        self.users_count.configure(text=f"共 {total} | 正常 {active}")

    def _filter_users(self):
        keyword = self.user_search_var.get().strip().lower()
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)

        for u in self._users_data:
            if keyword and keyword not in u["username"].lower():
                continue

            if u["is_banned"]:
                status_text, tag = "⛔ 封禁", "banned"
            elif u["is_expired"]:
                status_text, tag = "🔴 过期", "expired"
            elif u.get("remaining_seconds", 0) < 86400:
                status_text, tag = "🟡 即将", "warning"
            else:
                status_text, tag = "🟢 正常", "active"

            last_ip = u.get("last_ip", "") or "—"
            ip_changes = u.get("ip_change_count", 0)
            ip_text = str(ip_changes) if ip_changes > 0 else "0"

            self.users_tree.insert("", "end", iid=str(u["id"]),
                                    values=(u["username"],
                                            u.get("plain_password", "—"),
                                            status_text,
                                            u.get("remaining_text", "—"),
                                            last_ip, ip_text,
                                            self._fmt_time(u.get("created_at", 0)),
                                            self._fmt_time(u.get("last_heartbeat", 0))),
                                    tags=(tag,))

    def _get_selected_username(self) -> str | None:
        sel = self.users_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个用户")
            return None
        user_id = int(sel[0])
        user = next((u for u in self._users_data if u["id"] == user_id), None)
        return user["username"] if user else None

    def _do_recharge(self):
        username = self._get_selected_username()
        if not username:
            return
        try:
            days = float(self.user_days_var.get().strip())
            if days <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "请输入有效天数")
            return

        seconds = int(days * 86400)
        if not messagebox.askyesno("确认充值", f"确定给 [{username}] 充值 {days} 天？"):
            return

        def _do():
            result = self.api.recharge(username, seconds, "超级管理员直接充值")
            self.after(0, lambda: self._on_recharge_result(result, username, days))

        threading.Thread(target=_do, daemon=True).start()

    def _on_recharge_result(self, result, username, days):
        if result.get("ok"):
            self._set_status(f"✅ {username} +{days}天 → 剩余 {result.get('remaining_text', '?')}")
            messagebox.showinfo("充值成功",
                                f"用户: {username}\n充值: +{days} 天\n剩余: {result.get('remaining_text', '?')}")
            self._refresh_users()
        else:
            messagebox.showerror("充值失败", result.get("error", "未知错误"))

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

    # ── 管理员右键菜单 ──

    def _on_admins_right_click(self, event):
        item = self.admins_tree.identify_row(event.y)
        if item:
            self.admins_tree.selection_set(item)
            self.admins_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_admin_password(self):
        admin = self._get_selected_admin()
        if not admin:
            return
        pw = admin.get("plain_password", "")
        if pw and pw != "(旧账号无记录)":
            self.clipboard_clear()
            self.clipboard_append(pw)
            self._set_status(f"📋 已复制 {admin['display_name']} 的密码")
        else:
            self._set_status("该管理员无明文密码记录")

    def _show_admin_ip_logs(self):
        admin = self._get_selected_admin()
        if not admin:
            return
        if not self.api:
            return

        def _do():
            result = self.api.get_admin_ip_logs(admin["username"])
            self.after(0, lambda: self._show_ip_logs_dialog(
                f"管理员 [{admin['display_name']}] IP登录记录", result))

        threading.Thread(target=_do, daemon=True).start()

    # ── 用户右键菜单 ──

    def _on_users_right_click(self, event):
        item = self.users_tree.identify_row(event.y)
        if item:
            self.users_tree.selection_set(item)
            self.users_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_user_password(self):
        username = self._get_selected_username()
        if not username:
            return
        user = next((u for u in self._users_data if u["username"] == username), None)
        if not user:
            return
        pw = user.get("plain_password", "")
        if pw and pw != "(旧账号无记录)":
            self.clipboard_clear()
            self.clipboard_append(pw)
            self._set_status(f"📋 已复制 {username} 的密码")
        else:
            self._set_status("该用户无明文密码记录")

    def _show_user_ip_logs(self):
        username = self._get_selected_username()
        if not username:
            return
        if not self.api:
            return
        user = next((u for u in self._users_data if u["username"] == username), None)
        if not user:
            return

        def _do():
            result = self.api.get_user_ip_logs(user["id"])
            self.after(0, lambda: self._show_ip_logs_dialog(
                f"用户 [{username}] IP登录记录", result))

        threading.Thread(target=_do, daemon=True).start()

    # ── IP 记录详情弹窗 ──

    def _show_ip_logs_dialog(self, title, result):
        if not result.get("ok"):
            messagebox.showerror("加载失败", result.get("error", ""))
            return

        logs = result.get("ip_logs", [])

        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.geometry("550x450")
        dlg.configure(bg=C["bg"])
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text=title, font=("Microsoft YaHei UI", 13, "bold"),
                 bg=C["bg"], fg=C["accent"]).pack(pady=(15, 5))

        # 统计
        ips = set(log["ip"] for log in logs if log.get("ip"))
        tk.Label(dlg, text=f"共 {len(logs)} 次登录 | {len(ips)} 个不同IP | 换IP {max(0, len(ips)-1)} 次",
                 font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text2"]).pack(pady=(0, 8))

        tree_frame = tk.Frame(dlg, bg=C["border"], bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        cols = ("time", "ip", "machine_id")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            selectmode="browse", height=15)

        tree.heading("time", text="登录时间")
        tree.heading("ip", text="IP地址")
        tree.heading("machine_id", text="机器ID")

        tree.column("time", width=140)
        tree.column("ip", width=140)
        tree.column("machine_id", width=220)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        prev_ip = None
        for log in logs:
            ip = log.get("ip", "—")
            tag = ""
            if prev_ip is not None and ip != prev_ip:
                tag = "ip_changed"
            prev_ip = ip

            tree.insert("", "end",
                        values=(self._fmt_time(log["created_at"]),
                                ip,
                                log.get("machine_id", "—") or "—"),
                        tags=(tag,) if tag else ())

        tree.tag_configure("ip_changed", foreground=C["red"])

    # ═══════════════════════════════════════════════════
    #  充值Key（含归档操作）
    # ═══════════════════════════════════════════════════

    def _refresh_keys(self):
        if not self.api:
            return
        status = self.key_filter_var.get()

        def _do():
            result = self.api.list_keys(status=status)
            self.after(0, lambda: self._on_keys_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_keys_loaded(self, result):
        if not result.get("ok"):
            return

        self._keys_data = result.get("keys", [])
        for item in self.keys_tree.get_children():
            self.keys_tree.delete(item)

        for k in self._keys_data:
            if k.get("is_revoked"):
                status = "🚫 撤销"
                tag = "revoked"
            elif k["is_archived"]:
                status = "📦 归档"
                tag = "archived"
            elif k["is_used"]:
                status = "✅ 已用"
                tag = "unarchived"  # 已用但未归档 → 橙色提醒
            else:
                status = "🟢 可用"
                tag = "unused"

            if k.get("is_revoked"):
                archive_text = "🚫"
            elif k["is_archived"]:
                archive_text = "✅"
            elif k["is_used"]:
                archive_text = "⏳"
            else:
                archive_text = "—"

            self.keys_tree.insert("", "end", iid=str(k["id"]),
                                   values=(k["key_code"], k["days_text"],
                                           k["created_by"], status,
                                           k["used_by"] or "—",
                                           k.get("wechat", ""),
                                           k.get("phone", ""),
                                           k.get("remark", ""),
                                           archive_text,
                                           self._fmt_time(k["created_at"])),
                                   tags=(tag,))

        self.keys_count.configure(text=f"共 {len(self._keys_data)} 个Key")

    def _get_selected_key(self) -> dict | None:
        sel = self.keys_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个充值Key")
            return None
        key_id = int(sel[0])
        return next((k for k in self._keys_data if k["id"] == key_id), None)

    def _do_archive_key(self):
        key = self._get_selected_key()
        if not key:
            return
        if not key["is_used"]:
            messagebox.showwarning("提示", "该Key还未被使用，无需归档")
            return
        if key["is_archived"]:
            messagebox.showinfo("提示", "该Key已经归档")
            return

        info = f"Key: {key['key_code']}\n天数: {key['days_text']}\n使用者: {key['used_by']}"
        if key.get("wechat"):
            info += f"\n微信: {key['wechat']}"
        if key.get("phone"):
            info += f"\n手机: {key['phone']}"
        if key.get("remark"):
            info += f"\n备注: {key['remark']}"

        if not messagebox.askyesno("确认归档（确认到账）", f"确认以下Key已到账？\n\n{info}"):
            return

        def _do():
            result = self.api.archive_key(key["id"], True)
            self.after(0, lambda: self._on_archive_result(result, "归档"))

        threading.Thread(target=_do, daemon=True).start()

    def _do_unarchive_key(self):
        key = self._get_selected_key()
        if not key:
            return
        if not key["is_archived"]:
            messagebox.showwarning("提示", "该Key未归档")
            return

        def _do():
            result = self.api.archive_key(key["id"], False)
            self.after(0, lambda: self._on_archive_result(result, "取消归档"))

        threading.Thread(target=_do, daemon=True).start()

    def _on_archive_result(self, result, action):
        if result.get("ok"):
            self._set_status(f"✅ {action}成功")
            self._refresh_keys()
        else:
            messagebox.showerror(f"{action}失败", result.get("error", ""))

    def _on_keys_right_click(self, event):
        """右键菜单 — 选中行并弹出"""
        item = self.keys_tree.identify_row(event.y)
        if item:
            self.keys_tree.selection_set(item)
            self.keys_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _do_revoke_key(self):
        """撤销Key — 扣回用户时长并标记为已撤销"""
        key = self._get_selected_key()
        if not key:
            return
        if key.get("is_revoked"):
            messagebox.showinfo("提示", "该Key已被撤销")
            return

        # 构建确认信息
        info = f"Key: {key['key_code']}\n天数: {key['days_text']}\n创建者: {key['created_by']}"
        if key["is_used"]:
            info += f"\n使用者: {key['used_by']}"
            info += f"\n\n⚠️ 该Key已被使用，撤销后将扣回用户 [{key['used_by']}] 的 {key['days_text']} 时长！"
        else:
            info += "\n\n该Key尚未使用，撤销后该Key将被作废。"
        if key.get("wechat"):
            info += f"\n微信: {key['wechat']}"
        if key.get("phone"):
            info += f"\n手机: {key['phone']}"

        # 弹出输入撤销原因的对话框
        dlg = tk.Toplevel(self)
        dlg.title("撤销充值Key")
        dlg.geometry("450x320")
        dlg.configure(bg=C["bg"])
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="🚫 撤销充值Key", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=C["bg"], fg=C["red"]).pack(pady=(15, 5))

        info_label = tk.Label(dlg, text=info, font=("Microsoft YaHei UI", 9),
                              bg=C["bg"], fg=C["text"], justify="left", wraplength=400)
        info_label.pack(padx=20, pady=5, anchor="w")

        reason_frame = tk.Frame(dlg, bg=C["bg"])
        reason_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(reason_frame, text="撤销原因:", font=("Microsoft YaHei UI", 9),
                 bg=C["bg"], fg=C["text2"]).pack(anchor="w")
        reason_var = tk.StringVar(value="")
        reason_entry = tk.Entry(reason_frame, textvariable=reason_var,
                                bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
                                font=("Microsoft YaHei UI", 10), relief="flat",
                                highlightthickness=1, highlightbackground=C["input_bd"],
                                highlightcolor=C["accent"])
        reason_entry.pack(fill="x", pady=3)
        reason_entry.focus_set()

        btn_frame = tk.Frame(dlg, bg=C["bg"])
        btn_frame.pack(pady=15)

        def _confirm():
            reason = reason_var.get().strip()
            if not reason:
                messagebox.showwarning("提示", "请填写撤销原因")
                return

            def _do():
                result = self.api.revoke_key(key["id"], reason)
                self.after(0, lambda: self._on_revoke_result(result, dlg))

            threading.Thread(target=_do, daemon=True).start()

        tk.Button(btn_frame, text="🚫 确认撤销", font=("Microsoft YaHei UI", 10, "bold"),
                  bg=C["btn_danger"], fg=C["white"], relief="flat",
                  activebackground=C["btn_danger_h"], cursor="hand2",
                  padx=15, pady=3, command=_confirm).pack(side="left", padx=(0, 10))

        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei UI", 10),
                  bg=C["btn_default"], fg=C["text"], relief="flat",
                  activebackground=C["btn_default_h"], cursor="hand2",
                  padx=15, pady=3, command=dlg.destroy).pack(side="left")

    def _on_revoke_result(self, result, dlg):
        dlg.destroy()
        if result.get("ok"):
            msg = result.get("message", "撤销成功")
            if result.get("deducted"):
                msg += f"\n已扣回 {result['deducted_from']} 的 {result['deducted_text']}"
            self._set_status(f"✅ {msg}")
            messagebox.showinfo("撤销成功", msg)
            self._refresh_keys()
            self._refresh_users()
        else:
            messagebox.showerror("撤销失败", result.get("error", "未知错误"))

    # ═══════════════════════════════════════════════════
    #  操作日志
    # ═══════════════════════════════════════════════════

    def _refresh_logs(self):
        if not self.api:
            return

        def _do():
            result = self.api.get_logs()
            self.after(0, lambda: self._on_logs_loaded(result))

        threading.Thread(target=_do, daemon=True).start()

    def _on_logs_loaded(self, result):
        if not result.get("ok"):
            return

        for item in self.logs_tree.get_children():
            self.logs_tree.delete(item)

        for log in result.get("logs", []):
            self.logs_tree.insert("", "end",
                                   values=(self._fmt_time(log["created_at"]),
                                           log["admin_username"],
                                           log["action"],
                                           log["target"],
                                           log["detail"]))

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
        self.status_label.configure(text=text)

    def _tick_clock(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.configure(text=now)
        self.after(1000, self._tick_clock)


# ─── 入口 ────────────────────────────────────────────────

if __name__ == "__main__":
    app = SuperAdminTool()
    app.mainloop()
