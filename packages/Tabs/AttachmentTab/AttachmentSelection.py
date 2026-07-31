# -*- coding: utf-8 -*-
import os
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGroupBox, QMessageBox,
    QCheckBox
)

from packages.Tabs.GlobalSetting import GlobalSetting
from packages.Startup.PreDefined import ATTACHMENT_EXTENSIONS
from packages.Widgets.FloatingReorderButtons import FloatingReorderButtons
from packages.Utils.TableHelpers import populate_video_ref_table


class AttachmentSelectionSetting(QWidget):
    activation_signal = Signal(bool)
    tab_clicked_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.attachment_files = []
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
        
        attachment_files = []
        folders = []
        non_attachment_files = []
        
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ATTACHMENT_EXTENSIONS:
                    attachment_files.append(path)
                else:
                    non_attachment_files.append(path)
            elif os.path.isdir(path):
                folders.append(path)
        
        if non_attachment_files and not attachment_files and not folders:
            QMessageBox.warning(self, "提示", "支持的附件格式：\n字体: .ttf .otf .woff\n图片: .jpg .png .webp\n文档: .xml .json .txt .pdf .md .nfo")
            event.ignore()
            return
        
        if folders:
            folder = folders[0]
            self.source_path_edit.setText(folder)
            self.load_attachments()
        elif attachment_files:
            existing_files = set(self.attachment_files)
            new_files = [af for af in attachment_files if af not in existing_files]
            
            if new_files:
                total_count = len(self.attachment_files) + len(new_files)
                
                if total_count == 1:
                    self.source_path_edit.setText(os.path.dirname(new_files[0]))
                else:
                    self.source_path_edit.clear()
                
                self.load_attachment_files_append(new_files)
        
        event.acceptProposedAction()
    
    def load_attachment_files_append(self, file_paths):
        file_paths.sort()
        
        for file_path in file_paths:
            self.attachment_files.append(file_path)
            
            row = self.attachment_table.rowCount()
            self.attachment_table.insertRow(row)
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.attachment_table.setItem(row, 0, idx_item)
            self.attachment_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))
        
        self.auto_match_by_index()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        source_group = QGroupBox("附件源")
        source_layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("附件源："))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("选择包含附件文件的文件夹")
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
        
        match_group = QGroupBox("附件匹配")
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
        
        attachment_table_widget = QWidget()
        attachment_layout = QVBoxLayout()
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.addWidget(QLabel("附件列表"))
        
        self.attachment_table = QTableWidget()
        self.attachment_table.setColumnCount(2)
        self.attachment_table.setHorizontalHeaderLabels(["序号", "附件文件"])
        self.attachment_table.verticalHeader().setVisible(False)
        self.attachment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.attachment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.attachment_table.setColumnWidth(0, 40)
        self.attachment_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.attachment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        attachment_layout.addWidget(self.attachment_table)
        
        # ── 浮动重排序按钮（统一组件） ──
        self.floating_btns = FloatingReorderButtons(self.attachment_table)
        self.floating_btns.move_up.connect(self.move_attachment_up)
        self.floating_btns.move_down.connect(self.move_attachment_down)
        
        attachment_table_widget.setLayout(attachment_layout)
        
        match_layout.addWidget(video_table_widget, 1)
        match_layout.addWidget(attachment_table_widget, 1)
        
        match_group.setLayout(match_layout)
        main_layout.addWidget(match_group)
        
        option_layout = QHBoxLayout()
        
        self.replace_attachment_check = QCheckBox("清除原附件")
        self.replace_attachment_check.setChecked(True)
        self.replace_attachment_check.setToolTip("勾选后将清除视频文件中原有的附件，只保留用户添加的附件")
        option_layout.addWidget(self.replace_attachment_check)
        
        info_label = QLabel("提示：附件将添加到所有视频文件中")
        info_label.setStyleSheet("color: gray;")
        option_layout.addWidget(info_label)
        
        main_layout.addLayout(option_layout)
        
        self.setLayout(main_layout)
    
    def connect_signals(self):
        self.browse_button.clicked.connect(self.browse_folder)
        self.clear_button.clicked.connect(self.clear_files)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.attachment_table.itemClicked.connect(self.on_attachment_clicked)
    
    def hideEvent(self, event):
        self.floating_btns.hide_buttons()
        super().hideEvent(event)
    
    def mousePressEvent(self, event):
        global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        self.floating_btns.check_click_outside(global_pos)
        super().mousePressEvent(event)
    
    def on_attachment_clicked(self, item):
        row = item.row()
        self.current_selected_row = row
        self.last_click_pos = self.attachment_table.cursor().pos()
        self.floating_btns.show_for_row(row, self.last_click_pos)
    
    def on_video_table_clicked(self, item):
        self.floating_btns.hide_buttons()
    
    def move_attachment_up(self, row):
        if row <= 0:
            return
        
        self.attachment_files[row], self.attachment_files[row - 1] = \
            self.attachment_files[row - 1], self.attachment_files[row]
        
        self.refresh_attachment_table()
        self.current_selected_row = row - 1
        self.attachment_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()
    
    def move_attachment_down(self, row):
        if row < 0 or row >= len(self.attachment_files) - 1:
            return
        
        self.attachment_files[row], self.attachment_files[row + 1] = \
            self.attachment_files[row + 1], self.attachment_files[row]
        
        self.refresh_attachment_table()
        self.current_selected_row = row + 1
        self.attachment_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()
    
    def refresh_attachment_table(self):
        self.attachment_table.setRowCount(0)
        for idx, file_path in enumerate(self.attachment_files, 1):
            row = self.attachment_table.rowCount()
            self.attachment_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.attachment_table.setItem(row, 0, idx_item)
            self.attachment_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择附件源文件夹")
        if folder:
            self.source_path_edit.setText(folder)
            self.load_attachments()
    
    def clear_files(self):
        self.source_path_edit.clear()
        self.attachment_table.setRowCount(0)
        self.attachment_files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()
        GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.clear()
        GlobalSetting.ATTACHMENT_ENABLED = False
    
    def refresh_files(self):
        if self.source_path_edit.text():
            self.load_attachments()
    
    def load_attachments(self):
        folder = self.source_path_edit.text()
        if not folder or not os.path.isdir(folder):
            return
        
        self.attachment_table.setRowCount(0)
        self.attachment_files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()
        
        files = []
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in ATTACHMENT_EXTENSIONS:
                files.append(f)
        
        files.sort()
        
        for idx, file_name in enumerate(files, 1):
            file_path = os.path.join(folder, file_name)
            self.attachment_files.append(file_path)
            
            row = self.attachment_table.rowCount()
            self.attachment_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.attachment_table.setItem(row, 0, idx_item)
            self.attachment_table.setItem(row, 1, QTableWidgetItem(file_name))
        
        self.auto_match_by_index()
    
    def auto_match_by_index(self):
        GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.clear()
        
        for video_idx in GlobalSetting.VIDEO_SELECTED_INDICES:
            if video_idx not in GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST:
                GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST[video_idx] = []
            for attachment_path in self.attachment_files:
                GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST[video_idx].append(attachment_path)
        
        GlobalSetting.ATTACHMENT_REPLACE_EXISTING = self.replace_attachment_check.isChecked()
        
        if self.attachment_files:
            GlobalSetting.ATTACHMENT_ENABLED = True
        else:
            GlobalSetting.ATTACHMENT_ENABLED = False
    
    def update_theme_mode_state(self):
        pass
    
    def set_preset_options(self):
        self.refresh_video_list()
    
    def refresh_video_list(self):
        populate_video_ref_table(self.video_table, self.auto_match_by_index)
