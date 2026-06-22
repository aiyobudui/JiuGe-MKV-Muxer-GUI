# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy
)
from packages.Startup import GlobalIcons


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)
        
        title_layout = QHBoxLayout()
        
        if GlobalIcons.AppIcon.get():
            icon_label = QLabel()
            icon_label.setPixmap(GlobalIcons.AppIcon.get().pixmap(64, 64))
            title_layout.addWidget(icon_label)
            title_layout.addSpacing(15)
        
        title_label = QLabel("九歌批量MKV混流工具")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line1)
        
        author_label = QLabel()
        author_label.setTextFormat(Qt.TextFormat.RichText)
        author_label.setOpenExternalLinks(True)
        author_label.setText(
            "<p style='line-height: 1.6;'>"
            "<b>作者：</b>对酒当歌<br><br>"
            "<b>海里免费资源分享</b><br>"
            "网站：<a href='http://www.haozy.top' style='color: #2196F3; text-decoration: none;'>www.haozy.top</a><br>"
            "防失联：<a href='https://link3.cc/hack' style='color: #2196F3; text-decoration: none;'>link3.cc/hack</a>"
            "</p>"
        )
        layout.addWidget(author_label)
        
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line2)
        
        link_label = QLabel()
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setOpenExternalLinks(True)
        link_label.setText(
            "<p style='line-height: 1.8;'>"
            "<b>夸克下载：</b><br>"
            "<a href='https://pan.quark.cn/s/280a143de78b' style='color: #2196F3; text-decoration: none;'>https://pan.quark.cn/s/280a143de78b</a><br><br>"
            "<b>GitHub 仓库：</b><br>"
            "<a href='https://github.com/aiyobudui/jiuge-mkv-gui' style='color: #2196F3; text-decoration: none;'>https://github.com/aiyobudui/jiuge-mkv-gui</a>"
            "</p>"
        )
        layout.addWidget(link_label)
        
        self.setLayout(layout)
        self.adjustSize()
