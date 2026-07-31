# -*- coding: utf-8 -*-
"""附件选择页。附件匹配规则与音轨/字幕不同（全部附件加到全部视频），故覆盖钩子。"""
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel

from packages.Tabs.TrackFileSelectionBase import TrackFileSelectionBase
from packages.Startup.PreDefined import ATTACHMENT_EXTENSIONS
from packages.Tabs.GlobalSetting import GlobalSetting


class AttachmentSelectionSetting(TrackFileSelectionBase):
    EXTENSIONS = ATTACHMENT_EXTENSIONS
    SOURCE_GROUP_TITLE = "附件源"
    SOURCE_LABEL_TEXT = "附件源："
    SOURCE_PLACEHOLDER = "选择包含附件文件的文件夹"
    MATCH_GROUP_TITLE = "附件匹配"
    TRACK_LIST_LABEL = "附件列表"
    TABLE_HEADER_TRACK = "附件文件"
    INFO_TEXT = "提示：附件将添加到所有视频文件中"
    DROP_WARNING_TEXT = "支持的附件格式：\n字体: .ttf .otf .woff\n图片: .jpg .png .webp\n文档: .xml .json .txt .pdf .md .nfo"
    DIALOG_TITLE = "选择附件源文件夹"
    LANGUAGE_DEFAULT = None
    FILES_GLOBAL_ATTR = "ATTACHMENT_FILES_ABSOLUTE_PATH_LIST"
    LANG_GLOBAL_ATTR = None

    def auto_match_by_index(self):
        files_map = GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST
        files_map.clear()

        for video_idx in GlobalSetting.VIDEO_SELECTED_INDICES:
            if video_idx not in files_map:
                files_map[video_idx] = []
            for attachment_path in self.files:
                files_map[video_idx].append(attachment_path)

        GlobalSetting.ATTACHMENT_REPLACE_EXISTING = self.replace_attachment_check.isChecked()

        if self.files:
            GlobalSetting.ATTACHMENT_ENABLED = True
        else:
            GlobalSetting.ATTACHMENT_ENABLED = False

    def clear_global_state(self):
        GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.ATTACHMENT_ENABLED = False

    def setup_extra_options(self, main_layout):
        option_layout = QHBoxLayout()

        self.replace_attachment_check = QCheckBox("清除原附件")
        self.replace_attachment_check.setChecked(True)
        self.replace_attachment_check.setToolTip("勾选后将清除视频文件中原有的附件，只保留用户添加的附件")
        option_layout.addWidget(self.replace_attachment_check)

        info_label = QLabel(self.INFO_TEXT)
        info_label.setStyleSheet("color: gray;")
        option_layout.addWidget(info_label)

        main_layout.addLayout(option_layout)
