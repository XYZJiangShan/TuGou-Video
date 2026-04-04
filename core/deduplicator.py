"""
土狗视频下载器 - 视频去重引擎
多模式视频处理，规避平台重复检测

集成12种去重手段，覆盖：
- 视觉层: 对比度/亮度/饱和度/色温/锐化/模糊
- 几何层: 裁剪/镜像/缩放/旋转
- 时间层: 变速/抽帧/帧插值
- 音频层: 变调/变速
- 元数据层: MD5/EXIF/时间戳
- 结构层: 片头片尾裁剪

所有处理通过FFmpeg实现，确保60fps流畅输出。
"""
import os
import re
import json
import random
import subprocess
import time
import uuid
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, List


@dataclass
class DedupConfig:
    """去重配置 - 控制各项去重参数"""

    # ---- 视觉调整 ----
    adjust_brightness: bool = True      # 亮度微调
    brightness_value: float = 0.02      # 亮度偏移 (-1.0 ~ 1.0)

    adjust_contrast: bool = True        # 对比度微调
    contrast_value: float = 1.04        # 对比度倍率 (0.0 ~ 2.0，1.0为原始)

    adjust_saturation: bool = True      # 饱和度微调
    saturation_value: float = 1.05      # 饱和度倍率

    adjust_gamma: bool = True           # Gamma校正
    gamma_value: float = 1.02           # Gamma值

    sharpen: bool = True                # 锐化
    denoise: bool = True                # 降噪增强(hqdn3d)

    # ---- 几何变换 ----
    crop_edges: bool = True             # 边缘裁剪
    crop_percent: float = 0.98          # 保留比例 (0.95~0.99)

    horizontal_flip: bool = False       # 水平镜像翻转
    slight_rotation: bool = True        # 轻微旋转
    rotation_angle: float = 0.5         # 旋转角度 (0.1~2.0度)

    # ---- 时间轴操作 ----
    speed_change: bool = True           # 变速
    speed_factor: float = 1.04          # 速度因子 (0.9~1.1)

    trim_head: bool = True              # 掐头
    trim_head_frames: int = 3           # 掐掉前N帧

    trim_tail: bool = True              # 去尾
    trim_tail_seconds: float = 0.1      # 去掉尾部秒数

    # ---- 音频处理 ----
    audio_pitch_shift: bool = True      # 音频变调
    audio_pitch_semitones: float = 0.5  # 变调半音数 (微调，人耳不易察觉)

    audio_speed_match: bool = True      # 音频随视频同步变速

    # ---- 元数据修改 ----
    modify_metadata: bool = True        # 修改元数据
    randomize_md5: bool = True          # 随机化MD5(通过重编码+随机元数据)

    # ---- 水印/覆盖 ----
    add_invisible_watermark: bool = True  # 添加不可见水印(单像素随机噪点)

    # ---- 帧膨胀(Frame Stuffing) ----
    frame_stuffing: bool = False          # 启用帧膨胀去重
    stuffing_mode: str = "interleave"     # interleave=帧间交替插入, append=末尾追加, boost_fps=帧率倍增, geometric=几何图案插帧
    stuffing_image: str = ""              # 自定义填充图片路径(空=自动生成随机图案)
    stuffing_ratio: float = 2.0           # 膨胀倍率(2.0=每个原始帧后插入1帧, 4.0=插入3帧)
    stuffing_target_fps: int = 0          # 目标帧率(0=自动计算, 如120/240)
    stuffing_frame_type: str = "noise"    # 自动生成帧类型: noise=随机噪点, gradient=渐变色, solid=纯色, pattern=几何图案
    stuffing_opacity: float = 0.01        # 填充帧与原始帧的混合透明度(越低越不可见, 0.01=几乎透明)

    # ---- 上采样设置 ----
    upscale_1080p: bool = False         # 上采样到1080p（720p→1080p，增加像素级指纹差异）
    upscale_method: str = "lanczos"     # 上采样算法: lanczos / bicubic / bilinear

    # ---- 帧替换设置 ----
    frame_replace: bool = False         # 启用帧替换（保持原始帧率，替换部分帧为图案帧）
    replace_ratio: float = 0.35         # 替换比例 (0.2~0.5，即20%~50%的帧被替换)
    replace_interval: int = 3           # 替换间隔 (每N帧替换1帧, 3=33%, 2=50%)
    replace_skip_start: int = 60        # 跳过前N帧不替换（保护片头）
    replace_mode: str = "v4"            # 帧替换模式: v3=实时enable条件模糊, v4=预生成混淆帧overlay(夜猫方式)

    # ---- 平台专属设置 ----
    target_codec: str = "h264"          # 编码器: h264 / hevc / auto
    target_bitrate: str = ""            # 目标码率(空=自动): "5800k" / "15M" 等
    max_bitrate: str = ""               # 最大码率(空=自动): "8500k" 等
    target_level: str = ""              # H.264 Level: "" / "5" / "5.1"
    audio_noise_mix: bool = False       # 混入环境底噪(-26dB)
    audio_noise_db: float = -26.0       # 底噪分贝
    hue_shift: float = 0.0             # 色相偏移(度), 0=不偏移
    color_balance_rs: float = 0.0      # 色彩平衡 red-shadow
    color_balance_gs: float = 0.0      # 色彩平衡 green-shadow
    pad_edges: bool = False             # 边缘padding（区别于crop）
    pad_pixels: int = 0                 # padding像素数

    # ---- 输出设置 ----
    output_quality: str = "high"        # high / medium / low
    output_fps: int = 0                 # 0 = 保持原始帧率
    output_resolution: str = ""         # "" = 保持原始, "1080x1920" = 指定
    gpu_acceleration: bool = False      # GPU硬件加速(需要NVIDIA显卡)


# ==================== 平台预设结构 ====================
# 顶层key是平台名，每个平台下是 {"模式名": DedupConfig}
# GUI按"平台 → 模式"双级选择
# "通用"分类保留原有预设，不绑定特定平台

