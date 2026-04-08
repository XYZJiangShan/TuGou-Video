# 🐟 泥鳅视频工具箱 — 下载模块开发文档

> **面向对象**：其他 AI Agent / 开发者
> **最后更新**：2026-04-04
> **维护者**：Kai (AI) + S哥

---

## 一、项目总览

```
video-toolkit/
├── app.py                     # GUI 主程序（tkinter）
├── core/
│   ├── __init__.py            # 包初始化（仅注释）
│   ├── downloader.py          # ⭐ 视频下载核心模块（本文档重点）
│   └── deduplicator.py        # 视频去重引擎（146KB，独立模块）
├── downloads/                 # 默认下载目录
├── output/                    # 去重输出目录
├── assets/                    # 静态资源（混淆帧图片等）
├── tools/                     # 外部工具（mkvmerge等）
├── docs/                      # 文档目录
├── README.md
└── requirements.txt           # 依赖：requests, opencv-python, numpy, Pillow
```

**核心依赖**：`requests`（HTTP）、`socket`（DNS）、`re`/`json`（解析）

---

## 二、下载模块架构

### 文件：`core/downloader.py`（527行）

```
VideoDownloader (class)
│
├── __init__(save_dir)              # 初始化 session、UA headers、DNS缓存
│
├── 🔍 链接解析层
│   ├── extract_url_from_text()     # 从分享文本提取URL
│   └── detect_platform()          # 平台检测（抖音/快手/B站）
│
├── 🌐 网络请求层
│   ├── _resolve_and_cache()       # DNS解析+缓存
│   └── _get_with_dns_fallback()   # DNS容错GET（核心网络方法）
│
├── 🎬 抖音解析层
│   ├── _pick_best_quality()       # 最高清晰度选择（static method）
│   ├── _extract_video_from_html() # HTML页面视频URL提取
│   └── _douyin_download_info()    # 一站式解析入口
│
├── 📥 下载执行层
│   ├── _download_file()           # 通用下载引擎（多策略绕过防盗链）
│   └── download_douyin()          # 抖音下载完整流程
│
└── 🚪 统一入口
    └── download()                 # 自动检测平台 → 路由到对应下载方法
```

### 调用关系

```
download(url, filename, callback)
  ├── extract_url_from_text(url)
  ├── detect_platform(real_url)
  └── download_douyin(real_url, filename, callback)
        ├── _douyin_download_info(share_url)
        │     ├── _get_with_dns_fallback(url, headers, allow_redirects=True)
        │     ├── _extract_video_from_html(resp.text)
        │     │     └── _pick_best_quality(video_obj)  [static]
        │     ├── [fallback] iesdouyin分享页
        │     └── [fallback] douyin.com页面
        └── _download_file(video_url, save_path, callback, fallback_url)
              └── _get_with_dns_fallback(url, headers, stream=True)
```

---

## 三、关键方法详解

### 3.1 `_get_with_dns_fallback(url, headers, **kwargs)` — 第60行

> **DNS容错请求**，是整个下载器的网络基石。

**逻辑**：
1. 先正常 `session.get()`
2. 如果抛出 `ConnectionError` 且包含 DNS 解析失败关键词 →
3. 查 `known_ips` 字典（硬编码了 `www.iesdouyin.com` 和 `www.douyin.com` 的IP）
4. 如果没有已知IP → 用 `nslookup` 命令尝试解析
5. IP直连 + 手动处理重定向（最多10次）

**已知IP映射**（第75行）：
```python
known_ips = {
    "www.iesdouyin.com": "163.177.180.10",
    "www.douyin.com": "122.13.173.223",
}
```

⚠️ **注意**：这些IP可能过期，需要定期更新。

### 3.2 `_pick_best_quality(video_obj)` — 第158行（静态方法）

> **从抖音video JSON对象中选最高清晰度URL**

**三级优先策略**：
```
1. bit_rate 列表 → 按分辨率(宽×高)排序，选最高
2. download_addr → 通常是最高清下载地址
3. play_addr → 默认播放地址（可能只有720p）
```

**关键处理**：所有URL都做 `playwm → play` 替换（去水印）

**返回**：`(best_url, raw_url)` 或 `(None, None)`

### 3.3 `_extract_video_from_html(html_text)` — 第218行

> **从HTML页面提取视频URL和描述**

**三种提取方法**（按优先级）：

