# -*- coding: utf-8 -*-
import os
import winreg
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QFrame, QVBoxLayout, QMessageBox, QFileDialog, QDialog

from packages.Startup import GlobalIcons
from packages.Startup.Options import Options
from packages.Startup.PreDefined import VIDEO_EXTENSIONS
from packages.Tabs.TabsManager import TabsManager
from packages.Tabs.GlobalSetting import GlobalSetting
from packages.Widgets.MyMainWindow import MyMainWindow
from packages.Widgets.MkvtoolnixNotFoundDialog import MktoolnixNotFoundDialog


class MainWindow(MyMainWindow):
    def __init__(self, args=None, parent=None):
        super().__init__(args=args, parent=parent)
        self.resize(1160, 635)
        self.setWindowTitle("九歌批量MKV混流工具 v1.4.1")
        self.setWindowIcon(GlobalIcons.AppIcon.get())
        
        Options.load()
        
        if not Options.Mkvmerge_Path or not os.path.exists(Options.Mkvmerge_Path):
            mkvmerge_path = self.get_mkvtoolnix_path_from_registry()
            if mkvmerge_path:
                Options.Mkvmerge_Path = mkvmerge_path
                Options.save()
        
        self.tabs = TabsManager()
        self.tabs_frame = QFrame()
        self.tabs_layout = QVBoxLayout()
        self.setup_tabs_layout()
        self.setCentralWidget(self.tabs_frame)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        self.show_window()
        self.tabs.set_preset_options()
        self.connect_signals()
        self.apply_light_theme()
        
        QTimer.singleShot(100, self.check_mkvmuxing_path)
    
    def get_mkvtoolnix_path_from_registry(self):
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\MKVToolNix Settings\DefaultIcon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MKVToolNix"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MKVToolNix"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\MKVToolNix"),
        ]
        
        for hkey, subkey in registry_paths:
            try:
                key = winreg.OpenKey(hkey, subkey, 0, winreg.KEY_READ)
                value, _ = winreg.QueryValueEx(key, "")
                winreg.CloseKey(key)
                
                if value:
                    if "," in value:
                        value = value.split(",")[0]
                    
                    if value.endswith("mkvtoolnix-gui.exe"):
                        install_dir = os.path.dirname(value)
                        mkvmerge_path = os.path.join(install_dir, "mkvmerge.exe")
                        if os.path.exists(mkvmerge_path):
                            return mkvmerge_path
                    
                    if os.path.isdir(value):
                        mkvmerge_path = os.path.join(value, "mkvmerge.exe")
                        if os.path.exists(mkvmerge_path):
                            return mkvmerge_path
            except WindowsError:
                continue
        
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ)
            for i in range(winreg.QueryInfoKey(key)[0]):
                subkey_name = winreg.EnumKey(key, i)
                try:
                    subkey = winreg.OpenKey(key, subkey_name, 0, winreg.KEY_READ)
                    display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                    if "MKVToolNix" in display_name:
                        install_location, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                        winreg.CloseKey(subkey)
                        winreg.CloseKey(key)
                        
                        if install_location:
                            mkvmerge_path = os.path.join(install_location, "mkvmerge.exe")
                            if os.path.exists(mkvmerge_path):
                                return mkvmerge_path
                    winreg.CloseKey(subkey)
                except WindowsError:
                    continue
            winreg.CloseKey(key)
        except WindowsError:
            pass
        
        return None
    
    def check_mkvmuxing_path(self):
        if Options.Mkvmerge_Path and os.path.exists(Options.Mkvmerge_Path):
            return
        
        dialog = MktoolnixNotFoundDialog(self)
        result = dialog.exec()
        
        if result == QDialog.Accepted:
            self.select_mkvtoolnix_dir()
    
    def select_mkvtoolnix_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 MKVToolNix 安装目录",
            ""
        )
        
        if folder:
            mkvmerge_path = self.find_mkvmerge_in_dir(folder)
            if mkvmerge_path:
                Options.Mkvmerge_Path = mkvmerge_path
                Options.save()
                QMessageBox.information(self, "成功", f"已找到 mkvmerge.exe：\n{mkvmerge_path}")
                self.tabs.video_tab.refresh_track_info_now()
                return True
            else:
                QMessageBox.warning(self, "错误", f"在所选目录中未找到 mkvmerge.exe：\n{folder}")
        return False
    
    def find_mkvmerge_in_dir(self, folder):
        mkvmerge_path = os.path.join(folder, "mkvmerge.exe")
        if os.path.exists(mkvmerge_path):
            return mkvmerge_path
        return None
    
    def connect_signals(self):
        self.tabs.currentChanged.connect(self.update_minimum_size)
    
    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
    
    def setup_tabs_layout(self):
        self.tabs_frame.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setContentsMargins(9, 9, 9, 12)
        self.tabs_layout.addWidget(self.tabs)
        self.tabs_frame.setLayout(self.tabs_layout)
    
    def update_minimum_size(self):
        self.setMinimumSize(self.minimumSizeHint())
    
    def closeEvent(self, event):
        muxing_on = GlobalSetting.MUXING_ON
        if muxing_on:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("确认退出")
            msg_box.setText("正在混流中，确定要退出吗？")
            msg_box.setIcon(QMessageBox.Question)
            yes_btn = msg_box.addButton("是", QMessageBox.YesRole)
            no_btn = msg_box.addButton("否", QMessageBox.NoRole)
            msg_box.setDefaultButton(no_btn)
            msg_box.exec()
            if msg_box.clickedButton() == yes_btn:
                super().closeEvent(event)
            else:
                event.ignore()
            return
        
        option_selected = len(GlobalSetting.VIDEO_FILES_LIST) > 0 and not GlobalSetting.JOB_QUEUE_FINISHED
        if option_selected:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("确认退出")
            msg_box.setText("有未完成的任务，确定要退出吗？")
            msg_box.setIcon(QMessageBox.Question)
            yes_btn = msg_box.addButton("是", QMessageBox.YesRole)
            no_btn = msg_box.addButton("否", QMessageBox.NoRole)
            msg_box.setDefaultButton(no_btn)
            msg_box.exec()
            if msg_box.clickedButton() == yes_btn:
                super().closeEvent(event)
            else:
                event.ignore()
            return
        
        super().closeEvent(event)
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        
        video_files = []
        folders = []
        
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    video_files.append(path)
            elif os.path.isdir(path):
                folders.append(path)
        
        if folders:
            folder = folders[0]
            self.tabs.video_tab.current_source_dir = folder
            self.tabs.video_tab.source_path_edit.setText(folder)
            self.tabs.video_tab.load_videos()
        elif video_files:
            existing_files = set(GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST)
            new_files = [vf for vf in video_files if vf not in existing_files]
            
            if new_files:
                total_count = len(GlobalSetting.VIDEO_FILES_ABSOLUTE_PATH_LIST) + len(new_files)
                
                if total_count == 1:
                    self.tabs.video_tab.current_source_dir = os.path.dirname(new_files[0])
                    self.tabs.video_tab.source_path_edit.setText(self.tabs.video_tab.current_source_dir)
                else:
                    self.tabs.video_tab.current_source_dir = ""
                    self.tabs.video_tab.source_path_edit.clear()
                
                self.tabs.video_tab.load_video_files_append(new_files)
        
        event.acceptProposedAction()
