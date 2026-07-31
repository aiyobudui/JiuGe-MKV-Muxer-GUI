# -*- coding: utf-8 -*-
import os
import subprocess
import threading
import logging
import time
from datetime import datetime
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGroupBox, QCheckBox,
    QProgressBar, QMessageBox,
)

from packages.Startup.Options import Options
from packages.Startup import GlobalFiles
from packages.Tabs.GlobalSetting import GlobalSetting, get_readable_filesize
from packages.Tabs.MuxSetting.TrackSelectionDialog import TrackSelectionDialog
from packages.Tabs.MuxSetting.mux_helpers import (
    parse_mkvmerge_progress,
    get_output_path_from_args,
    get_attachment_mime_type,
    calculate_crc32,
    remove_crc_from_filename,
    add_crc_to_filename,
    clamp_cut_times_to_duration,
)

from packages.Tabs.MuxSetting.VideoPreviewDialog import VideoPreviewDialog


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
        self.video_selection = None  # 由 TabsManager 接线，用于入队前重新计算勾选状态
    
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

        # 入队前重新计算勾选状态，确保队列与视频选项卡中实际勾选的一致。
        # 避免 VIDEO_SELECTED_INDICES 因时序/异常停留在旧值，导致只进部分文件。
        if self.video_selection is not None:
            try:
                self.video_selection.update_selected_indices()
            except Exception as e:  # 勾选刷新失败不应阻断入队
                logging.warning("重新计算视频勾选状态失败: %s", e)

        try:
            _msg = (
                f"[添加到队列] 视频总数={len(GlobalSetting.VIDEO_FILES_LIST)}, "
                f"勾选数={len(GlobalSetting.VIDEO_SELECTED_INDICES)}, "
                f"勾选索引={GlobalSetting.VIDEO_SELECTED_INDICES}"
            )
            logging.warning(_msg)
            with open(GlobalFiles.AppLogFilePath, "a", encoding="utf-8") as _lf:
                _lf.write(_msg + "\n")
        except Exception:
            pass

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
        
        # 等待视频轨道信息解析完成，避免轨道选择/默认轨/语言被静默丢弃
        if not GlobalSetting.VIDEO_TRACK_INFO_READY:
            from PySide6.QtWidgets import QApplication
            waited = 0
            while not GlobalSetting.VIDEO_TRACK_INFO_READY and waited < 8000:
                QApplication.processEvents()
                time.sleep(0.1)
                waited += 100
            if not GlobalSetting.VIDEO_TRACK_INFO_READY:
                QMessageBox.warning(self, "警告", "视频轨道信息仍在解析中，请稍候再点击开始混流")
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
        output_size = "-"  # 兜底：确保任何异常/失败路径下都有定义，避免返回时 NameError

        # 从 args 安全提取输出路径（避免硬编码 args[2] 索引）
        output_path = get_output_path_from_args(args)
        
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
            # 注意：必须并发排空 stderr，否则当 mkvmerge 输出大量 warning 时，
            # stderr 管道写满会阻塞子进程，导致 stdout 读取死锁、整个批次卡死。
            last_progress = 0

            def _drain_stderr():
                nonlocal stderr_text
                if process.stderr:
                    stderr_text = process.stderr.read()

            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            if process.stdout:
                for line in process.stdout:
                    stdout_text += line
                    # 解析 mkvmerge 的进度信息（格式通常是 "Progress: X%"）
                    progress = parse_mkvmerge_progress(line)
                    if progress is not None and progress != last_progress:
                        last_progress = progress
                        self.update_task_progress_signal.emit(task_index, progress)

            stderr_thread.join()
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
                        # mkvmerge 拒绝覆盖已存在的输出文件，先清理上一次残留的最终文件
                        if os.path.exists(split_final_output):
                            try:
                                os.remove(split_final_output)
                            except OSError as e:
                                logging.warning(f"删除旧最终输出失败: {split_final_output}, {e}")

                        if len(split_files) == 1:
                            # 使用 '+' 前缀后 mkvmerge 把多个保留段合并进单个分片，
                            # 直接重命名为最终文件即可，无需再次 concat（更可靠）。
                            try:
                                os.replace(split_files[0], split_final_output)
                                output_path = split_final_output
                            except OSError as e:
                                logging.error(f"切割分片重命名失败: {e}")
                                success = False
                        else:
                            # 兜底：多分片时用 mkvmerge 拼接为最终单文件
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
                            else:
                                logging.error(f"切割文件拼接失败: {concat_stderr}")
                                success = False

                        # 对最终文件做 CRC 校验和大小计算（仅当拼接/重命名成功）
                        if success and os.path.exists(output_path):
                            if self.add_crc_check.isChecked():
                                crc = calculate_crc32(output_path)
                                if crc:
                                    input_dir = os.path.dirname(video_path)
                                    final_dir = os.path.dirname(output_path)
                                    if os.path.abspath(input_dir) == os.path.abspath(final_dir):
                                        new_path = add_crc_to_filename(output_path, crc)
                                        if new_path != output_path:
                                            output_path = new_path
                            output_size = get_readable_filesize(os.path.getsize(output_path))
                        elif success:
                            output_size = "-"
                    elif split_files:
                        # 没有 split_final_output 但仍按多文件处理（兜底）
                        total_size = sum(os.path.getsize(f) for f in split_files)
                        output_size = get_readable_filesize(total_size)
                    elif os.path.exists(output_path):
                        # 单段切割：mkvmerge 直接写入基础文件名，未产生 name-001.ext 分片
                        if self.add_crc_check.isChecked():
                            crc = calculate_crc32(output_path)
                            if crc:
                                input_dir = os.path.dirname(video_path)
                                final_dir = os.path.dirname(output_path)
                                if os.path.abspath(input_dir) == os.path.abspath(final_dir):
                                    new_path = add_crc_to_filename(output_path, crc)
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
                            crc = calculate_crc32(output_path)
                            if crc:
                                # 只有当输出目录与输入目录相同时才添加CRC到文件名（避免覆盖原文件）
                                input_dir = os.path.dirname(video_path)
                                output_dir = os.path.dirname(output_path)
                                if os.path.abspath(input_dir) == os.path.abspath(output_dir):
                                    new_path = add_crc_to_filename(output_path, crc)
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
    
    def get_output_path(self, video_path):
        output_dir = self.output_path_edit.text()
        if output_dir:
            video_name = os.path.splitext(os.path.basename(video_path))[0]
            if self.add_crc_check.isChecked():
                video_name = remove_crc_from_filename(video_name)
            output_format = self.output_format_combo.currentText().lower()
            
            # 检查输出目录是否与输入目录相同
            input_dir = os.path.dirname(video_path)
            if os.path.abspath(output_dir) == os.path.abspath(input_dir):
                # 输出目录与输入目录相同，自动递增后缀避免覆盖已存在文件
                base_name = video_name
                candidate = os.path.join(output_dir, f"{base_name}_1.{output_format}")
                suffix = 1
                while os.path.exists(candidate):
                    suffix += 1
                    candidate = os.path.join(output_dir, f"{base_name}_{suffix}.{output_format}")
                return candidate
            
            return os.path.join(output_dir, video_name + "." + output_format)
        else:
            return video_path
    
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
                # 按本视频实际时长校验/截断，避免短视频因切割点超出时长而报错失败
                keep_times = clamp_cut_times_to_duration(video_path, keep_times)
            if keep_times:
                # 组装 mkvmerge --split parts: 参数：
                # 第一段不加前缀；后续段用 '+' 前缀，让 mkvmerge 在单个输出分片内
                # 直接合并（拼接）所有保留段，时间码连续无间隙。这样无需后续额外的
                # concat 步骤，避免多文件拼接可能导致的失败/异常。
                segs = [s.strip() for s in keep_times.split(',') if s.strip()]
                if segs:
                    parts_spec = segs[0]
                    for s in segs[1:]:
                        parts_spec += ',+' + s
                    split_final_output = output_path
                    args.extend(['--split', f'parts:{parts_spec}'])
        
        # 如果勾选了清除原附件
        if GlobalSetting.ATTACHMENT_REPLACE_EXISTING:
            args.append('--no-attachments')
        
        # 添加附件（必须在视频文件之前）
        attachment_list = GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if attachment_list:
            for attachment_path in attachment_list:
                if os.path.exists(attachment_path):
                    ext = os.path.splitext(attachment_path)[1].lower()
                    mime_type = get_attachment_mime_type(ext)
                    args.extend(['--attachment-name', 'cover' + ext])
                    args.extend(['--attachment-mime-type', mime_type])
                    args.extend(['--attach-file', attachment_path])
        
        # 获取轨道信息
        video_subs_info = GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO) else []
        video_audios_info = GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO) else []
        # 解析未完成/失败的分片可能为 None，统一兜底为空列表，避免 enumerate(None) 崩溃
        if video_subs_info is None:
            video_subs_info = []
        if video_audios_info is None:
            video_audios_info = []
        
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
        if video_tracks_info_for_name is None:
            video_tracks_info_for_name = []
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