| 方法 | 目标 | 数据源 | 清晰度选择 |
|------|------|--------|-----------|
| A | `window._ROUTER_DATA` | JSON解析 → `loaderData` → `videoInfoRes` → `item_list` | ✅ 调用 `_pick_best_quality()` |
| B | `window.__RENDER_DATA__` | URL解码 → JSON → 递归搜索 `bit_rate`/`play_addr` | ✅ 递归搜索 |
| C | 正则兜底 | 直接匹配 `playApi`/`play_addr`/`download_addr` URL | ❌ 无法选清晰度 |

**返回**：`(video_url, description, raw_url)` 或 `(None, None, None)`

### 3.4 `_douyin_download_info(share_url)` — 第306行

> **一站式抖音链接解析**

**4步策略**：
```
Step 1: 请求短链接 → 跟随重定向 → 提取video_id
Step 2: 直接从重定向页面HTML提取视频URL（最快路径）
Step 3: [回退] 请求 iesdouyin.com/share/video/{video_id}
Step 4: [回退] 请求 douyin.com/video/{video_id}（PC端UA）
```

**video_id 提取**：
- 优先从URL路径 `/video/(\d+)` 匹配
- 兜底从HTML中 `"aweme_id":"(\d+)"` 匹配

### 3.5 `_download_file(url, save_path, callback, fallback_url)` — 第410行

> **通用文件下载引擎**

**防盗链绕过策略**（4种Headers组合）：
```python
方案1: 移动端UA + iesdouyin Referer
方案2: 移动端UA + douyin Referer
方案3: 移动端UA + 无Referer
方案4: PC端UA + douyin Referer
```

**URL尝试顺序**：
```
1. 无水印URL（/play/）
2. 原始URL（fallback_url，可能有水印）
3. 有水印URL（/playwm/）
```

**下载参数**：
- Chunk size: 64KB
- Stream模式
- 文件有效性验证: > 1KB

### 3.6 `download(url, filename, callback)` — 第492行

> **统一下载入口**

```python
def download(self, url, filename=None, callback=None):
    real_url = self.extract_url_from_text(url)
    platform = self.detect_platform(real_url)
    if platform == "douyin":
        return self.download_douyin(real_url, filename, callback)
    elif platform == "kuaishou":
        raise NotImplementedError("kuaishou download coming soon...")
    elif platform == "bilibili":
        raise NotImplementedError("bilibili download coming soon...")
```

---

## 四、GUI集成

### 文件：`app.py`（989行）

GUI通过 `VideoToolkitApp` 类集成下载功能。

### 4.1 单个下载（第780行 `_start_download`）

```python
def _start_download(self):
    url = self.url_entry.get("1.0", "end").strip()
    save_dir = self.download_dir_var.get()
    
    def do_download():  # 后台线程
        downloader = VideoDownloader(save_dir=save_dir)
        def callback(downloaded, total, percent, msg):
            # 更新进度条和状态标签（通过 root.after 线程安全更新）
            ...
        path = downloader.download(url, callback=callback)
    
    threading.Thread(target=do_download, daemon=True).start()
```

### 4.2 批量下载+去重（第906行 `_start_batch`）

```python
def _start_batch(self):
    urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
    
    def do_batch():  # 后台线程
        for idx, url in enumerate(urls):
            # 1. 下载
            downloader = VideoDownloader(save_dir=self.download_dir)
            dl_path = downloader.download(url, callback=dl_callback)
            
            # 2. 可选自动去重
            if auto_dedup and self.deduplicator:
                self.deduplicator.process(dl_path, dedup_path, preset=preset)
    
    threading.Thread(target=do_batch, daemon=True).start()
```

### 4.3 回调函数签名

```python
def callback(downloaded_bytes: int, total_bytes: int, percent: int, msg: str):
    """
    downloaded_bytes: 已下载字节数
    total_bytes: 总字节数（可能为0）
    percent: 0-100 进度百分比（20%起步，前20%留给链接解析）
    msg: 状态消息字符串
    """
```

---

## 五、平台检测逻辑

```python
def detect_platform(self, url):
    url_lower = url.lower()
    if any(k in url_lower for k in ["douyin", "iesdouyin", "v.douyin"]):
        return "douyin"
    elif any(k in url_lower for k in ["kuaishou", "gifshow", "v.kuaishou", "v.kwai"]):
        return "kuaishou"
    elif any(k in url_lower for k in ["bilibili", "b23.tv", "bili"]):
        return "bilibili"
    else:
        return "unknown"
```

---

## 六、已知问题 & 待开发

### ❌ 未实现
- **快手下载**：`NotImplementedError`
- **B站下载**：`NotImplementedError`

