# -*- coding: utf-8 -*-
import os
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGroupBox, QMessageBox
)

from packages.Tabs.GlobalSetting import GlobalSetting
from packages.Startup.PreDefined import AUDIO_EXTENSIONS
from packages.Widgets.FloatingReorderButtons import FloatingReorderButtons
from packages.Utils.TableHelpers import populate_video_ref_table


class AudioSelectionSetting(QWidget):
    activation_signal = Signal(bool)
    tab_clicked_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.audio_files = []
        self.current_selected_row = -1
        self.last_click_pos = None
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
        
        audio_files = []
        folders = []
        non_audio_files = []
        
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in AUDIO_EXTENSIONS:
                    audio_files.append(path)
                else:
                    non_audio_files.append(path)
            elif os.path.isdir(path):
                folders.append(path)
        
        if non_audio_files and not audio_files and not folders:
            QMessageBox.warning(self, "提示", "支持的音轨格式：\nAAC, MP3...")
            event.ignore()
            return
        
        if folders:
            folder = folders[0]
            self.source_path_edit.setText(folder)
            self.load_audios()
        elif audio_files:
            existing_files = set(self.audio_files)
            new_files = [af for af in audio_files if af not in existing_files]
            
            if new_files:
                total_count = len(self.audio_files) + len(new_files)
                
                if total_count == 1:
                    self.source_path_edit.setText(os.path.dirname(new_files[0]))
                else:
                    self.source_path_edit.clear()
                
                self.load_audio_files_append(new_files)
        
        event.acceptProposedAction()
    
    def load_audio_files_append(self, file_paths):
        file_paths.sort()
        
        for file_path in file_paths:
            self.audio_files.append(file_path)
            
            row = self.audio_table.rowCount()
            self.audio_table.insertRow(row)
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.audio_table.setItem(row, 0, idx_item)
            self.audio_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))
        
        self.auto_match_by_index()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        source_group = QGroupBox("音轨源")
        source_layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("音轨源："))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("选择包含音轨文件的文件夹")
        path_layout.addWidget(self.source_path_edit)
        
        self.clear_button = QPushButton("清空")
        self.clear_button.setFixedWidth(60)
        path_layout.addWidget(self.clear_button)
        
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setFixedWidth(60)
        path_layout.addWidget(self.refresh_button)
        
        self.browse_button = QPushButton("浏览")
        self.browse_button.setFixedWidth(60)
        path_layout.addWidget(self.browse_button)
        
        source_layout.addLayout(path_layout)
        source_group.setLayout(source_layout)
        main_layout.addWidget(source_group)
        
        match_group = QGroupBox("音轨匹配")
        match_layout = QHBoxLayout()
        
        video_table_widget = QWidget()
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.addWidget(QLabel("视频列表"))
        self.video_table = QTableWidget()
        self.video_table.setColumnCount(2)
        self.video_table.setHorizontalHeaderLabels(["序号", "视频文件"])
        self.video_table.verticalHeader().setVisible(False)
        self.video_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.video_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.video_table.setColumnWidth(0, 40)
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.video_table.itemClicked.connect(self.on_video_table_clicked)
        video_layout.addWidget(self.video_table)
        video_table_widget.setLayout(video_layout)
        
        audio_table_widget = QWidget()
        audio_layout = QVBoxLayout()
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(QLabel("音轨列表"))
        
        self.audio_table = QTableWidget()
        self.audio_table.setColumnCount(2)
        self.audio_table.setHorizontalHeaderLabels(["序号", "音轨文件"])
        self.audio_table.verticalHeader().setVisible(False)
        self.audio_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.audio_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.audio_table.setColumnWidth(0, 40)
        self.audio_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.audio_table.setEditTriggers(QTableWidget.NoEditTriggers)
        audio_layout.addWidget(self.audio_table)
        
        # ── 浮动重排序按钮（统一组件） ──
        self.floating_btns = FloatingReorderButtons(self.audio_table)
        self.floating_btns.move_up.connect(self.move_audio_up)
        self.floating_btns.move_down.connect(self.move_audio_down)
        
        audio_table_widget.setLayout(audio_layout)
        
        match_layout.addWidget(video_table_widget, 1)
        match_layout.addWidget(audio_table_widget, 1)
        
        match_group.setLayout(match_layout)
        main_layout.addWidget(match_group)
        
        info_label = QLabel("提示：音轨按序号一一对应添加到视频（第1个音轨→第1个视频，以此类推）")
        info_label.setStyleSheet("color: gray;")
        main_layout.addWidget(info_label)
        
        self.setLayout(main_layout)
    
    def connect_signals(self):
        self.browse_button.clicked.connect(self.browse_folder)
        self.clear_button.clicked.connect(self.clear_files)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.audio_table.itemClicked.connect(self.on_audio_clicked)
    
    def hideEvent(self, event):
        self.floating_btns.hide_buttons()
        super().hideEvent(event)
    
    def mousePressEvent(self, event):
        global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        self.floating_btns.check_click_outside(global_pos)
        super().mousePressEvent(event)
    
    def on_audio_clicked(self, item):
        row = item.row()
        self.current_selected_row = row
        self.last_click_pos = self.audio_table.cursor().pos()
        self.floating_btns.show_for_row(row, self.last_click_pos)
    
    def on_video_table_clicked(self, item):
        self.floating_btns.hide_buttons()
    
    def move_audio_up(self, row):
        if row <= 0:
            return
        
        self.audio_files[row], self.audio_files[row - 1] = \
            self.audio_files[row - 1], self.audio_files[row]
        
        self.refresh_audio_table()
        self.current_selected_row = row - 1
        self.audio_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()
    
    def move_audio_down(self, row):
        if row < 0 or row >= len(self.audio_files) - 1:
            return
        
        self.audio_files[row], self.audio_files[row + 1] = \
            self.audio_files[row + 1], self.audio_files[row]
        
        self.refresh_audio_table()
        self.current_selected_row = row + 1
        self.audio_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()
    
    def refresh_audio_table(self):
        self.audio_table.setRowCount(0)
        for idx, file_path in enumerate(self.audio_files, 1):
            row = self.audio_table.rowCount()
            self.audio_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.audio_table.setItem(row, 0, idx_item)
            self.audio_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择音轨源文件夹")
        if folder:
            self.source_path_edit.setText(folder)
            self.load_audios()
    
    def clear_files(self):
        self.source_path_edit.clear()
        self.audio_table.setRowCount(0)
        self.audio_files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()
        GlobalSetting.AUDIO_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.AUDIO_LANGUAGE.clear()
    
    def refresh_files(self):
        if self.source_path_edit.text():
            self.load_audios()
    
    def load_audios(self):
        folder = self.source_path_edit.text()
        if not folder or not os.path.isdir(folder):
            return
        
        self.audio_table.setRowCount(0)
        self.audio_files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()
        
        files = []
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                files.append(f)
        
        files.sort()
        
        for idx, file_name in enumerate(files, 1):
            file_path = os.path.join(folder, file_name)
            self.audio_files.append(file_path)
            
            row = self.audio_table.rowCount()
            self.audio_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.audio_table.setItem(row, 0, idx_item)
            self.audio_table.setItem(row, 1, QTableWidgetItem(file_name))
        
        self.auto_match_by_index()
    
    def auto_match_by_index(self):
        GlobalSetting.AUDIO_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.AUDIO_LANGUAGE.clear()
        
        for display_idx, video_idx in enumerate(GlobalSetting.VIDEO_SELECTED_INDICES):
            if display_idx < len(self.audio_files):
                audio_path = self.audio_files[display_idx]
                GlobalSetting.AUDIO_FILES_ABSOLUTE_PATH_LIST[video_idx] = [audio_path]
                GlobalSetting.AUDIO_LANGUAGE[video_idx] = 'chi'
    
    def update_theme_mode_state(self):
        pass
    
    def set_preset_options(self):
        self.refresh_video_list()
    
    def refresh_video_list(self):
        populate_video_ref_table(self.video_table, self.auto_match_by_index)
