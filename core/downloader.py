"""
土狗视频下载器 - 视频下载模块
支持抖音/快手/B站无水印视频下载
"""
import re
import os
import json
import time
import random
import socket
import requests
from urllib.parse import urlparse, unquote


class VideoDownloader:
    """多平台视频下载器"""

    def __init__(self, save_dir="downloads"):
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

        # 移动端UA，模拟iPhone访问
        self.mobile_headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # PC端UA
        self.pc_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        self.session = requests.Session()

        # DNS缓存 - 手动解析某些可能有DNS问题的域名
        self._dns_cache = {}

    def _resolve_and_cache(self, hostname):
        """尝试DNS解析并缓存结果"""
        if hostname in self._dns_cache:
            return self._dns_cache[hostname]
        try:
            ip = socket.getaddrinfo(hostname, 443)[0][4][0]
            self._dns_cache[hostname] = ip
            return ip
        except socket.gaierror:
            return None

    def _get_with_dns_fallback(self, url, headers=None, **kwargs):
        """
        发送GET请求，如果DNS解析失败则尝试使用IP直连+手动重定向。
        """
        try:
            return self.session.get(url, headers=headers, **kwargs)
        except requests.ConnectionError as e:
            if "NameResolutionError" not in str(e) and "getaddrinfo failed" not in str(e):
                raise

            # DNS解析失败，尝试IP直连
            parsed = urlparse(url)
            hostname = parsed.hostname

            # 已知IP映射
            known_ips = {
                "www.iesdouyin.com": "163.177.180.10",
                "www.douyin.com": "122.13.173.223",
            }
            ip = known_ips.get(hostname)

            if not ip:
                try:
                    import subprocess
                    result = subprocess.run(
                        ["nslookup", hostname],
                        capture_output=True, text=True, timeout=5
                    )
                    parts = result.stdout.split("Non-authoritative") if "Non-authoritative" in result.stdout else [result.stdout]
                    ip_match = re.search(r'Address:\s+(\d+\.\d+\.\d+\.\d+)', parts[-1])
                    if ip_match:
                        ip = ip_match.group(1)
                except Exception:
                    pass

            if not ip:
                raise  # 没有IP可用

            # IP直连，关闭自动重定向，手动处理
            ip_url = url.replace(f"://{hostname}", f"://{ip}")
            h = {**(headers or {}), "Host": hostname}

            # 去掉allow_redirects（我们手动处理）
            kw = {k: v for k, v in kwargs.items() if k != "allow_redirects"}
            resp = self.session.get(ip_url, headers=h, verify=False, allow_redirects=False, **kw)

            # 手动处理重定向（最多10次）
            for _ in range(10):
                if resp.status_code not in (301, 302, 303, 307, 308):
                    break
                redirect_url = resp.headers.get("Location", "")
                if not redirect_url:
                    break
                # 相对URL处理
                if redirect_url.startswith("/"):
                    redirect_url = f"{parsed.scheme}://{hostname}{redirect_url}"

                # 对重定向URL也检查DNS
                rd_parsed = urlparse(redirect_url)
                rd_host = rd_parsed.hostname
                try:
                    socket.getaddrinfo(rd_host, 443, socket.AF_INET, socket.SOCK_STREAM)
                    # DNS正常，直接请求
                    resp = self.session.get(redirect_url, headers=headers, allow_redirects=False,
                                           **{k: v for k, v in kwargs.items() if k != 'allow_redirects'})
                except socket.gaierror:
                    # DNS失败，继续IP直连
                    rd_ip = known_ips.get(rd_host)
                    if not rd_ip:
                        # 不认识的域名，尝试返回当前resp
                        break
                    rd_ip_url = redirect_url.replace(f"://{rd_host}", f"://{rd_ip}")
                    rd_h = {**(headers or {}), "Host": rd_host}
                    resp = self.session.get(rd_ip_url, headers=rd_h, verify=False, allow_redirects=False,
                                           **{k: v for k, v in kwargs.items() if k != 'allow_redirects'})

            return resp

    def detect_platform(self, url):
        """自动检测链接所属平台"""
        url_lower = url.lower()
        if any(k in url_lower for k in ["douyin", "iesdouyin", "v.douyin"]):
            return "douyin"
        elif any(k in url_lower for k in ["kuaishou", "gifshow", "v.kuaishou", "v.kwai"]):
            return "kuaishou"
        elif any(k in url_lower for k in ["bilibili", "b23.tv", "bili"]):
            return "bilibili"
        else:
            return "unknown"

    def extract_url_from_text(self, text):
        """从分享文本中提取URL"""
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(pattern, text)
        return urls[0] if urls else text.strip()

    # ==================== 抖音下载 ====================

    def _extract_video_from_html(self, html_text):
        """从HTML页面中提取视频URL和描述"""
        # 方法A: 提取 _ROUTER_DATA
        pattern = re.compile(r'window\._ROUTER_DATA\s*=\s*(.*?)</script>', re.DOTALL)
        match = pattern.search(html_text)
        if match:
            json_text = match.group(1).strip()
            if json_text.endswith(';'):
                json_text = json_text[:-1]
            try:
                json_data = json.loads(json_text)
                loader_data = json_data.get("loaderData", {})
                for key in loader_data:
                    page_data = loader_data[key]
                    if not isinstance(page_data, dict):
                        continue
                    video_info = page_data.get("videoInfoRes")
                    if not isinstance(video_info, dict):
                        continue
                    item_list = video_info.get("item_list", [])
                    if not item_list:
                        continue
                    item = item_list[0]
                    video = item.get("video", {})
                    play_addr = video.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])
                    if url_list:
                        raw_url = url_list[0]
                        # 无水印URL: playwm -> play
                        video_url = raw_url.replace("playwm", "play")
                        desc = item.get("desc", "douyin_video")
                        # 返回无水印URL和原始URL（备选）
                        return video_url, desc, raw_url
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # 方法B: 提取 __RENDER_DATA__
        render_match = re.search(r'window\.__RENDER_DATA__\s*=\s*(.*?)</script>', html_text, re.DOTALL)
        if render_match:
            try:
                from urllib.parse import unquote as url_unquote
                raw = render_match.group(1).strip().rstrip(';')
                decoded = url_unquote(raw)
                rd = json.loads(decoded)

                def _find_play_addr(obj, depth=0):
                    if depth > 10 or obj is None:
                        return None
                    if isinstance(obj, dict):
                        if "play_addr" in obj and isinstance(obj["play_addr"], dict):
                            urls = obj["play_addr"].get("url_list", [])
                            if urls:
                                return urls[0].replace("playwm", "play")
                        if "playApi" in obj and isinstance(obj["playApi"], str) and obj["playApi"]:
                            return obj["playApi"].replace("\\u002F", "/")
                        for v in obj.values():
                            r = _find_play_addr(v, depth + 1)
                            if r:
                                return r
                    elif isinstance(obj, list):
                        for item in obj[:5]:
                            r = _find_play_addr(item, depth + 1)
                            if r:
                                return r
                    return None

                url = _find_play_addr(rd)
                if url:
                    return url, "douyin_video", url
            except Exception:
                pass

        # 方法C: 正则直接搜索视频URL
        direct_patterns = [
            r'"playApi"\s*:\s*"(https?://[^"]+)"',
            r'"play_addr"[^}]*"url_list"\s*:\s*\["(https?://[^"]+)"',
            r'src="(https?://v[^"]*(?:douyinvod|bytevod)[^"]*\.mp4[^"]*)"',
            r'"download_addr"[^}]*"url_list"\s*:\s*\["(https?://[^"]+)"',
        ]
        for pat in direct_patterns:
            m = re.search(pat, html_text, re.DOTALL)
            if m:
                url = m.group(1).replace("\\u002F", "/").replace("playwm", "play")
                return url, "douyin_video", m.group(1)

        return None, None, None

    def _douyin_download_info(self, share_url):
        """
        一站式获取抖音视频的video_id和下载URL。
        核心策略：在第一次重定向请求中就尝试提取视频信息，
        避免后续请求可能遇到的DNS问题。
        """
        url = self.extract_url_from_text(share_url)

        # Step 1: 请求短链接，跟随重定向
        resp = self._get_with_dns_fallback(
            url, headers=self.mobile_headers,
            allow_redirects=True, timeout=20
        )
        real_url = resp.url

        # 提取video_id
        video_id = None
        match = re.search(r'/video/(\d+)', real_url)
        if match:
            video_id = match.group(1)
        else:
            match = re.search(r'/(\d{15,})/?', real_url)
            if match:
                video_id = match.group(1)

        if not video_id:
            match = re.search(r'"aweme_id"\s*:\s*"(\d+)"', resp.text)
            if match:
                video_id = match.group(1)

        # Step 2: 直接从重定向后的页面提取视频URL
        # （如果重定向目标是 iesdouyin 的分享页，页面里已经有完整数据）
        video_url, desc, raw_url = self._extract_video_from_html(resp.text)
        if video_url:
            return video_id, video_url, desc, raw_url

        # Step 3: 如果重定向页没有数据，单独请求iesdouyin
        if video_id:
            try:
                share_page = f"https://www.iesdouyin.com/share/video/{video_id}"
                resp2 = self._get_with_dns_fallback(
                    share_page, headers=self.mobile_headers, timeout=20
                )
                video_url, desc, raw_url = self._extract_video_from_html(resp2.text)
                if video_url:
                    return video_id, video_url, desc, raw_url
            except Exception:
                pass

            # Step 4: 尝试douyin.com页面
            try:
                page_url = f"https://www.douyin.com/video/{video_id}"
                resp3 = self._get_with_dns_fallback(
                    page_url, headers=self.pc_headers, timeout=20
                )
                video_url, desc, raw_url = self._extract_video_from_html(resp3.text)
                if video_url:
                    return video_id, video_url, desc, raw_url
            except Exception:
                pass

        vid_str = video_id or "unknown"
        raise ValueError(f"无法获取视频 {vid_str} 的下载地址，可能需要更新解析方式")

    def download_douyin(self, share_url, filename=None, callback=None):
        """
        下载抖音视频
        :param share_url: 抖音分享链接或文本
        :param filename: 自定义文件名（不含扩展名），None则自动命名
        :param callback: 进度回调函数 callback(downloaded_bytes, total_bytes, percent, msg)
        :return: 保存的文件路径
        """
        if callback:
            callback(0, 0, 0, "正在解析抖音链接...")

        video_id, video_url, desc, raw_url = self._douyin_download_info(share_url)

        if callback:
            callback(0, 0, 15, f"视频ID: {video_id}，下载地址已获取")

        # 生成文件名
        if not filename:
            safe_desc = re.sub(r'[\\/:*?"<>|#@\n\r]', '', desc)[:50].strip()
            if not safe_desc:
                safe_desc = f"douyin_{video_id}"
            filename = safe_desc

        save_path = os.path.join(self.save_dir, f"{filename}.mp4")

        # 避免文件名冲突
        counter = 1
        while os.path.exists(save_path):
            save_path = os.path.join(self.save_dir, f"{filename}_{counter}.mp4")
            counter += 1

        if callback:
            callback(0, 0, 20, "开始下载视频...")

        # 下载视频（传入无水印URL和原始URL作为备选）
        self._download_file(video_url, save_path, callback, fallback_url=raw_url)
        return save_path

    # ==================== 通用下载 ====================

    def _download_file(self, url, save_path, callback=None, fallback_url=None):
        """通用文件下载（支持进度回调，带防盗链绕过）"""
        # 尝试多种headers组合来绕过403
        header_variants = [
            {
                # 方案1: 移动端 + iesdouyin referer
                "User-Agent": self.mobile_headers["User-Agent"],
                "Referer": "https://www.iesdouyin.com/",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            {
                # 方案2: 移动端 + douyin referer
                "User-Agent": self.mobile_headers["User-Agent"],
                "Referer": "https://www.douyin.com/",
                "Accept": "*/*",
            },
            {
                # 方案3: 无referer
                "User-Agent": self.mobile_headers["User-Agent"],
                "Accept": "*/*",
            },
            {
                # 方案4: PC端UA
                "User-Agent": self.pc_headers["User-Agent"],
                "Referer": "https://www.douyin.com/",
                "Accept": "*/*",
            },
        ]

        # 构建URL尝试列表：无水印URL、原始URL(带水印)、playwm版本
        urls_to_try = [url]
        if fallback_url and fallback_url != url:
            urls_to_try.append(fallback_url)
        if "/play/" in url and "/playwm/" not in url:
            urls_to_try.append(url.replace("/play/", "/playwm/"))

        last_error = None
        for try_url in urls_to_try:
            for headers in header_variants:
                try:
                    resp = self._get_with_dns_fallback(
                        try_url, headers=headers, stream=True, timeout=60
                    )
                    if resp.status_code == 200:
                        total_size = int(resp.headers.get('content-length', 0))
                        downloaded = 0

                        with open(save_path, 'wb') as f:
                            for chunk in resp.iter_content(chunk_size=1024 * 64):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if callback and total_size > 0:
                                        percent = 20 + int((downloaded / total_size) * 80)
                                        callback(
                                            downloaded, total_size, percent,
                                            f"downloading {downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB"
                                        )

                        # 验证文件有效
                        if os.path.exists(save_path) and os.path.getsize(save_path) > 1024:
                            if callback:
                                size_mb = os.path.getsize(save_path) / 1024 / 1024
                                callback(downloaded, total_size, 100, f"done! {size_mb:.1f}MB -> {save_path}")
                            return

                    elif resp.status_code in (301, 302, 303, 307, 308):
                        # 跟随重定向
                        redirect_url = resp.headers.get("Location", "")
                        if redirect_url:
                            urls_to_try.append(redirect_url)

                except requests.RequestException as e:
                    last_error = e
                    continue

        # 所有方案都失败
        if os.path.exists(save_path):
            os.remove(save_path)
        raise ConnectionError(f"download failed after all attempts: {last_error}")

    def download(self, url, filename=None, callback=None):
        """
        统一下载入口 - 自动检测平台并下载
        :param url: 视频分享链接
        :param filename: 自定义文件名
        :param callback: 进度回调
        :return: 保存的文件路径
        """
        real_url = self.extract_url_from_text(url)
        platform = self.detect_platform(real_url)

        if platform == "douyin":
            return self.download_douyin(real_url, filename, callback)
        elif platform == "kuaishou":
            raise NotImplementedError("kuaishou download coming soon...")
        elif platform == "bilibili":
            raise NotImplementedError("bilibili download coming soon...")
        else:
            raise ValueError(f"unsupported platform: {real_url}")


# ==================== 命令行测试 ====================
if __name__ == "__main__":
    downloader = VideoDownloader(save_dir="downloads")

    def progress(downloaded, total, percent, msg):
        print(f"\r[{'=' * (percent // 2)}{' ' * (50 - percent // 2)}] {percent}% {msg}", end="", flush=True)

    url = input("\nInput douyin share link: ").strip()
    if url:
        try:
            path = downloader.download(url, callback=progress)
            print(f"\n\nDONE: {path}")
        except Exception as e:
            print(f"\n\nFAILED: {e}")
