# -*- coding: utf-8 -*-
"""MuxSetting 相关的纯函数工具（无 Qt/self 状态依赖，可独立测试）。

从 MuxSetting.py 抽出，避免主文件过度膨胀，并便于单元测试。
"""
import logging
import os
import re
import zlib


def parse_mkvmerge_progress(line):
    """解析 mkvmerge 输出中的进度信息。"""
    # mkvmerge --gui-mode 输出格式是 "#GUI#progress X"
    # 同时也尝试匹配普通模式的格式
    patterns = [
        r'#GUI#progress\s+(\d+)',
        r'Progress:\s*(\d+)%',
        r'(\d+)%',
    ]

    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            try:
                progress = int(match.group(1))
                if 0 <= progress <= 100:
                    return progress
            except ValueError:
                pass

    return None


def get_output_path_from_args(args):
    """从 mkvmerge args 列表中安全提取输出路径（查找 -o 参数）。

    避免硬编码 args[2] 索引，适应参数结构的未来变化。
    """
    try:
        idx = args.index('-o')
        return args[idx + 1]
    except (ValueError, IndexError):
        return args[2]  # 兜底：保持旧行为


def get_attachment_mime_type(ext):
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp',
        '.ttf': 'font/ttf',
        '.otf': 'font/otf',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
    }
    return mime_types.get(ext, 'application/octet-stream')


def calculate_crc32(file_path):
    crc = 0
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                crc = zlib.crc32(chunk, crc)
        return format(crc & 0xFFFFFFFF, '08X')
    except (OSError, zlib.error) as e:
        logging.warning(f"CRC32计算失败 ({file_path}): {e}")
        return None


def remove_crc_from_filename(filename):
    crc_pattern = r'\[[A-Fa-f0-9]{8}\]'
    return re.sub(crc_pattern, '', filename).strip()


def add_crc_to_filename(file_path, crc):
    dir_path = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    name, ext = os.path.splitext(filename)
    new_filename = f"{name} [{crc}]{ext}"
    new_path = os.path.join(dir_path, new_filename)
    try:
        os.rename(file_path, new_path)
        return new_path
    except OSError as e:
        logging.warning(f"文件重命名失败 ({file_path}): {e}")
        return file_path


def hms_to_seconds(time_str):
    """解析 HH:MM:SS / HH:MM:SS.fff / MM:SS / SS.fff 为秒（float）。失败返回 None。"""
    try:
        parts = [float(p) for p in time_str.split(':')]
    except (ValueError, TypeError):
        return None
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    elif len(parts) == 1:
        h, m, s = 0, 0, parts[0]
    else:
        return None
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        return None
    return h * 3600 + m * 60 + s


def seconds_to_hms(seconds):
    """秒（float）格式化为 HH:MM:SS.fff（mkvmerge --split parts: 接受）。"""
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def clamp_cut_times_to_duration(video_path, keep_times):
    """将切割保留段时间点按视频实际时长截断，避免短视频因切割点超界而失败。

    仅做安全截断：超出时长的段被裁剪或丢弃；无法获取时长时降级为原样返回。
    """
    try:
        from packages.Utils.TrackInfo import get_video_duration_seconds
        duration = get_video_duration_seconds(video_path)
    except Exception:
        duration = None
    if duration is None or duration <= 0:
        return keep_times  # 降级：不截断

    segments = []
    for seg in keep_times.split(','):
        seg = seg.strip()
        if '-' not in seg:
            continue
        start_s, end_s = seg.split('-', 1)
        start_s = start_s.strip()
        end_s = end_s.strip()
        start = hms_to_seconds(start_s)
        if start is None:
            continue
        if start >= duration:
            continue  # 整段都在视频之外
        if end_s == '':
            end = duration  # 开放式 "start-" 表示到结尾
        else:
            end = hms_to_seconds(end_s)
            if end is None:
                continue
        if end > duration:
            end = duration
        if end <= start:
            continue
        segments.append(f"{seconds_to_hms(start)}-{seconds_to_hms(end)}")
    return ','.join(segments)
