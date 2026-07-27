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


def get_video_fps(video_path, mkvmerge_path=None):
    """获取视频的帧率"""
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return None
    
    tracks = info.get('tracks', [])
    for track in tracks:
        if track.get('type') == 'video':
            properties = track.get('properties', {})
            fps_num = properties.get('fps_num', 0)
            fps_den = properties.get('fps_den', 1)
            if fps_num and fps_den:
                return fps_num / fps_den
            return None
    return None


def get_subtitle_tracks(video_path, mkvmerge_path=None):
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return []
    
    subtitles = []
    tracks = info.get('tracks', [])
    
    for track in tracks:
        if track.get('type') == 'subtitles':
            properties = track.get('properties', {})
            sub_info = {
                'id': track.get('id', 0),
                'language': properties.get('language', 'und'),
                'name': properties.get('track_name', ''),
                'is_default': properties.get('default_track', False),
                'is_forced': properties.get('forced_track', False),
                'codec': track.get('codec', '')
            }
            subtitles.append(sub_info)
    
    return subtitles


def get_audio_tracks(video_path, mkvmerge_path=None):
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return []
    
    audios = []
    tracks = info.get('tracks', [])
    
    for track in tracks:
        if track.get('type') == 'audio':
            properties = track.get('properties', {})
            audio_info = {
                'id': track.get('id', 0),
                'language': properties.get('language', 'und'),
                'name': properties.get('track_name', ''),
                'is_default': properties.get('default_track', False),
                'is_forced': properties.get('forced_track', False),
                'codec': track.get('codec', ''),
                'channels': properties.get('audio_channels', 0),
                'sample_rate': properties.get('audio_sampling_rate', 0)
            }
            audios.append(audio_info)
    
    return audios


def get_video_tracks(video_path, mkvmerge_path=None):
    """读取视频文件中的视频轨道信息"""
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return []
    
    videos = []
    tracks = info.get('tracks', [])
    
    for track in tracks:
        if track.get('type') == 'video':
            properties = track.get('properties', {})
            video_info = {
                'id': track.get('id', 0),
                'language': properties.get('language', 'und'),
                'name': properties.get('track_name', ''),
                'is_default': properties.get('default_track', False),
                'is_forced': properties.get('forced_track', False),
                'codec': track.get('codec', ''),
                'width': properties.get('video_pixel_width', 0),
                'height': properties.get('video_pixel_height', 0)
            }
            videos.append(video_info)
    
    return videos


def get_video_title(video_path, mkvmerge_path=None):
    """获取视频文件的标题信息（读取视频元数据中的title属性）"""
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return ""
    
    if info.get('title'):
        return info['title']
    
    if 'properties' in info and info['properties'].get('title'):
        return info['properties']['title']
    
    if 'container' in info and 'properties' in info['container']:
        if info['container']['properties'].get('title'):
            return info['container']['properties']['title']
    
    return ""


def format_track_info(track_info, index):
    name = track_info.get('name', '')
    codec = track_info.get('codec', '')
    is_default = " [默认]" if track_info.get('is_default') else ""
    is_forced = " [强制]" if track_info.get('is_forced') else ""
    
    display = f"#{index} {track_info.get('language', 'und')}"
    if name:
        display += f" ({name})"
    if codec:
        display += f" [{codec}]"
    display += is_default + is_forced
    
    return display


def get_attachments(video_path, mkvmerge_path=None):
    info = get_video_tracks_info(video_path, mkvmerge_path)
    if not info:
        return []
    
    attachments = []
    attachment_list = info.get('attachments', [])
    
    for attachment in attachment_list:
        att_info = {
            'id': attachment.get('id', 0),
            'filename': attachment.get('file_name', ''),
            'mime_type': attachment.get('content_type', ''),
            'size': attachment.get('size', 0)
        }
        attachments.append(att_info)
    
    return attachments


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
