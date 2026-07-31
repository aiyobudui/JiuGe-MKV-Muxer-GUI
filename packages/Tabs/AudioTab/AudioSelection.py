# -*- coding: utf-8 -*-
"""音轨选择页。共用逻辑见 TrackFileSelectionBase，此处仅注入音轨相关差异。"""
from packages.Tabs.TrackFileSelectionBase import TrackFileSelectionBase
from packages.Startup.PreDefined import AUDIO_EXTENSIONS


class AudioSelectionSetting(TrackFileSelectionBase):
    EXTENSIONS = AUDIO_EXTENSIONS
    SOURCE_GROUP_TITLE = "音轨源"
    SOURCE_LABEL_TEXT = "音轨源："
    SOURCE_PLACEHOLDER = "选择包含音轨文件的文件夹"
    MATCH_GROUP_TITLE = "音轨匹配"
    TRACK_LIST_LABEL = "音轨列表"
    TABLE_HEADER_TRACK = "音轨文件"
    INFO_TEXT = "提示：音轨按序号一一对应添加到视频（第1个音轨→第1个视频，以此类推）"
    DROP_WARNING_TEXT = "支持的音轨格式：\nAAC, MP3..."
    DIALOG_TITLE = "选择音轨源文件夹"
    LANGUAGE_DEFAULT = "chi"
    FILES_GLOBAL_ATTR = "AUDIO_FILES_ABSOLUTE_PATH_LIST"
    LANG_GLOBAL_ATTR = "AUDIO_LANGUAGE"
