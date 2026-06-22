# -*- coding: utf-8 -*-
import os
import re
import zlib
import subprocess
import threading
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import Signal, Qt, QUrl, QEvent, QSize
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGroupBox, QCheckBox,
    QProgressBar, QMessageBox, QDialog, QTextEdit, QSlider, QSplitter, QListWidget
)

from packages.Startup import GlobalIcons
from packages.Startup.Options import Options
from packages.Tabs.GlobalSetting import GlobalSetting, get_readable_filesize
from packages.Tabs.MuxSetting.TrackSelectionDialog import TrackSelectionDialog



class MuxSettingTab(QWidget):
    start_muxing_signal = Signal()
    update_task_bar_progress_signal = Signal(int)
    update_task_signal = Signal(int, str, str, str)
    update_task_progress_signal = Signal(int, int)
    update_progress_signal = Signal(int, str)
    muxing_finished_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.track_selections = {
            'audio': {}, 
            'subtitle': {}, 
            'default_audio': {}, 
            'default_subtitle': {},
            'default_video': {},
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {},
            'audio_track_names': {},
            'subtitle_track_names': {},
            'video_track_names': {}
        }
        self.video_cut_selections = {}  # 存储每个视频的切割时间设置
        self.setup_ui()
        self.connect_signals()
        self.total_tasks = 0
        self.stop_requested = False
        self.completed_count = 0
        self.count_lock = threading.Lock()
        self.task_progress = {}  # 存储每个任务的进度 (task_index -> progress)
        self.task_progress_lock = threading.Lock()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        top_layout = QHBoxLayout()
        
        output_group = QGroupBox("输出设置")
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出目录："))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.setPlaceholderText("请选择输出文件夹")
        output_layout.addWidget(self.output_path_edit)
        
        self.browse_output_button = QPushButton("浏览")
        self.browse_output_button.setFixedWidth(60)
        output_layout.addWidget(self.browse_output_button)
        
        output_layout.addWidget(QLabel("输出格式："))
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItems(["MP4", "MKV"])
        self.output_format_combo.setFixedWidth(80)
        output_layout.addWidget(self.output_format_combo)
        
        output_group.setLayout(output_layout)
        top_layout.addWidget(output_group)
        
        button_group = QGroupBox("操作按钮")
        button_layout = QHBoxLayout()
        self.clear_all_button = QPushButton("清空全部")
        self.clear_all_button.setFixedWidth(80)
        button_layout.addWidget(self.clear_all_button)
        
        self.add_to_queue_button = QPushButton("添加到队列")
        self.add_to_queue_button.setFixedWidth(100)
        button_layout.addWidget(self.add_to_queue_button)
        
        button_layout.addSpacing(20)
        
        self.start_button = QPushButton("开始混流")
        self.start_button.setFixedWidth(100)
        self.start_button.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold;")
        button_layout.addWidget(self.start_button)
        
        button_group.setLayout(button_layout)
        top_layout.addWidget(button_group)
        
        main_layout.addLayout(top_layout)
        
        options_group = QGroupBox("混流选项")
        options_layout = QHBoxLayout()
        
        self.add_crc_check = QCheckBox("写入新CRC")
        self.add_crc_check.setChecked(True)
        options_layout.addWidget(self.add_crc_check)
        
        self.keep_log_check = QCheckBox("保留日志")
        options_layout.addWidget(self.keep_log_check)
        self.abort_on_error_check = QCheckBox("出错中止")
        self.abort_on_error_check.setChecked(True)
        options_layout.addWidget(self.abort_on_error_check)
        
        options_layout.addWidget(QLabel("视频标题："))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("设置视频内标题（留空则清空）")
        self.title_edit.setFixedWidth(250)
        options_layout.addWidget(self.title_edit)
        
        options_layout.addStretch()
        
        self.video_cut_button = QPushButton("视频切割")
        self.video_cut_button.setFixedWidth(80)
        self.video_cut_button.setEnabled(False)
        self.video_cut_button.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #999999;
                border: 1px solid #cccccc;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
        options_layout.addWidget(self.video_cut_button)
        options_layout.addSpacing(10)
        
        self.track_select_button = QPushButton("轨道选择")
        self.track_select_button.setFixedWidth(80)
        self.track_select_button.setEnabled(False)
        self.track_select_button.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #999999;
                border: 1px solid #cccccc;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
        options_layout.addWidget(self.track_select_button)
        
        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)
        
        queue_group = QGroupBox("任务队列")
        queue_layout = QVBoxLayout()
        
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(5)
        self.task_table.setHorizontalHeaderLabels(["名称", "状态", "处理前大小", "进度", "处理后大小"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.task_table.setColumnWidth(1, 80)
        self.task_table.setColumnWidth(2, 100)
        self.task_table.setColumnWidth(3, 80)
        self.task_table.setColumnWidth(4, 100)
        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        queue_layout.addWidget(self.task_table)
        queue_group.setLayout(queue_layout)
        main_layout.addWidget(queue_group)
        
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("总进度"))
        self.total_progress_bar = QProgressBar()
        self.total_progress_bar.setTextVisible(True)
        self.total_progress_bar.setFormat("%p% - %v/%m")
        progress_layout.addWidget(self.total_progress_bar)
        progress_group = QWidget()
        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)
        
        self.setLayout(main_layout)
    
    def connect_signals(self):
        self.browse_output_button.clicked.connect(self.browse_output_folder)
        self.clear_all_button.clicked.connect(self.clear_all_tasks)
        self.add_to_queue_button.clicked.connect(self.add_to_queue)
        self.start_button.clicked.connect(self.toggle_muxing)
        
        self.update_task_signal.connect(self.on_update_task)
        self.update_task_progress_signal.connect(self.on_update_task_progress)
        self.update_progress_signal.connect(self.on_update_progress)
        self.muxing_finished_signal.connect(self.on_muxing_finished)
        
        self.track_select_button.clicked.connect(self.show_track_selection_dialog)
        self.video_cut_button.clicked.connect(self.show_video_cut_dialog)
    
    def show_track_selection_dialog(self):
        if not GlobalSetting.VIDEO_FILES_LIST:
            QMessageBox.warning(self, "警告", "请先添加视频文件")
            return
        # 传递之前的轨道选择设置
        dialog = TrackSelectionDialog(self, self.track_selections)
        if dialog.exec():
            selections = dialog.get_selections()
            self.track_selections['audio'] = selections['audio']
            self.track_selections['subtitle'] = selections['subtitle']
            self.track_selections['default_audio'] = selections['default_audio']
            self.track_selections['default_subtitle'] = selections['default_subtitle']
            self.track_selections['external_audio'] = selections['external_audio']
            self.track_selections['external_subtitle'] = selections['external_subtitle']
            self.track_selections['audio_languages'] = selections['audio_languages']
            self.track_selections['subtitle_languages'] = selections['subtitle_languages']
            self.track_selections['audio_track_names'] = selections.get('audio_track_names', {})
            self.track_selections['subtitle_track_names'] = selections.get('subtitle_track_names', {})
            self.track_selections['video_track_names'] = selections.get('video_track_names', {})
            self.track_selections['default_video'] = selections.get('default_video', {})
    
    def show_video_cut_dialog(self):
        if not GlobalSetting.VIDEO_FILES_LIST:
            QMessageBox.warning(self, "警告", "请先添加视频文件")
            return
        
        if not GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST:
            QMessageBox.warning(self, "警告", "视频文件路径列表为空")
            return
        
        # 使用第一个视频文件作为预览
        try:
            video_path = GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST[0]
            if not os.path.exists(video_path):
                QMessageBox.warning(self, "警告", f"视频文件不存在: {video_path}")
                return
            
            # 获取之前的切割设置（如果有）
            cut_times = ""
            if self.video_cut_selections:
                # 使用第一个视频的切割设置作为参考
                first_video_index = next(iter(self.video_cut_selections.keys()))
                data = self.video_cut_selections[first_video_index]
                # video_cut_selections 存储 (keep_times, keep_times) 元组，用户选中的就是保留段
                if isinstance(data, tuple) and len(data) == 2:
                    cut_times = data[0]  # 用户选中的保留段（用于对话框加载）
                else:
                    cut_times = data if isinstance(data, str) else ""
            
            dialog = VideoPreviewDialog(video_path, cut_times, self)
            if dialog.exec():
                # 用户选中的时间段就是要保留的，直接用作 mkvmerge --split parts: 参数
                keep_times = dialog.get_cut_times()
                if keep_times:
                    self.video_cut_selections.clear()
                    for i in GlobalSetting.VIDEO_SELECTED_INDICES:
                        self.video_cut_selections[i] = (keep_times, keep_times)
                    # 同时也用范围索引兜底
                    for i in range(len(GlobalSetting.VIDEO_FILES_LIST)):
                        self.video_cut_selections[i] = (keep_times, keep_times)
                else:
                    # 用户清空了切割段，清除所有设置
                    self.video_cut_selections.clear()
            # 不再在取消时清除切割设置，保持之前的设置
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开视频预览对话框失败: {str(e)}")
    
    def on_update_task(self, row, status, progress, output_size):
        if row < self.task_table.rowCount():
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 1, status_item)
            
            progress_item = QTableWidgetItem(progress)
            progress_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 3, progress_item)
            
            output_size_item = QTableWidgetItem(output_size)
            output_size_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(row, 4, output_size_item)
    
    def on_update_task_progress(self, task_index, progress):
        # 更新任务列表中的进度
        if task_index < self.task_table.rowCount():
            progress_item = QTableWidgetItem(f"{progress}%")
            progress_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(task_index, 3, progress_item)
        
        # 更新任务进度字典
        with self.task_progress_lock:
            self.task_progress[task_index] = progress
        
        # 计算总进度
        self.calculate_and_update_total_progress()
    
    def calculate_and_update_total_progress(self):
        total_tasks = self.total_tasks
        if total_tasks == 0:
            return
        
        # 计算所有任务的平均进度
        with self.task_progress_lock:
            sum_progress = sum(self.task_progress.get(i, 0) for i in range(total_tasks))
        
        total_progress = int(sum_progress / total_tasks)
        with self.count_lock:
            completed = self.completed_count
        
        self.update_progress_signal.emit(total_progress, f"正在处理 {completed}/{total_tasks}")
    
    def on_update_progress(self, progress, text):
        self.total_progress_bar.setMaximum(100)
        self.total_progress_bar.setValue(progress)
        self.total_progress_bar.setFormat(f"%p% - {text}")
    
    def on_muxing_finished(self):
        self.set_button_state(is_muxing=False)
        GlobalSetting.MUXING_ON = False
        GlobalSetting.JOB_QUEUE_FINISHED = True
        
        success_count = sum(1 for i in range(self.task_table.rowCount()) 
                          if self.task_table.item(i, 1) and self.task_table.item(i, 1).text() == "成功")
        fail_count = self.task_table.rowCount() - success_count
        
        self.total_progress_bar.setValue(100)
        if fail_count == 0:
            self.total_progress_bar.setFormat(f"100% - 完成！成功: {success_count}")
        else:
            self.total_progress_bar.setFormat(f"100% - 完成！成功: {success_count}，失败: {fail_count}")
    
    def set_button_state(self, is_muxing):
        if is_muxing:
            self.start_button.setText("停止混流")
            self.start_button.setStyleSheet("background-color: #d13438; color: white; font-weight: bold;")
            self.clear_all_button.setEnabled(False)
            self.add_to_queue_button.setEnabled(False)
        else:
            self.start_button.setText("开始混流")
            self.start_button.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold;")
            self.clear_all_button.setEnabled(True)
            self.add_to_queue_button.setEnabled(True)
    
    def toggle_muxing(self):
        if GlobalSetting.MUXING_ON:
            self.stop_muxing()
        else:
            self.start_muxing()
    
    def browse_output_folder(self):
        # 默认打开视频源的路径
        default_dir = ""
        if GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST:
            default_dir = os.path.dirname(GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST[0])
        
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹", default_dir)
        if folder:
            self.output_path_edit.setText(folder)
    
    def clear_all_tasks(self):
        self.task_table.setRowCount(0)
        self.track_selections = {
            'audio': {}, 
            'subtitle': {}, 
            'default_audio': {}, 
            'default_subtitle': {},
            'default_video': {},
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {},
            'audio_track_names': {},
            'subtitle_track_names': {},
            'video_track_names': {}
        }
        self.track_select_button.setEnabled(False)
        self.track_select_button.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #999999;
                border: 1px solid #cccccc;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
        
        self.video_cut_button.setEnabled(False)
        self.video_cut_button.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #999999;
                border: 1px solid #cccccc;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
    
    def update_track_menus(self):
        self.track_selections = {
            'audio': {}, 
            'subtitle': {}, 
            'default_audio': {}, 
            'default_subtitle': {},
            'default_video': {},
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {},
            'audio_track_names': {},
            'subtitle_track_names': {},
            'video_track_names': {}
        }
    
    def get_selected_audio_tracks(self):
        result = {}
        if self.track_selections['audio']:
            for video_idx, track_ids in self.track_selections['audio'].items():
                result[video_idx] = track_ids
        return result
    
    def get_selected_subtitle_tracks(self):
        result = {}
        if self.track_selections['subtitle']:
            for video_idx, track_ids in self.track_selections['subtitle'].items():
                result[video_idx] = track_ids
        return result
    
    def add_to_queue(self):
        if not GlobalSetting.VIDEO_FILES_LIST:
            QMessageBox.warning(self, "警告", "请先在视频选项卡中添加视频文件")
            return
        
        # 不再重置轨道选择设置，保留用户之前的设置
        
        self.task_table.setRowCount(0)
        self.task_video_indices = []
        self.task_progress = {}  # 重置任务进度字典
        
        for video_idx in GlobalSetting.VIDEO_SELECTED_INDICES:
            if video_idx < len(GlobalSetting.VIDEO_FILES_LIST):
                video_name = GlobalSetting.VIDEO_FILES_LIST[video_idx]
                video_size = get_readable_filesize(GlobalSetting.VIDEO_FILES_SIZE_LIST[video_idx])
                
                row = self.task_table.rowCount()
                self.task_table.insertRow(row)
                self.task_table.setItem(row, 0, QTableWidgetItem(video_name))
                
                status_item = QTableWidgetItem("等待中")
                status_item.setTextAlignment(Qt.AlignCenter)
                self.task_table.setItem(row, 1, status_item)
                
                size_item = QTableWidgetItem(video_size)
                size_item.setTextAlignment(Qt.AlignCenter)
                self.task_table.setItem(row, 2, size_item)
                
                progress_item = QTableWidgetItem("0%")
                progress_item.setTextAlignment(Qt.AlignCenter)
                self.task_table.setItem(row, 3, progress_item)
                
                output_size_item = QTableWidgetItem("-")
                output_size_item.setTextAlignment(Qt.AlignCenter)
                self.task_table.setItem(row, 4, output_size_item)
                self.task_video_indices.append(video_idx)
                self.task_progress[row] = 0  # 初始化任务进度为 0%
        
        self.total_tasks = self.task_table.rowCount()
        self.completed_count = 0
        
        self.track_select_button.setEnabled(True)
        self.track_select_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: 1px solid #006cbd;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        
        self.video_cut_button.setEnabled(True)
        self.video_cut_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: 1px solid #006cbd;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
    
    def start_muxing(self):
        if self.task_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "请先添加任务到队列")
            return
        
        if not Options.Mkvmerge_Path or not os.path.exists(Options.Mkvmerge_Path):
            QMessageBox.warning(self, "警告", "请先设置 mkvmerge.exe 路径")
            return
        
        output_dir = self.output_path_edit.text()
        if not output_dir:
            QMessageBox.warning(self, "警告", "请先设置输出目录")
            return
        
        self.set_button_state(is_muxing=True)
        GlobalSetting.MUXING_ON = True
        self.stop_requested = False
        self.completed_count = 0
        
        # 重置任务进度字典
        with self.task_progress_lock:
            for i in range(self.total_tasks):
                self.task_progress[i] = 0
        
        self.start_muxing_signal.emit()
        
        # 混流是 IO 密集型（mkvmerge subprocess），最高 16 线程
        from packages.Utils.BackgroundRunner import BackgroundRunner
        total_tasks = self.task_table.rowCount()
        thread_count = BackgroundRunner.calc_workers(total_tasks)
        
        # 构建任务数据列表
        tasks = []
        for i in range(total_tasks):
            original_video_index = self.task_video_indices[i]
            video_path = GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST[original_video_index]
            video_name = GlobalSetting.VIDEO_FILES_LIST[original_video_index]
            output_path = self.get_output_path(video_path)
            args, split_final_output = self.build_mkvmerge_args(original_video_index, video_path, output_path)
            tasks.append({
                'task_index': i,
                'args': args,
                'video_name': video_name,
                'video_path': video_path,
                'split_final_output': split_final_output,
            })
        
        def mux_worker(task_data, task_id):
            """包装 process_single_task 为 BackgroundRunner 要求的签名"""
            success, output_size, return_code = self.process_single_task(
                task_data['task_index'], task_data['args'],
                task_data['video_name'], task_data['video_path'],
                task_data.get('split_final_output')
            )
            return {'success': success, 'output_size': output_size, 'return_code': return_code}
        
        def on_task_complete(task_id, result):
            """后台线程回调：每完成一个任务时更新 UI"""
            success = result.get('success', False)
            output_size = result.get('output_size', '-')
            self.update_task_signal.emit(task_id, "成功" if success else "失败",
                                         "100%" if success else "0%", output_size)
            with self.count_lock:
                self.completed_count += 1
            # 出错中止检查
            if not success and self.abort_on_error_check.isChecked():
                self._bg_runner.request_stop()
        
        def on_all_complete(completed, failed, total):
            """后台线程回调：全部任务完成"""
            if not self.stop_requested:
                self.muxing_finished_signal.emit()
        
        self._bg_runner = BackgroundRunner()
        self._bg_runner.task_error.connect(
            lambda task_id, error: self.update_task_signal.emit(task_id, "失败", "0%", "-")
        )
        self._bg_runner.run(tasks, mux_worker, max_workers=thread_count,
                            on_task_done=on_task_complete, on_all_done=on_all_complete)
    
    def stop_muxing(self):
        self.stop_requested = True
        if hasattr(self, '_bg_runner'):
            self._bg_runner.request_stop()
        GlobalSetting.MUXING_ON = False
        self.set_button_state(is_muxing=False)
    
    def process_single_task(self, task_index, args, video_name, video_path, split_final_output=None):
        self.update_task_signal.emit(task_index, "执行中", "0%", "-")
        self.update_task_progress_signal.emit(task_index, 0)
        
        stdout_text = ""
        stderr_text = ""
        
        # 从 args 安全提取输出路径（避免硬编码 args[2] 索引）
        output_path = self._get_output_path_from_args(args)
        
        try:
            # 如果使用了切割（--split），提前清理旧的切割输出文件，避免 mkvmerge 因文件已存在而失败
            is_split = any('--split' in arg for arg in args)
            if is_split:
                import glob
                output_dir = os.path.dirname(output_path)
                name_without_ext, ext = os.path.splitext(os.path.basename(output_path))
                ext_clean = ext[1:] if ext else ''
                # 查找并删除旧的切割文件（形如 name-001.ext 等）
                cleanup_patterns = [
                    f"{name_without_ext}-*.{ext_clean}",
                    f"{name_without_ext}_*.{ext_clean}",
                ]
                for pattern in cleanup_patterns:
                    for old_file in glob.glob(os.path.join(output_dir, pattern)):
                        try:
                            os.remove(old_file)
                            logging.info(f"已删除旧切割文件: {old_file}")
                        except OSError as e:
                            logging.warning(f"删除旧切割文件失败: {old_file}, 错误: {e}")
            
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # 使用 Popen 实时读取输出
            process = subprocess.Popen(
                [Options.Mkvmerge_Path] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
            
            # 实时读取输出并解析进度
            last_progress = 0
            if process.stdout:
                for line in process.stdout:
                    stdout_text += line
                    # 解析 mkvmerge 的进度信息（格式通常是 "Progress: X%"）
                    progress = self.parse_mkvmerge_progress(line)
                    if progress is not None and progress != last_progress:
                        last_progress = progress
                        self.update_task_progress_signal.emit(task_index, progress)
            
            # 读取剩余的错误输出
            if process.stderr:
                stderr_text = process.stderr.read()
            
            # 等待进程结束
            return_code = process.wait()
            success = return_code in [0, 1]
            
            # 任务完成，设置进度为 100%
            self.update_task_progress_signal.emit(task_index, 100)
            
            # 检查是否使用了切割功能
            is_split = any('--split' in arg for arg in args)
            
            if success:
                if is_split:
                    # 查找 mkvmerge 产生的切割文件（形如 name-001.ext 等）
                    output_dir = os.path.dirname(output_path)
                    output_name = os.path.basename(output_path)
                    name_without_ext, ext = os.path.splitext(output_name)
                    ext_clean = ext[1:] if ext else ''
                    
                    import glob
                    # 匹配切割输出文件的命名模式
                    split_pattern = f"{name_without_ext}-*.{ext_clean}"
                    split_files = sorted(glob.glob(os.path.join(output_dir, split_pattern)))
                    
                    if split_files and split_final_output:
                        # 用 mkvmerge 拼接所有切割文件为最终单文件
                        concat_args = ['--gui-mode', '-o', split_final_output]
                        for sf in split_files:
                            concat_args.append(sf)
                            concat_args.append('+')
                        concat_args.pop()  # 去掉最后一个 '+'
                        
                        concat_process = subprocess.Popen(
                            [Options.Mkvmerge_Path] + concat_args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            encoding='utf-8',
                            errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        concat_stdout, concat_stderr = concat_process.communicate()
                        concat_rc = concat_process.returncode
                        
                        if concat_rc in [0, 1]:
                            # 拼接成功：更新 output_path 指向最终文件
                            output_path = split_final_output
                            # 删除临时切割分片文件（name-001.ext 等）
                            for sf in split_files:
                                try:
                                    os.remove(sf)
                                except OSError:
                                    pass
                            
                            # 对最终文件做 CRC 校验和大小计算
                            if os.path.exists(output_path):
                                if self.add_crc_check.isChecked():
                                    crc = self.calculate_crc32(output_path)
                                    if crc:
                                        input_dir = os.path.dirname(video_path)
                                        final_dir = os.path.dirname(output_path)
                                        if os.path.abspath(input_dir) == os.path.abspath(final_dir):
                                            new_path = self.add_crc_to_filename(output_path, crc)
                                            if new_path != output_path:
                                                output_path = new_path
                                output_size = get_readable_filesize(os.path.getsize(output_path))
                            else:
                                output_size = "-"
                        else:
                            logging.error(f"切割文件拼接失败: {concat_stderr}")
                            success = False
                    elif split_files:
                        # 没有 split_final_output 但仍按多文件处理（兜底）
                        total_size = sum(os.path.getsize(f) for f in split_files)
                        output_size = get_readable_filesize(total_size)
                    elif os.path.exists(output_path):
                        # 单段切割：mkvmerge 直接写入基础文件名，未产生 name-001.ext 分片
                        if self.add_crc_check.isChecked():
                            crc = self.calculate_crc32(output_path)
                            if crc:
                                input_dir = os.path.dirname(video_path)
                                final_dir = os.path.dirname(output_path)
                                if os.path.abspath(input_dir) == os.path.abspath(final_dir):
                                    new_path = self.add_crc_to_filename(output_path, crc)
                                    if new_path != output_path:
                                        output_path = new_path
                        output_size = get_readable_filesize(os.path.getsize(output_path))
                    else:
                        output_size = "-"
                else:
                    # 正常情况，检查原始输出路径
                    if os.path.exists(output_path):
                        if self.add_crc_check.isChecked():
                            # 计算CRC32校验值（用于完整性验证）
                            crc = self.calculate_crc32(output_path)
                            if crc:
                                # 只有当输出目录与输入目录相同时才添加CRC到文件名（避免覆盖原文件）
                                input_dir = os.path.dirname(video_path)
                                output_dir = os.path.dirname(output_path)
                                if os.path.abspath(input_dir) == os.path.abspath(output_dir):
                                    new_path = self.add_crc_to_filename(output_path, crc)
                                    if new_path != output_path:
                                        output_path = new_path
                        
                        output_size = get_readable_filesize(os.path.getsize(output_path))
                    else:
                        output_size = "-"
            else:
                output_size = "-"
            
            self.save_log_file(video_name, stdout_text, stderr_text, success)
            
            return success, output_size, return_code
        except Exception as e:
            logging.error(f"运行mkvmerge异常: {e}")
            return False, "-", -1
    
    def parse_mkvmerge_progress(self, line):
        """解析 mkvmerge 输出中的进度信息"""
        # mkvmerge --gui-mode 输出格式是 "#GUI#progress X"
        # 同时也尝试匹配普通模式的格式
        patterns = [
            r'#GUI#progress\s+(\d+)',
            r'Progress:\s*(\d+)%',
            r'(\d+)%',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    progress = int(match.group(1))
                    if 0 <= progress <= 100:
                        return progress
                except ValueError:
                    pass
        
        return None
    
    def get_output_path(self, video_path):
        output_dir = self.output_path_edit.text()
        if output_dir:
            video_name = os.path.splitext(os.path.basename(video_path))[0]
            if self.add_crc_check.isChecked():
                video_name = self.remove_crc_from_filename(video_name)
            output_format = self.output_format_combo.currentText().lower()
            
            # 检查输出目录是否与输入目录相同
            input_dir = os.path.dirname(video_path)
            if os.path.abspath(output_dir) == os.path.abspath(input_dir):
                # 添加后缀避免冲突
                video_name += "_1"
            
            return os.path.join(output_dir, video_name + "." + output_format)
        else:
            return video_path
    
    @staticmethod
    def _get_output_path_from_args(args):
        """从 mkvmerge args 列表中安全提取输出路径（查找 -o 参数）。
        
        避免硬编码 args[2] 索引，适应参数结构的未来变化。
        """
        try:
            idx = args.index('-o')
            return args[idx + 1]
        except (ValueError, IndexError):
            return args[2]  # 兜底：保持旧行为
    
    def build_mkvmerge_args(self, video_index, video_path, output_path):
        args = ['--gui-mode', '-o', output_path]
        split_final_output = None  # 不为空时表示使用了视频切割，需要拼接
        
        # 添加/清空文件标题
        title = self.title_edit.text().strip()
        args.extend(['--title', title])
        
        # 添加视频切割参数（video_cut_selections 存储 (keep_times, keep_times) 元组，用户选中的就是保留段）
        if video_index in self.video_cut_selections:
            data = self.video_cut_selections[video_index]
            if isinstance(data, tuple) and len(data) == 2:
                keep_times = data[0]  # 用户选中的保留段
            else:
                keep_times = data if isinstance(data, str) else ""  # 兼容旧格式
            if keep_times:
                # 直接使用用户选择的输出路径
                # mkvmerge --split parts: 不会写入基础文件名，只产生 name-001.ext 等分片
                split_final_output = output_path
                args.extend(['--split', f'parts:{keep_times}'])
        
        # 如果勾选了清除原附件
        if GlobalSetting.ATTACHMENT_REPLACE_EXISTING:
            args.append('--no-attachments')
        
        # 添加附件（必须在视频文件之前）
        attachment_list = GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if attachment_list:
            for attachment_path in attachment_list:
                if os.path.exists(attachment_path):
                    ext = os.path.splitext(attachment_path)[1].lower()
                    mime_type = self.get_attachment_mime_type(ext)
                    args.extend(['--attachment-name', 'cover' + ext])
                    args.extend(['--attachment-mime-type', mime_type])
                    args.extend(['--attach-file', attachment_path])
        
        # 获取轨道信息
        video_subs_info = GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO) else []
        video_audios_info = GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO) else []
        
        # 获取轨道选择设置
        selected_audio = self.get_selected_audio_tracks()
        selected_subtitle = self.get_selected_subtitle_tracks()
        sub_languages = self.track_selections.get('subtitle_languages', {}).get(video_index, {})
        audio_languages = self.track_selections.get('audio_languages', {}).get(video_index, {})
        sub_track_names = self.track_selections.get('subtitle_track_names', {}).get(video_index, {})
        audio_track_names = self.track_selections.get('audio_track_names', {}).get(video_index, {})
        video_track_names = self.track_selections.get('video_track_names', {}).get(video_index, {})
        
        # 外部轨道选择（None=从未保存过，默认全部保留）
        external_sub_selected = self.track_selections.get('external_subtitle', {}).get(video_index)
        external_audio_selected = self.track_selections.get('external_audio', {}).get(video_index)
        
        # 获取默认轨道设置
        default_audio_info = self.track_selections.get('default_audio', {}).get(video_index, {})
        default_audio_idx = default_audio_info.get('idx', -1) if isinstance(default_audio_info, dict) else -1
        default_audio_external = default_audio_info.get('external', False) if isinstance(default_audio_info, dict) else False
        
        default_sub_info = self.track_selections.get('default_subtitle', {}).get(video_index, {})
        default_sub_idx = default_sub_info.get('idx', -1) if isinstance(default_sub_info, dict) else -1
        default_sub_external = default_sub_info.get('external', False) if isinstance(default_sub_info, dict) else False
        
        lang_name_map = {
            'chi': '国语',
            'eng': '英语',
            'jpn': '日语',
            'kor': '韩语',
            'und': ''
        }
        
        # 构建视频文件的轨道选择参数（必须在视频文件之前）
        if video_index in selected_audio:
            if selected_audio[video_index]:
                tracks_str = ','.join(str(t) for t in selected_audio[video_index])
                args.extend(['--audio-tracks', tracks_str])
            else:
                args.append('--no-audio')
        elif video_audios_info:
            tracks_str = ','.join(str(track.get('id', i)) for i, track in enumerate(video_audios_info))
            args.extend(['--audio-tracks', tracks_str])
        
        if video_index in selected_subtitle:
            if selected_subtitle[video_index]:
                tracks_str = ','.join(str(t) for t in selected_subtitle[video_index])
                args.extend(['--subtitle-tracks', tracks_str])
            else:
                args.append('--no-subtitles')
        elif video_subs_info:
            tracks_str = ','.join(str(track.get('id', i)) for i, track in enumerate(video_subs_info))
            args.extend(['--subtitle-tracks', tracks_str])
        
        # 构建视频文件的内置轨道语言和默认设置参数（必须在视频文件之前）
        # 处理视频文件的内置字幕轨道参数
        if video_index not in selected_subtitle or selected_subtitle[video_index]:
            for i, track in enumerate(video_subs_info):
                track_id = track.get('id', i)
                # 从二级字典中获取语言设置（video_index -> track_idx -> lang_code）
                new_lang = sub_languages.get(i)
                if new_lang:
                    args.extend(['--language', f'{track_id}:{new_lang}'])
                    # 使用用户填写的轨道名称（始终设置，空字符串表示清空）
                    track_name = sub_track_names.get(i, lang_name_map.get(new_lang, ''))
                    args.extend(['--track-name', f'{track_id}:{track_name}'])
                if not default_sub_external and i == default_sub_idx:
                    args.extend(['--default-track', f'{track_id}:yes'])
        
        # 处理视频文件的内置音轨轨道参数
        if video_index not in selected_audio or selected_audio[video_index]:
            for i, track in enumerate(video_audios_info):
                track_id = track.get('id', i)
                # 从二级字典中获取语言设置（video_index -> track_idx -> lang_code）
                new_lang = audio_languages.get(i)
                if new_lang:
                    args.extend(['--language', f'{track_id}:{new_lang}'])
                    # 使用用户填写的轨道名称（始终设置，空字符串表示清空）
                    track_name = audio_track_names.get(i, lang_name_map.get(new_lang, ''))
                    args.extend(['--track-name', f'{track_id}:{track_name}'])
                if not default_audio_external and i == default_audio_idx:
                    args.extend(['--default-track', f'{track_id}:yes'])
        
        # 处理视频轨道名称（用户设置的值，空字符串=清空，未设置=不改变）
        video_tracks_info_for_name = GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_VIDEOS_INFO) else []
        if video_track_names:
            for track_idx, track_name in video_track_names.items():
                if isinstance(track_idx, int) and track_idx < len(video_tracks_info_for_name):
                    track_id = video_tracks_info_for_name[track_idx].get('id', track_idx)
                else:
                    track_id = track_idx
                args.extend(['--track-name', f'{track_id}:{track_name}'])
        else:
            # 没有保存设置时，给视频轨清空名称（仅当有视频轨信息时才操作）
            if video_tracks_info_for_name:
                track_id = video_tracks_info_for_name[0].get('id', 0)
                args.extend(['--track-name', f'{track_id}:'])
        
        # 添加视频文件路径
        args.append(video_path)
        
        # 处理外部字幕文件
        sub_list = GlobalSetting.SUBTITLE_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if sub_list:
            for i, sub_path in enumerate(sub_list):
                ext_key = f'ext_{i}'
                # 如果用户明确取消勾选了外部字幕，则跳过
                if external_sub_selected is not None and ext_key not in external_sub_selected:
                    continue
                ext_lang = sub_languages.get(ext_key, 'chi')
                is_default = default_sub_external and ext_key == default_sub_idx
                
                # 为外部字幕构建参数
                sub_args = []
                if ext_lang:
                    sub_args.extend(['--language', f'0:{ext_lang}'])
                    # 只有当用户明确填写了轨道名称时才设置（空字符串不添加 --track-name 参数）
                    ext_track_name = sub_track_names.get(ext_key, '')
                    if ext_track_name:
                        sub_args.extend(['--track-name', f'0:{ext_track_name}'])
                if is_default:
                    sub_args.extend(['--default-track', '0:yes'])
                
                # 添加外部字幕文件和参数
                args.extend(sub_args)
                args.append(sub_path)
        
        # 处理外部音轨文件
        audio_list = GlobalSetting.AUDIO_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if audio_list:
            for i, audio_path in enumerate(audio_list):
                ext_key = f'ext_{i}'
                # 如果用户明确取消勾选了外部音轨，则跳过
                if external_audio_selected is not None and ext_key not in external_audio_selected:
                    continue
                ext_lang = audio_languages.get(ext_key, 'chi')
                is_default = default_audio_external and ext_key == default_audio_idx
                
                # 为外部音轨构建参数
                audio_args = []
                if ext_lang:
                    audio_args.extend(['--language', f'0:{ext_lang}'])
                    # 只有当用户明确填写了轨道名称时才设置（空字符串不添加 --track-name 参数，与字幕行为一致）
                    ext_track_name = audio_track_names.get(ext_key, lang_name_map.get(ext_lang, ''))
                    if ext_track_name:
                        audio_args.extend(['--track-name', f'0:{ext_track_name}'])
                if is_default:
                    audio_args.extend(['--default-track', '0:yes'])
                
                # 添加外部音轨文件和参数
                args.extend(audio_args)
                args.append(audio_path)
        
        return args, split_final_output
    def get_attachment_mime_type(self, ext):
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.ttf': 'font/ttf',
            '.otf': 'font/otf',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
        }
        return mime_types.get(ext, 'application/octet-stream')
    
    def calculate_crc32(self, file_path):
        crc = 0
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    crc = zlib.crc32(chunk, crc)
            return format(crc & 0xFFFFFFFF, '08X')
        except (OSError, zlib.error) as e:
            logging.warning(f"CRC32计算失败 ({file_path}): {e}")
            return None
    
    def remove_crc_from_filename(self, filename):
        crc_pattern = r'\[[A-Fa-f0-9]{8}\]'
        return re.sub(crc_pattern, '', filename).strip()
    
    def add_crc_to_filename(self, file_path, crc):
        dir_path = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        new_filename = f"{name} [{crc}]{ext}"
        new_path = os.path.join(dir_path, new_filename)
        try:
            os.rename(file_path, new_path)
            return new_path
        except OSError as e:
            logging.warning(f"文件重命名失败 ({file_path}): {e}")
            return file_path
    
    def save_log_file(self, video_name, stdout_text, stderr_text, success):
        if not self.keep_log_check.isChecked():
            return
        
        output_dir = self.output_path_edit.text()
        if not output_dir:
            return
        
        log_dir = os.path.join(output_dir, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"创建日志目录失败 ({log_dir}): {e}")
            return
        
        # 提取文件名（去掉路径和扩展名）
        video_basename = os.path.splitext(os.path.basename(video_name))[0]
        
        log_filename = f"{video_basename}.log"
        log_path = os.path.join(log_dir, log_filename)
        
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== 九歌批量MKV混流日志 ===\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"视频: {video_name}\n")
                f.write(f"状态: {'成功' if success else '失败'}\n")
                f.write(f"\n{'='*50}\n")
                f.write(f"\n=== 标准输出 ===\n")
                f.write(stdout_text if stdout_text else "(无)")
                f.write(f"\n\n=== 标准错误 ===\n")
                f.write(stderr_text if stderr_text else "(无)")
        except OSError as e:
            logging.warning(f"写入日志文件失败 ({log_path}): {e}")
    
    def update_theme_mode_state(self):
        pass
    
    def set_preset_options(self):
        self.update_track_menus()


class VideoCutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("视频切割设置")
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        self.cut_times = ""
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        
        # 说明文本
        info_label = QLabel("使用说明：")
        info_text = QLabel("超重要格式规则（必须遵守）：\n"
                          "1. 时间格式必须是：HH:MM:SS\n"
                          "2. 不能写 05:00，必须写 00:05:00\n"
                          "3. 开始和结束用英文减号 -\n"
                          "4. 多段用英文逗号 ,\n"
                          "5. 不能有空格\n"
                          "6. 不能有中文符号\n\n"
                          "例 1（单段）：00:05:00-00:15:00\n"
                          "例 2（多段）：00:05:00-00:15:00,00:25:00-00:35:00\n\n"
                          "批量视频切割说明：\n"
                          "- 设置的切割时间会应用到所有添加到队列的视频文件\n"
                          "- 所有视频都会按照相同的时间点进行切割\n"
                          "- 建议确保所有视频的长度都大于设置的切割时间范围\n\n"
                          "结果：只输出你写的时间段内容，其余全部切掉")
        info_text.setWordWrap(True)
        
        # 时间输入
        input_label = QLabel("切割时间：")
        self.time_edit = QTextEdit()
        self.time_edit.setPlaceholderText("请输入切割时间，例如：00:05:00-00:15:00")
        
        # 按钮布局
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        # 添加到主布局
        main_layout.addWidget(info_label)
        main_layout.addWidget(info_text)
        main_layout.addWidget(input_label)
        main_layout.addWidget(self.time_edit)
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
        # 连接信号
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
    
    def accept(self):
        self.cut_times = self.time_edit.toPlainText().strip()
        if self.cut_times:
            # 简单验证时间格式
            if self.validate_time_format(self.cut_times):
                super().accept()
            else:
                QMessageBox.warning(self, "警告", "时间格式不正确，请按照示例格式输入")
        else:
            super().accept()
    
    def validate_time_format(self, time_str):
        import re
        # 严格的时间格式正则：HH:MM:SS-HH:MM:SS，确保没有空格和中文符号
        time_pattern = r'^\d{2}:\d{2}:\d{2}-\d{2}:\d{2}:\d{2}(,\d{2}:\d{2}:\d{2}-\d{2}:\d{2}:\d{2})*$'
        # 检查是否包含空格或中文符号
        if ' ' in time_str or re.search('[\u4e00-\u9fa5]', time_str):
            return False
        return bool(re.match(time_pattern, time_str))
    
    def get_cut_times(self):
        return self.cut_times