PLATFORM_PRESETS = {
    "抖音": {
        "模式1 - 帧替换+多维微调": DedupConfig(
            # 核心: 帧替换v4(夜猫方式) + 1080p上采样 + 音频修改
            # 针对: 帧级指纹99.7% + 音频波纹99.2% + 语义理解
            frame_replace=True,
            replace_mode="v4",
            replace_ratio=0.35,
            replace_interval=3,
            replace_skip_start=60,
            upscale_1080p=True,
            upscale_method="lanczos",
            # 多维度画面微调
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.02,
            adjust_saturation=True, saturation_value=1.05,
            adjust_gamma=True, gamma_value=1.02,
            hue_shift=2.0,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.99,
            slight_rotation=True, rotation_angle=0.3,
            speed_change=True, speed_factor=1.02,
            trim_head=True, trim_head_frames=3,
            trim_tail=True, trim_tail_seconds=0.1,
            # 音频: 变调+变速（破坏音频波纹指纹）
            audio_pitch_shift=True, audio_pitch_semitones=0.5,
            audio_speed_match=True,
            # 元数据
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
            # 平台参数: H.264, 抖音会重编码所以码率不限
            target_codec="h264",
        ),
    },
    "快手": {
        "模式1 - GPU高速(VFR插帧)": DedupConfig(
            # 夜猫模式A复刻: h264_nvenc + Main + VFR帧数翻倍 + mono音频 + MKV
            # 核心策略: 帧数翻倍(VFR) + GPU编码 + 音频降mono
            # 特殊处理: 走 _apply_kuaishou_mode_a 专用方法
            frame_stuffing=True,           # 复用 frame_stuffing 作为触发标记
            stuffing_mode="kuaishou_a",    # 自定义模式名，在 process() 里识别
            # 画面微调（不需要太多，VFR插帧本身就是主力）
            adjust_brightness=False,
            adjust_contrast=False,
            adjust_saturation=False,
            sharpen=False, denoise=False,
            crop_edges=False,
            add_invisible_watermark=False,
            speed_change=False,
            trim_head=False,
            trim_tail=False,
            audio_pitch_shift=False,
            # 元数据
            modify_metadata=True, randomize_md5=True,
            # 平台参数
            target_codec="h264",
            gpu_acceleration=True,
        ),
        "模式2 - CPU精确(444色度)": DedupConfig(
            # 夜猫模式B复刻: libx264 + High 4:4:4 Predictive + yuv444p + VFR帧数翻倍 + MKV
            # 核心策略: yuv444p色度空间变换彻底改变色彩指纹hash
            # 特殊处理: 走 _apply_kuaishou_mode_b 专用方法
            frame_stuffing=True,
            stuffing_mode="kuaishou_b",
            # 画面不调（444p本身就改变了所有色彩数据）
            adjust_brightness=False,
            adjust_contrast=False,
            adjust_saturation=False,
            sharpen=False, denoise=False,
            crop_edges=False,
            add_invisible_watermark=False,
            speed_change=False,
            trim_head=False,
            trim_tail=False,
            audio_pitch_shift=False,
            # 元数据
            modify_metadata=True, randomize_md5=True,
            # 平台参数
            target_codec="h264",
            gpu_acceleration=False,
        ),
    },
    "小红书": {
        "模式1 - 色相锐化+高码率": DedupConfig(
            # 核心: 色相偏移 + 锐化（破坏LBP纹理）+ 高码率上传
            # 针对: HSV色彩模型 + LBP纹理 + BERT语义
            # 小红书检测相对最弱，不需要帧替换
            frame_replace=False,
            upscale_1080p=True,
            upscale_method="lanczos",
            # 画面: 色相偏移 + 强锐化（破坏LBP纹理特征）
            adjust_brightness=True, brightness_value=0.01,
            adjust_contrast=True, contrast_value=1.01,
            adjust_saturation=True, saturation_value=1.05,
            hue_shift=3.0,
            sharpen=True, denoise=False,  # 强锐化破坏纹理
            crop_edges=True, crop_percent=0.99,
            add_invisible_watermark=True,
            # 时间轴: 不变速
            speed_change=False,
            trim_head=True, trim_head_frames=2,
            trim_tail=True, trim_tail_seconds=0.05,
            # 音频: 轻度变调
            audio_pitch_shift=True, audio_pitch_semitones=0.3,
            # 元数据
            modify_metadata=True, randomize_md5=True,
            # 平台参数: H.264, 高码率上传
            target_codec="h264",
            target_bitrate="15M",
        ),
    },
    "B站": {
        "模式1 - 帧替换+不二压": DedupConfig(
            # 核心: 帧替换v4(夜猫方式) + 画面调整 + 不二压参数（≤6000kbps）
            # 针对: ResNet50+Faiss工业级检索 + 霍夫变换精排
            frame_replace=True,
            replace_mode="v4",
            replace_ratio=0.35,
            replace_interval=3,
            replace_skip_start=60,
            # 画面: 多维度微调
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.02,
            adjust_saturation=True, saturation_value=1.03,
            adjust_gamma=True, gamma_value=1.02,
            hue_shift=2.0,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.99,
            slight_rotation=True, rotation_angle=0.3,
            add_invisible_watermark=True,
            # 速度微调（干扰片段匹配）
            speed_change=True, speed_factor=0.98,
            trim_head=True, trim_head_frames=3,
            trim_tail=True, trim_tail_seconds=0.1,
            # 音频
            audio_pitch_shift=True, audio_pitch_semitones=0.3,
            # 元数据
            modify_metadata=True, randomize_md5=True,
            # 平台参数: H.264, 不二压阈值
            target_codec="h264",
            target_bitrate="5800k",
            max_bitrate="8500k",
            target_level="5",
        ),
    },
    "通用": {
        "轻度去重": DedupConfig(
            adjust_brightness=True, brightness_value=0.01,
            adjust_contrast=True, contrast_value=1.02,
            adjust_saturation=True, saturation_value=1.02,
            adjust_gamma=False,
            sharpen=False, denoise=False,
            crop_edges=True, crop_percent=0.99,
            horizontal_flip=False, slight_rotation=False,
            speed_change=True, speed_factor=1.02,
            trim_head=True, trim_head_frames=2,
            trim_tail=True, trim_tail_seconds=0.05,
            audio_pitch_shift=False,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "中度去重": DedupConfig(
            # 默认值即为中度
        ),
        "深度去重": DedupConfig(
            adjust_brightness=True, brightness_value=0.03,
            adjust_contrast=True, contrast_value=1.06,
            adjust_saturation=True, saturation_value=1.06,
            adjust_gamma=True, gamma_value=1.03,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.97,
            horizontal_flip=False, slight_rotation=True, rotation_angle=0.8,
            speed_change=True, speed_factor=1.06,
            trim_head=True, trim_head_frames=6,
            trim_tail=True, trim_tail_seconds=0.2,
            audio_pitch_shift=True, audio_pitch_semitones=0.8,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "镜像翻转模式": DedupConfig(
            horizontal_flip=True,
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.03,
            crop_edges=True, crop_percent=0.98,
            speed_change=True, speed_factor=1.03,
            modify_metadata=True, randomize_md5=True,
        ),
        "极限去重": DedupConfig(
            adjust_brightness=True, brightness_value=0.04,
            adjust_contrast=True, contrast_value=1.08,
            adjust_saturation=True, saturation_value=1.08,
            adjust_gamma=True, gamma_value=1.05,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.96,
            horizontal_flip=True, slight_rotation=True, rotation_angle=1.0,
            speed_change=True, speed_factor=1.08,
            trim_head=True, trim_head_frames=8,
            trim_tail=True, trim_tail_seconds=0.3,
            audio_pitch_shift=True, audio_pitch_semitones=1.0,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "帧膨胀模式": DedupConfig(
            frame_stuffing=True,
            stuffing_mode="boost_fps",
            stuffing_ratio=3.0,
            stuffing_frame_type="noise",
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.03,
            adjust_saturation=True, saturation_value=1.02,
            crop_edges=True, crop_percent=0.99,
            speed_change=True, speed_factor=1.02,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "帧膨胀+深度去重": DedupConfig(
            frame_stuffing=True,
            stuffing_mode="interleave",
            stuffing_ratio=2.0,
            stuffing_frame_type="noise",
            adjust_brightness=True, brightness_value=0.03,
            adjust_contrast=True, contrast_value=1.06,
            adjust_saturation=True, saturation_value=1.05,
            adjust_gamma=True, gamma_value=1.03,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.97,
            horizontal_flip=False, slight_rotation=True, rotation_angle=0.5,
            speed_change=True, speed_factor=1.04,
            trim_head=True, trim_head_frames=4,
            trim_tail=True, trim_tail_seconds=0.15,
            audio_pitch_shift=True, audio_pitch_semitones=0.5,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "几何图案插帧": DedupConfig(
            frame_stuffing=True,
            stuffing_mode="geometric",
            stuffing_ratio=2.0,
            stuffing_frame_type="noise",
            adjust_brightness=True, brightness_value=0.01,
            adjust_contrast=True, contrast_value=1.02,
            adjust_saturation=True, saturation_value=1.02,
            crop_edges=True, crop_percent=0.99,
            speed_change=True, speed_factor=1.02,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "智能帧替换": DedupConfig(
            frame_replace=True,
            replace_mode="v4",
            replace_ratio=0.35,
            replace_interval=3,
            replace_skip_start=60,
            adjust_brightness=True, brightness_value=0.01,
            adjust_contrast=True, contrast_value=1.02,
            adjust_saturation=True, saturation_value=1.02,
            crop_edges=True, crop_percent=0.99,
            speed_change=True, speed_factor=1.02,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "上采样+重编码": DedupConfig(
            upscale_1080p=True,
            upscale_method="lanczos",
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.03,
            adjust_saturation=True, saturation_value=1.03,
            adjust_gamma=True, gamma_value=1.02,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.99,
            speed_change=True, speed_factor=1.02,
            trim_head=True, trim_head_frames=2,
            trim_tail=True, trim_tail_seconds=0.1,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
        "帧替换+上采样": DedupConfig(
            frame_replace=True,
            replace_ratio=0.35,
            replace_interval=3,
            replace_skip_start=60,
            upscale_1080p=True,
            upscale_method="lanczos",
            adjust_brightness=True, brightness_value=0.02,
            adjust_contrast=True, contrast_value=1.03,
            adjust_saturation=True, saturation_value=1.03,
            adjust_gamma=True, gamma_value=1.02,
            sharpen=True, denoise=True,
            crop_edges=True, crop_percent=0.99,
            speed_change=True, speed_factor=1.02,
            trim_head=True, trim_head_frames=2,
            trim_tail=True, trim_tail_seconds=0.1,
            audio_pitch_shift=True, audio_pitch_semitones=0.3,
            modify_metadata=True, randomize_md5=True,
            add_invisible_watermark=True,
        ),
    },
}

# 兼容旧代码: 扁平化 PRESETS 字典（"平台/模式名" 格式）
PRESETS = {}
for _platform, _modes in PLATFORM_PRESETS.items():
    for _mode_name, _config in _modes.items():
        if _platform == "通用":
            PRESETS[_mode_name] = _config
        else:
            PRESETS[f"{_platform}/{_mode_name}"] = _config


class VideoDeduplicator:
    """视频去重处理器"""

    def __init__(self, ffmpeg_path=None, ffprobe_path=None):
        # 自动查找本地目录下的ffmpeg
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        if ffmpeg_path is None:
            local_ffmpeg = os.path.join(base_dir, "ffmpeg.exe")
            self.ffmpeg_path = local_ffmpeg if os.path.exists(local_ffmpeg) else "ffmpeg"
        else:
            self.ffmpeg_path = ffmpeg_path

        if ffprobe_path is None:
            local_ffprobe = os.path.join(base_dir, "ffprobe.exe")
            self.ffprobe_path = local_ffprobe if os.path.exists(local_ffprobe) else "ffprobe"
        else:
            self.ffprobe_path = ffprobe_path

        self._check_ffmpeg()

    @staticmethod
    def _run(cmd, **kwargs):
        """subprocess.run 包装器，统一处理 Windows 编码问题"""
        kwargs.setdefault("text", True)
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
        return subprocess.run(cmd, **kwargs)

    @staticmethod
    def _popen(cmd, **kwargs):
        """subprocess.Popen 包装器，统一处理 Windows 编码问题"""
        kwargs.setdefault("universal_newlines", True)
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
        return subprocess.Popen(cmd, **kwargs)

    def _check_ffmpeg(self):
        """检查FFmpeg是否可用"""
        try:
            result = self._run(
                [self.ffmpeg_path, "-version"],
                capture_output=True, timeout=10
            )
            if result.returncode != 0:
                raise FileNotFoundError()
            # 提取版本号
            version_match = re.search(r'ffmpeg version (\S+)', result.stdout)
            self.ffmpeg_version = version_match.group(1) if version_match else "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            raise RuntimeError(
                "FFmpeg未找到！请确保ffmpeg在系统PATH中，或指定ffmpeg_path参数。\n"
                "下载地址: https://ffmpeg.org/download.html"
            )

    def get_video_info(self, input_path):
        """获取视频信息"""
        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path
        ]
        try:
            result = self._run(cmd, capture_output=True, timeout=30)
            info = json.loads(result.stdout)
            return info
        except Exception as e:
            return None

    def _generate_stuffing_image(self, width, height, frame_type, output_path):
        """生成用于帧膨胀的填充图片"""
        try:
            import numpy as np
            from PIL import Image

            if frame_type == "noise":
                # 随机噪点图 - 每次生成都不同
                arr = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
                img = Image.fromarray(arr)
            elif frame_type == "gradient":
                # 随机渐变色
                arr = np.zeros((height, width, 3), dtype=np.uint8)
                c1 = np.random.randint(0, 256, 3)
                c2 = np.random.randint(0, 256, 3)
                for i in range(3):
                    arr[:, :, i] = np.linspace(c1[i], c2[i], width).astype(np.uint8)
                img = Image.fromarray(arr)
            elif frame_type == "solid":
                # 随机纯色
                color = tuple(np.random.randint(0, 256, 3).tolist())
                img = Image.new("RGB", (width, height), color)
            elif frame_type == "pattern":
                # 几何图案 - 随机条纹/格子
                arr = np.zeros((height, width, 3), dtype=np.uint8)
                stripe_width = random.randint(4, 20)
                c1 = np.random.randint(0, 256, 3)
                c2 = np.random.randint(0, 256, 3)
                for y in range(height):
                    if (y // stripe_width) % 2 == 0:
                        arr[y, :] = c1
                    else:
                        arr[y, :] = c2
                img = Image.fromarray(arr)
            else:
                # 默认黑帧
                img = Image.new("RGB", (width, height), (0, 0, 0))

            img.save(output_path, quality=95)
            return output_path
        except ImportError:
            # 没有PIL/numpy，用ffmpeg生成
            cmd = [
                self.ffmpeg_path, "-y", "-f", "lavfi", "-i",
                f"color=c=#{random.randint(0, 0xFFFFFF):06x}:size={width}x{height}:d=0.04",
                "-frames:v", "1", output_path
            ]
            self._run(cmd, capture_output=True, timeout=10)
            return output_path

    def _generate_geometric_frame(self, width, height, output_path):
        """
        生成类似参考软件的几何图案插帧图片
        
        特点：
        - 带交叉网格线的柔和背景
        - 随机分布的彩色半透明几何形状（三角形、矩形、圆形、椭圆、菱形等）
        - 视觉上丰富多彩，但在平台压缩后由于仅显示1帧（1/60s）而不可见
        """
        try:
            from PIL import Image, ImageDraw
            import numpy as np
            
            # 1. 创建柔和背景（浅粉/浅黄色调 + 交叉网格线）
            bg_r = random.randint(210, 240)
            bg_g = random.randint(210, 235)
            bg_b = random.randint(200, 225)
            img = Image.new("RGBA", (width, height), (bg_r, bg_g, bg_b, 255))
            draw = ImageDraw.Draw(img)
            
            # 2. 画交叉网格线（斜线网格，类似参考图）
            grid_color = (bg_r - 30, bg_g - 25, bg_b - 20, 80)
            spacing = random.randint(15, 25)
            # 正斜线
            for offset in range(-max(width, height), max(width, height), spacing):
                draw.line([(offset, 0), (offset + height, height)], fill=grid_color, width=1)
            # 反斜线
            for offset in range(-max(width, height), max(width, height), spacing):
                draw.line([(offset + height, 0), (offset, height)], fill=grid_color, width=1)
            
            # 3. 随机绘制 30-60 个彩色半透明几何形状
            num_shapes = random.randint(30, 60)
            shape_types = ["triangle", "rectangle", "circle", "ellipse", "diamond", "pentagon"]
            
            for _ in range(num_shapes):
                shape = random.choice(shape_types)
                # 随机颜色（鲜艳的半透明色）
                r = random.randint(40, 255)
                g = random.randint(40, 255)
                b = random.randint(40, 255)
                alpha = random.randint(100, 200)
                color = (r, g, b, alpha)
                
                # 随机位置和大小
                size = random.randint(int(min(width, height) * 0.03), int(min(width, height) * 0.18))
                cx = random.randint(-size // 2, width + size // 2)
                cy = random.randint(-size // 2, height + size // 2)
                
                # 创建临时透明图层用于混合
                overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                odraw = ImageDraw.Draw(overlay)
                
                if shape == "triangle":
                    # 随机三角形
                    pts = []
                    for _ in range(3):
                        px = cx + random.randint(-size, size)
                        py = cy + random.randint(-size, size)
                        pts.append((px, py))
                    odraw.polygon(pts, fill=color)
                    
                elif shape == "rectangle":
                    w2 = random.randint(size // 2, size * 2)
                    h2 = random.randint(size // 2, size)
                    odraw.rectangle([cx - w2 // 2, cy - h2 // 2, cx + w2 // 2, cy + h2 // 2], fill=color)
                    
                elif shape == "circle":
                    odraw.ellipse([cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2], fill=color)
                    
                elif shape == "ellipse":
                    w2 = random.randint(size, size * 2)
                    h2 = random.randint(size // 2, size)
                    odraw.ellipse([cx - w2 // 2, cy - h2 // 2, cx + w2 // 2, cy + h2 // 2], fill=color)
                    
                elif shape == "diamond":
                    pts = [
                        (cx, cy - size),
                        (cx + size // 2, cy),
                        (cx, cy + size),
                        (cx - size // 2, cy),
                    ]
                    odraw.polygon(pts, fill=color)
                    
                elif shape == "pentagon":
                    import math
                    pts = []
                    for k in range(5):
                        angle = math.radians(72 * k - 90 + random.randint(-10, 10))
                        px = cx + int(size * 0.7 * math.cos(angle))
                        py = cy + int(size * 0.7 * math.sin(angle))
                        pts.append((px, py))
                    odraw.polygon(pts, fill=color)
                
                img = Image.alpha_composite(img, overlay)
            
            # 4. 转为 RGB 并保存
            img_rgb = img.convert("RGB")
            img_rgb.save(output_path, quality=95)
            return output_path
            
        except ImportError:
            # 没有 PIL，回退到 ffmpeg 生成纯色帧
            cmd = [
                self.ffmpeg_path, "-y", "-f", "lavfi", "-i",
                f"color=c=#{random.randint(0, 0xFFFFFF):06x}:size={width}x{height}:d=0.04",
                "-frames:v", "1", output_path
            ]
            self._run(cmd, capture_output=True, timeout=10)
            return output_path

    def _stuffing_geometric_interleave(self, input_path, output_path, config,
                                        width, height, fps, target_fps, temp_dir, callback):
        """
        几何图案插帧模式 — CFR + libx264 High profile + B-frames（夜猫同款方案 v2）
        
        核心原理（对标夜猫电商视频处理工具箱逆向分析结果）：
        =====================================================
        夜猫特征: 30fps CFR, High profile, has_b_frames=2, 图案帧自然落入B帧位置
        
        关键发现：夜猫不用VFR时间戳技巧！而是利用H.264 B-frame的双向预测机制：
        1. 保持原始帧率（如30fps），在内容帧间交替插入图案帧 → 60fps CFR
        2. 使用 libx264 High profile + bf=2（允许B帧）
        3. 编码器自动把"与前后内容帧差异极大"的图案帧分配为B帧
        4. B帧使用双向预测 + 极低码率，图案帧被压缩到极小（几百~几千字节）
        5. 平台VFR→CFR转码不会暴露图案帧，因为本来就是CFR
        6. sc_threshold=0 防止图案帧触发场景切换（不生成额外I帧）
        
        vs 旧方案的改进：
        - 不再使用 VFR 时间戳（平台转码会暴露帧）
        - 不再使用 NVENC Main profile + no B-frames（图案帧作为P帧太大）
        - 改用 libx264 High profile + B-frames = 夜猫同款技术路线
        """
        if callback:
            callback(15, "图案插帧(夜猫v2): 生成几何图案...")
        
        # 1. 生成几何图案图片
        pattern_img = os.path.join(temp_dir, "geometric_pattern.png")
        self._generate_geometric_frame(width, height, pattern_img)
        
        # 2. 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-show_entries", "stream=nb_frames,r_frame_rate",
                "-select_streams", "v:0",
                "-of", "json",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            probe_info = json.loads(result.stdout)
            duration_total = float(probe_info.get("format", {}).get("duration", 0))
        except Exception:
            pass
        
        if callback:
            callback(20, "图案插帧(夜猫v2): 构建CFR + High + B-frames编码...")
        
        # 3. 核心滤镜：两个独立流交织 → 60fps CFR
        #
        # 交织后帧序列：[内容0, 图案0, 内容1, 图案1, 内容2, 图案2, ...]
        # 帧率从 30fps → 60fps CFR（不是VFR！）
        #
        # libx264 High profile + bf=2 的 GOP 结构会自然形成：
        #   I  B  B  P  B  B  P  B  B  P ...
        # 图案帧因为与前后内容帧差异极大，编码器倾向于将其编为 B帧
        # B帧的双向预测 + skip机制 → 图案帧被压到极小
        
        output_fps = fps * 2  # 30fps → 60fps CFR
        trim_duration = (duration_total + 5) if duration_total else 600
        
        filter_complex = (
            f"[0:v]fps={fps},setpts=PTS-STARTPTS,setsar=1[main];"
            f"[1:v]loop=-1:size=1,trim=duration={trim_duration:.1f},"
            f"fps={fps},scale={width}:{height},format=yuv420p,setsar=1,"
            f"setpts=PTS-STARTPTS[pattern];"
            f"[main][pattern]interleave,"
            # CFR时间戳：每帧均匀分配，60fps → 每帧间隔 1/60s
            f"setpts=N/{output_fps}/TB"
            f"[out]"
        )
        
        # 4. 构建编码命令 — libx264 High profile + B-frames（夜猫同款）
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-i", pattern_img,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
        ]
        
        # 编码器参数：关键是 High profile + bf=2 + b_strategy=2
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "high",       # High profile — 支持B帧（夜猫同款）
            "-bf", "2",                 # 最多2个连续B帧（夜猫 has_b_frames=2）
            "-b_strategy", "2",         # 自适应B帧决策（让x264自行判断最优B帧分配）
            "-crf", "20",               # 质量目标
            "-maxrate", "15000k",
            "-bufsize", "15000k",
            "-g", str(output_fps * 2),  # GOP = 2秒（120帧@60fps）
            "-sc_threshold", "0",       # 禁用场景切换检测 — 图案帧不触发I帧
            "-refs", "3",               # 参考帧数 = 3（增强B帧压缩效率）
            "-direct-pred", "auto",     # B帧MV预测模式自动
        ])
        
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(output_fps),       # 60fps CFR 输出（不是VFR！）
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ])
        
        # 限制时长
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)
        
        if callback:
            callback(25, f"图案插帧(夜猫v2): {fps}fps → {output_fps}fps CFR + High + B-frames...")
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(25 + (current / duration_total) * 65))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"图案插帧(High+B帧)中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            error_text = "".join(stderr_output[-30:])
            if callback:
                callback(25, "interleave方案失败，尝试overlay备用方案...")
            return self._stuffing_geometric_nvenc_overlay(
                input_path, output_path, config,
                width, height, fps, pattern_img, temp_dir,
                duration_total, False, callback  # use_nvenc=False, 统一用libx264
            )
        
        if callback:
            callback(95, f"图案插帧(夜猫v2)完成! (High profile + B-frames)")
        
        return output_path

    def _check_nvenc_available(self):
        """检测 h264_nvenc 是否可用"""
        try:
            # NVENC 最小分辨率要求 >=145x145 左右，用 256x256 测试
            test_output = os.path.join(
                os.environ.get("TEMP", "."),
                f"_nvenc_test_{uuid.uuid4().hex[:6]}.mp4"
            )
            cmd = [
                self.ffmpeg_path, "-y", "-f", "lavfi", "-i",
                "color=c=black:s=256x256:d=0.1:r=30",
                "-c:v", "h264_nvenc", "-preset", "p4",
                test_output
            ]
            result = self._run(cmd, capture_output=True, timeout=15)
            ok = result.returncode == 0
            try:
                os.remove(test_output)
            except Exception:
                pass
            return ok
        except Exception:
            return False

    def _stuffing_geometric_nvenc_overlay(self, input_path, output_path, config,
                                           width, height, fps, pattern_img, temp_dir,
                                           duration_total, use_nvenc, callback):
        """
        备用方案：overlay + CFR + High + B-frames（当 interleave 不可用时）
        
        原理与主方案一致，但使用 overlay + enable='mod(n,2)' 替代 interleave 滤镜：
        1. tpad 每帧后克隆一帧 → 60fps
        2. overlay 在奇数帧（克隆帧位置）替换为图案
        3. CFR + libx264 High profile + B-frames 编码
        """
        if callback:
            callback(28, "备用方案: overlay + CFR + High + B-frames...")
        
        output_fps = fps * 2
        trim_duration = (duration_total + 5) if duration_total else 600
        
        # 关键滤镜：overlay 方式实现同样的交织效果
        filter_complex = (
            f"[0:v]fps={fps},tpad=stop_mode=clone:stop_duration=0[padded];"
            f"[padded]fps={output_fps}[base];"
            f"[1:v]loop=-1:size=1,trim=duration={trim_duration:.1f},"
            f"fps={output_fps},scale={width}:{height},format=yuva420p[pat];"
            f"[base][pat]overlay=0:0:enable='mod(n\\,2)':shortest=1,"
            # CFR 时间戳：均匀分配
            f"setpts=N/{output_fps}/TB"
            f"[out]"
        )
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-i", pattern_img,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
        ]
        
        # 统一使用 libx264 High + B-frames
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "high",
            "-bf", "2",
            "-b_strategy", "2",
            "-crf", "20",
            "-maxrate", "15000k", "-bufsize", "15000k",
            "-g", str(output_fps * 2),
            "-sc_threshold", "0",
            "-refs", "3",
            "-direct-pred", "auto",
        ])
        
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(output_fps),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ])
        
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(30 + (current / duration_total) * 60))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"图案插帧(overlay备用)中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            error_text = "".join(stderr_output[-30:])
            if callback:
                callback(28, "overlay备用方案失败，回退到CFR简单方案...")
            return self._stuffing_geometric_cfr_simple(
                input_path, output_path, config,
                width, height, fps, pattern_img, temp_dir,
                duration_total, callback
            )
        
        if callback:
            callback(95, "图案插帧(overlay+High+B帧)完成!")
        
        return output_path

    def _stuffing_geometric_cfr_simple(self, input_path, output_path, config,
                                        width, height, fps, pattern_img, temp_dir,
                                        duration_total, callback):
        """
        最终回退方案：简单 overlay + CFR + High + B-frames
        
        interleave 和 overlay+tpad 都失败时的兜底。
        帧率翻倍，每隔一帧替换为图案，CFR输出。
        依然使用 High profile + B-frames 来压缩图案帧。
        """
        if callback:
            callback(30, "CFR兜底方案: overlay + High + B-frames...")
        
        output_fps = fps * 2
        trim_duration = (duration_total + 5) if duration_total else 600
        
        filter_complex = (
            f"[0:v]fps={output_fps}[base];"
            f"[1:v]loop=-1:size=1,trim=duration={trim_duration:.1f},"
            f"fps={output_fps},scale={width}:{height},format=yuva420p[pat];"
            f"[base][pat]overlay=0:0:enable='mod(n\\,2)':shortest=1,"
            f"setpts=N/{output_fps}/TB[out]"
        )
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-i", pattern_img,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
        ]
        
        # 统一使用 libx264 High + B-frames
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "high",
            "-bf", "2",
            "-b_strategy", "2",
            "-crf", "20",
            "-maxrate", "15000k", "-bufsize", "15000k",
            "-g", str(output_fps * 2),
            "-sc_threshold", "0",
        ])
        
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(output_fps),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ])
        
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        for line in process.stderr:
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(30 + (current / duration_total) * 60))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"CFR图案插帧(兜底)中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            raise RuntimeError("几何图案插帧处理失败（所有方案均失败）")
        
        if callback:
            callback(95, "图案插帧(CFR兜底)完成!")
        
        return output_path

    def _apply_kuaishou_mode_a(self, input_path, output_path, config,
                                width, height, fps, temp_dir, callback=None):
        """
        快手模式A — GPU高速重编码
        
        策略（基于夜猫模式A逆向，去掉帧数翻倍）：
        ============================
        - 编码器: h264_nvenc (GPU高速)
        - Profile: Main, 无B帧, refs=1
        - 音频: stereo→mono (改变音频指纹)
        - 容器: MKV (不同于原始MP4)
        - 不做帧数翻倍（减少体积膨胀，先测试纯重编码去重效果）
        """
        if callback:
            callback(10, "快手模式A(GPU高速): 分析视频参数...")
        
        # 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass
        
        if callback:
            callback(15, f"快手模式A: h264_nvenc + Main + mono + MKV...")
        
        # 输出路径改为MKV
        if not output_path.lower().endswith(".mkv"):
            output_path = os.path.splitext(output_path)[0] + ".mkv"
        
        # 音频降为mono（改变音频指纹）
        audio_fc = "[0:a]pan=mono|c0=0.5*c0+0.5*c1,aformat=sample_rates=44100[aout]"
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-filter_complex", audio_fc,
            "-map", "0:v",
            "-map", "[aout]",
        ]
        
        # h264_nvenc 编码（Main profile, no B-frames）
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-profile:v", "main",
            "-rc", "vbr",
            "-cq", "20",
            "-b:v", "0",
            "-maxrate", "15000k",
            "-bufsize", "15000k",
            "-g", str(int(fps * 4)),
            "-bf", "0",               # 无B帧
            "-refs", "1",
        ])
        
        cmd.extend([
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100",
            "-ac", "1",                # mono
            "-pix_fmt", "yuv420p",
        ])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=Lavf",
            ])
        
        cmd.append(output_path)
        
        if callback:
            callback(20, f"快手模式A: h264_nvenc重编码 + mono...")
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(20 + (current / duration_total) * 70))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"快手A处理中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            error_text = "".join(stderr_output[-30:])
            raise RuntimeError(f"快手模式A处理失败:\n{error_text}")
        
        if callback:
            callback(95, "快手模式A(GPU高速)完成!")
        
        return output_path

    def _apply_kuaishou_mode_b(self, input_path, output_path, config,
                                width, height, fps, temp_dir, callback=None):
        """
        快手模式B — CPU精确/444色度重编码
        
        策略（基于夜猫模式B逆向，去掉帧数翻倍）：
        ============================
        - 编码器: libx264 (CPU软编码)
        - Profile: High 4:4:4 Predictive, Level: 6.2
        - 像素格式: yuv444p（核心！色度不降采样，彻底改变色彩指纹hash）
        - 有B帧 (对齐夜猫)
        - 音频: stereo (保持)
        - 容器: MKV
        - 不做帧数翻倍（先测试纯444p重编码去重效果）
        
        核心原理：
        yuv420p→yuv444p 改变了色度采样方式，每个像素的色彩信息完全不同。
        平台的指纹hash基于像素值计算，444p重编码后指纹彻底废掉。
        """
        if callback:
            callback(10, "快手模式B(CPU精确/444p): 分析视频参数...")
        
        # 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass
        
        if callback:
            callback(15, f"快手模式B: libx264 + High 4:4:4 + yuv444p + MKV...")
        
        # 输出路径改为MKV
        if not output_path.lower().endswith(".mkv"):
            output_path = os.path.splitext(output_path)[0] + ".mkv"
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-map", "0:v",
            "-map", "0:a",
        ]
        
        # libx264 编码（High 4:4:4 Predictive + Level 6.2）
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-profile:v", "high444",     # High 4:4:4 Predictive
            "-level", "6.2",
            "-crf", "20",
            "-maxrate", "15000k",
            "-bufsize", "15000k",
            "-g", str(int(fps * 4)),
            "-bf", "2",                  # 有B帧
            "-b_strategy", "2",
            "-refs", "1",
            "-sc_threshold", "0",
        ])
        
        cmd.extend([
            "-pix_fmt", "yuv444p",       # 核心！444色度不降采样
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100",
        ])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"ENCODER=Lavf61.7.100",
            ])
        
        cmd.append(output_path)
        
        if callback:
            callback(20, f"快手模式B: libx264 High 4:4:4 + yuv444p...")
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(20 + (current / duration_total) * 70))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"快手B处理中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            error_text = "".join(stderr_output[-30:])
            raise RuntimeError(f"快手模式B处理失败:\n{error_text}")
        
        if callback:
            callback(95, "快手模式B(CPU/444p)完成!")
        
        return output_path
        
        return output_path

    def _apply_frame_replace(self, input_path, output_path, config, video_info, callback=None):
        """
        智能帧替换 v3 — 保持原始帧率，替换部分帧为"模糊化近似帧"（不闪烁）
        
        v3 修复闪烁问题：
        ==================
        v2问题: 替换帧是彩色几何图案 → 与内容差异极大 → 肉眼每秒看到10次闪烁
        v3方案: 替换帧改为"对当前帧做极度模糊+色偏+噪点"，视觉差异极小
        
        核心原理：
        1. 保持原始帧率（30fps）和帧数不变 → 平台检测风险最低
        2. 按固定间隔（每N帧）对选中帧施加强模糊+色彩偏移+噪点
        3. 替换帧在编码层面是全新数据（像素全变），改变视频指纹
        4. 替换帧在视觉层面与相邻帧近似（模糊版本），**不产生闪烁**
        5. libx264 High + B-frames + sc_threshold=0
        
        与v2的区别：
        - 不使用外部图案图片（不再overlay独立图片流）
        - 直接在视频滤镜链中用enable条件对选中帧做模糊+扰动
        - 完全不闪烁，因为替换帧是原始帧的模糊变体
        """
        if callback:
            callback(10, "智能帧替换v3: 分析视频参数...")
        
        # 获取视频尺寸和帧率
        width, height, fps = 1920, 1080, 30
        if video_info:
            for stream in video_info.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width", 1920))
                    height = int(stream.get("height", 1080))
                    fps_str = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        fps = round(int(num) / max(int(den), 1))
                    else:
                        fps = int(float(fps_str))
                    break
        
        # 如果启用上采样，目标分辨率改为1080p
        target_w, target_h = width, height
        if config.upscale_1080p and height < 1080:
            target_h = 1080
            target_w = int(width * (1080 / height))
            target_w = target_w + (target_w % 2)
        
        # 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass
        
        if callback:
            callback(15, f"智能帧替换v3: 每{config.replace_interval}帧模糊1帧, 跳过前{config.replace_skip_start}帧...")
        
        skip = config.replace_skip_start
        interval = config.replace_interval
        
        # 构建滤镜链 — 核心思路：
        # 1. 分流：原始流 + 模糊流
        # 2. 模糊流对每一帧做：强高斯模糊(boxblur=30:5) + 色偏(hue) + 噪点
        # 3. overlay条件：在选中帧位置用模糊流覆盖原始流
        # 4. 模糊帧看起来像"虚焦的同一画面"，不是完全不同的图案
        
        # 上采样滤镜
        vf_scale = ""
        if config.upscale_1080p and height < 1080:
            vf_scale = f"scale={target_w}:{target_h}:flags={config.upscale_method},"
        
        # 随机模糊参数和色偏
        blur_radius = random.randint(20, 40)
        blur_power = random.randint(3, 6)
        hue_shift = random.uniform(3, 8)  # 轻度色偏（3-8度，肉眼勉强可见）
        noise_str = random.randint(8, 15)
        
        # enable条件：帧号>=skip 且 (帧号-skip)%interval==0
        enable_expr = f"gte(n\\,{skip})*not(mod(n-{skip}\\,{interval}))"
        
        # 滤镜策略：使用 geq 或 boxblur + enable 条件
        # boxblur 的 enable 可以让选中帧被模糊，其余帧保持原样
        # 然后叠加噪点和色偏（也用enable条件）
        
        # --- 全局画面微调（对所有帧生效，来自平台预设） ---
        global_filters = []
        if config.adjust_brightness and config.brightness_value != 0:
            global_filters.append(f"eq=brightness={config.brightness_value:.3f}")
        if config.adjust_contrast and config.contrast_value != 1.0:
            global_filters.append(f"eq=contrast={config.contrast_value:.3f}")
        if config.adjust_saturation and config.saturation_value != 1.0:
            global_filters.append(f"eq=saturation={config.saturation_value:.3f}")
        if config.adjust_gamma and config.gamma_value != 1.0:
            global_filters.append(f"eq=gamma={config.gamma_value:.3f}")
        if config.hue_shift != 0:
            global_filters.append(f"hue=h={config.hue_shift:.1f}")
        if config.color_balance_rs != 0 or config.color_balance_gs != 0:
            global_filters.append(
                f"colorbalance=rs={config.color_balance_rs:.3f}:gs={config.color_balance_gs:.3f}"
            )
        if config.sharpen:
            global_filters.append("unsharp=5:5:0.8:5:5:0.0")
        if config.denoise:
            global_filters.append("hqdn3d=2:2:3:3")
        if config.crop_edges and config.crop_percent < 1.0:
            global_filters.append(
                f"crop=iw*{config.crop_percent:.4f}:ih*{config.crop_percent:.4f}"
            )
        if config.slight_rotation and config.rotation_angle != 0:
            angle_rad = config.rotation_angle * 3.14159 / 180
            global_filters.append(
                f"rotate={angle_rad:.6f}:fillcolor=black@0"
            )
        
        global_vf = ",".join(global_filters) + "," if global_filters else ""
        
        filter_complex = (
            f"[0:v]fps={fps},{vf_scale}setsar=1,"
            # 全局画面微调
            f"{global_vf}"
            # 选中帧做强高斯模糊（其余帧不受影响）
            f"boxblur=lr={blur_radius}:lp={blur_power}:enable='{enable_expr}',"
            # 选中帧叠加噪点
            f"noise=alls={noise_str}:allf=t+u:enable='{enable_expr}',"
            # 选中帧做色偏（帧替换专用，加在全局色偏之上）
            f"hue=h={hue_shift:.1f}:enable='{enable_expr}',"
            # 选中帧做轻度亮度偏移
            f"eq=brightness=0.03:enable='{enable_expr}',"
            # 时间戳归一化
            f"setpts=N/{fps}/TB"
            f"[out]"
        )
        
        # 构建编码命令
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
        ]
        
        # 底噪混入需要额外输入源
        if config.audio_noise_mix:
            cmd.extend([
                "-f", "lavfi", "-i",
                "anoisesrc=d=3600:c=pink:r=44100:a=0.002"
            ])
            # 音频滤镜链
            af_chain = ""
            af_parts = []
            if config.speed_change and config.speed_factor != 1.0:
                af_parts.append(f"atempo={config.speed_factor}")
            if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
                pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
                af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
                af_parts.append("aresample=44100")
            if af_parts:
                af_chain = ",".join(af_parts) + ","
            
            noise_db = config.audio_noise_db
            # 第二个输入（噪声源）的索引
            noise_idx = 1
            audio_fc = (
                f"[{noise_idx}:a]volume={noise_db}dB[noise];"
                f"[0:a]{af_chain}aformat=sample_rates=44100[amain];"
                f"[amain][noise]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            # 合并视频和音频 filter_complex
            full_fc = filter_complex + ";" + audio_fc
            cmd.extend(["-filter_complex", full_fc])
            cmd.extend(["-map", "[out]", "-map", "[aout]"])
        else:
            cmd.extend(["-filter_complex", filter_complex])
            cmd.extend(["-map", "[out]", "-map", "0:a?"])
        
        # 编码器选择（支持平台指定）
        codec = config.target_codec or "h264"
        if codec == "hevc":
            if config.gpu_acceleration:
                cmd.extend(["-c:v", "hevc_nvenc"])
            else:
                cmd.extend(["-c:v", "libx265", "-tag:v", "hvc1"])
        else:
            if config.gpu_acceleration:
                cmd.extend(["-c:v", "h264_nvenc"])
            else:
                cmd.extend(["-c:v", "libx264"])
        
        cmd.extend([
            "-preset", "medium",
            "-profile:v", "high" if codec == "h264" else "main",
            "-bf", "2",
        ])
        if codec == "h264":
            cmd.extend(["-b_strategy", "2"])
        
        # 码率控制（平台指定 > 默认）
        if config.target_bitrate:
            cmd.extend(["-b:v", config.target_bitrate])
            if config.max_bitrate:
                cmd.extend(["-maxrate", config.max_bitrate, "-bufsize", config.max_bitrate])
            else:
                cmd.extend(["-maxrate", config.target_bitrate, "-bufsize", config.target_bitrate])
        else:
            cmd.extend(["-crf", "20", "-maxrate", "15000k", "-bufsize", "15000k"])
        
        cmd.extend([
            "-g", str(fps * 4),         # GOP = 4秒
            "-sc_threshold", "0",        # 模糊帧不触发场景切换
            "-refs", "3",
        ])
        if codec == "h264":
            cmd.extend(["-direct-pred", "auto"])
        
        # H.264 Level（B站不二压等）
        if config.target_level:
            cmd.extend(["-level", config.target_level])
        
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(fps),              # 保持原始帧率
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ])
        
        # 音频滤镜（非底噪混入模式时）
        if not config.audio_noise_mix:
            af_parts = []
            if config.speed_change and config.speed_factor != 1.0:
                af_parts.append(f"atempo={config.speed_factor}")
            if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
                pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
                af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
                af_parts.append("aresample=44100")
            if af_parts:
                cmd.extend(["-af", ",".join(af_parts)])
        
        # 去尾
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)
        
        if callback:
            replace_pct = int(100 / interval)
            msg = f"智能帧替换v3: {fps}fps(不变), ~{replace_pct}%帧模糊替换(不闪烁)"
            if config.upscale_1080p:
                msg += f", {width}x{height}→{target_w}x{target_h}"
            callback(25, msg)
        
        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(25 + (current / duration_total) * 65))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"帧替换v3处理中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
        
        process.wait()
        
        if process.returncode != 0:
            error_text = "".join(stderr_output[-30:])
            raise RuntimeError(f"智能帧替换v3处理失败:\n{error_text}")
        
        if callback:
            callback(95, "智能帧替换v3完成!(模糊替换,不闪烁)")
        
        return output_path

    def _apply_frame_replace_v4(self, input_path, output_path, config, video_info, callback=None):
        """
        帧替换 v4 — 预生成混淆帧 + overlay替换（夜猫方式）
        
        核心原理：
        ==================
        1. 从视频提取第一帧
        2. 对该帧做强模糊+色偏+噪点+亮度偏移 → 生成一张固定的"混淆帧"PNG
        3. 用overlay滤镜按间隔把这张图覆盖到视频帧上（enable条件控制）
        4. 所有被替换的帧都是同一张图 → 跟夜猫分析结果一致
        5. 平台发布后重编码会洗掉这些替换帧，播放效果正常
        
        与v3的区别：
        - v3: 对每帧实时做enable条件模糊（每帧模糊结果略有不同）
        - v4: 预生成一张固定混淆帧图片，按间隔overlay上去（所有替换帧完全相同）
        - v4更接近夜猫的实际做法（夜鹰分析看到的"隔一阵出现相同的奇怪图"）
        """
        import tempfile
        
        if callback:
            callback(10, "帧替换v4: 分析视频参数...")
        
        # 获取视频尺寸和帧率
        width, height, fps = 1920, 1080, 30
        if video_info:
            for stream in video_info.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width", 1920))
                    height = int(stream.get("height", 1080))
                    fps_str = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        fps = round(int(num) / max(int(den), 1))
                    else:
                        fps = int(float(fps_str))
                    break
        
        # 如果启用上采样，目标分辨率改为1080p
        target_w, target_h = width, height
        if config.upscale_1080p and height < 1080:
            target_h = 1080
            target_w = int(width * (1080 / height))
            target_w = target_w + (target_w % 2)
        
        # 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="tugou_v4_")
        first_frame_path = os.path.join(temp_dir, "first_frame.png")
        confuse_frame_path = os.path.join(temp_dir, "confuse_frame.png")
        
        try:
            if callback:
                callback(12, "帧替换v4: 提取首帧并生成混淆帧...")
            
            # ---- 第1步：提取第一帧 ----
            extract_cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_path,
                "-vframes", "1",
                "-q:v", "2",
                first_frame_path
            ]
            self._run(extract_cmd, capture_output=True, timeout=30)
            
            if not os.path.exists(first_frame_path):
                raise RuntimeError("提取首帧失败")
            
            # ---- 第2步：对首帧做强变换生成混淆帧 ----
            # 随机参数（每次处理都不同，增加随机性）
            blur_radius = random.randint(25, 45)
            blur_power = random.randint(4, 7)
            hue_val = random.uniform(15, 40)  # 较大色偏（因为只有一张图）
            noise_strength = random.randint(20, 40)
            bright_shift = random.uniform(0.05, 0.15)
            sat_shift = random.uniform(0.6, 0.85)
            
            # 用FFmpeg处理首帧 → 混淆帧
            # 强模糊 + 色偏 + 噪点 + 亮度/饱和度偏移
            confuse_vf = (
                f"boxblur=lr={blur_radius}:lp={blur_power},"
                f"hue=h={hue_val:.1f}:s={sat_shift:.2f},"
                f"noise=alls={noise_strength}:allf=t+u,"
                f"eq=brightness={bright_shift:.3f}:contrast=0.85"
            )
            
            # 如果有上采样，混淆帧也要匹配目标尺寸
            if config.upscale_1080p and height < 1080:
                confuse_vf = f"scale={target_w}:{target_h}:flags={config.upscale_method}," + confuse_vf
            
            confuse_cmd = [
                self.ffmpeg_path, "-y",
                "-i", first_frame_path,
                "-vf", confuse_vf,
                "-q:v", "2",
                confuse_frame_path
            ]
            self._run(confuse_cmd, capture_output=True, timeout=30)
            
            if not os.path.exists(confuse_frame_path):
                raise RuntimeError("生成混淆帧失败")
            
            if callback:
                callback(15, f"帧替换v4: 混淆帧已生成, 每{config.replace_interval}帧替换1帧...")
            
            # ---- 第3步：构建overlay滤镜链 ----
            skip = config.replace_skip_start
            interval = config.replace_interval
            
            # enable条件：帧号>=skip 且 (帧号-skip)%interval==0
            enable_expr = f"gte(n\\,{skip})*not(mod(n-{skip}\\,{interval}))"
            
            # 上采样滤镜
            vf_scale = ""
            if config.upscale_1080p and height < 1080:
                vf_scale = f"scale={target_w}:{target_h}:flags={config.upscale_method},"
            
            # --- 全局画面微调（对所有帧生效） ---
            global_filters = []
            if config.adjust_brightness and config.brightness_value != 0:
                global_filters.append(f"eq=brightness={config.brightness_value:.3f}")
            if config.adjust_contrast and config.contrast_value != 1.0:
                global_filters.append(f"eq=contrast={config.contrast_value:.3f}")
            if config.adjust_saturation and config.saturation_value != 1.0:
                global_filters.append(f"eq=saturation={config.saturation_value:.3f}")
            if config.adjust_gamma and config.gamma_value != 1.0:
                global_filters.append(f"eq=gamma={config.gamma_value:.3f}")
            if config.hue_shift != 0:
                global_filters.append(f"hue=h={config.hue_shift:.1f}")
            if config.color_balance_rs != 0 or config.color_balance_gs != 0:
                global_filters.append(
                    f"colorbalance=rs={config.color_balance_rs:.3f}:gs={config.color_balance_gs:.3f}"
                )
            if config.sharpen:
                global_filters.append("unsharp=5:5:0.8:5:5:0.0")
            if config.denoise:
                global_filters.append("hqdn3d=2:2:3:3")
            if config.crop_edges and config.crop_percent < 1.0:
                global_filters.append(
                    f"crop=iw*{config.crop_percent:.4f}:ih*{config.crop_percent:.4f}"
                )
            if config.slight_rotation and config.rotation_angle != 0:
                angle_rad = config.rotation_angle * 3.14159 / 180
                global_filters.append(
                    f"rotate={angle_rad:.6f}:fillcolor=black@0"
                )
            
            global_vf = ",".join(global_filters) + "," if global_filters else ""
            
            # filter_complex:
            # 输入0=视频, 输入1=混淆帧图片(loop循环)
            # 视频流做全局微调 → 混淆帧overlay上去(enable条件控制)
            filter_complex = (
                # 视频流：帧率+缩放+全局滤镜
                f"[0:v]fps={fps},{vf_scale}setsar=1,{global_vf}"
                f"format=yuv420p[vmain];"
                # 混淆帧流：loop循环+缩放到相同尺寸
                f"[1:v]loop=loop=-1:size=1:start=0,"
                f"scale={target_w}:{target_h}:flags=bilinear,"
                f"setsar=1,format=yuv420p[vconf];"
                # overlay：在选中帧位置用混淆帧完全覆盖原始帧
                f"[vmain][vconf]overlay=0:0:enable='{enable_expr}',"
                # 时间戳归一化
                f"setpts=N/{fps}/TB"
                f"[out]"
            )
            
            # ---- 第4步：构建编码命令 ----
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_path,
                "-loop", "1", "-i", confuse_frame_path,
            ]
            
            # 底噪混入需要额外输入源
            if config.audio_noise_mix:
                cmd.extend([
                    "-f", "lavfi", "-i",
                    "anoisesrc=d=3600:c=pink:r=44100:a=0.002"
                ])
                af_chain = ""
                af_parts = []
                if config.speed_change and config.speed_factor != 1.0:
                    af_parts.append(f"atempo={config.speed_factor}")
                if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
                    pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
                    af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
                    af_parts.append("aresample=44100")
                if af_parts:
                    af_chain = ",".join(af_parts) + ","
                
                noise_db = config.audio_noise_db
                noise_idx = 2  # 视频=0, 混淆帧=1, 噪声源=2
                audio_fc = (
                    f"[{noise_idx}:a]volume={noise_db}dB[noise];"
                    f"[0:a]{af_chain}aformat=sample_rates=44100[amain];"
                    f"[amain][noise]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                )
                full_fc = filter_complex + ";" + audio_fc
                cmd.extend(["-filter_complex", full_fc])
                cmd.extend(["-map", "[out]", "-map", "[aout]"])
            else:
                cmd.extend(["-filter_complex", filter_complex])
                cmd.extend(["-map", "[out]", "-map", "0:a?"])
            
            # 编码器选择
            codec = config.target_codec or "h264"
            if codec == "hevc":
                if config.gpu_acceleration:
                    cmd.extend(["-c:v", "hevc_nvenc"])
                else:
                    cmd.extend(["-c:v", "libx265", "-tag:v", "hvc1"])
            else:
                if config.gpu_acceleration:
                    cmd.extend(["-c:v", "h264_nvenc"])
                else:
                    cmd.extend(["-c:v", "libx264"])
            
            cmd.extend([
                "-preset", "medium",
                "-profile:v", "high" if codec == "h264" else "main",
                "-bf", "2",
            ])
            if codec == "h264":
                cmd.extend(["-b_strategy", "2"])
            
            # 码率控制
            if config.target_bitrate:
                cmd.extend(["-b:v", config.target_bitrate])
                if config.max_bitrate:
                    cmd.extend(["-maxrate", config.max_bitrate, "-bufsize", config.max_bitrate])
                else:
                    cmd.extend(["-maxrate", config.target_bitrate, "-bufsize", config.target_bitrate])
            else:
                cmd.extend(["-crf", "20", "-maxrate", "15000k", "-bufsize", "15000k"])
            
            cmd.extend([
                "-g", str(fps * 4),
                "-sc_threshold", "0",
                "-refs", "3",
            ])
            if codec == "h264":
                cmd.extend(["-direct-pred", "auto"])
            
            if config.target_level:
                cmd.extend(["-level", config.target_level])
            
            cmd.extend([
                "-c:a", "aac", "-b:a", "192k",
                "-r", str(fps),
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest",  # 以最短流为准（防止loop无限）
            ])
            
            # 音频滤镜（非底噪混入模式时）
            if not config.audio_noise_mix:
                af_parts = []
                if config.speed_change and config.speed_factor != 1.0:
                    af_parts.append(f"atempo={config.speed_factor}")
                if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
                    pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
                    af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
                    af_parts.append("aresample=44100")
                if af_parts:
                    cmd.extend(["-af", ",".join(af_parts)])
            
            # 去尾
            if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
                end_time = duration_total - config.trim_tail_seconds
                if end_time > 0:
                    cmd.extend(["-t", f"{end_time:.3f}"])
            
            # 随机元数据
            if config.modify_metadata:
                cmd.extend([
                    "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                    "-metadata", f"comment={uuid.uuid4().hex}",
                    "-metadata", f"creation_time={int(time.time())}",
                    "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
                ])
            
            cmd.append(output_path)
            
            if callback:
                replace_pct = int(100 / interval)
                msg = f"帧替换v4(夜猫方式): {fps}fps, ~{replace_pct}%帧替换为预生成混淆帧"
                if config.upscale_1080p:
                    msg += f", {width}x{height}->{target_w}x{target_h}"
                callback(25, msg)
            
            # ---- 第5步：执行编码 ----
            process = self._popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            
            stderr_output = []
            for line in process.stderr:
                stderr_output.append(line)
                if callback and duration_total:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                    if time_match:
                        h, m, s, cs = map(int, time_match.groups())
                        current = h * 3600 + m * 60 + s + cs / 100.0
                        progress = min(90, int(25 + (current / duration_total) * 65))
                        speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                        speed = speed_match.group(1) if speed_match else "?"
                        callback(progress, f"帧替换v4处理中... {current:.1f}s / {duration_total:.1f}s ({speed}x)")
            
            process.wait()
            
            if process.returncode != 0:
                error_text = "".join(stderr_output[-30:])
                raise RuntimeError(f"帧替换v4处理失败:\n{error_text}")
            
            if callback:
                callback(95, "帧替换v4完成!(预生成混淆帧overlay,发布后自动恢复)")
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(first_frame_path):
                    os.remove(first_frame_path)
                if os.path.exists(confuse_frame_path):
                    os.remove(confuse_frame_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception:
                pass
        
        return output_path

    def _apply_frame_stuffing(self, input_path, output_path, config, video_info, callback=None):
        """
        帧膨胀处理 - 在视频帧间插入填充帧

        原理:
        1. 大幅提升视频帧率（如30fps→120fps）
        2. 在原始帧之间插入静态图片帧（噪点/渐变/纯色/自定义图）
        3. 视频文件体积暴增，MD5/帧特征/文件指纹完全改变
        4. 平台上传后二次编码会自动压缩掉冗余帧，播放效果正常

        实现方式:
        - 方案A (interleave): 用ffmpeg的tpad/loop+overlay交替插入
        - 方案B (boost_fps): 帧率倍增+帧复制+微调
        - 方案C (append): 在视频前后追加短片段
        """
        if callback:
            callback(12, "帧膨胀处理: 分析视频参数...")

        # 获取视频尺寸和帧率
        width, height, fps = 1920, 1080, 30
        if video_info:
            for stream in video_info.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width", 1920))
                    height = int(stream.get("height", 1080))
                    # 解析帧率
                    fps_str = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        fps = round(int(num) / max(int(den), 1))
                    else:
                        fps = int(float(fps_str))
                    break

        # 计算目标帧率
        if config.stuffing_target_fps > 0:
            target_fps = config.stuffing_target_fps
        else:
            target_fps = int(fps * config.stuffing_ratio)
            target_fps = min(target_fps, 240)  # 上限240fps

        if callback:
            callback(15, f"帧膨胀: {fps}fps → {target_fps}fps (膨胀{config.stuffing_ratio:.1f}x)")

        # 创建临时工作目录
        temp_dir = os.path.join(os.path.dirname(output_path), f"_stuffing_temp_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            if config.stuffing_mode == "kuaishou_a":
                return self._apply_kuaishou_mode_a(
                    input_path, output_path, config,
                    width, height, fps, temp_dir, callback
                )
            elif config.stuffing_mode == "kuaishou_b":
                return self._apply_kuaishou_mode_b(
                    input_path, output_path, config,
                    width, height, fps, temp_dir, callback
                )
            elif config.stuffing_mode == "interleave":
                return self._stuffing_interleave(
                    input_path, output_path, config, 
                    width, height, fps, target_fps, temp_dir, callback
                )
            elif config.stuffing_mode == "boost_fps":
                return self._stuffing_boost_fps(
                    input_path, output_path, config,
                    width, height, fps, target_fps, temp_dir, callback
                )
            elif config.stuffing_mode == "geometric":
                return self._stuffing_geometric_interleave(
                    input_path, output_path, config,
                    width, height, fps, target_fps, temp_dir, callback
                )
            elif config.stuffing_mode == "append":
                return self._stuffing_append(
                    input_path, output_path, config,
                    width, height, fps, temp_dir, callback
                )
            else:
                # 默认用interleave
                return self._stuffing_interleave(
                    input_path, output_path, config,
                    width, height, fps, target_fps, temp_dir, callback
                )
        finally:
            # 清理临时文件
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _stuffing_interleave(self, input_path, output_path, config, 
                             width, height, fps, target_fps, temp_dir, callback):
        """
        交替插入模式 - 帧率提升 + 强随机噪点 + 深度视觉调整 + CBR高码率
        
        与 boost_fps 的区别：
        - 更强的视觉扰动（更高噪点、更大色彩偏移）
        - 配合 config 里的深度去重参数（旋转、镜像、降噪+锐化等）
        - 适合"帧膨胀+深度去重"预设
        """
        if callback:
            callback(20, f"帧膨胀(交替插入): {fps}fps -> {target_fps}fps...")

        # 获取视频时长
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass

        # ---- 构建完整滤镜链 ----
        vf_parts = []
        
        # 1. 掐头(来自config)
        if config.trim_head and config.trim_head_frames > 0:
            vf_parts.append(f"trim=start_frame={config.trim_head_frames}")
            vf_parts.append("setpts=PTS-STARTPTS")
        
        # 2. 帧率提升
        vf_parts.append(f"fps={target_fps}")
        
        # 3. 微弱随机噪点（仅改变像素值，肉眼几乎不可见）
        noise_strength = random.randint(3, 8)
        vf_parts.append(f"noise=alls={noise_strength}:allf=t+u")
        
        # 4. hue微偏移
        hue_shift = random.uniform(-2, 2)
        vf_parts.append(f"hue=h={hue_shift:.2f}")
        
        # 5. 色彩调整
        eq_parts = []
        brightness = random.uniform(0.015, 0.03)
        if config.adjust_brightness:
            brightness = max(brightness, config.brightness_value)
        eq_parts.append(f"brightness={brightness:.4f}")
        
        contrast = random.uniform(1.03, 1.06)
        if config.adjust_contrast:
            contrast = max(contrast, config.contrast_value)
        eq_parts.append(f"contrast={contrast:.4f}")
        
        saturation = random.uniform(1.02, 1.05)
        if config.adjust_saturation:
            saturation = max(saturation, config.saturation_value)
        eq_parts.append(f"saturation={saturation:.4f}")
        
        if config.adjust_gamma:
            eq_parts.append(f"gamma={config.gamma_value}")
        
        vf_parts.append(f"eq={':'.join(eq_parts)}")
        
        # 6. 轻度锐化（不再放大噪点）
        vf_parts.append("unsharp=5:5:0.3:5:5:0.0")
        
        # 7. 降噪(来自config) - 在锐化后做可增加独特纹理
        if config.denoise:
            vf_parts.append("hqdn3d=2:2:3:3")
        
        # 8. 边缘裁剪
        if config.crop_edges and config.crop_percent < 1.0:
            vf_parts.append(
                f"crop=iw*{config.crop_percent}:ih*{config.crop_percent}:"
                f"(iw-iw*{config.crop_percent})/2:(ih-ih*{config.crop_percent})/2"
            )
        
        # 9. 轻微旋转(来自config)
        if config.slight_rotation and config.rotation_angle > 0:
            angle_rad = config.rotation_angle * 3.14159265 / 180.0
            angle_rad += random.uniform(-0.002, 0.002)
            vf_parts.append(f"rotate={angle_rad:.6f}:fillcolor=black:bilinear=1")
        
        # 10. 水平镜像(来自config)
        if config.horizontal_flip:
            vf_parts.append("hflip")
        
        # 11. 变速(来自config)
        if config.speed_change and config.speed_factor != 1.0:
            vf_parts.append(f"setpts=PTS/{config.speed_factor}")
        
        vf_chain = ",".join(vf_parts)
        
        # ---- 音频滤镜 ----
        af_parts = []
        if config.speed_change and config.speed_factor != 1.0:
            af_parts.append(f"atempo={config.speed_factor}")
        if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
            pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
            af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
            af_parts.append("aresample=44100")

        # ---- 完整FFmpeg命令 ----
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", vf_chain,
        ]
        
        if af_parts:
            cmd.extend(["-af", ",".join(af_parts)])
        
        # CBR高码率编码
        cmd.extend([
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", "20000k", "-minrate", "15000k",
            "-maxrate", "25000k", "-bufsize", "30000k",
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(target_fps),
            "-pix_fmt", "yuv420p",
        ])
        
        # 去尾
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)

        if callback:
            callback(30, f"帧膨胀处理中 (噪点强度: {noise_strength})...")

        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        for line in process.stderr:
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(30 + (current / duration_total) * 60))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"帧膨胀中... {current:.1f}s / {duration_total:.1f}s (速度: {speed}x)")

        process.wait()
        
        if process.returncode != 0:
            raise RuntimeError("帧膨胀(交替插入)处理失败")

        if callback:
            callback(90, "帧膨胀处理完成!")

        return output_path

    def _stuffing_boost_fps(self, input_path, output_path, config,
                            width, height, fps, target_fps, temp_dir, callback):
        """
        帧率倍增模式 - 快速帧率提升 + 强随机噪点 + CBR高码率
        
        直接一步到位输出最终文件(不需要第二阶段重编码):
        1. 用 fps 滤镜将帧率从 30fps 提升到 90fps（帧复制填充）
        2. 叠加强随机噪点(alls=35-50)，使每一帧都有独特的像素内容
        3. 合并 config 中的视觉调整（裁剪、亮度、变速等）
        4. 使用 CBR 高码率编码(20Mbps)，强制维持大文件体积
        
        实测效果: 61.5MB -> 600-700MB (10x+)
        """
        if callback:
            callback(20, f"帧率倍增: {fps}fps -> {target_fps}fps + 强化随机噪点...")

        # 获取视频时长用于进度显示
        duration_total = None
        try:
            probe_cmd = [
                self.ffprobe_path, "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            result = self._run(probe_cmd, capture_output=True, timeout=15)
            duration_total = float(result.stdout.strip())
        except Exception:
            pass

        # ---- 构建完整滤镜链（合并帧膨胀+视觉调整） ----
        vf_parts = []
        
        # 1. 帧率提升(核心)
        vf_parts.append(f"fps={target_fps}")
        
        # 2. 微弱随机噪点(核心) - 让每帧像素值略有不同，肉眼几乎不可见
        noise_strength = random.randint(3, 8)
        vf_parts.append(f"noise=alls={noise_strength}:allf=t+u")
        
        # 3. hue微偏移 - 进一步打破帧间相似度
        hue_shift = random.uniform(-3, 3)
        vf_parts.append(f"hue=h={hue_shift:.2f}")
        
        # 4. 色彩调整(合并config的亮度/对比度/饱和度 + 帧膨胀自身的微调)
        eq_parts = []
        brightness = random.uniform(0.01, 0.025)
        if config.adjust_brightness:
            brightness = max(brightness, config.brightness_value)
        eq_parts.append(f"brightness={brightness:.4f}")
        
        contrast = random.uniform(1.02, 1.05)
        if config.adjust_contrast:
            contrast = max(contrast, config.contrast_value)
        eq_parts.append(f"contrast={contrast:.4f}")
        
        saturation = random.uniform(1.01, 1.04)
        if config.adjust_saturation:
            saturation = max(saturation, config.saturation_value)
        eq_parts.append(f"saturation={saturation:.4f}")
        
        if config.adjust_gamma:
            eq_parts.append(f"gamma={config.gamma_value}")
        
        vf_parts.append(f"eq={':'.join(eq_parts)}")
        
        # 5. 轻度锐化（不再放大噪点）
        vf_parts.append("unsharp=5:5:0.3:5:5:0.0")
        
        # 6. 边缘裁剪(来自config)
        if config.crop_edges and config.crop_percent < 1.0:
            vf_parts.append(
                f"crop=iw*{config.crop_percent}:ih*{config.crop_percent}:"
                f"(iw-iw*{config.crop_percent})/2:(ih-ih*{config.crop_percent})/2"
            )
        
        # 7. 变速(来自config)
        if config.speed_change and config.speed_factor != 1.0:
            vf_parts.append(f"setpts=PTS/{config.speed_factor}")
        
        vf_chain = ",".join(vf_parts)
        
        # ---- 构建音频滤镜 ----
        af_parts = []
        if config.speed_change and config.speed_factor != 1.0:
            af_parts.append(f"atempo={config.speed_factor}")
        if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
            pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
            af_parts.append(f"asetrate=44100*{pitch_factor:.6f}")
            af_parts.append("aresample=44100")

        # ---- 构建完整FFmpeg命令 ----
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", vf_chain,
        ]
        
        # 音频滤镜
        if af_parts:
            cmd.extend(["-af", ",".join(af_parts)])
        
        # CBR高码率编码 - 20Mbps目标码率，确保大文件输出
        cmd.extend([
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", "20000k", "-minrate", "15000k",
            "-maxrate", "25000k", "-bufsize", "30000k",
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(target_fps),
            "-pix_fmt", "yuv420p",
        ])
        
        # 去尾(来自config)
        if config.trim_tail and config.trim_tail_seconds > 0 and duration_total:
            end_time = duration_total - config.trim_tail_seconds
            if end_time > 0:
                cmd.extend(["-t", f"{end_time:.3f}"])
        
        # 随机元数据
        if config.modify_metadata:
            cmd.extend([
                "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={int(time.time())}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])
        
        cmd.append(output_path)

        if callback:
            callback(30, f"帧率倍增处理中 (噪点强度: {noise_strength})...")

        process = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        for line in process.stderr:
            if callback and duration_total:
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if time_match:
                    h, m, s, cs = map(int, time_match.groups())
                    current = h * 3600 + m * 60 + s + cs / 100.0
                    progress = min(90, int(30 + (current / duration_total) * 60))
                    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                    speed = speed_match.group(1) if speed_match else "?"
                    callback(progress, f"帧率倍增中... {current:.1f}s / {duration_total:.1f}s (速度: {speed}x)")

        process.wait()
        
        if process.returncode != 0:
            raise RuntimeError("帧率倍增处理失败")

        if callback:
            callback(95, "帧率倍增完成!")

        return output_path

    def _stuffing_append(self, input_path, output_path, config,
                         width, height, fps, temp_dir, callback):
        """
        前后追加模式 - 在视频前后追加短片段(填充帧组成)
        这些片段在发布后会被平台裁剪/压缩掉，但改变了文件指纹
        """
        if callback:
            callback(20, "生成前缀/后缀填充片段...")

        # 生成0.5-2秒的填充片段
        prefix_duration = random.uniform(0.3, 1.0)
        suffix_duration = random.uniform(0.3, 1.0)

        prefix_video = os.path.join(temp_dir, "prefix.mp4")
        suffix_video = os.path.join(temp_dir, "suffix.mp4")

        for vid_path, dur in [(prefix_video, prefix_duration), (suffix_video, suffix_duration)]:
            color = f"#{random.randint(0, 0xFFFFFF):06x}"
            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "lavfi", "-i",
                f"color=c={color}:size={width}x{height}:rate={fps}:d={dur:.2f},"
                f"noise=alls={random.randint(20,40)}:allf=t+u",
                "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{dur:.2f}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                vid_path
            ]
            self._run(cmd, capture_output=True, timeout=30)

        if callback:
            callback(40, "重编码原始视频...")

        # 确保原始视频格式兼容concat
        reformatted = os.path.join(temp_dir, "main_reformatted.mp4")
        reformat_cmd = [
            self.ffmpeg_path, "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(fps), "-pix_fmt", "yuv420p",
            reformatted
        ]
        self._run(reformat_cmd, capture_output=True, timeout=600)

        if callback:
            callback(70, "拼接视频片段...")

        # 使用concat demuxer合并
        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            f.write(f"file '{prefix_video}'\n")
            f.write(f"file '{reformatted}'\n")
            f.write(f"file '{suffix_video}'\n")

        concat_cmd = [
            self.ffmpeg_path, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-metadata", f"title=vid_{uuid.uuid4().hex[:12]}",
            "-metadata", f"comment={uuid.uuid4().hex}",
            output_path
        ]
        self._run(concat_cmd, capture_output=True, timeout=600)

        if callback:
            callback(95, "前后追加处理完成!")

        return output_path

    def _build_video_filters(self, config: DedupConfig, video_info=None):
        """构建FFmpeg视频滤镜链"""
        filters = []

        # 1. 掐头 (trim)
        if config.trim_head and config.trim_head_frames > 0:
            filters.append(f"trim=start_frame={config.trim_head_frames}")
            filters.append("setpts=PTS-STARTPTS")  # 重置时间戳

        # 2. 色彩调整 (eq滤镜)
        eq_parts = []
        if config.adjust_brightness:
            eq_parts.append(f"brightness={config.brightness_value}")
        if config.adjust_contrast:
            eq_parts.append(f"contrast={config.contrast_value}")
        if config.adjust_saturation:
            eq_parts.append(f"saturation={config.saturation_value}")
        if config.adjust_gamma:
            eq_parts.append(f"gamma={config.gamma_value}")
        if eq_parts:
            filters.append(f"eq={':'.join(eq_parts)}")

        # 3. 边缘裁剪
        if config.crop_edges and config.crop_percent < 1.0:
            filters.append(
                f"crop=iw*{config.crop_percent}:ih*{config.crop_percent}:"
                f"(iw-iw*{config.crop_percent})/2:(ih-ih*{config.crop_percent})/2"
            )

        # 4. 轻微旋转
        if config.slight_rotation and config.rotation_angle > 0:
            angle_rad = config.rotation_angle * 3.14159265 / 180.0
            # 添加微小随机偏移增加唯一性
            angle_rad += random.uniform(-0.002, 0.002)
            filters.append(
                f"rotate={angle_rad:.6f}:fillcolor=black:bilinear=1"
            )

        # 5. 水平镜像
        if config.horizontal_flip:
            filters.append("hflip")

        # 6. 锐化
        if config.sharpen:
            filters.append("unsharp=5:5:0.8:5:5:0.0")

        # 7. 降噪
        if config.denoise:
            filters.append("hqdn3d=2:2:3:3")

        # 7.5 色相偏移（平台专属）
        if config.hue_shift != 0:
            filters.append(f"hue=h={config.hue_shift:.1f}")

        # 7.6 色彩平衡（平台专属）
        if config.color_balance_rs != 0 or config.color_balance_gs != 0:
            filters.append(
                f"colorbalance=rs={config.color_balance_rs:.3f}:gs={config.color_balance_gs:.3f}"
            )

        # 8. 不可见水印 (随机噪点叠加)
        if config.add_invisible_watermark:
            # 添加极微弱的随机噪点，人眼不可见但改变像素值
            filters.append(f"noise=alls={random.randint(1, 3)}:allf=t+u")

        # 9. 变速
        if config.speed_change and config.speed_factor != 1.0:
            filters.append(f"setpts=PTS/{config.speed_factor}")

        # 10. 上采样到1080p（如启用）
        if config.upscale_1080p:
            # 获取原始高度，只在低于1080p时上采样
            orig_h = 1080
            if video_info:
                for stream in video_info.get("streams", []):
                    if stream.get("codec_type") == "video":
                        orig_h = int(stream.get("height", 1080))
                        break
            if orig_h < 1080:
                filters.append(f"scale=-2:1080:flags={config.upscale_method}")

        # 11. 输出分辨率（手动指定，优先级高于上采样）
        if config.output_resolution:
            w, h = config.output_resolution.split("x")
            filters.append(f"scale={w}:{h}")

        # 12. 输出帧率
        if config.output_fps > 0:
            filters.append(f"fps={config.output_fps}")

        return filters

    def _build_audio_filters(self, config: DedupConfig):
        """构建FFmpeg音频滤镜链"""
        filters = []

        # 音频变速（与视频同步）
        if config.speed_change and config.speed_factor != 1.0:
            filters.append(f"atempo={config.speed_factor}")

        # 音频变调
        if config.audio_pitch_shift and config.audio_pitch_semitones != 0:
            # asetrate改变采样率来变调，aresample恢复采样率
            pitch_factor = 2 ** (config.audio_pitch_semitones / 12.0)
            filters.append(f"asetrate=44100*{pitch_factor:.6f}")
            filters.append("aresample=44100")

        return filters

    def _build_audio_cmd_extra(self, config: DedupConfig, input_path):
        """构建音频处理的额外FFmpeg参数（底噪混入等需要额外输入源的功能）"""
        extra_inputs = []
        extra_filter = []

        if config.audio_noise_mix:
            # 生成粉噪并以指定dB混入
            # 使用amix或者amerge，这里通过filter_complex实现
            extra_inputs.extend([
                "-f", "lavfi", "-i",
                f"anoisesrc=d=3600:c=pink:r=44100:a=0.002"
            ])
            # 需要在调用处组合 filter_complex
            extra_filter.append(
                f"[1:a]volume={config.audio_noise_db}dB[noise];"
                f"[0:a][noise]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )

        return extra_inputs, extra_filter

    def _get_quality_params(self, config: DedupConfig):
        """根据质量设置和平台参数获取编码参数"""
        params = []

        # 确定编码器
        codec = config.target_codec or "h264"

        if config.gpu_acceleration:
            if codec == "hevc":
                params.extend(["-c:v", "hevc_nvenc"])
            else:
                params.extend(["-c:v", "h264_nvenc"])
            if config.output_quality == "high":
                params.extend(["-preset", "p7", "-cq", "18"])
            elif config.output_quality == "medium":
                params.extend(["-preset", "p4", "-cq", "23"])
            else:
                params.extend(["-preset", "p1", "-cq", "28"])
        else:
            if codec == "hevc":
                params.extend(["-c:v", "libx265"])
                params.extend(["-tag:v", "hvc1"])  # 兼容性标签
            else:
                params.extend(["-c:v", "libx264"])

            # 如果有平台指定的目标码率，优先使用
            if config.target_bitrate:
                params.extend(["-b:v", config.target_bitrate])
                if config.max_bitrate:
                    params.extend(["-maxrate", config.max_bitrate])
                    params.extend(["-bufsize", config.max_bitrate])
                else:
                    # 默认maxrate = 1.5x target
                    params.extend(["-maxrate", config.target_bitrate])
                    params.extend(["-bufsize", config.target_bitrate])
            else:
                # 使用质量预设
                if config.output_quality == "high":
                    params.extend([
                        "-preset", "slow",
                        "-crf", "18",
                        "-b:v", "15000k",
                        "-maxrate", "20000k",
                        "-bufsize", "20000k",
                    ])
                elif config.output_quality == "medium":
                    params.extend([
                        "-preset", "medium",
                        "-crf", "23",
                        "-b:v", "8000k",
                        "-maxrate", "12000k",
                        "-bufsize", "12000k",
                    ])
                else:
                    params.extend([
                        "-preset", "fast",
                        "-crf", "28",
                        "-b:v", "4000k",
                        "-maxrate", "6000k",
                        "-bufsize", "6000k",
                    ])

        # H.264 Level（B站不二压需要 Level 5）
        if config.target_level:
            params.extend(["-level", config.target_level])

        # 音频编码
        params.extend(["-c:a", "aac", "-b:a", "192k"])

        return params

    def process(
        self,
        input_path: str,
        output_path: str,
        config: DedupConfig = None,
        preset: str = None,
        callback: Callable = None,
    ) -> str:
        """
        执行视频去重处理

        :param input_path: 输入视频路径
        :param output_path: 输出视频路径
        :param config: 去重配置(与preset二选一)
        :param preset: 预设模式名称
        :param callback: 进度回调 callback(percent, message)
        :return: 输出文件路径
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"输入文件不存在: {input_path}")

        # 使用预设或自定义配置
        if preset and preset in PRESETS:
            config = PRESETS[preset]
        elif config is None:
            config = DedupConfig()  # 默认中度去重

        # 输出文件名增加时间戳后缀
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        base, ext = os.path.splitext(output_path)
        output_path = f"{base}{ts}{ext}"

        if callback:
            callback(5, "正在分析视频信息...")

        # 获取视频信息
        video_info = self.get_video_info(input_path)

        # ---- 智能帧替换处理（优先级最高，最隐蔽） ----
        if config.frame_replace:
            mode_label = "v4预生成混淆帧" if config.replace_mode == "v4" else "v3实时模糊"
            if callback:
                callback(8, f"启动帧替换处理({mode_label})...")
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            try:
                if config.replace_mode == "v4":
                    self._apply_frame_replace_v4(
                        input_path, output_path, config, video_info, callback
                    )
                else:
                    self._apply_frame_replace(
                        input_path, output_path, config, video_info, callback
                    )
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                    if callback:
                        output_size = os.path.getsize(output_path) / 1024 / 1024
                        input_size = os.path.getsize(input_path) / 1024 / 1024
                        ratio = output_size / input_size if input_size > 0 else 1.0
                        callback(100, f"处理完成! 输出: {output_size:.1f}MB (原始: {input_size:.1f}MB, {ratio:.1f}x)")
                    return output_path
                else:
                    if callback:
                        callback(12, "帧替换输出异常，回退到常规处理...")
            except Exception as e:
                if callback:
                    callback(12, f"帧替换失败({e})，回退到常规处理...")

        # ---- 帧膨胀处理 ----
        # 帧膨胀模式直接一次性输出最终文件（不经过第二阶段重编码，避免码率被洗掉）
        if config.frame_stuffing:
            if callback:
                callback(8, "启动帧膨胀处理...")
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            
            # 快手专用模式不回退到常规处理
            is_kuaishou = config.stuffing_mode in ("kuaishou_a", "kuaishou_b")
            
            try:
                # 返回值可能被改为MKV路径
                actual_output = self._apply_frame_stuffing(
                    input_path, output_path, config, video_info, callback
                )
                if actual_output and os.path.exists(actual_output) and os.path.getsize(actual_output) > 1024:
                    if callback:
                        output_size = os.path.getsize(actual_output) / 1024 / 1024
                        input_size = os.path.getsize(input_path) / 1024 / 1024
                        ratio = output_size / input_size if input_size > 0 else 1.0
                        callback(100, f"处理完成! 输出: {output_size:.1f}MB (原始: {input_size:.1f}MB, {ratio:.1f}x)")
                    return actual_output
                else:
                    if is_kuaishou:
                        raise RuntimeError("快手专用模式输出异常")
                    if callback:
                        callback(12, "帧膨胀输出异常，回退到常规处理...")
            except Exception as e:
                if is_kuaishou:
                    raise  # 快手模式直接抛出，不回退
                if callback:
                    callback(12, f"帧膨胀失败({e})，回退到常规处理...")

        # ---- 常规处理流程（非帧膨胀模式，或帧膨胀失败的回退） ----
        if callback:
            callback(10, "正在构建处理参数...")

        # 构建滤镜链
        video_filters = self._build_video_filters(config, video_info)
        audio_filters = self._build_audio_filters(config)

        # 构建FFmpeg命令
        cmd = [self.ffmpeg_path, "-hide_banner", "-y"]

        # 输入文件
        cmd.extend(["-i", input_path])

        # 底噪混入需要额外输入源 + filter_complex
        use_filter_complex = config.audio_noise_mix
        
        if use_filter_complex:
            # 添加噪声源输入
            cmd.extend([
                "-f", "lavfi", "-i",
                "anoisesrc=d=3600:c=pink:r=44100:a=0.002"
            ])
            
            # 构建 filter_complex
            fc_parts = []
            
            # 视频滤镜链
            if video_filters:
                vf_str = ",".join(video_filters)
                fc_parts.append(f"[0:v]{vf_str}[vout]")
            
            # 音频滤镜链 + 底噪混入
            audio_chain = ""
            if audio_filters:
                audio_chain = ",".join(audio_filters) + ","
            
            noise_db = config.audio_noise_db
            fc_parts.append(
                f"[1:a]volume={noise_db}dB[noise];"
                f"[0:a]{audio_chain}aformat=sample_rates=44100[amain];"
                f"[amain][noise]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            
            cmd.extend(["-filter_complex", ";".join(fc_parts)])
            
            if video_filters:
                cmd.extend(["-map", "[vout]"])
            else:
                cmd.extend(["-map", "0:v"])
            cmd.extend(["-map", "[aout]"])
        else:
            # 标准路径：分开的 -vf 和 -af
            if video_filters:
                vf_str = ",".join(video_filters)
                cmd.extend(["-vf", vf_str])

            if audio_filters:
                af_str = ",".join(audio_filters)
                cmd.extend(["-af", af_str])

        # 编码质量参数
        cmd.extend(self._get_quality_params(config))

        # 去尾
        if config.trim_tail and config.trim_tail_seconds > 0:
            if video_info:
                try:
                    duration = float(video_info["format"]["duration"])
                    end_time = duration - config.trim_tail_seconds
                    if end_time > 0:
                        cmd.extend(["-t", f"{end_time:.3f}"])
                except (KeyError, ValueError):
                    pass

        # 元数据修改
        if config.modify_metadata:
            random_id = uuid.uuid4().hex[:16]
            timestamp = int(time.time())
            cmd.extend([
                "-metadata", f"title=vid_{random_id}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-metadata", f"creation_time={timestamp}",
                "-metadata", f"encoder=custom_{random.randint(1000, 9999)}",
            ])

        # 强制关键帧间隔（增加差异性）
        keyframe_interval = 0.99 + random.uniform(-0.05, 0.05)
        cmd.extend([
            "-force_key_frames", f"expr:gte(t,n_forced*{keyframe_interval:.4f})"
        ])

        # 输出文件
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        cmd.append(output_path)

        if callback:
            callback(15, "开始处理视频...")

        # 执行FFmpeg
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )

            # 解析FFmpeg进度输出
            duration_total = None
            if video_info:
                try:
                    duration_total = float(video_info["format"]["duration"])
                except (KeyError, ValueError):
                    pass

            stderr_lines = []
            for line in process.stderr:
                stderr_lines.append(line)
                if callback and duration_total:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                    if time_match:
                        h, m, s, cs = map(int, time_match.groups())
                        current_time = h * 3600 + m * 60 + s + cs / 100.0
                        progress = min(95, int(15 + (current_time / duration_total) * 80))
                        speed_match = re.search(r'speed=\s*([\d.]+)x', line)
                        speed = speed_match.group(1) if speed_match else "?"
                        callback(
                            progress,
                            f"处理中... {current_time:.1f}s / {duration_total:.1f}s (速度: {speed}x)"
                        )

            process.wait()

            if process.returncode != 0:
                error_msg = "".join(stderr_lines[-10:])
                raise RuntimeError(f"FFmpeg处理失败 (code={process.returncode}):\n{error_msg}")

        except FileNotFoundError:
            raise RuntimeError(f"FFmpeg不可用: {self.ffmpeg_path}")

        if callback:
            callback(98, "正在验证输出文件...")

        # 验证输出文件
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise RuntimeError("输出文件生成失败或文件过小")

        if callback:
            output_size = os.path.getsize(output_path) / 1024 / 1024
            input_size = os.path.getsize(input_path) / 1024 / 1024
            ratio = output_size / input_size if input_size > 0 else 1.0
            callback(100, f"处理完成! 输出: {output_size:.1f}MB (原始: {input_size:.1f}MB, {ratio:.1f}x)")

        return output_path

    def batch_process(
        self,
        input_dir: str,
        output_dir: str,
        config: DedupConfig = None,
        preset: str = None,
        callback: Callable = None,
    ) -> List[str]:
        """
        批量处理目录中的所有视频

        :param input_dir: 输入目录
        :param output_dir: 输出目录
        :param config: 去重配置
        :param preset: 预设名称
        :param callback: 进度回调 callback(file_index, total_files, percent, message)
        :return: 处理成功的文件路径列表
        """
        video_exts = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
        input_files = [
            f for f in Path(input_dir).iterdir()
            if f.suffix.lower() in video_exts
        ]

        if not input_files:
            raise FileNotFoundError(f"目录中未找到视频文件: {input_dir}")

        os.makedirs(output_dir, exist_ok=True)
        results = []
        total = len(input_files)

        for idx, input_file in enumerate(input_files):
            output_file = os.path.join(output_dir, f"dedup_{input_file.name}")

            def file_callback(percent, msg):
                if callback:
                    overall = int(((idx + percent / 100) / total) * 100)
                    callback(idx + 1, total, overall, f"[{idx+1}/{total}] {input_file.name}: {msg}")

            try:
                result = self.process(
                    str(input_file), output_file,
                    config=config, preset=preset,
                    callback=file_callback
                )
                results.append(result)
            except Exception as e:
                if callback:
                    callback(idx + 1, total, -1, f"[{idx+1}/{total}] {input_file.name} 处理失败: {e}")

        return results


def get_preset_names():
    """获取所有预设名称（扁平化，兼容旧代码）"""
    return list(PRESETS.keys())


def get_platform_names():
    """获取所有平台名称（按显示顺序）"""
    # 平台列表固定顺序：四大平台在前，通用在后
    order = ["抖音", "快手", "小红书", "B站", "通用"]
    return [p for p in order if p in PLATFORM_PRESETS]


def get_platform_modes(platform):
    """获取指定平台下的所有模式名称"""
    return list(PLATFORM_PRESETS.get(platform, {}).keys())


def get_platform_preset(platform, mode):
    """获取指定平台的指定模式的 DedupConfig"""
    return PLATFORM_PRESETS.get(platform, {}).get(mode)


def get_preset_description(name):
    """获取预设的简要描述"""
    descriptions = {
        # ==== 平台专用 ====
        "抖音/模式1 - 帧替换+多维微调": "★抖音专用 帧替换v3+1080P上采样+音频变调+多维微调",
        "快手/模式1 - GPU高速(VFR插帧)": "★快手专用 h264_nvenc+Main+mono音频+MKV重编码(夜猫A)",
        "快手/模式2 - CPU精确(444色度)": "★快手专用 libx264+yuv444p+High4:4:4+MKV重编码(夜猫B)",
        "小红书/模式1 - 色相锐化+高码率": "★小红书专用 色相偏移+强锐化+15Mbps高码率上传",
        "B站/模式1 - 帧替换+不二压": "★B站专用 帧替换+不二压参数(≤6000kbps)+Level5",
        # ==== 通用 ====
        "轻度去重": "微调色彩+裁剪+轻微变速，适合质量要求高的视频",
        "中度去重": "全面调整色彩/裁剪/变速/锐化/降噪/噪点，推荐日常使用",
        "深度去重": "大幅调整所有参数+音频变调，适合高重复度视频",
        "镜像翻转模式": "水平镜像+色彩微调，简单粗暴但有效",
        "极限去重": "所有手段全开+镜像+大幅旋转，最强去重但画质有损",
        "帧膨胀模式": "帧率3倍膨胀+噪点，文件体积暴增但发布后自动压缩",
        "帧膨胀+深度去重": "帧膨胀+深度视觉调整，终极去重组合",
        "几何图案插帧": "60fps CFR插帧(有闪烁风险)，建议改用'智能帧替换'",
        "智能帧替换": "★推荐! v3模糊替换(不闪烁)，保持原始帧率，35%帧模糊+色偏",
        "上采样+重编码": "★最隐蔽! 720p->1080p+滤镜微调+GOP重构，完全不闪烁",
        "帧替换+上采样": "★终极方案! 模糊帧替换+1080p上采样，不闪烁+最接近夜猫",
    }
    return descriptions.get(name, "")


def get_mode_description(platform, mode):
    """获取平台模式的简要描述"""
    key = f"{platform}/{mode}" if platform != "通用" else mode
    return get_preset_description(key) or get_preset_description(mode)


# ==================== 命令行测试 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("  视频去重引擎 - 命令行测试")
    print("=" * 60)

    dedup = VideoDeduplicator()
    print(f"FFmpeg版本: {dedup.ffmpeg_version}")
    print(f"\n可用预设模式:")
    for name in get_preset_names():
        print(f"  - {name}: {get_preset_description(name)}")

    input_path = input("\n请输入视频文件路径: ").strip().strip('"')
    if not input_path:
        print("未输入路径，退出")
        exit()

    print("\n选择预设模式:")
    presets = get_preset_names()
    for i, name in enumerate(presets):
        print(f"  {i+1}. {name}")
    choice = input("请输入编号 (默认2): ").strip() or "2"
    preset_name = presets[int(choice) - 1]

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    basename = Path(input_path).stem
    output_path = os.path.join(output_dir, f"dedup_{basename}.mp4")

    def progress(percent, msg):
        bar = "=" * (percent // 2) + " " * (50 - percent // 2)
        print(f"\r[{bar}] {percent}% {msg}", end="", flush=True)

    try:
        result = dedup.process(input_path, output_path, preset=preset_name, callback=progress)
        print(f"\n\n✅ 去重完成: {result}")
    except Exception as e:
        print(f"\n\n❌ 处理失败: {e}")
