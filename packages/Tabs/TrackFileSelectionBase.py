# -*- coding: utf-8 -*-
"""音轨/字幕/附件 三个选择页的公有基类。

Audio / Subtitle / Attachment 三个 Tab 的「源选择 + 拖拽 + 表格渲染 + 上下移 +
浏览/清空/刷新 + 与视频列表一一匹配」逻辑 95% 相同，仅文案、扩展名、GlobalSetting
键名与个别匹配规则不同。此处抽出共用实现，差异通过「类属性」+「钩子方法」注入：

- 类属性（子类必须覆盖）：EXTENSIONS / SOURCE_GROUP_TITLE / SOURCE_LABEL_TEXT /
  SOURCE_PLACEHOLDER / MATCH_GROUP_TITLE / TRACK_LIST_LABEL / TABLE_HEADER_TRACK /
  INFO_TEXT / DROP_WARNING_TEXT / DIALOG_TITLE / FILES_GLOBAL_ATTR / LANG_GLOBAL_ATTR。
- 钩子方法（按需覆盖）：auto_match_by_index / clear_global_state / setup_extra_options。
"""
import os

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGroupBox, QMessageBox,
)

from packages.Tabs.GlobalSetting import GlobalSetting
from packages.Widgets.FloatingReorderButtons import FloatingReorderButtons
from packages.Utils.TableHelpers import populate_video_ref_table


