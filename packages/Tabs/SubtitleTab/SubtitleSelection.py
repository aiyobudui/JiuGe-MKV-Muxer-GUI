# -*- coding: utf-8 -*-
"""字幕选择页。共用逻辑见 TrackFileSelectionBase，此处仅注入字幕相关差异。"""
from packages.Tabs.TrackFileSelectionBase import TrackFileSelectionBase
from packages.Startup.PreDefined import SUBTITLE_EXTENSIONS


class SubtitleSelectionSetting(TrackFileSelectionBase):
    EXTENSIONS = SUBTITLE_EXTENSIONS
    SOURCE_GROUP_TITLE = "字幕源"
    SOURCE_LABEL_TEXT = "字幕源："
    SOURCE_PLACEHOLDER = "选择包含字幕文件的文件夹"
    MATCH_GROUP_TITLE = "字幕匹配"
    TRACK_LIST_LABEL = "字幕列表"
    TABLE_HEADER_TRACK = "字幕文件"
    INFO_TEXT = "提示：字幕按序号一一对应匹配到视频（第1个字幕→第1个视频，第2个字幕→第2个视频...）"
    DROP_WARNING_TEXT = "支持的字幕格式：\n.srt .ass ..."
    DIALOG_TITLE = "选择字幕源文件夹"
    LANGUAGE_DEFAULT = "chi"
    FILES_GLOBAL_ATTR = "SUBTITLE_FILES_ABSOLUTE_PATH_LIST"
    LANG_GLOBAL_ATTR = "SUBTITLE_LANGUAGE"
