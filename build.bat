@echo off
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
setlocal enabledelayedexpansion

title 九歌 MKV 混流工具 - 编译脚本

echo ========================================
echo   九歌 MKV 混流工具 - 编译脚本
echo ========================================
echo.

:: 自动探测 Python 命令（兼容 python / py 启动器）
set PY=python
where python >nul 2>nul
if not !errorlevel!==0 (
    where py >nul 2>nul
    if !errorlevel!==0 (
        set PY=py -3
    ) else (
        echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并勾选“添加到 PATH”。
        pause
        exit /b 1
    )
)

:: 步骤 1/9 关闭残留进程
echo [步骤 1/9] 正在关闭正在运行的程序及残留子进程...
taskkill /f /im "JiuGe MKV Muxer GUI.exe" >nul 2>&1
taskkill /f /im mkvmerge.exe >nul 2>&1
echo     完成！

:: 步骤 2/9 检查 Python 版本
echo.
echo [步骤 2/9] 检查 Python 环境...
for /f "tokens=2" %%i in ('%PY% --version 2^>^&1') do set PYVER=%%i
echo     Python %PYVER%
echo     Python 环境正常

:: 步骤 3/9 检查并安装核心构建依赖
echo.
echo [步骤 3/9] 检查并安装核心构建依赖（PySide6 / psutil / pyinstaller）...
%PY% -c "import PySide6" 2>nul && ( echo     PySide6 已存在 ) || ( echo     PySide6 缺失，正在安装... && %PY% -m pip install --upgrade PySide6 )
%PY% -c "import psutil" 2>nul && ( echo     psutil 已存在 ) || ( echo     psutil 缺失，正在安装... && %PY% -m pip install --upgrade psutil )
%PY% -c "import PyInstaller" 2>nul && ( echo     pyinstaller 已存在 ) || ( echo     pyinstaller 缺失，正在安装... && %PY% -m pip install --upgrade pyinstaller )
%PY% -c "import PySide6, psutil, PyInstaller" 2>nul
if not !errorlevel!==0 (
    echo [错误] 核心依赖安装不完整，请检查网络后重试。
    pause
    exit /b 1
)
echo     依赖检查完成

:: 步骤 4/9 处理程序图标（有旧图标则复用，无则安装 Pillow 生成）
echo.
echo [步骤 4/9] 处理程序图标（ICO）...
if exist "Resources\Icons\App.ico" (
    echo     已存在图标文件，直接复用（如需重新生成，请先删除 Resources\Icons\App.ico）。
    goto :icon_done
)
if not exist "Resources\Icons\App.png" (
    echo [错误] 未找到 Resources\Icons\App.png，且无图标文件，无法继续。
    pause
    exit /b 1
)
echo     未找到图标，尝试从 PNG 生成（需要 Pillow）...
%PY% -c "import PIL" 2>nul
if not !errorlevel!==0 (
    echo     Pillow 缺失，正在安装...
    %PY% -m pip install --upgrade pillow
)
%PY% -c "from PIL import Image; img=Image.open('Resources/Icons/App.png'); sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(96,96),(128,128),(256,256)]; img.save('Resources/Icons/App.ico', format='ICO', sizes=sizes); print('图标生成成功')" 2>nul
if not !errorlevel!==0 (
    echo [错误] 图标生成失败，请手动执行：%PY% -m pip install pillow 后重试。
    pause
    exit /b 1
)
echo     图标生成成功
:icon_done

:: 步骤 5/9 清理临时文件
echo.
echo [步骤 5/9] 清理临时文件...
if exist build rmdir /s /q build >nul 2>&1
if exist "JiuGe MKV Muxer GUI.spec" del /f /q "JiuGe MKV Muxer GUI.spec" >nul 2>&1
echo     完成！

:: 步骤 6/9 清理 PyInstaller 缓存
echo.
echo [步骤 6/9] 清理 PyInstaller 缓存...
if exist "%LOCALAPPDATA%\pyinstaller" rmdir /s /q "%LOCALAPPDATA%\pyinstaller" >nul 2>&1
echo     完成！

:: 步骤 7/9 清理 Python 缓存
echo.
echo [步骤 7/9] 清理 Python 缓存...
for /d /r . %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d" >nul 2>&1
del /s /q *.pyc >nul 2>&1
echo     完成！

:: 步骤 8/9 构建 EXE（--noconfirm 不卡覆盖确认；--noupx 避免被杀软拦截）
echo.
echo [步骤 8/9] 开始构建可执行文件（EXE）...
%PY% -m PyInstaller --noconfirm --noupx --name "JiuGe MKV Muxer GUI" --windowed --icon "Resources/Icons/App.ico" --add-data "Resources/Icons/App.ico;Resources/Icons" --collect-submodules packages --hidden-import packages.Styles --hidden-import packages.Widgets.CustomCheckBox main.py
if not !errorlevel!==0 (
    echo [错误] 构建失败，请查看上方日志。
    pause
    exit /b 1
)

:: 步骤 9/9 清理构建残留
echo.
echo [步骤 9/9] 清理构建过程产生的临时文件...
if exist build rmdir /s /q build >nul 2>&1
if exist "JiuGe MKV Muxer GUI.spec" del /f /q "JiuGe MKV Muxer GUI.spec" >nul 2>&1
echo     完成！

echo.
echo ========================================
echo          构建成功！
echo ========================================
echo.
echo 输出目录：%cd%\dist\JiuGe MKV Muxer GUI\
echo.
pause
