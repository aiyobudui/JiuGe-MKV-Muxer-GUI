# -*- coding: utf-8 -*-
"""视频切割可视化预览对话框。

从 MuxSetting.py 抽离为独立模块，降低 MuxSetting.py 单文件体积，
便于单独维护视频播放 / 帧级取点逻辑。依赖 PySide6 的 QtMultimedia 组件。
"""

import logging
import subprocess

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QSlider, QListWidget, QTextEdit, QMessageBox,
)
from packages.Startup.Options import Options


class VideoPreviewDialog(QDialog):
    def __init__(self, video_path, cut_times="", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)  # 兜底：避免焦点落在对话框自身时逃逸到主窗口
        self.setWindowTitle("视频切割 - 可视化预览精准取点")
        self.setMinimumWidth(1100)
        self.setMinimumHeight(800)
        self.video_path = video_path
        self.duration = 0  # 初始化 duration
        self.is_dragging = False  # 标记是否正在拖拽进度条
        self.is_muted = False  # 标记是否静音
        self.cut_segments = []  # 切割段列表，每个元素为 (start_time, end_time)
        self.current_segment_start = None  # 当前正在设置的段的开始时间
        self.editing_segment_index = None  # 当前正在编辑的切割段索引
        self.last_update_time = 0  # 上次更新时间，用于限制更新频率
        self.update_interval = 100  # 更新间隔，单位毫秒
        self.frame_duration_ms = 33.33  # 默认帧时长（30fps），将在首次帧导航时更新为真实值
        self.frame_rate_detected = False  # 标记帧率是否已检测完成
        
        self.setup_ui()
        self.load_video()
        # 加载之前的切割设置
        if cut_times:
            self.load_cut_times(cut_times)
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        
        # 视频播放区域
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(500)
        self.video_widget.setFocusPolicy(Qt.StrongFocus)  # 点击视频画面也能接收键盘快捷键
        main_layout.addWidget(self.video_widget, 1)
        
        # 视频进度条
        self.progress_bar = QSlider(Qt.Horizontal)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1000)
        self.progress_bar.setValue(0)
        # 启用滑块跟踪，使拖拽更流畅
        self.progress_bar.setTracking(True)
        main_layout.addWidget(self.progress_bar)
        
        # 主要内容区域 - 分为左右两部分
        main_content_layout = QHBoxLayout()
        
        # 左侧区域：切割点和切割段列表
        left_layout = QVBoxLayout()
        
        # 切割点（支持手动输入）
        points_group = QGroupBox("切割点（支持手动输入）")
        points_group_layout = QHBoxLayout()
        
        # 开始时间
        self.in_point_label = QLabel("开始：")
        self.in_point_edit = QLineEdit()
        self.in_point_edit.setPlaceholderText("HH:MM:SS.fff")
        self.in_point_edit.setFixedWidth(100)
        self.preview_start_button = QPushButton("跳转")
        self.preview_start_button.setFixedWidth(50)
        
        # 结束时间
        self.out_point_label = QLabel("结束：")
        self.out_point_edit = QLineEdit()
        self.out_point_edit.setPlaceholderText("HH:MM:SS.fff")
        self.out_point_edit.setFixedWidth(100)
        self.preview_end_button = QPushButton("跳转")
        self.preview_end_button.setFixedWidth(50)
        
        self.save_segment_button = QPushButton("保存")
        self.save_segment_button.setFixedWidth(60)
        self.save_segment_button.setEnabled(False)
        
        points_group_layout.addWidget(self.in_point_label)
        points_group_layout.addWidget(self.in_point_edit)
        points_group_layout.addWidget(self.preview_start_button)
        points_group_layout.addSpacing(20)
        points_group_layout.addWidget(self.out_point_label)
        points_group_layout.addWidget(self.out_point_edit)
        points_group_layout.addWidget(self.preview_end_button)
        points_group_layout.addStretch()  # 添加弹性空间，使保存按钮靠右
        points_group_layout.addWidget(self.save_segment_button)
        
        points_group.setLayout(points_group_layout)
        left_layout.addWidget(points_group)
        
        # 切割段列表
        segments_group = QGroupBox("切割段列表")
        segments_group_layout = QVBoxLayout()
        
        # 切割段列表控件
        self.segments_list = QListWidget()
        self.segments_list.setMinimumHeight(60)
        self.segments_list.setMaximumHeight(80)
        segments_group_layout.addWidget(self.segments_list)
        
        # 切割段控制按钮
        segments_buttons_layout = QHBoxLayout()
        segments_buttons_layout.addStretch()
        self.remove_segment_button = QPushButton("删除选中段")
        self.remove_segment_button.setFixedWidth(100)
        self.clear_segments_button = QPushButton("清空所有段")
        self.clear_segments_button.setFixedWidth(100)
        segments_buttons_layout.addWidget(self.remove_segment_button)
        segments_buttons_layout.addWidget(self.clear_segments_button)
        segments_buttons_layout.addStretch()
        segments_group_layout.addLayout(segments_buttons_layout)
        
        segments_group.setLayout(segments_group_layout)
        left_layout.addWidget(segments_group)
        
        # 右侧区域：播放控制和标记按钮
        right_layout = QVBoxLayout()
        
        # 播放控制
        control_layout = QHBoxLayout()
        control_layout.addStretch()
        self.play_button = QPushButton("播放")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止")
        self.mute_button = QPushButton("静音")
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.mute_button)
        control_layout.addSpacing(20)
        # 逐帧控制
        frame_control_layout = QVBoxLayout()
        frame_control_layout.setSpacing(2)
        
        # 第一行：10帧
        frame_10_layout = QHBoxLayout()
        frame_10_layout.setSpacing(2)
        self.prev_10_frame_button = QPushButton("前10帧")
        self.prev_10_frame_button.setFixedWidth(80)
        self.next_10_frame_button = QPushButton("后10帧")
        self.next_10_frame_button.setFixedWidth(80)
        frame_10_layout.addWidget(self.prev_10_frame_button)
        frame_10_layout.addWidget(self.next_10_frame_button)
        frame_10_layout.addStretch()
        frame_control_layout.addLayout(frame_10_layout)
        
        # 第二行：1帧
        frame_1_layout = QHBoxLayout()
        frame_1_layout.setSpacing(2)
        self.prev_frame_button = QPushButton("前1帧")
        self.prev_frame_button.setFixedWidth(80)
        self.next_frame_button = QPushButton("后1帧")
        self.next_frame_button.setFixedWidth(80)
        frame_1_layout.addWidget(self.prev_frame_button)
        frame_1_layout.addWidget(self.next_frame_button)
        frame_1_layout.addStretch()
        frame_control_layout.addLayout(frame_1_layout)
        
        control_layout.addLayout(frame_control_layout)
        control_layout.addStretch()
        right_layout.addLayout(control_layout)
        
        # 时间显示和标记按钮
        time_mark_layout = QHBoxLayout()
        time_mark_layout.addStretch()
        # 时间显示标签
        self.time_label = QLabel("00:00:00.000")
        self.time_label.setFixedWidth(150)
        time_mark_layout.addWidget(QLabel("当前时间："))
        time_mark_layout.addWidget(self.time_label)
        time_mark_layout.addSpacing(20)
        # 标记按钮
        self.mark_in_button = QPushButton("标记开始")
        self.mark_out_button = QPushButton("标记结束")
        time_mark_layout.addWidget(self.mark_in_button)
        time_mark_layout.addWidget(self.mark_out_button)
        time_mark_layout.addStretch()
        right_layout.addLayout(time_mark_layout)
        
        # 将左右布局添加到主内容布局
        main_content_layout.addLayout(left_layout, 1)
        main_content_layout.addLayout(right_layout, 1)
        main_layout.addLayout(main_content_layout)
        
        # 底部按钮
        bottom_layout = QHBoxLayout()
        self.help_button = QPushButton("使用说明")
        bottom_layout.addWidget(self.help_button)
        bottom_layout.addStretch()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        bottom_layout.addWidget(self.ok_button)
        bottom_layout.addWidget(self.cancel_button)
        main_layout.addLayout(bottom_layout)
        
        self.setLayout(main_layout)
        
        # 连接信号
        self.play_button.clicked.connect(self.play_video)
        self.pause_button.clicked.connect(self.pause_video)
        self.stop_button.clicked.connect(self.stop_video)
        self.mute_button.clicked.connect(self.toggle_mute)
        self.prev_frame_button.clicked.connect(self.prev_frame)
        self.next_frame_button.clicked.connect(self.next_frame)
        self.prev_10_frame_button.clicked.connect(self.prev_10_frames)
        self.next_10_frame_button.clicked.connect(self.next_10_frames)
        self.mark_in_button.clicked.connect(self.mark_start_point)
        self.mark_out_button.clicked.connect(self.mark_end_point)
        self.remove_segment_button.clicked.connect(self.remove_segment)
        self.clear_segments_button.clicked.connect(self.clear_segments)
        self.save_segment_button.clicked.connect(self.save_segment)
        self.help_button.clicked.connect(self.show_help)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        # 输入框内容变化时，自动更新保存按钮状态
        self.in_point_edit.textChanged.connect(self.update_save_button_state)
        self.out_point_edit.textChanged.connect(self.update_save_button_state)
        
        # 双击切割段列表时，加载该段的切割点到输入框并跳转到该位置
        self.segments_list.itemDoubleClicked.connect(self.on_segment_double_clicked)
        # 预览按钮信号
        self.preview_start_button.clicked.connect(self.preview_segment_start)
        self.preview_end_button.clicked.connect(self.preview_segment_end)
        self.progress_bar.sliderPressed.connect(self.on_progress_slider_pressed)
        self.progress_bar.sliderReleased.connect(self.on_progress_slider_released)
        self.progress_bar.sliderMoved.connect(self.on_progress_slider_moved)
        
        # 为所有按钮添加点击事件，使它们在点击后将焦点返回进度条
        def set_focus_to_progress_bar():
            self.progress_bar.setFocus()
        
        buttons = [
            self.play_button, self.pause_button, self.stop_button, self.mute_button,
            self.prev_10_frame_button, self.next_10_frame_button,
            self.prev_frame_button, self.next_frame_button, self.mark_in_button,
            self.mark_out_button, self.remove_segment_button,
            self.preview_start_button, self.preview_end_button,
            self.clear_segments_button, self.help_button, self.ok_button, self.cancel_button
        ]
        for button in buttons:
            button.clicked.connect(set_focus_to_progress_bar)
        
        # 为输入框添加焦点丢失事件，使它们在失去焦点后将焦点返回进度条
        def return_focus_to_progress_bar():
            # 延迟一点时间，确保事件处理完成
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self.progress_bar.setFocus)
        
        self.in_point_edit.editingFinished.connect(return_focus_to_progress_bar)
        self.out_point_edit.editingFinished.connect(return_focus_to_progress_bar)
        
        # 使用 QShortcut 实现窗口级全局快捷键：不依赖焦点、不依赖事件过滤器，
        # 无论焦点在进度条/视频画面/按钮/文本框都能可靠触发，彻底消除焦点逃逸问题。
        self._bind_shortcut(Qt.Key_Space, self._toggle_play)
        self._bind_shortcut(Qt.Key_Left, self.prev_frame)
        self._bind_shortcut(Qt.Key_Right, self.next_frame)
        self._bind_shortcut(Qt.Key_Up, self.next_10_frames)
        self._bind_shortcut(Qt.Key_Down, self.prev_10_frames)
        
        # 延迟检测视频帧率，避免界面打开慢
        # 改为：不自动检测，等到用户使用帧导航时再检测
        # from PySide6.QtCore import QTimer
        # QTimer.singleShot(500, self.detect_frame_rate)
        pass  # 不自动检测帧率
    
    def load_video(self):
        try:
            self.player = QMediaPlayer()
            self.player.setVideoOutput(self.video_widget)
            # 启用音频
            self.audio_output = QAudioOutput()
            self.player.setAudioOutput(self.audio_output)
            
            # 优化视频播放性能
            self.player.setPlaybackRate(1.0)  # 确保播放速率正常
            
            # 使用 setSource 方法加载视频（PySide6 6.10+）
            self.player.setSource(QUrl.fromLocalFile(self.video_path))
            
            # 连接信号
            self.player.durationChanged.connect(self.on_duration_changed)
            self.player.positionChanged.connect(self.on_position_changed)
            # 移除 videoAvailableChanged 信号连接，因为在当前 PySide6 版本中不可用
            
            # 后台检测帧率（不阻塞 UI）
            self.detect_frame_rate_async()
        except Exception as e:
            logging.warning(f"视频加载失败: {e}")
            # 视频加载失败时，显示错误信息但仍允许对话框打开
            error_label = QLabel(f"视频加载失败: {str(e)}")
            error_label.setStyleSheet("color: red;")
            error_label.setWordWrap(True)
            # 找到视频播放区域的布局并添加错误信息
            video_container = self.video_widget.parent()
            if video_container:
                video_layout = video_container.layout()
                if video_layout:
                    video_layout.addWidget(error_label)
    
    def detect_frame_rate_async(self):
        """后台线程检测视频帧率（不阻塞 UI）"""
        if self.frame_rate_detected:
            return
        
        import threading as _threading
        
        def _worker():
            self._detect_frame_rate_sync()
        
        thread = _threading.Thread(target=_worker, daemon=True)
        thread.start()
    
    def _detect_frame_rate_sync(self):
        """同步检测视频帧率（在后台线程中调用）"""
        # 如果已经检测完成，直接返回
        if self.frame_rate_detected:
            return
        
        try:
            import os
            import json
            from packages.Startup.Options import Options
            
            if not Options.Mkvmerge_Path or not os.path.exists(Options.Mkvmerge_Path):
                logging.warning("mkvmerge 未找到，使用默认帧率 30fps")
                self.frame_duration_ms = 33.33
                self.frame_rate_detected = True
                return
            
            # 使用 mkvmerge -J 获取视频信息
            result = subprocess.run(
                [Options.Mkvmerge_Path, "-J", self.video_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode != 0:
                logging.warning("mkvmerge 解析失败，使用默认帧率 30fps")
                self.frame_duration_ms = 33.33
                self.frame_rate_detected = True
                return
            
            info = json.loads(result.stdout)
            tracks = info.get("tracks", [])
            
            # 查找视频轨道的帧率
            for track in tracks:
                if track.get("type") == "video":
                    properties = track.get("properties", {})
                    
                    # 方法1：通过 default_duration 计算帧时长
                    # mkvmerge 的 default_duration 单位为纳秒，需转换为毫秒
                    default_duration = properties.get("default_duration")
                    if default_duration:
                        self.frame_duration_ms = default_duration / 1000000.0
                        self.frame_rate_detected = True
                        logging.info(f"检测到帧率：每帧 {self.frame_duration_ms:.2f}ms")
                        return
                    
                    # 方法2：通过 fps 计算帧时长
                    fps = properties.get("fps") or properties.get("frame_rate")
                    if fps:
                        self.frame_duration_ms = 1000.0 / float(fps)
                        self.frame_rate_detected = True
                        logging.info(f"检测到帧率：{fps} fps，每帧 {self.frame_duration_ms:.2f}ms")
                        return
            
            # 如果没有找到帧率信息，使用默认值
            logging.warning("未检测到帧率信息，使用默认 30fps")
            self.frame_duration_ms = 33.33
            self.frame_rate_detected = True
            
        except Exception as e:
            logging.warning(f"帧率检测失败: {e}，使用默认 30fps")
            self.frame_duration_ms = 33.33
            self.frame_rate_detected = True
    
    def play_video(self):
        self.player.play()
        # 更新按钮高亮状态
        self.play_button.setStyleSheet("background-color: #106ebe; color: white;")
        self.pause_button.setStyleSheet("")
        self.stop_button.setStyleSheet("")
    
    def pause_video(self):
        self.player.pause()
        current_pos = self.player.position()
        self.time_label.setText(self.format_time(current_pos))
        self.play_button.setStyleSheet("")
        self.pause_button.setStyleSheet("background-color: #106ebe; color: white;")
        self.stop_button.setStyleSheet("")
    
    def stop_video(self):
        self.player.stop()
        # 更新按钮高亮状态
        self.play_button.setStyleSheet("")
        self.pause_button.setStyleSheet("")
        self.stop_button.setStyleSheet("background-color: #106ebe; color: white;")
    
    def toggle_mute(self):
        self.is_muted = not self.is_muted
        self.audio_output.setMuted(self.is_muted)
        # 更新静音按钮高亮状态
        if self.is_muted:
            self.mute_button.setStyleSheet("background-color: #106ebe; color: white;")
        else:
            self.mute_button.setStyleSheet("")
    
    def prev_frame(self):
        # 逐帧后退。帧率未检测完时使用默认值（30fps），检测完后自动切换为精确值
        frame_duration = self.frame_duration_ms  # 默认 33.33ms = 30fps
        new_pos = max(0, int(self.player.position() - frame_duration))
        self._seek_to(new_pos)
    
    def next_frame(self):
        # 逐帧前进。帧率未检测完时使用默认值（30fps），检测完后自动切换为精确值
        frame_duration = self.frame_duration_ms  # 默认 33.33ms = 30fps
        new_pos = min(self.player.duration(), int(self.player.position() + frame_duration))
        self._seek_to(new_pos)
    
    def prev_10_frames(self):
        # 后退10帧。帧率未检测完时使用默认值（30fps），检测完后自动切换为精确值
        frame_duration = self.frame_duration_ms  # 默认 33.33ms = 30fps
        new_pos = max(0, int(self.player.position() - frame_duration * 10))
        self._seek_to(new_pos)
    
    def next_10_frames(self):
        # 前进10帧。帧率未检测完时使用默认值（30fps），检测完后自动切换为精确值
        frame_duration = self.frame_duration_ms  # 默认 33.33ms = 30fps
        new_pos = min(self.player.duration(), int(self.player.position() + frame_duration * 10))
        self._seek_to(new_pos)
    
    def mark_start_point(self):
        current_pos = self.player.position()
        start_time = self.format_time(current_pos)
        self.current_segment_start = start_time
        self.in_point_edit.setText(start_time)
    
    def mark_end_point(self):
        current_pos = self.player.position()
        end_time = self.format_time(current_pos)
        self.out_point_edit.setText(end_time)
        # 不再自动添加，等待用户点击"保存"按钮
        self.update_save_button_state()

    
    def remove_segment(self):
        selected_items = self.segments_list.selectedItems()
        if selected_items:
            # 收集所有要删除的索引，并从大到小排序（从后往前删）
            indices = sorted([self.segments_list.row(item) for item in selected_items], reverse=True)
            
            # 从后往前删除，避免索引变化
            for index in indices:
                if 0 <= index < len(self.cut_segments):
                    self.cut_segments.pop(index)
            
            # 先更新列表显示
            self.update_segments_list()
            
            # 再重置编辑状态（但不清空输入框）
            self.current_segment_start = None
            self.editing_segment_index = None
            self.update_save_button_state()  # 根据输入框内容更新保存按钮状态
        else:
            QMessageBox.warning(self, "警告", "请先选择要删除的切割段")
    
    def on_segment_double_clicked(self, item):
        """双击切割段列表时，加载该段的切割点到输入框并跳转到开始位置"""
        index = self.segments_list.row(item)
        if 0 <= index < len(self.cut_segments):
            start_time, end_time = self.cut_segments[index]
            self.in_point_edit.setText(start_time)
            self.out_point_edit.setText(end_time)
            self.current_segment_start = start_time
            self.editing_segment_index = index
            self.save_segment_button.setEnabled(True)
            start_ms = self.time_to_ms(start_time)
            self._seek_to(start_ms)
    
    def preview_segment_start(self):
        """跳转到开始输入框中的时间"""
        start_time_str = self.in_point_edit.text().strip()
        if not start_time_str:
            QMessageBox.information(self, "提示", "请先在开始输入框中输入时间")
            return
        
        try:
            start_ms = self.time_to_ms(start_time_str)
            if start_ms < 0 or start_ms > self.player.duration():
                QMessageBox.information(self, "提示", "开始时间超出视频范围")
                return
            self._seek_to(start_ms)
            self.progress_bar.setFocus()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"时间格式错误：{str(e)}")

    
    def preview_segment_end(self):
        """跳转到结束输入框中的时间"""
        end_time_str = self.out_point_edit.text().strip()
        if not end_time_str:
            QMessageBox.information(self, "提示", "请先在结束输入框中输入时间")
            return
        
        try:
            end_ms = self.time_to_ms(end_time_str)
            if end_ms < 0 or end_ms > self.player.duration():
                QMessageBox.information(self, "提示", "结束时间超出视频范围")
                return
            self._seek_to(end_ms)
            self.progress_bar.setFocus()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"时间格式错误：{str(e)}")
    
    def clear_segments(self):
        """清空所有切割段（但不清空输入框）"""
        self.cut_segments.clear()
        self.update_segments_list()
        # 不清空输入框，让用户可以继续使用当前输入的内容
        self.current_segment_start = None
        self.editing_segment_index = None
        self.update_save_button_state()  # 根据输入框内容更新保存按钮状态
    
    def update_segments_list(self):
        self.segments_list.clear()
        for i, (start, end) in enumerate(self.cut_segments):
            item_text = f"段 {i+1}: {start} - {end}"
            self.segments_list.addItem(item_text)
    
    def save_segment(self):
        """保存切割段（添加新段或修改已有段）
        
        Returns:
            bool: True 表示保存成功，False 表示未保存（验证失败/重复）
        """
        start_time = self.in_point_edit.text().strip()
        end_time = self.out_point_edit.text().strip()
        
        if not start_time or not end_time:
            QMessageBox.warning(self, "警告", "请填写完整的开始时间和结束时间")
            return False
        
        if not self.validate_time_format(start_time):
            QMessageBox.warning(self, "警告", "开始时间格式不正确，请使用 HH:MM:SS.fff 格式")
            return False
        
        if not self.validate_time_format(end_time):
            QMessageBox.warning(self, "警告", "结束时间格式不正确，请使用 HH:MM:SS.fff 格式")
            return False
        
        start_ms = self.time_to_ms(start_time)
        end_ms = self.time_to_ms(end_time)
        
        if start_ms >= end_ms:
            QMessageBox.warning(self, "警告", "结束时间必须大于开始时间")
            return False
        
        if self.editing_segment_index is not None:
            # 修改已有段（允许修改为与其他段相同的时间，不做去重）
            self.cut_segments[self.editing_segment_index] = (start_time, end_time)
        else:
            # 添加新段：检查是否已存在相同的时间段
            for existing_start, existing_end in self.cut_segments:
                if existing_start == start_time and existing_end == end_time:
                    QMessageBox.warning(self, "警告", "当前时间段已存在")
                    return False
            self.cut_segments.append((start_time, end_time))
        
        self.update_segments_list()
        # 不清空输入框，让用户可以继续添加或修改其他段
        self.current_segment_start = None
        self.editing_segment_index = None
        self.update_save_button_state()  # 根据输入框内容更新保存按钮状态
        return True
    
    def update_save_button_state(self):
        """根据输入框内容更新保存按钮状态"""
        start_time = self.in_point_edit.text().strip()
        end_time = self.out_point_edit.text().strip()
        # 只有当开始和结束时间都有内容时，才启用保存按钮
        self.save_segment_button.setEnabled(bool(start_time and end_time))
    
    def validate_time_format(self, time_str):
        # 验证时间格式是否为 HH:MM:SS.fff
        import re
        pattern = r'^\d{2}:\d{2}:\d{2}\.\d{3}$'
        return bool(re.match(pattern, time_str))
    
    def time_to_ms(self, time_str):
        # 将时间字符串转换为毫秒
        try:
            parts = time_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds, milliseconds = parts[2].split('.')
            seconds = int(seconds)
            milliseconds = int(milliseconds)
            return hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds
        except (ValueError, IndexError, AttributeError):
            return 0
    
    def format_time(self, ms):
        # 将毫秒转换为 HH:MM:SS.fff 格式
        seconds = ms / 1000
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"
    
    def _seek_to(self, new_pos):
        """统一跳转方法：设置视频位置、更新标签和进度条"""
        self.player.setPosition(new_pos)
        self.time_label.setText(self.format_time(new_pos))
        if not self.is_dragging:
            self.progress_bar.setValue(new_pos)
    
    def on_duration_changed(self, duration):
        # 更新进度条最大值为视频时长（毫秒），实现精准定位
        self.duration = duration
        self.progress_bar.setMaximum(duration)
    
    def on_position_changed(self, position):
        # 限制更新频率，避免过于频繁的UI更新导致卡顿
        if position - self.last_update_time >= self.update_interval or position < self.last_update_time:
            self.last_update_time = position
            self.time_label.setText(self.format_time(position))
            # 更新进度条（毫秒精度），拖拽时不更新以免抢焦点
            if self.duration > 0 and not self.is_dragging:
                self.progress_bar.setValue(position)
    
    def on_progress_slider_pressed(self):
        # 进度条开始拖拽
        self.is_dragging = True
    
    def on_progress_slider_released(self):
        # 拖拽释放时，一次性跳转到滑块位置（value 即毫秒）
        position = self.progress_bar.value()
        self.player.setPosition(position)
        self.is_dragging = False
    
    def on_progress_slider_moved(self, value):
        # 拖拽过程中只更新标签，不跳转视频（避免频繁 seek 导致卡顿）
        # 视频跳转延迟到 on_progress_slider_released 时一次性执行
        self.time_label.setText(self.format_time(value))
    
    def get_cut_times(self):
        # 从切割段列表中获取切割时间（要删除的片段）
        if self.cut_segments:
            segments_str = []
            for start, end in self.cut_segments:
                segments_str.append(f"{start}-{end}")
            return ",".join(segments_str)
        
        # 如果切割段列表为空，直接返回空字符串，不进行视频切割
        return ""
    
    
    def load_cut_times(self, cut_times):
        # 解析并加载之前的切割设置
        if cut_times:
            # 分割多个切割段
            segments = cut_times.split(",")
            for segment in segments:
                segment = segment.strip()
                # 分割开始和结束时间（使用 maxsplit=1，避免时间中的其他字符干扰）
                if "-" in segment:
                    parts = segment.split("-", 1)
                    if len(parts) == 2:
                        start, end = parts[0].strip(), parts[1].strip()
                        # 验证时间格式
                        if self.validate_time_format(start) and self.validate_time_format(end):
                            # 添加到切割段列表
                            self.cut_segments.append((start, end))
            # 更新切割段列表显示
            self.update_segments_list()
    
    def showEvent(self, event):
        # 确保对话框获得焦点，并且进度条获得焦点
        super().showEvent(event)
        # 延迟一点时间，确保界面完全加载
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.progress_bar.setFocus)
    
    def _bind_shortcut(self, key, slot):
        """绑定窗口级全局快捷键，不依赖焦点、不依赖事件过滤器。"""
        sc = QShortcut(QKeySequence(key), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(slot)

    def _toggle_play(self):
        """空格键：在播放/暂停之间切换。"""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause_video()
        else:
            self.play_video()
    
    def show_help(self):
        # 显示详细的使用说明
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle("视频切割使用说明")
        help_dialog.setMinimumWidth(800)
        help_dialog.setMinimumHeight(600)
        
        layout = QVBoxLayout()
        
        # 详细使用说明文本
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setText('''视频切割使用说明

键盘快捷键
- 空格键：播放/暂停视频
- 左箭头：向后移动1帧
- 右箭头：向前移动1帧
- 上箭头：向前移动10帧
- 下箭头：向后移动10帧

精确调整切割点
- 使用方向键的左右箭头逐帧调整，上下箭头每次移动10帧，左右箭头移动1帧，确保精确找到切割点
- 播放视频时，可以按空格键暂停，然后使用方向键微调位置

切割方法
方法一：可视化标记（推荐）
1. 标记开始点：
   - 播放视频到想要保留的开始位置
   - 点击"标记开始"按钮
   - 如果想要更精准，使用快捷键调整帧数到准确位置

2. 标记结束点：
   - 播放视频到想要保留的结束位置
   - 点击"标记结束"按钮
   - 如果想要更精准，使用快捷键调整帧数到准确位置

3. 添加切割段：
   - 开始和结束时间段设置好后，点击"保存"按钮，可将切割段添加到列表中
   - 重复上述步骤，可添加多个切割段
   - 切割段只保留开始和结束中间的部分保存，外部的将被删除

方法二：手动输入时间
1. 在"开始"和"结束"输入框中直接输入时间，格式为 HH:MM:SS.fff
2. 点击"保存"按钮，将设置的切割段添加到列表中

切割段管理
- 删除切割段：在切割段列表中选择要删除的段，点击"删除选中段"按钮
- 清空所有段：点击"清空所有段"按钮，删除所有已设置的切割段

时间格式说明
- 时间格式必须为 HH:MM:SS.fff（小时:分钟:秒.毫秒）
- 例如：00:02:30.500 表示 2分30秒500毫秒
- 不能简化为 02:30 或其他格式

高级技巧
切割掉片头、广告和片尾
1. 保留第一段：设置从片头结束后到广告开始前的时间段
2. 保留第二段：设置从广告结束后到片尾开始前的时间段

注意事项
- 设置的切割时间会应用到所有添加到队列的视频文件（批量）
- 确保切割段的开始时间小于结束时间
- 多个切割段之间可以有间隔，间隔部分会被切割掉
- 切割后的视频会按照原始视频的格式保存，保持画质不变''')
        
        layout.addWidget(help_text)
        
        # 确定按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(help_dialog.accept)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)
        
        help_dialog.setLayout(layout)
        help_dialog.exec()
    
    def accept(self):
        """点击确定时，自动保存当前切割点（如果有），然后关闭对话框。

        仅当输入框中的时间段尚未存在于列表中时才调用 save_segment()，
        避免用户保留已保存段时点击确定触发“当前时间段已存在”的弹窗。
        格式不合法则静默跳过，不提示、不阻止关闭。
        """
        start_time = self.in_point_edit.text().strip()
        end_time = self.out_point_edit.text().strip()

        if start_time and end_time:
            # 先静默校验格式，格式合法才继续处理
            if (self.validate_time_format(start_time) and
                self.validate_time_format(end_time)):
                try:
                    start_ms = self.time_to_ms(start_time)
                    end_ms = self.time_to_ms(end_time)
                    if start_ms < end_ms:
                        # 若该时间段已在列表中（例如用户未清空输入框就点确定），
                        # 直接跳过保存，不再弹出去重警告。
                        if (start_time, end_time) not in self.cut_segments:
                            self.save_segment()  # 复用保存按钮逻辑
                except Exception:
                    pass

        # 停止视频播放并断开信号连接
        if hasattr(self, 'player') and self.player is not None:
            try:
                self.player.stop()
                try:
                    self.player.durationChanged.disconnect(self.on_duration_changed)
                except Exception:
                    pass
                try:
                    self.player.positionChanged.disconnect(self.on_position_changed)
                except Exception:
                    pass
            except Exception:
                pass
        
        super().accept()
    
    def reject(self):
        """点击取消时，关闭对话框"""
        try:
            # 停止视频播放并断开信号连接
            if hasattr(self, 'player') and self.player is not None:
                try:
                    self.player.stop()
                    # 断开信号连接，避免内存泄漏（指定特定的槽函数）
                    try:
                        self.player.durationChanged.disconnect(self.on_duration_changed)
                    except Exception:
                        pass
                    try:
                        self.player.positionChanged.disconnect(self.on_position_changed)
                    except Exception:
                        pass
                except Exception:
                    pass  # 静默失败，不影响关闭对话框
            
            super().reject()
        except Exception as e:
            logging.error(f"reject() 方法执行失败: {e}")
            # 发生错误时，强制关闭对话框
            super().reject()
    
