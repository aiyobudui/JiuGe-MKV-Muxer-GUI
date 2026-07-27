# -*- coding: utf-8 -*-
import os
import re
import logging
import subprocess
from PySide6.QtCore import Signal, Qt, QMimeData, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox, QCheckBox
)

from packages.Startup import GlobalIcons
from packages.Startup.Options import Options
from packages.Tabs.GlobalSetting import GlobalSetting, get_readable_filesize
from packages.Startup.PreDefined import VIDEO_EXTENSIONS
from packages.Utils.TrackInfo import get_subtitle_tracks, get_audio_tracks, get_attachments, get_video_tracks
from packages.Widgets.ExtractTracksDialog import ExtractTracksDialog


class VideoSelectionSetting(QWidget):
    tab_clicked_signal = Signal()
    video_list_updated = Signal()
    refresh_track_info = Signal()
    # 新增：用于跨线程更新 UI 的信号
    update_track_info_signal = Signal(int, int, int, int, str)  # index, audio_count, sub_count, attach_count, title
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.current_source_dir = ""
        self._track_info_gen = 0  # 生成计数器，丢弃过期结果
        self.setup_ui()
        self.connect_signals()
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        
        video_files = []
        folders = []
        non_video_files = []
        
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    video_files.append(path)
                else:
                    non_video_files.append(path)
            elif os.path.isdir(path):
                folders.append(path)
        
        if non_video_files and not video_files and not folders:
            supported = " ".join(VIDEO_EXTENSIONS)
            QMessageBox.warning(self, "提示", f"支持的视频格式：\n{supported}")
            event.ignore()
            return
        
        if folders:
            folder = folders[0]
            self.current_source_dir = folder
            self.source_path_edit.setText(folder)
            self.load_videos()
        elif video_files:
            existing_files = set(GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST)
            new_files = [vf for vf in video_files if vf not in existing_files]
            
            if new_files:
                # 检测所有拖拽文件的公共目录
                dirs = set(os.path.dirname(f) for f in new_files)
                if len(dirs) == 1:
                    self.current_source_dir = dirs.pop()
                    self.source_path_edit.setText(self.current_source_dir)
                else:
                    self.current_source_dir = ""
                    self.source_path_edit.clear()
                
                self.load_video_files_append(new_files)
        
        event.acceptProposedAction()
    
    def load_video_files_append(self, file_paths):
        file_paths.sort()
        
        has_mkvmerge = Options.Mkvmerge_Path and os.path.exists(Options.Mkvmerge_Path)
        
        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            GlobalSetting.VIDEO_FILES_LIST.append(file_name)
            GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.append(file_path)
            GlobalSetting.VIDEO_FILES_SIZE_LIST.append(file_size)
            
            row = self.video_table.rowCount()
            self.video_table.insertRow(row)
            
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.clicked.connect(self.update_selected_indices)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.video_table.setCellWidget(row, 0, checkbox_widget)
            
            self.video_table.setItem(row, 1, QTableWidgetItem(file_name))
            
            audio_item = QTableWidgetItem("...")
            audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 2, audio_item)
            
            sub_item = QTableWidgetItem("...")
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 3, sub_item)
            
            attachment_item = QTableWidgetItem("...")
            attachment_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 4, attachment_item)
            
            title_item = QTableWidgetItem("")
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 5, title_item)
            
            size_item = QTableWidgetItem(get_readable_filesize(file_size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 6, size_item)
            
            # 追加空轨道占位，后续由 load_track_info_threaded 在后台填充
            GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO.append([])
            GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO.append([])
            GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO.append([])
            GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO.append([])
        
        self.update_selected_indices()
        self.video_list_updated.emit()
        
        # 后台线程加载轨道信息，不阻塞 UI
        if has_mkvmerge:
            self.load_track_info_threaded()
    
    def load_video_files(self, file_paths):
        self.video_table.setRowCount(0)
        GlobalSetting.VIDEO_FILES_LIST.clear()
        GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.VIDEO_FILES_SIZE_LIST.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO.clear()
        
        file_paths.sort()
        
        has_mkvmerge = Options.Mkvmerge_Path and os.path.exists(Options.Mkvmerge_Path)
        
        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            GlobalSetting.VIDEO_FILES_LIST.append(file_name)
            GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.append(file_path)
            GlobalSetting.VIDEO_FILES_SIZE_LIST.append(file_size)
            
            row = self.video_table.rowCount()
            self.video_table.insertRow(row)
            
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.clicked.connect(self.update_selected_indices)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.video_table.setCellWidget(row, 0, checkbox_widget)
            
            self.video_table.setItem(row, 1, QTableWidgetItem(file_name))
            
            audio_item = QTableWidgetItem("...")
            audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 2, audio_item)
            
            sub_item = QTableWidgetItem("...")
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 3, sub_item)
            
            attachment_item = QTableWidgetItem("...")
            attachment_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 4, attachment_item)
            
            title_item = QTableWidgetItem("")
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 5, title_item)
            
            size_item = QTableWidgetItem(get_readable_filesize(file_size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 6, size_item)
        
        if has_mkvmerge:
            self.load_track_info_threaded()
        
        # 更新选中索引，因为复选框默认是选中状态
        self.update_selected_indices()
        
        self.video_list_updated.emit()
    
    def refresh_track_info_now(self):
        """刷新视频轨道信息（异步，通过后台线程加载）"""
        if not Options.Mkvmerge_Path or not os.path.exists(Options.Mkvmerge_Path):
            return
        
        if not GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST:
            return
        
        # 清空旧轨道数据并重置 UI 为 "..."，然后启动后台线程加载
        GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO.clear()
        
        for i in range(self.video_table.rowCount()):
            for col in (2, 3, 4):
                item = QTableWidgetItem("...")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.video_table.setItem(i, col, item)
            title_item = QTableWidgetItem("")
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(i, 5, title_item)
        
        self.load_track_info_threaded()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        source_group = QGroupBox("视频源")
        source_layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("视频源："))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("选择包含视频文件的文件夹")
        path_layout.addWidget(self.source_path_edit)
        
        self.clear_button = QPushButton("清空")
        self.clear_button.setFixedWidth(60)
        self.clear_button.setIcon(GlobalIcons.ClearIcon.get())
        path_layout.addWidget(self.clear_button)
        
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setFixedWidth(60)
        self.refresh_button.setIcon(GlobalIcons.RefreshIcon.get())
        path_layout.addWidget(self.refresh_button)
        
        self.browse_button = QPushButton("浏览")
        self.browse_button.setFixedWidth(60)
        self.browse_button.setIcon(GlobalIcons.FolderIcon.get())
        path_layout.addWidget(self.browse_button)
        
        source_layout.addLayout(path_layout)
        
        info_layout = QHBoxLayout()
        self.select_all_checkbox = QCheckBox("全选")
        self.select_all_checkbox.setChecked(True)
        info_layout.addWidget(self.select_all_checkbox)
        
        info_layout.addStretch()
        
        self.extract_tracks_button = QPushButton("轨道提取")
        self.extract_tracks_button.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold;")
        self.extract_tracks_button.setFixedWidth(80)
        info_layout.addWidget(self.extract_tracks_button)
        
        source_layout.addLayout(info_layout)
        
        source_group.setLayout(source_layout)
        main_layout.addWidget(source_group)
        
        table_group = QGroupBox("视频列表")
        table_layout = QVBoxLayout()
        
        self.video_table = QTableWidget()
        self.video_table.setColumnCount(7)
        self.video_table.setHorizontalHeaderLabels(["选择", "文件名", "音轨", "字幕轨", "附件", "视频标题", "大小"])
        self.video_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.video_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.video_table.setColumnWidth(0, 50)
        self.video_table.setColumnWidth(2, 60)
        self.video_table.setColumnWidth(3, 60)
        self.video_table.setColumnWidth(4, 60)
        self.video_table.setColumnWidth(5, 120)
        self.video_table.setColumnWidth(6, 100)
        
        from PySide6.QtWidgets import QStyledItemDelegate
        class CenterAlignDelegate(QStyledItemDelegate):
            def initStyleOption(self, option, index):
                super().initStyleOption(option, index)
                option.displayAlignment = Qt.AlignmentFlag.AlignCenter
        self.video_table.setItemDelegateForColumn(2, CenterAlignDelegate())
        self.video_table.setItemDelegateForColumn(3, CenterAlignDelegate())
        self.video_table.setItemDelegateForColumn(4, CenterAlignDelegate())
        self.video_table.setItemDelegateForColumn(5, CenterAlignDelegate())
        self.video_table.setItemDelegateForColumn(6, CenterAlignDelegate())
        
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.video_table.setAlternatingRowColors(True)
        
        table_layout.addWidget(self.video_table)
        table_group.setLayout(table_layout)
        main_layout.addWidget(table_group)
        
        self.setLayout(main_layout)
    
    def connect_signals(self):
        self.browse_button.clicked.connect(self.browse_folder)
        self.clear_button.clicked.connect(self.clear_files)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        self.extract_tracks_button.clicked.connect(self.show_extract_tracks_dialog)
        # 连接跨线程更新 UI 的信号
        self.update_track_info_signal.connect(self.update_track_info_ui)
    
    def update_selected_indices(self):
        GlobalSetting.VIDEO_SELECTED_INDICES.clear()
        for row in range(self.video_table.rowCount()):
            checkbox_widget = self.video_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    GlobalSetting.VIDEO_SELECTED_INDICES.append(row)
        self.video_list_updated.emit()
    
    def update_track_info_ui(self, index, audio_count, sub_count, attach_count, title):
        """在主线程中更新 UI（通过信号槽跨线程调用）"""
        if index < 0 or index >= self.video_table.rowCount():
            return
        
        # 更新音频轨道数量
        audio_item = QTableWidgetItem(str(audio_count))
        audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_table.setItem(index, 2, audio_item)
        
        # 更新字幕轨道数量
        sub_item = QTableWidgetItem(str(sub_count))
        sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_table.setItem(index, 3, sub_item)
        
        # 更新附件数量
        attachment_item = QTableWidgetItem(str(attach_count))
        attachment_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_table.setItem(index, 4, attachment_item)
        
        # 更新标题
        title_item = QTableWidgetItem(title)
        self.video_table.setItem(index, 5, title_item)
    
    def toggle_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for row in range(self.video_table.rowCount()):
            checkbox_widget = self.video_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(checked)
        self.update_selected_indices()
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择视频源文件夹")
        if folder:
            self.current_source_dir = folder
            self.source_path_edit.setText(folder)
            self.load_videos()
    
    def clear_files(self):
        self.current_source_dir = ""
        self.source_path_edit.clear()
        self.video_table.setRowCount(0)
        GlobalSetting.VIDEO_FILES_LIST.clear()
        GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.VIDEO_FILES_SIZE_LIST.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO.clear()
        self.video_list_updated.emit()
    
    def refresh_files(self):
        # 如果有源文件夹路径，扫描文件夹（文件夹模式）
        if self.source_path_edit.text():
            self.load_videos()
        # 否则如果有已加载的文件（拖拽模式），只刷新元数据，不重新扫描文件夹
        elif GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST:
            self.refresh_track_info_now()
            self.video_list_updated.emit()
    
    def load_videos(self):
        folder = self.source_path_edit.text()
        if not folder or not os.path.isdir(folder):
            return
        
        self.video_table.setRowCount(0)
        GlobalSetting.VIDEO_FILES_LIST.clear()
        GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.VIDEO_FILES_SIZE_LIST.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO.clear()
        GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO.clear()
        GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO.clear()
        
        files = []
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                files.append(f)
        
        files.sort()
        
        has_mkvmerge = Options.Mkvmerge_Path and os.path.exists(Options.Mkvmerge_Path)
        
        for file_name in files:
            file_path = os.path.join(folder, file_name)
            file_size = os.path.getsize(file_path)
            
            GlobalSetting.VIDEO_FILES_LIST.append(file_name)
            GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.append(file_path)
            GlobalSetting.VIDEO_FILES_SIZE_LIST.append(file_size)
            
            row = self.video_table.rowCount()
            self.video_table.insertRow(row)
            
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.clicked.connect(self.update_selected_indices)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.video_table.setCellWidget(row, 0, checkbox_widget)
            
            self.video_table.setItem(row, 1, QTableWidgetItem(file_name))
            
            audio_item = QTableWidgetItem("...")
            audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 2, audio_item)
            
            sub_item = QTableWidgetItem("...")
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 3, sub_item)
            
            attachment_item = QTableWidgetItem("...")
            attachment_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 4, attachment_item)
            
            title_item = QTableWidgetItem("")
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 5, title_item)
            
            size_item = QTableWidgetItem(get_readable_filesize(file_size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 6, size_item)
        
        if has_mkvmerge:
            self.load_track_info_threaded()
        
        self.update_selected_indices()
    
    def load_track_info_threaded(self):
        """使用 BackgroundRunner 在后台线程中加载视频轨道信息"""
        GlobalSetting.VIDEO_TRACK_INFO_READY = False
        self._track_info_gen += 1
        
        file_paths = GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST.copy()
        total_files = len(file_paths)
        
        if total_files == 0:
            return
        
        from packages.Utils.BackgroundRunner import BackgroundRunner
        
        # 临时存储（后台线程写入，线程安全：每索引只写一次）
        temp_subtitles = [None] * total_files
        temp_audios = [None] * total_files
        temp_videos = [None] * total_files
        temp_attachments = [None] * total_files
        temp_titles = [None] * total_files
        
        def on_task_done(task_id, result):
            """每完成一个文件的解析"""
            subtitle_tracks = result.get('subtitle_tracks', [])
            audio_tracks = result.get('audio_tracks', [])
            video_tracks = result.get('video_tracks', [])
            attachment_tracks = result.get('attachment_tracks', [])
            title = result.get('title', '')
            
            temp_subtitles[task_id] = subtitle_tracks
            temp_audios[task_id] = audio_tracks
            temp_videos[task_id] = video_tracks
            temp_attachments[task_id] = attachment_tracks
            temp_titles[task_id] = title
            
            self.update_track_info_signal.emit(
                task_id, len(audio_tracks), len(subtitle_tracks),
                len(attachment_tracks), title
            )
        
        def on_all_done(completed, failed, total):
            """全部解析完成，写入 GlobalSetting"""
            GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO = temp_videos
            GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO = temp_subtitles
            GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO = temp_audios
            GlobalSetting.VIDEO_OLD_ATTACHMENTS_INFO = temp_attachments
            GlobalSetting.VIDEO_TRACK_INFO_READY = True
            
            if not hasattr(GlobalSetting, 'VIDEO_TITLES'):
                GlobalSetting.VIDEO_TITLES = [None] * total_files
            GlobalSetting.VIDEO_TITLES = temp_titles
        
        if not hasattr(self, '_track_info_runner'):
            self._track_info_runner = BackgroundRunner()
            self._track_info_runner.task_error.connect(
                lambda tid, err: logging.warning(f"视频轨道信息获取失败 (task {tid}): {err}")
            )
        
        self._track_info_runner.run(
            file_paths, self._get_track_info_worker,
            on_task_done=on_task_done, on_all_done=on_all_done
        )
    
    @staticmethod
    def _get_track_info_worker(file_path, task_id):
        """获取单个视频的全部轨道信息（BackgroundRunner worker 签名）。
        
        Returns:
            dict: 包含 subtitle_tracks, audio_tracks, video_tracks, attachment_tracks, title
        """
        from packages.Utils.TrackInfo import get_video_tracks_info
        
        try:
            info = get_video_tracks_info(file_path)
        except Exception as e:
            logging.warning(f"get_video_tracks_info 异常 ({file_path}): {e}")
            return {'subtitle_tracks': [], 'audio_tracks': [], 'video_tracks': [],
                    'attachment_tracks': [], 'title': ''}
        
        subtitle_tracks = []
        audio_tracks = []
        video_tracks = []
        attachment_tracks = []
        title = ""
        
        if info:
            tracks = info.get('tracks', [])
            for track in tracks:
                track_type = track.get('type', '')
                if track_type == 'subtitle':
                    subtitle_tracks.append(track)
                elif track_type == 'audio':
                    audio_tracks.append(track)
                elif track_type == 'video':
                    video_tracks.append(track)
            
            attachment_tracks = info.get('attachments', [])
            
            if info.get('title'):
                title = info['title']
            elif 'properties' in info and info['properties'].get('title'):
                title = info['properties']['title']
        
        return {
            'subtitle_tracks': subtitle_tracks,
            'audio_tracks': audio_tracks,
            'video_tracks': video_tracks,
            'attachment_tracks': attachment_tracks,
            'title': title,
        }
    
    def update_theme_mode_state(self):
        pass
    
    def get_selected_files(self):
        """获取勾选的视频行索引"""
        selected = []
        for row in range(self.video_table.rowCount()):
            checkbox = self.video_table.cellWidget(row, 0)
            if checkbox and checkbox.findChild(QCheckBox).isChecked():
                selected.append(row)
        return selected
    
    def show_extract_tracks_dialog(self):
        """打开轨道提取对话框"""
        if not GlobalSetting.VIDEO_FILES_LIST:
            QMessageBox.warning(self, "警告", "请先添加视频文件")
            return
        
        if not Options.Mkvmerge_Path or not os.path.exists(Options.Mkvmerge_Path):
            QMessageBox.warning(self, "警告", "请先设置 mkvmerge.exe 路径")
            return
        
        selected_rows = self.get_selected_files()
        dialog = ExtractTracksDialog(self, selected_rows)
        dialog.exec()
    
    def refresh_video_list(self):
        if self.source_path_edit.text():
            self.load_videos()
    
    def set_preset_options(self):
        if self.source_path_edit.text():
            self.load_videos()