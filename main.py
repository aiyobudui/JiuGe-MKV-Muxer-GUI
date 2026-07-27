# -*- coding: utf-8 -*-
import logging
import sys
import os
import atexit
import tempfile
from traceback import format_exception
import psutil

window = None
app = None
_app_lock_file = None


# ---------------------------------------------------------------------------
# 单实例锁：基于临时目录下的锁文件 + PID 存活检测（纯标准库，无需加载 Qt）
# 目的：重复双击时，在加载整套 GUI 之前就发现"已在运行"并直接退出。
# ---------------------------------------------------------------------------
def _pid_alive(pid):
    """跨平台检测某个 PID 是否仍存活。"""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if h:
                kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _show_already_running():
    """用原生 Windows 消息框提示（不依赖 Qt，避免为提示而加载 GUI）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "程序已经在运行中，请勿重复打开。",
            "九歌 MKV 混流工具", 0x40
        )
    except Exception:
        pass


def ensure_single_instance():
    """确保全局只有一个实例运行。锁文件写入当前 PID，启动时检测旧 PID 是否存活。"""
    global _app_lock_file
    lock_path = os.path.join(tempfile.gettempdir(), "JiuGeMkvMuxerGUI.lock")
    for _ in range(3):
        try:
            # O_EXCL 保证创建动作原子：同一时刻只有一个进程能成功创建锁文件
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # 锁文件已存在：判断持有者是否仍存活
            try:
                with open(lock_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                pid = int(content) if content.isdigit() else -1
            except (ValueError, OSError):
                pid = -1
            if pid > 0 and _pid_alive(pid):
                _show_already_running()
                sys.exit(1)
            # 陈旧锁（进程已退出或文件损坏）：删除后重试
            try:
                os.remove(lock_path)
            except OSError:
                pass
            continue
        else:
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            _app_lock_file = lock_path
            return
    # 极少数情况：多次重试仍无法创建锁文件
    _show_already_running()
    sys.exit(1)


def _release_lock():
    """正常退出时释放锁文件（崩溃留下的锁由下次启动的 PID 检测处理）。"""
    global _app_lock_file
    if _app_lock_file and os.path.exists(_app_lock_file):
        try:
            os.remove(_app_lock_file)
        except OSError:
            pass
        _app_lock_file = None


def setup_application_font():
    from PySide6.QtGui import QFont, QFontDatabase
    from packages.Startup import GlobalFiles
    if os.path.exists(GlobalFiles.MyFontPath):
        try:
            font_id = QFontDatabase.addApplicationFont(GlobalFiles.MyFontPath)
            if font_id >= 0:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    font_name = font_families[0]
                    font = QFont(font_name, 10)
                    app.setFont(font)
        except Exception:
            logging.warning("字体加载失败，使用系统默认字体")


def create_application():
    global app
    from PySide6.QtWidgets import QApplication
    from packages.Startup import GlobalFiles
    from packages.Startup import GlobalIcons
    app = QApplication(sys.argv)
    # 调试图标路径
    icon_path = os.path.join(GlobalFiles.IconsPath, "App.ico")
    logging.info(f"ROOT_DIR: {GlobalFiles.ROOT_DIR}")
    logging.info(f"IconsPath: {GlobalFiles.IconsPath}")
    logging.info(f"Icon path: {icon_path}")
    logging.info(f"Icon exists: {os.path.exists(icon_path)}")
    if GlobalIcons.AppIcon:
        app.setWindowIcon(GlobalIcons.AppIcon.get())
    else:
        logging.warning("AppIcon is null or empty")


def create_window():
    global window
    from packages.MainWindow import MainWindow
    window = MainWindow()


def run_application():
    app_execute = app.exec()
    kill_all_children()
    sys.exit(app_execute)


def kill_all_children():
    """终止当前进程的所有子孙进程（主要是 mkvmerge.exe），避免残留孤儿进程。"""
    try:
        current_process = psutil.Process()
        children = current_process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def logger_exception(exception_type, exception_value, exception_trace_back):
    # 未捕获异常导致退出时，也清掉可能仍在运行的 mkvmerge 子进程
    kill_all_children()
    for string in format_exception(exception_type, exception_value, exception_trace_back):
        logging.error(string)


def setup_logger():
    from packages.Startup import GlobalFiles
    log_dir = os.path.dirname(GlobalFiles.AppLogFilePath)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        format='(%(asctime)s): %(name)s [%(levelname)s]: %(message)s',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        level=logging.DEBUG,
        handlers=[
            logging.FileHandler(filename=GlobalFiles.AppLogFilePath, encoding='utf-8', mode='a+'),
            logging.StreamHandler()
        ]
    )
    sys.excepthook = logger_exception


if __name__ == "__main__":
    # 1) 先确认没有其它实例在运行（失败会直接退出，不会加载 GUI）
    ensure_single_instance()
    # 2) 注册退出兜底：无论正常退出、崩溃还是未捕获异常，都清掉子进程与锁文件
    atexit.register(kill_all_children)
    atexit.register(_release_lock)

    setup_logger()
    create_application()
    setup_application_font()
    create_window()
    run_application()