class VideoPreviewDialog(QDialog):
    def __init__(self, video_path, cut_times="", parent=None):
        super().__init__(parent)
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
        
        # 为所有可能抢占焦点的控件安装事件过滤器，确保键盘快捷键始终有效
        self.installEventFilter(self)
        self.video_widget.installEventFilter(self)
        self.progress_bar.installEventFilter(self)
        self.segments_list.installEventFilter(self)
        self.in_point_edit.installEventFilter(self)
        self.out_point_edit.installEventFilter(self)
        
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
                    default_duration = properties.get("default_duration")
                    if default_duration:
                        self.frame_duration_ms = default_duration / 1000000000.0
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
    
    def get_keep_times(self):
        """【已废弃】计算反向保留段。
        
        当前主流程已改为用户选中的时间段直接作为保留段（不再取补集）。
        此方法保留供参考：传入 cut_segments（要删除的片段），返回反向保留段。
        
        mkvmerge --split parts: 语义是保留指定片段，所以传入 cut_segments 时需取反。
        例如：cut=[00:01:00-00:02:00, 00:04:00-00:05:00], duration=10:00
        → keep=[00:00:00-00:01:00, 00:02:00-00:04:00, 00:05:00-00:10:00]
        """
        if not self.cut_segments:
            return ""
        
        # 获取视频总时长（毫秒）
        try:
            duration_ms = self.player.duration()
            if duration_ms <= 0:
                return self.get_cut_times()  # 无法获取时长，降级使用切割段
        except Exception:
            return self.get_cut_times()  # 播放器不可用，降级使用切割段
        
        # 解析切割段为毫秒值
        cut_ranges = []
        for start_str, end_str in self.cut_segments:
            start_ms = self.time_to_ms(start_str)
            end_ms = self.time_to_ms(end_str)
            if end_ms > start_ms:
                cut_ranges.append((start_ms, end_ms))
        
        if not cut_ranges:
            return ""
        
        # 按开始时间排序
        cut_ranges.sort(key=lambda x: x[0])
        
        # 合并重叠的切割段
        merged = []
        for start, end in cut_ranges:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        
        # 计算反向保留段
        keep_segments = []
        cursor = 0
        
        for cut_start, cut_end in merged:
            if cursor < cut_start:
                keep_segments.append((cursor, cut_start))
            cursor = max(cursor, cut_end)
        
        # 最后一段：最后一个切割结束到视频结尾
        if cursor < duration_ms:
            keep_segments.append((cursor, duration_ms))
        
        if not keep_segments:
            return ""  # 整个视频都被切掉了
        
        # 格式化保留段
        parts = []
        for start_ms, end_ms in keep_segments:
            parts.append(f"{self.format_time(start_ms)}-{self.format_time(end_ms)}")
        
        return ",".join(parts)
    
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
    
    def keyPressEvent(self, event):
        # 支持空格键播放/暂停
        if event.key() == Qt.Key_Space:
            # 直接切换播放状态，不依赖playbackState()
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.pause_video()
            else:
                self.play_video()
            # 阻止事件传递，避免其他控件响应
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def focusInEvent(self, event):
        # 确保对话框获得焦点时，视频控件也获得焦点
        self.video_widget.setFocus()
        super().focusInEvent(event)
    
    def showEvent(self, event):
        # 确保对话框获得焦点，并且进度条获得焦点
        super().showEvent(event)
        # 延迟一点时间，确保界面完全加载
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.progress_bar.setFocus)
    
    def eventFilter(self, obj, event):
        """全局键盘快捷键：空格=播放/暂停, 左右=1帧, 上下=10帧。
        
        QLineEdit 特殊处理：左右箭头留给文本光标移动，不拦截。
        其余所有可聚焦控件均拦截快捷键，确保快捷键始终可用。
        """
        if event.type() == QEvent.KeyPress:
            key = event.key()
            
            # QLineEdit 中保留左右箭头用于光标移动
            if isinstance(obj, QLineEdit) and key in (Qt.Key_Left, Qt.Key_Right):
                return super().eventFilter(obj, event)
            
            if key == Qt.Key_Space:
                # 空格键：控制播放/暂停（全局生效）
                if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self.pause_video()
                else:
                    self.play_video()
                self.progress_bar.setFocus()
                event.accept()
                return True
            elif key == Qt.Key_Left:
                # 左箭头：向后移动1帧
                new_pos = max(0, int(self.player.position() - self.frame_duration_ms))
                self._seek_to(new_pos)
                self.progress_bar.setFocus()
                event.accept()
                return True
            elif key == Qt.Key_Right:
                # 右箭头：向前移动1帧
                new_pos = min(self.player.duration(), int(self.player.position() + self.frame_duration_ms))
                self._seek_to(new_pos)
                self.progress_bar.setFocus()
                event.accept()
                return True
            elif key == Qt.Key_Up:
                # 上箭头：向前移动10帧
                new_pos = min(self.player.duration(), int(self.player.position() + self.frame_duration_ms * 10))
                self._seek_to(new_pos)
                self.progress_bar.setFocus()
                event.accept()
                return True
            elif key == Qt.Key_Down:
                # 下箭头：向后移动10帧
                new_pos = max(0, int(self.player.position() - self.frame_duration_ms * 10))
                self._seek_to(new_pos)
                self.progress_bar.setFocus()
                event.accept()
                return True
        return super().eventFilter(obj, event)
    
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
        help_text.setText('视频切割使用说明\n\n切割方法\n方法一：可视化标记（推荐）\n1. 标记开始点：\n   - 播放视频到想要保留的开始位置\n   - 点击"标记开始"按钮\n   - 或按空格键暂停视频后点击"标记开始"按钮\n\n2. 标记结束点：\n   - 播放视频到想要保留的结束位置\n   - 点击"标记结束"按钮\n   - 或按空格键暂停视频后点击"标记结束"按钮\n\n3. 添加切割段：\n   - 点击"添加当前段"按钮，将设置的切割段添加到列表中\n   - 重复上述步骤，添加多个切割段\n\n方法二：手动输入时间\n1. 在"开始"和"结束"输入框中直接输入时间，格式为 HH:MM:SS.fff\n2. 点击"添加当前段"按钮，将设置的切割段添加到列表中\n\n切割段管理\n- 删除切割段：在切割段列表中选择要删除的段，点击"删除选中段"按钮\n- 清空所有段：点击"清空所有段"按钮，删除所有已设置的切割段\n\n键盘快捷键\n- 空格键：播放/暂停视频\n- 左箭头：向后移动1帧\n- 右箭头：向前移动1帧\n- 上箭头：向前移动10帧\n- 下箭头：向后移动10帧\n\n时间格式说明\n- 时间格式必须为 HH:MM:SS.fff（小时:分钟:秒.毫秒）\n- 例如：00:02:30.500 表示 2分30秒500毫秒\n- 不能简化为 02:30 或其他格式\n\n高级技巧\n切割掉片头、广告和片尾\n1. 保留第一段：设置从片头结束后到广告开始前的时间段\n2. 保留第二段：设置从广告结束后到片尾开始前的时间段\n3. 点击确定：程序会自动只保留这两个时间段，其他部分会被切割掉\n\n精确调整切割点\n- 使用方向键的左右箭头逐帧调整，上下箭头每次移动10帧，确保精确找到切割点\n- 播放视频时，可以按空格键暂停，然后使用方向键微调位置\n\n注意事项\n- 设置的切割时间会应用到所有添加到队列的视频文件\n- 确保切割段的开始时间小于结束时间\n- 多个切割段之间可以有间隔，间隔部分会被切割掉\n- 切割后的视频会按照原始视频的格式保存，保持画质不变')
        
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
        
        格式合法时直接调用 save_segment() 复用保存按钮逻辑（含去重检查），
        格式不合法则静默跳过，不提示、不阻止关闭。
        """
        start_time = self.in_point_edit.text().strip()
        end_time = self.out_point_edit.text().strip()
        
        if start_time and end_time:
            # 先静默校验格式，格式合法才调用 save_segment（避免触发 save_segment 的弹窗提示）
            if (self.validate_time_format(start_time) and 
                self.validate_time_format(end_time)):
                try:
                    start_ms = self.time_to_ms(start_time)
                    end_ms = self.time_to_ms(end_time)
                    if start_ms < end_ms:
                        self.save_segment()  # 复用保存按钮逻辑（含去重 + 警告提示）
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
    