class TrackFileSelectionBase(QWidget):
    activation_signal = Signal(bool)
    tab_clicked_signal = Signal()

    # ── 子类必须覆盖的类属性（默认值仅为占位，避免误用基类本身） ──
    EXTENSIONS = ()
    SOURCE_GROUP_TITLE = ""
    SOURCE_LABEL_TEXT = ""
    SOURCE_PLACEHOLDER = ""
    MATCH_GROUP_TITLE = ""
    TRACK_LIST_LABEL = ""
    TABLE_HEADER_TRACK = ""
    INFO_TEXT = ""
    DROP_WARNING_TEXT = ""
    DIALOG_TITLE = ""
    FILES_GLOBAL_ATTR = ""      # 对应 GlobalSetting 上的「文件路径映射」dict 名
    LANG_GLOBAL_ATTR = None     # 对应 GlobalSetting 上的「语言」dict 名；无则为 None
    LANGUAGE_DEFAULT = "chi"

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.files = []
        self.current_selected_row = -1
        self.last_click_pos = None
        self.setup_ui()
        self.connect_signals()

    # ───────────────────────────── UI ─────────────────────────────
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)

        source_group = QGroupBox(self.SOURCE_GROUP_TITLE)
        source_layout = QVBoxLayout()

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel(self.SOURCE_LABEL_TEXT))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText(self.SOURCE_PLACEHOLDER)
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

        match_group = QGroupBox(self.MATCH_GROUP_TITLE)
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

        track_table_widget = QWidget()
        track_layout = QVBoxLayout()
        track_layout.setContentsMargins(0, 0, 0, 0)
        track_layout.addWidget(QLabel(self.TRACK_LIST_LABEL))

        self.track_table = QTableWidget()
        self.track_table.setColumnCount(2)
        self.track_table.setHorizontalHeaderLabels(["序号", self.TABLE_HEADER_TRACK])
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.track_table.setColumnWidth(0, 40)
        self.track_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.track_table.setEditTriggers(QTableWidget.NoEditTriggers)
        track_layout.addWidget(self.track_table)

        # ── 浮动重排序按钮（统一组件） ──
        self.floating_btns = FloatingReorderButtons(self.track_table)
        self.floating_btns.move_up.connect(self.move_up)
        self.floating_btns.move_down.connect(self.move_down)

        track_table_widget.setLayout(track_layout)

        match_layout.addWidget(video_table_widget, 1)
        match_layout.addWidget(track_table_widget, 1)

        match_group.setLayout(match_layout)
        main_layout.addWidget(match_group)

        # 子类注入的额外选项（默认只放提示文案；附件页会覆盖加复选框）
        self.setup_extra_options(main_layout)

        self.setLayout(main_layout)

    def setup_extra_options(self, main_layout):
        """钩子：在匹配组之后往主布局追加额外控件。默认仅放提示文案。"""
        info = QLabel(self.INFO_TEXT)
        info.setStyleSheet("color: gray;")
        main_layout.addWidget(info)

    def connect_signals(self):
        self.browse_button.clicked.connect(self.browse_folder)
        self.clear_button.clicked.connect(self.clear_files)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.track_table.itemClicked.connect(self.on_track_clicked)

    # ───────────────────────── 拖拽 / 事件 ─────────────────────────
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

        dropped_files = []
        folders = []
        non_match_files = []

        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in self.EXTENSIONS:
                    dropped_files.append(path)
                else:
                    non_match_files.append(path)
            elif os.path.isdir(path):
                folders.append(path)

        if non_match_files and not dropped_files and not folders:
            QMessageBox.warning(self, "提示", self.DROP_WARNING_TEXT)
            event.ignore()
            return

        if folders:
            folder = folders[0]
            self.source_path_edit.setText(folder)
            self.load_folder()
        elif dropped_files:
            existing_files = set(self.files)
            new_files = [f for f in dropped_files if f not in existing_files]

            if new_files:
                total_count = len(self.files) + len(new_files)

                if total_count == 1:
                    self.source_path_edit.setText(os.path.dirname(new_files[0]))
                else:
                    self.source_path_edit.clear()

                self.load_files_append(new_files)

        event.acceptProposedAction()

    def hideEvent(self, event):
        self.floating_btns.hide_buttons()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        self.floating_btns.check_click_outside(global_pos)
        super().mousePressEvent(event)

    # ───────────────────────── 表格操作 ─────────────────────────
    def on_track_clicked(self, item):
        row = item.row()
        self.current_selected_row = row
        self.last_click_pos = self.track_table.cursor().pos()
        self.floating_btns.show_for_row(row, self.last_click_pos)

    def on_video_table_clicked(self, item):
        self.floating_btns.hide_buttons()

    def move_up(self, row):
        if row <= 0:
            return

        self.files[row], self.files[row - 1] = \
            self.files[row - 1], self.files[row]

        self.refresh_table()
        self.current_selected_row = row - 1
        self.track_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()

    def move_down(self, row):
        if row < 0 or row >= len(self.files) - 1:
            return

        self.files[row], self.files[row + 1] = \
            self.files[row + 1], self.files[row]

        self.refresh_table()
        self.current_selected_row = row + 1
        self.track_table.selectRow(self.current_selected_row)
        self.floating_btns.show_for_row(self.current_selected_row, self.last_click_pos)
        self.auto_match_by_index()

    def refresh_table(self):
        self.track_table.setRowCount(0)
        for idx, file_path in enumerate(self.files, 1):
            row = self.track_table.rowCount()
            self.track_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.track_table.setItem(row, 0, idx_item)
            self.track_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.DIALOG_TITLE)
        if folder:
            self.source_path_edit.setText(folder)
            self.load_folder()

    def clear_files(self):
        self.source_path_edit.clear()
        self.track_table.setRowCount(0)
        self.files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()
        self.clear_global_state()

    def refresh_files(self):
        if self.source_path_edit.text():
            self.load_folder()

    def load_folder(self):
        folder = self.source_path_edit.text()
        if not folder or not os.path.isdir(folder):
            return

        self.track_table.setRowCount(0)
        self.files = []
        self.current_selected_row = -1
        self.floating_btns.hide_buttons()

        files = []
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in self.EXTENSIONS:
                files.append(f)

        files.sort()

        for idx, file_name in enumerate(files, 1):
            file_path = os.path.join(folder, file_name)
            self.files.append(file_path)

            row = self.track_table.rowCount()
            self.track_table.insertRow(row)
            idx_item = QTableWidgetItem(str(idx))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.track_table.setItem(row, 0, idx_item)
            self.track_table.setItem(row, 1, QTableWidgetItem(file_name))

        self.auto_match_by_index()

    def load_files_append(self, file_paths):
        file_paths.sort()

        for file_path in file_paths:
            self.files.append(file_path)

            row = self.track_table.rowCount()
            self.track_table.insertRow(row)
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.track_table.setItem(row, 0, idx_item)
            self.track_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))

        self.auto_match_by_index()

    # ──────────────────── 与 GlobalSetting 同步（钩子） ────────────────────
    def auto_match_by_index(self):
        """默认「按序号一一对应」匹配（音轨/字幕通用）。附件页覆盖此方法。"""
        files_map = getattr(GlobalSetting, self.FILES_GLOBAL_ATTR)
        files_map.clear()
        lang_map = getattr(GlobalSetting, self.LANG_GLOBAL_ATTR) if self.LANG_GLOBAL_ATTR else None
        if lang_map is not None:
            lang_map.clear()

        for display_idx, video_idx in enumerate(GlobalSetting.VIDEO_SELECTED_INDICES):
            if display_idx < len(self.files):
                path = self.files[display_idx]
                files_map[video_idx] = [path]
                if lang_map is not None:
                    lang_map[video_idx] = self.LANGUAGE_DEFAULT

    def clear_global_state(self):
        """清空本页在 GlobalSetting 上写入的状态。子类可覆盖。"""
        getattr(GlobalSetting, self.FILES_GLOBAL_ATTR).clear()
        if self.LANG_GLOBAL_ATTR:
            getattr(GlobalSetting, self.LANG_GLOBAL_ATTR).clear()

    # ─────────────────────── 主题 / 预设（保持原行为） ───────────────────────
    def update_theme_mode_state(self):
        pass

    def set_preset_options(self):
        self.refresh_video_list()

    def refresh_video_list(self):
        populate_video_ref_table(self.video_table, self.auto_match_by_index)