### ⚠️ 已知限制
1. **清晰度选择**：`_pick_best_quality` 已实现三级优先选择，但部分抖音API返回可能只有720p的 `play_addr`
2. **DNS硬编码IP**：`known_ips` 中的IP地址可能过期
3. **无异步支持**：全部同步 `requests`，批量下载是串行的
4. **无断点续传**：下载中断需要重新下载
5. **Cookie/登录**：目前不需要登录态，但某些视频可能需要

### 📋 改进方向
1. 增加快手/B站下载支持
2. 异步下载（aiohttp）
3. 断点续传
4. 代理支持
5. 下载历史记录

---

## 七、如何摘抄/复用代码

### 场景1：只需要下载功能

复制 `core/downloader.py` 整个文件，依赖仅 `requests`：

```python
from core.downloader import VideoDownloader

dl = VideoDownloader(save_dir="./downloads")
path = dl.download("https://v.douyin.com/xxx", callback=lambda d,t,p,m: print(f"{p}% {m}"))
print(f"Downloaded: {path}")
```

### 场景2：只需要URL解析（不下载）

```python
dl = VideoDownloader()
video_id, video_url, desc, raw_url = dl._douyin_download_info("分享链接文本")
print(f"Video ID: {video_id}")
print(f"Download URL: {video_url}")
print(f"Description: {desc}")
```

### 场景3：集成到自己的GUI

参考 `app.py` 第780-819行的 `_start_download` 方法：
- 在后台线程中调用 `downloader.download()`
- 通过回调函数更新UI
- 使用 `root.after()` 保证线程安全

---

## 八、代码索引速查

| 功能 | 文件 | 行号 | 方法/类 |
|------|------|------|---------|
| 下载器主类 | `core/downloader.py` | 15 | `class VideoDownloader` |
| 初始化(UA/session) | `core/downloader.py` | 18 | `__init__` |
| DNS容错请求 | `core/downloader.py` | 60 | `_get_with_dns_fallback` |
| 平台检测 | `core/downloader.py` | 138 | `detect_platform` |
| URL提取 | `core/downloader.py` | 150 | `extract_url_from_text` |
| 最高清晰度选择 | `core/downloader.py` | 158 | `_pick_best_quality` (static) |
| HTML视频提取 | `core/downloader.py` | 218 | `_extract_video_from_html` |
| 抖音链接解析 | `core/downloader.py` | 306 | `_douyin_download_info` |
| 抖音下载 | `core/downloader.py` | 370 | `download_douyin` |
| 通用下载引擎 | `core/downloader.py` | 410 | `_download_file` |
| 统一入口 | `core/downloader.py` | 492 | `download` |
| GUI-单个下载 | `app.py` | 780 | `_start_download` |
| GUI-批量下载 | `app.py` | 906 | `_start_batch` |
| GUI-下载Tab构建 | `app.py` | 184 | `_build_download_tab` |
| GUI-批量Tab构建 | `app.py` | 546 | `_build_batch_tab` |

---

## 九、与去重模块的关系

下载模块和去重模块是**独立但互补**的：

```
用户输入链接 → [downloader.py] → 原始视频(.mp4)
                                      ↓
                              [deduplicator.py] → 去重视频(.mp4/.mkv)
```

- **独立使用**：`python -m core.downloader` 或 `python -m core.deduplicator`
- **组合使用**：`app.py` GUI 的批量Tab自动串联两者
- **API层面**：`VideoDownloader.download()` 返回文件路径 → 传给 `VideoDeduplicator.process()`

---

## 十、测试/分析脚本（参考用）

| 文件 | 用途 | 状态 |
|------|------|------|
| `_compare_videos.py` | 夜猫 vs 泥鳅 帧级对比 | 分析用，硬编码路径 |
| `_compare_yemao_vs_tugou.py` | 详细帧类型+亮度分析 | 分析用 |
| `_deep_compare.py` | VFR vs CFR 深度帧分析 | 分析用 |
| `_yemao_vfr.py` | 夜猫VFR帧特征分析 | 分析用 |
| `_test_vfr.py` | VFR成对帧策略测试 | 测试用 |
| `_test_vfr_quick.py` | VFR快速测试 | 测试用 |
| `_test_mosaic.py` | 碎片拼贴混淆帧测试 | 测试用 |
| `_test_mosaic_v2.py` | 混淆帧优化测试 | 测试用 |
| `test_replace.py` | 帧替换+上采样测试 | 测试用 |

> ⚠️ 这些脚本包含硬编码的本地路径，不可直接运行，仅供参考逻辑。
