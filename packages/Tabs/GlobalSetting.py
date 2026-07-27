# -*- coding: utf-8 -*-
import os
import re
from collections import defaultdict
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def get_readable_filesize(size_bytes, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(size_bytes) < 1024.0:
            return "%3.2f %s%s" % (size_bytes, unit, suffix)
        size_bytes /= 1024.0
    return "%.2f %s%s" % (size_bytes, 'Y', suffix)


class GlobalSetting(QWidget):
    LAST_DIRECTORY_PATH = ""
    
    VIDEO_FILES_LIST = []
    VIDEO_FILES_SIZE_LIST = []
    VIDEO_FILES_ABSOLUTE_PATH_LIST = []
    
    VIDEO_OLD_TRACKS_VIDEOS_INFO: List[List[dict]] = []
    VIDEO_OLD_TRACKS_SUBTITLES_INFO: List[List[dict]] = []
    VIDEO_OLD_TRACKS_AUDIOS_INFO: List[List[dict]] = []
    VIDEO_OLD_ATTACHMENTS_INFO: List[List[dict]] = []
    VIDEO_SELECTED_INDICES: List[int] = []
    # 轨道信息是否已完成后台解析（start_muxing 开始混流前用于守卫，避免轨道选择/默认轨/语言被静默丢弃）
    VIDEO_TRACK_INFO_READY = False
    
    SUBTITLE_FILES_LIST = defaultdict(list)
    SUBTITLE_FILES_ABSOLUTE_PATH_LIST = defaultdict(list)
    SUBTITLE_LANGUAGE = defaultdict(str)
    
    AUDIO_FILES_LIST = defaultdict(list)
    AUDIO_FILES_ABSOLUTE_PATH_LIST = defaultdict(list)
    AUDIO_LANGUAGE = defaultdict(str)
    
    ATTACHMENT_ENABLED = False
    ATTACHMENT_FILES_ABSOLUTE_PATH_LIST = {}
    ATTACHMENT_REPLACE_EXISTING = False  # 是否替换原有的附件
    
    DESTINATION_FOLDER_PATH = ""
    
    JOB_QUEUE_FINISHED = False
    MUXING_ON = False
    
    def __init__(self):
        super().__init__()
