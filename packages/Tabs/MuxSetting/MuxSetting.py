# -*- coding: utf-8 -*-
import os
import re
import zlib
import subprocess
import threading
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
    update_progress_signal = Signal(int, str)
    muxing_finished_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.track_selections = {
            'audio': {}, 
            'subtitle': {}, 
            'default_audio': {}, 
            'default_subtitle': {},
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {}
        }
        self.video_cut_selections = {}  # 存储每个视频的切割时间设置
        self.setup_ui()
        self.connect_signals()
        self.total_tasks = 0
        self.stop_requested = False
        self.completed_count = 0
        self.count_lock = threading.Lock()
    
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
                cut_times = self.video_cut_selections[first_video_index]
            
            dialog = VideoPreviewDialog(video_path, cut_times, self)
            if dialog.exec():
                cut_times = dialog.get_cut_times()
                if cut_times:
                    # 为所有视频设置相同的切割时间
                    for i in range(len(GlobalSetting.VIDEO_FILES_LIST)):
                        self.video_cut_selections[i] = cut_times
                else:
                    # 没有设置切割时间，清除设置
                    self.video_cut_selections.clear()
            # 不再在取消时清除切割设置，保持之前的设置
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开视频预览对话框失败: {str(e)}")
    
    def on_update_task(self, row, status, progress, output_size):
        if row < self.task_table.rowCount():
            self.task_table.setItem(row, 1, QTableWidgetItem(status))
            self.task_table.setItem(row, 3, QTableWidgetItem(progress))
            self.task_table.setItem(row, 4, QTableWidgetItem(output_size))
    
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
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.output_path_edit.setText(folder)
    
    def clear_all_tasks(self):
        self.task_table.setRowCount(0)
        self.track_selections = {
            'audio': {}, 
            'subtitle': {}, 
            'default_audio': {}, 
            'default_subtitle': {},
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {}
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
            'external_audio': {},
            'external_subtitle': {},
            'audio_languages': {},
            'subtitle_languages': {}
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
        
        for video_idx in GlobalSetting.VIDEO_SELECTED_INDICES:
            if video_idx < len(GlobalSetting.VIDEO_FILES_LIST):
                video_name = GlobalSetting.VIDEO_FILES_LIST[video_idx]
                video_size = get_readable_filesize(GlobalSetting.VIDEO_FILES_SIZE_LIST[video_idx])
                
                row = self.task_table.rowCount()
                self.task_table.insertRow(row)
                self.task_table.setItem(row, 0, QTableWidgetItem(video_name))
                self.task_table.setItem(row, 1, QTableWidgetItem("等待中"))
                self.task_table.setItem(row, 2, QTableWidgetItem(video_size))
                self.task_table.setItem(row, 3, QTableWidgetItem("0%"))
                self.task_table.setItem(row, 4, QTableWidgetItem("-"))
                self.task_video_indices.append(video_idx)
        
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
        
        self.start_muxing_signal.emit()
        
        thread_count = 4
        self.muxing_thread = threading.Thread(target=self.run_muxing_tasks_parallel, args=(thread_count,), daemon=True)
        self.muxing_thread.start()
    
    def run_muxing_tasks_parallel(self, thread_count):
        total_tasks = self.task_table.rowCount()
        self.update_progress_signal.emit(0, f"正在处理 0/{total_tasks}")
        
        futures = {}
        completed = [0]
        lock = threading.Lock()
        has_error = [False]
        
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            for i in range(total_tasks):
                if self.stop_requested:
                    break
                
                if self.abort_on_error_check.isChecked() and has_error[0]:
                    break
                
                # 使用 task_video_indices 中的原始视频索引
                original_video_index = self.task_video_indices[i]
                video_path = GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST[original_video_index]
                video_name = GlobalSetting.VIDEO_FILES_LIST[original_video_index]
                output_path = self.get_output_path(video_path)
                args = self.build_mkvmerge_args(original_video_index, video_path, output_path)
                
                future = executor.submit(self.process_single_task, i, args, video_name)
                futures[future] = i
            
            for future in as_completed(futures):
                task_index = futures[future]
                try:
                    success, output_size, return_code = future.result()
                    if success:
                        self.update_task_signal.emit(task_index, "成功", "100%", output_size)
                    else:
                        self.update_task_signal.emit(task_index, "失败", "0%", "-")
                        if self.abort_on_error_check.isChecked():
                            has_error[0] = True
                except Exception:
                    self.update_task_signal.emit(task_index, "失败", "0%", "-")
                    if self.abort_on_error_check.isChecked():
                        has_error[0] = True
                
                with lock:
                    completed[0] += 1
                progress = int((completed[0] / total_tasks) * 100)
                self.update_progress_signal.emit(progress, f"正在处理 {completed[0]}/{total_tasks}")
        
        if not self.stop_requested:
            self.muxing_finished_signal.emit()
    
    def stop_muxing(self):
        self.stop_requested = True
        GlobalSetting.MUXING_ON = False
        self.set_button_state(is_muxing=False)
    
    def process_single_task(self, task_index, args, video_name):
        self.update_task_signal.emit(task_index, "执行中", "50%", "-")
        
        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            result = subprocess.run(
                [Options.Mkvmerge_Path] + args,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
            
            success = result.returncode in [0, 1]
            output_path = args[1]
            
            # 检查是否使用了切割功能
            is_split = any('--split' in arg for arg in args)
            
            if success:
                if is_split:
                    # 对于切割功能，检查是否生成了任何输出文件
                    output_dir = os.path.dirname(output_path)
                    output_name = os.path.basename(output_path)
                    name_without_ext, ext = os.path.splitext(output_name)
                    ext = ext[1:] if ext else ''
                    
                    # 查找匹配的切割输出文件，考虑不同的命名格式
                    import glob
                    # 尝试多种可能的切割文件命名格式
                    patterns = [
                        f"{name_without_ext}-*.{ext}",
                        f"{name_without_ext}*.{ext}",
                        f"*{os.path.splitext(output_name)[0]}*.{ext}"
                    ]
                    
                    split_files = []
                    for pattern in patterns:
                        split_files.extend(glob.glob(os.path.join(output_dir, pattern)))
                    
                    # 去重并按文件名排序
                    split_files = sorted(list(set(split_files)))
                    
                    if split_files:
                        # 计算所有切割文件的总大小
                        total_size = sum(os.path.getsize(f) for f in split_files)
                        output_size = get_readable_filesize(total_size)
                    else:
                        output_size = "-"
                else:
                    # 正常情况，检查原始输出路径
                    if os.path.exists(output_path):
                        if self.add_crc_check.isChecked():
                            crc = self.calculate_crc32(output_path)
                            if crc:
                                new_path = self.add_crc_to_filename(output_path, crc)
                                if new_path != output_path:
                                    output_path = new_path
                        
                        output_size = get_readable_filesize(os.path.getsize(output_path))
                    else:
                        output_size = "-"
            else:
                output_size = "-"
            
            self.save_log_file(video_name, result.stdout, result.stderr, success)
            
            return success, output_size, result.returncode
        except Exception:
            return False, "-", -1
    
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
    
    def build_mkvmerge_args(self, video_index, video_path, output_path):
        args = ['-o', output_path]
        
        # 添加视频切割参数
        if video_index in self.video_cut_selections:
            cut_times = self.video_cut_selections[video_index]
            if cut_times:
                # 直接使用 cut_times 作为切割参数，格式已经是正确的 start1-end1,start2-end2 格式
                args.extend(['--split', f'parts:{cut_times}'])
        
        selected_audio = self.get_selected_audio_tracks()
        if video_index in selected_audio:
            if selected_audio[video_index]:
                tracks_str = ','.join(str(t) for t in selected_audio[video_index])
                args.extend(['--audio-tracks', tracks_str])
            else:
                args.append('--no-audio')
        else:
            video_audios = GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO) else []
            if video_audios:
                tracks_str = ','.join(str(track.get('id', i)) for i, track in enumerate(video_audios))
                args.extend(['--audio-tracks', tracks_str])
        
        selected_subtitle = self.get_selected_subtitle_tracks()
        sub_list = GlobalSetting.SUBTITLE_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if video_index in selected_subtitle:
            if selected_subtitle[video_index]:
                tracks_str = ','.join(str(t) for t in selected_subtitle[video_index])
                args.extend(['--subtitle-tracks', tracks_str])
            else:
                args.append('--no-subtitles')
        else:
            video_subs = GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO[video_index] if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO) else []
            if video_subs:
                tracks_str = ','.join(str(track.get('id', i)) for i, track in enumerate(video_subs))
                args.extend(['--subtitle-tracks', tracks_str])
        
        video_subs_info = []
        if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO):
            video_subs_info = GlobalSetting.VIDEO_OLD_TRACKS_SUBTITLES_INFO[video_index] or []
        
        video_audios_info = []
        if video_index < len(GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO):
            video_audios_info = GlobalSetting.VIDEO_OLD_TRACKS_AUDIOS_INFO[video_index] or []
        
        default_sub_info = self.track_selections.get('default_subtitle', {}).get(video_index, {})
        default_sub_idx = default_sub_info.get('idx', -1) if isinstance(default_sub_info, dict) else -1
        default_sub_external = default_sub_info.get('external', False) if isinstance(default_sub_info, dict) else False
        
        sub_languages = self.track_selections.get('subtitle_languages', {}).get(video_index, {})
        
        for i, track in enumerate(video_subs_info):
            track_id = track.get('id', i)
            new_lang = sub_languages.get(i)
            if new_lang:
                args.extend(['--language', f'{track_id}:{new_lang}'])
            if not default_sub_external and i == default_sub_idx:
                args.extend(['--default-track', f'{track_id}:yes'])
            else:
                args.extend(['--default-track', f'{track_id}:no'])
        
        default_audio_info = self.track_selections.get('default_audio', {}).get(video_index, {})
        default_audio_idx = default_audio_info.get('idx', -1) if isinstance(default_audio_info, dict) else -1
        default_audio_external = default_audio_info.get('external', False) if isinstance(default_audio_info, dict) else False
        
        audio_languages = self.track_selections.get('audio_languages', {}).get(video_index, {})
        
        for i, track in enumerate(video_audios_info):
            track_id = track.get('id', i)
            new_lang = audio_languages.get(i)
            if new_lang:
                args.extend(['--language', f'{track_id}:{new_lang}'])
            if not default_audio_external and i == default_audio_idx:
                args.extend(['--default-track', f'{track_id}:yes'])
            else:
                args.extend(['--default-track', f'{track_id}:no'])
        
        attachment_list = GlobalSetting.ATTACHMENT_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if attachment_list:
            for attachment_path in attachment_list:
                if os.path.exists(attachment_path):
                    ext = os.path.splitext(attachment_path)[1].lower()
                    mime_type = self.get_attachment_mime_type(ext)
                    args.extend(['--attachment-name', 'cover' + ext])
                    args.extend(['--attachment-mime-type', mime_type])
                    args.extend(['--attach-file', attachment_path])
        
        args.append(video_path)
        
        if sub_list:
            for i, sub_path in enumerate(sub_list):
                ext_lang = sub_languages.get(f'ext_{i}', 'chi')
                args.extend(['--language', f'0:{ext_lang}'])
                if default_sub_external and f'ext_{i}' == default_sub_idx:
                    args.extend(['--default-track', '0:yes'])
                else:
                    args.extend(['--default-track', '0:no'])
                args.append(sub_path)
        
        audio_list = GlobalSetting.AUDIO_FILES_ABSOLUTE_PATH_LIST.get(video_index, [])
        if audio_list:
            for i, audio_path in enumerate(audio_list):
                ext_lang = audio_languages.get(f'ext_{i}', 'chi')
                args.extend(['--language', f'0:{ext_lang}'])
                if default_audio_external and f'ext_{i}' == default_audio_idx:
                    args.extend(['--default-track', '0:yes'])
                else:
                    args.extend(['--default-track', '0:no'])
                args.append(audio_path)
        
        return args
    
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
        except Exception:
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
        except Exception:
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
        except Exception:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{video_name}_{timestamp}.log"
        log_path = os.path.join(log_dir, log_filename)
        
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== 九歌 MKV 混流日志 ===\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"视频: {video_name}\n")
                f.write(f"状态: {'成功' if success else '失败'}\n")
                f.write(f"\n{'='*50}\n")
                f.write(f"\n=== 标准输出 ===\n")
                f.write(stdout_text if stdout_text else "(无)")
                f.write(f"\n\n=== 标准错误 ===\n")
                f.write(stderr_text if stderr_text else "(无)")
        except Exception:
            pass
    
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
        self.last_update_time = 0  # 上次更新时间，用于限制更新频率
        self.update_interval = 100  # 更新间隔，单位毫秒
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
        self.in_point_label = QLabel("开始：")
        self.out_point_label = QLabel("结束：")
        self.in_point_edit = QLineEdit()
        self.in_point_edit.setPlaceholderText("HH:MM:SS.fff")
        self.in_point_edit.setFixedWidth(180)
        self.out_point_edit = QLineEdit()
        self.out_point_edit.setPlaceholderText("HH:MM:SS.fff")
        self.out_point_edit.setFixedWidth(180)
        points_group_layout.addWidget(self.in_point_label)
        points_group_layout.addWidget(self.in_point_edit)
        points_group_layout.addSpacing(20)
        points_group_layout.addWidget(self.out_point_label)
        points_group_layout.addWidget(self.out_point_edit)
        points_group_layout.addStretch()
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
        self.add_segment_button = QPushButton("添加当前段")
        self.add_segment_button.setFixedWidth(100)
        self.remove_segment_button = QPushButton("删除选中段")
        self.remove_segment_button.setFixedWidth(100)
        self.clear_segments_button = QPushButton("清空所有段")
        self.clear_segments_button.setFixedWidth(100)
        segments_buttons_layout.addWidget(self.add_segment_button)
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
        self.prev_frame_button = QPushButton("前1帧")
        self.next_frame_button = QPushButton("后1帧")
        control_layout.addWidget(self.prev_frame_button)
        control_layout.addWidget(self.next_frame_button)
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
        self.mark_in_button.clicked.connect(self.mark_start_point)
        self.mark_out_button.clicked.connect(self.mark_end_point)
        self.add_segment_button.clicked.connect(self.add_segment)
        self.remove_segment_button.clicked.connect(self.remove_segment)
        self.clear_segments_button.clicked.connect(self.clear_segments)
        self.help_button.clicked.connect(self.show_help)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.progress_bar.sliderPressed.connect(self.on_progress_slider_pressed)
        self.progress_bar.sliderReleased.connect(self.on_progress_slider_released)
        self.progress_bar.sliderMoved.connect(self.on_progress_slider_moved)
        
        # 为所有按钮添加点击事件，使它们在点击后将焦点返回进度条
        def set_focus_to_progress_bar():
            self.progress_bar.setFocus()
        
        buttons = [
            self.play_button, self.pause_button, self.stop_button, self.mute_button,
            self.prev_frame_button, self.next_frame_button, self.mark_in_button,
            self.mark_out_button, self.add_segment_button, self.remove_segment_button,
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
        
        # 只为关键控件安装事件过滤器，确保空格键总是控制播放/暂停
        self.installEventFilter(self)
        self.video_widget.installEventFilter(self)
        self.progress_bar.installEventFilter(self)
    
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
            
            # 优化缓存设置，减少延迟
            # 注意：QMediaPlayer 没有直接的缓存设置 API，它使用系统默认设置
            # 我们可以通过其他方式优化响应速度
        except Exception as e:
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
    
    def play_video(self):
        self.player.play()
        # 更新按钮高亮状态
        self.play_button.setStyleSheet("background-color: #106ebe; color: white;")
        self.pause_button.setStyleSheet("")
        self.stop_button.setStyleSheet("")
    
    def pause_video(self):
        self.player.pause()
        # 更新按钮高亮状态
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
        # 逐帧后退（这里使用10ms作为一帧的近似值）
        current_pos = self.player.position()
        new_pos = max(0, current_pos - 10)
        # 保存当前播放状态
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        # 暂停视频以确保画面更新
        self.player.pause()
        # 设置新位置
        self.player.setPosition(new_pos)
        # 恢复之前的播放状态
        if was_playing:
            self.player.play()
    
    def next_frame(self):
        # 逐帧前进（这里使用10ms作为一帧的近似值）
        current_pos = self.player.position()
        new_pos = min(self.player.duration(), current_pos + 10)
        # 保存当前播放状态
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        # 暂停视频以确保画面更新
        self.player.pause()
        # 设置新位置
        self.player.setPosition(new_pos)
        # 恢复之前的播放状态
        if was_playing:
            self.player.play()
    
    def mark_start_point(self):
        current_pos = self.player.position()
        start_time = self.format_time(current_pos)
        self.current_segment_start = start_time
        self.in_point_edit.setText(start_time)
    
    def mark_end_point(self):
        current_pos = self.player.position()
        end_time = self.format_time(current_pos)
        self.out_point_edit.setText(end_time)
    
    def add_segment(self):
        start_time = self.in_point_edit.text().strip()
        end_time = self.out_point_edit.text().strip()
        
        if start_time and end_time:
            # 验证时间格式
            if self.validate_time_format(start_time) and self.validate_time_format(end_time):
                # 确保开始时间小于结束时间
                if self.time_to_ms(start_time) < self.time_to_ms(end_time):
                    self.cut_segments.append((start_time, end_time))
                    self.update_segments_list()
                    # 清空输入框，准备设置下一段
                    self.in_point_edit.clear()
                    self.out_point_edit.clear()
                    self.current_segment_start = None
                else:
                    QMessageBox.warning(self, "警告", "开始时间必须小于结束时间")
            else:
                QMessageBox.warning(self, "警告", "时间格式不正确，请使用 HH:MM:SS.fff 格式")
        else:
            QMessageBox.warning(self, "警告", "请先设置开始和结束时间")
    
    def remove_segment(self):
        selected_items = self.segments_list.selectedItems()
        if selected_items:
            for item in selected_items:
                index = self.segments_list.row(item)
                if 0 <= index < len(self.cut_segments):
                    self.cut_segments.pop(index)
            self.update_segments_list()
        else:
            QMessageBox.warning(self, "警告", "请先选择要删除的切割段")
    
    def clear_segments(self):
        self.cut_segments.clear()
        self.update_segments_list()
        self.in_point_edit.clear()
        self.out_point_edit.clear()
        self.current_segment_start = None
    
    def update_segments_list(self):
        self.segments_list.clear()
        for i, (start, end) in enumerate(self.cut_segments):
            item_text = f"段 {i+1}: {start} - {end}"
            self.segments_list.addItem(item_text)
    
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
        except:
            return 0
    
    def format_time(self, ms):
        # 将毫秒转换为 HH:MM:SS.fff 格式
        seconds = ms / 1000
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"
    
    def on_duration_changed(self, duration):
        # 更新进度条最大值
        self.duration = duration
    
    def on_position_changed(self, position):
        # 限制更新频率，避免过于频繁的UI更新导致卡顿
        if position - self.last_update_time >= self.update_interval or position < self.last_update_time:
            self.last_update_time = position
            self.time_label.setText(self.format_time(position))
            # 更新进度条位置，但在拖拽时不更新
            if self.duration > 0 and not self.is_dragging:
                progress = int((position / self.duration) * 1000)
                self.progress_bar.setValue(progress)
    
    def on_progress_slider_pressed(self):
        # 进度条开始拖拽
        self.is_dragging = True
    
    def on_progress_slider_released(self):
        # 进度条拖拽释放时，跳转到对应位置
        if self.duration > 0:
            progress = self.progress_bar.value() / 1000
            position = int(progress * self.duration)
            self.player.setPosition(position)
        self.is_dragging = False
    
    def on_progress_slider_moved(self, value):
        # 进度条拖拽过程中更新时间显示和视频画面
        if self.duration > 0:
            progress = value / 1000
            position = int(progress * self.duration)
            # 暂停视频以确保画面更新
            was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            self.player.pause()
            # 设置新位置
            self.player.setPosition(position)
            # 更新时间显示
            self.time_label.setText(self.format_time(position))
            # 恢复之前的播放状态
            if was_playing:
                self.player.play()
    
    def get_cut_times(self):
        # 从切割段列表中获取切割时间
        if self.cut_segments:
            segments_str = []
            for start, end in self.cut_segments:
                segments_str.append(f"{start}-{end}")
            return ",".join(segments_str)
        
        # 如果没有添加切割段，尝试从输入框获取
        in_point = self.in_point_edit.text().strip()
        out_point = self.out_point_edit.text().strip()
        
        if in_point and out_point:
            return f"{in_point}-{out_point}"
        return ""
    
    def load_cut_times(self, cut_times):
        # 解析并加载之前的切割设置
        if cut_times:
            # 分割多个切割段
            segments = cut_times.split(",")
            for segment in segments:
                # 分割开始和结束时间
                if "-" in segment:
                    start, end = segment.split("-")
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
        # 捕获所有控件的键盘事件
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                # 空格键：控制播放/暂停
                if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self.pause_video()
                else:
                    self.play_video()
                # 确保焦点回到进度条
                self.progress_bar.setFocus()
                event.accept()
                return True
            elif event.key() == Qt.Key_Left:
                # 左箭头：向后一秒
                current_pos = self.player.position()
                new_pos = max(0, current_pos - 1000)  # 1000ms = 1秒
                # 保存当前播放状态
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                # 暂停视频以确保画面更新
                self.player.pause()
                # 设置新位置
                self.player.setPosition(new_pos)
                # 立即更新时间显示
                self.time_label.setText(self.format_time(new_pos))
                # 立即更新进度条
                if self.duration > 0 and not self.is_dragging:
                    progress = int((new_pos / self.duration) * 1000)
                    self.progress_bar.setValue(progress)
                # 恢复之前的播放状态
                if was_playing:
                    self.player.play()
                # 确保焦点回到进度条
                self.progress_bar.setFocus()
                # 立即处理事件，提高响应速度
                event.accept()
                return True
            elif event.key() == Qt.Key_Right:
                # 右箭头：前进一秒
                current_pos = self.player.position()
                new_pos = min(self.player.duration(), current_pos + 1000)  # 1000ms = 1秒
                # 保存当前播放状态
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                # 暂停视频以确保画面更新
                self.player.pause()
                # 设置新位置
                self.player.setPosition(new_pos)
                # 立即更新时间显示
                self.time_label.setText(self.format_time(new_pos))
                # 立即更新进度条
                if self.duration > 0 and not self.is_dragging:
                    progress = int((new_pos / self.duration) * 1000)
                    self.progress_bar.setValue(progress)
                # 恢复之前的播放状态
                if was_playing:
                    self.player.play()
                # 确保焦点回到进度条
                self.progress_bar.setFocus()
                # 立即处理事件，提高响应速度
                event.accept()
                return True
            elif event.key() == Qt.Key_Up:
                # 上箭头：上1帧
                current_pos = self.player.position()
                new_pos = max(0, current_pos - 10)
                # 保存当前播放状态
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                # 暂停视频以确保画面更新
                self.player.pause()
                # 设置新位置
                self.player.setPosition(new_pos)
                # 立即更新时间显示
                self.time_label.setText(self.format_time(new_pos))
                # 立即更新进度条
                if self.duration > 0 and not self.is_dragging:
                    progress = int((new_pos / self.duration) * 1000)
                    self.progress_bar.setValue(progress)
                # 恢复之前的播放状态
                if was_playing:
                    self.player.play()
                # 确保焦点回到进度条
                self.progress_bar.setFocus()
                # 立即处理事件，提高响应速度
                event.accept()
                return True
            elif event.key() == Qt.Key_Down:
                # 下箭头：下1帧
                current_pos = self.player.position()
                new_pos = min(self.player.duration(), current_pos + 10)
                # 保存当前播放状态
                was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                # 暂停视频以确保画面更新
                self.player.pause()
                # 设置新位置
                self.player.setPosition(new_pos)
                # 立即更新时间显示
                self.time_label.setText(self.format_time(new_pos))
                # 立即更新进度条
                if self.duration > 0 and not self.is_dragging:
                    progress = int((new_pos / self.duration) * 1000)
                    self.progress_bar.setValue(progress)
                # 恢复之前的播放状态
                if was_playing:
                    self.player.play()
                # 确保焦点回到进度条
                self.progress_bar.setFocus()
                # 立即处理事件，提高响应速度
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
        help_text.setText('视频切割使用说明\n\n切割方法\n方法一：可视化标记（推荐）\n1. 标记开始点：\n   - 播放视频到想要保留的开始位置\n   - 点击"标记开始"按钮\n   - 或按空格键暂停视频后点击"标记开始"按钮\n\n2. 标记结束点：\n   - 播放视频到想要保留的结束位置\n   - 点击"标记结束"按钮\n   - 或按空格键暂停视频后点击"标记结束"按钮\n\n3. 添加切割段：\n   - 点击"添加当前段"按钮，将设置的切割段添加到列表中\n   - 重复上述步骤，添加多个切割段\n\n方法二：手动输入时间\n1. 在"开始"和"结束"输入框中直接输入时间，格式为 HH:MM:SS.fff\n2. 点击"添加当前段"按钮，将设置的切割段添加到列表中\n\n切割段管理\n- 删除切割段：在切割段列表中选择要删除的段，点击"删除选中段"按钮\n- 清空所有段：点击"清空所有段"按钮，删除所有已设置的切割段\n\n键盘快捷键\n- 空格键：播放/暂停视频\n- 左箭头：向后移动1秒\n- 右箭头：向前移动1秒\n- 上箭头：向前移动1帧\n- 下箭头：向后移动1帧\n\n时间格式说明\n- 时间格式必须为 HH:MM:SS.fff（小时:分钟:秒.毫秒）\n- 例如：00:02:30.500 表示 2分30秒500毫秒\n- 不能简化为 02:30 或其他格式\n\n高级技巧\n切割掉片头、广告和片尾\n1. 保留第一段：设置从片头结束后到广告开始前的时间段\n2. 保留第二段：设置从广告结束后到片尾开始前的时间段\n3. 点击确定：程序会自动只保留这两个时间段，其他部分会被切割掉\n\n精确调整切割点\n- 使用方向键的上/下箭头可以逐帧调整，确保精确找到切割点\n- 播放视频时，可以按空格键暂停，然后使用方向键微调位置\n\n注意事项\n- 设置的切割时间会应用到所有添加到队列的视频文件\n- 确保切割段的开始时间小于结束时间\n- 多个切割段之间可以有间隔，间隔部分会被切割掉\n- 切割后的视频会按照原始视频的格式保存，保持画质不变')
        
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
        # 点击确定时停止视频播放
        if hasattr(self, 'player'):
            self.player.stop()
        super().accept()
    
    def reject(self):
        # 点击取消时停止视频播放
        if hasattr(self, 'player'):
            self.player.stop()
        super().reject()

