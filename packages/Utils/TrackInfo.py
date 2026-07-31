# -*- coding: utf-8 -*-
import subprocess
import json
import os
import sys
import logging


def get_video_tracks_info(video_path, mkvmerge_path=None):
    if mkvmerge_path is None:
        from packages.Startup.Options import Options
        mkvmerge_path = Options.Mkvmerge_Path
    
    if not mkvmerge_path:
        return None
    
    if not os.path.exists(mkvmerge_path):
        return None
    
    if not os.path.exists(video_path):
        return None
    
    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        result = subprocess.run(
            [mkvmerge_path, '-J', video_path],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            env=env
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        return None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        logging.warning(f"获取视频轨道信息失败 ({video_path}): {e}")
        return None


def get_video_duration_seconds(video_path, mkvmerge_path=None):
    """获取视频总时长（秒，float）。解析失败返回 None。

    用于切割时按各视频实际时长截断保留段，避免短视频因切割点超界而失败。
    """
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return None

    # 优先使用视频轨道的 duration（mkvmerge -J 返回纳秒）
    tracks = info.get('tracks', [])
    for track in tracks:
        if track.get('type') == 'video':
            dur_ns = track.get('properties', {}).get('duration')
            if dur_ns:
                try:
                    return float(dur_ns) / 1_000_000_000.0
                except (TypeError, ValueError):
                    pass

    # 退而求其次：容器级 duration
    container_dur = info.get('container', {}).get('properties', {}).get('duration')
    if container_dur:
        try:
            return float(container_dur) / 1_000_000_000.0
        except (TypeError, ValueError):
            pass

    return None
