# -*- coding: utf-8 -*-
import os
import webbrowser
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QWidget, QStyle, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QCursor


class MktoolnixNotFoundDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MKVToolNix 未安装")
        self.setFixedSize(460, 280)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setObjectName("MkvtoolnixNotFoundDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._selected_path = None

        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.container = QWidget()
        self.container.setObjectName("DialogContainer")
        self.container.setAutoFillBackground(True)

        content = QVBoxLayout()
        content.setContentsMargins(28, 28, 28, 20)
        content.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(16)

        icon_label = QLabel()
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(QSize(48, 48)))
        icon_label.setFixedSize(48, 48)
        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(6)

        title_label = QLabel("未检测到 MKVToolNix")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("DialogTitle")
        title_col.addWidget(title_label)

        desc_label = QLabel(
            "本程序依赖 MKVToolNix，处理 MKV 文件必须安装。<br>"
            "请先安装后再使用本程序，如果已有携带版，"
            "请手动选择 MKVToolNix 的存放文件夹。"
        )
        desc_label.setObjectName("DialogDesc")
        desc_label.setWordWrap(True)
        desc_label.setTextFormat(Qt.TextFormat.RichText)
        title_col.addWidget(desc_label)

        header.addLayout(title_col, 1)
        content.addLayout(header)

        link_row = QHBoxLayout()
        link_row.setContentsMargins(0, 4, 0, 0)
        link_row.addStretch()

        link_label = QLabel()
        link_label.setText(
            '<a href="https://mkvtoolnix.download/downloads.html#windows" '
            'style="color: #0078d4; text-decoration: none; font-size: 12px;">'
            '点击访问 MKVToolNix 官方下载页面'
            '</a>'
        )
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_label.setOpenExternalLinks(False)
        link_label.linkActivated.connect(self.open_download_page)
        link_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        link_row.addWidget(link_label)

        link_row.addStretch()
        content.addLayout(link_row)

        self.container.setLayout(content)
        outer.addWidget(self.container, 1)

        separator = QFrame()
        separator.setObjectName("DialogSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        outer.addWidget(separator)

        btn_bar = QVBoxLayout()
        btn_bar.setContentsMargins(28, 16, 28, 20)
        btn_bar.setSpacing(0)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.select_button = QPushButton("手动选择")
        self.select_button.setObjectName("PrimaryButton")
        self.select_button.setFixedSize(120, 32)
        self.select_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.select_button.clicked.connect(self._do_select)
        btn_row.addWidget(self.select_button)

        btn_row.addStretch()

        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("GhostButton")
        self.close_button.setFixedSize(80, 32)
        self.close_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.close_button.clicked.connect(self.reject)
        btn_row.addWidget(self.close_button)

        btn_bar.addLayout(btn_row)
        outer.addLayout(btn_bar)

        self.setLayout(outer)

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog#MkvtoolnixNotFoundDialog,
            QWidget#DialogContainer,
            QWidget#DialogContainer QLabel,
            QWidget#DialogContainer QFrame,
            QWidget#DialogContainer QPushButton {
                background-color: #ffffff;
            }
            QLabel#DialogTitle {
                color: #1a1a1a;
                font-size: 14px;
                font-weight: bold;
            }
            QLabel#DialogDesc {
                color: #555555;
                font-size: 12px;
            }
            QLabel {
                background: transparent;
            }
            QFrame#DialogSeparator {
                background-color: #e0e0e0;
                max-height: 1px;
            }
            QPushButton#PrimaryButton {
                background-color: #0078d4;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #106ebe;
            }
            QPushButton#PrimaryButton:pressed {
                background-color: #005a9e;
            }
            QPushButton#GhostButton {
                background-color: transparent;
                color: #666666;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton#GhostButton:hover {
                background-color: #f0f0f0;
                color: #333333;
            }
            QPushButton#GhostButton:pressed {
                background-color: #e0e0e0;
            }
        """)

    def _do_select(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 MKVToolNix 安装目录", "")
        if not folder:
            return
        mkvmerge_path = os.path.join(folder, "mkvmerge.exe")
        if os.path.exists(mkvmerge_path):
            self._selected_path = mkvmerge_path
            self.accept()
        else:
            QMessageBox.warning(self, "错误", f"在所选目录中未找到 mkvmerge.exe：\n{folder}")

    def get_selected_path(self):
        return self._selected_path

    def open_download_page(self):
        webbrowser.open("https://mkvtoolnix.download/downloads.html#windows")