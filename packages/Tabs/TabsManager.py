# -*- coding: utf-8 -*-
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QPushButton

from packages.Tabs.VideoTab.VideoSelection import VideoSelectionSetting
from packages.Tabs.SubtitleTab.SubtitleSelection import SubtitleSelectionSetting
from packages.Tabs.AudioTab.AudioSelection import AudioSelectionSetting
from packages.Tabs.AttachmentTab.AttachmentSelection import AttachmentSelectionSetting
from packages.Tabs.MuxSetting.MuxSetting import MuxSettingTab
from packages.Widgets.AboutDialog import AboutDialog


class TabsManager(QTabWidget):
    task_bar_start_muxing_signal = Signal()
    update_task_bar_progress_signal = Signal(int)
    update_task_bar_paused_signal = Signal()
    update_task_bar_clear_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.video_tab = VideoSelectionSetting()
        self.subtitle_tab = SubtitleSelectionSetting()
        self.audio_tab = AudioSelectionSetting()
        self.attachment_tab = AttachmentSelectionSetting()
        self.mux_setting_tab = MuxSettingTab()
        
        self.tabs_ids = {
            "Video": 0,
            "Subtitle": 1,
            "Audio": 2,
            "Attachment": 3,
            "Mux Setting": 4,
        }
        
        self.tabs_status = [True, True, False, False, True]
        
        self.add_tabs()
        self.setup_corner_button()
        self.connect_signals()
    
    def add_tabs(self):
        self.addTab(self.video_tab, "视频")
        self.addTab(self.subtitle_tab, "字幕")
        self.addTab(self.audio_tab, "音轨")
        self.addTab(self.attachment_tab, "附件")
        self.addTab(self.mux_setting_tab, "开始混流")
    
    def setup_corner_button(self):
        about_btn = QPushButton("关于")
        about_btn.setFlat(True)
        about_btn.clicked.connect(self.show_about_dialog)
        self.setCornerWidget(about_btn)
    
    def show_about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec()
    
    def connect_signals(self):
        self.video_tab.video_list_updated.connect(self.on_video_list_updated)
        self.subtitle_tab.activation_signal.connect(self.change_subtitle_activated_state)
        self.audio_tab.activation_signal.connect(self.change_audio_activated_state)
        self.attachment_tab.activation_signal.connect(self.change_attachment_activated_state)
        self.mux_setting_tab.start_muxing_signal.connect(self.start_muxing)
        self.mux_setting_tab.update_task_bar_progress_signal.connect(self.update_task_bar_progress_signal.emit)
    
    def on_video_list_updated(self):
        self.subtitle_tab.refresh_video_list()
        self.audio_tab.refresh_video_list()
        self.attachment_tab.refresh_video_list()
    
    def start_muxing(self):
        self.task_bar_start_muxing_signal.emit()
    
    def change_subtitle_activated_state(self, new_state):
        self.tabs_status[self.tabs_ids["Subtitle"]] = new_state
    
    def change_audio_activated_state(self, new_state):
        self.tabs_status[self.tabs_ids["Audio"]] = new_state
    
    def change_attachment_activated_state(self, new_state):
        self.tabs_status[self.tabs_ids["Attachment"]] = new_state
    
    def set_preset_options(self):
        self.video_tab.set_preset_options()
        self.subtitle_tab.set_preset_options()
        self.audio_tab.set_preset_options()
        self.attachment_tab.set_preset_options()
        self.mux_setting_tab.set_preset_options()
