@echo off
chcp 65001 >nul
cd /d "%~dp0"
set MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set PORT=8790
if defined GUIDANG_PORT set PORT=%GUIDANG_PORT%

if not exist .venv\Scripts\python.exe (
  echo 首次运行：正在创建运行环境...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo 没有找到 Python。请先安装 Python 3.9 或以上版本：https://www.python.org/downloads/windows/
  echo 安装时请勾选 Add python.exe to PATH
  pause
  exit /b 1
)

fc /b requirements.txt .venv\.installed >nul 2>&1
if errorlevel 1 (
  echo 正在安装依赖，大约需要 1 分钟...
  .venv\Scripts\python -m pip install -q --retries 1 --timeout 20 -r requirements.txt -i %MIRROR% || .venv\Scripts\python -m pip install -q -r requirements.txt
  if not errorlevel 1 copy /y requirements.txt .venv\.installed >nul
)

call :optional ocr 图片文字识别组件 "约 100 MB"
call :optional archive 压缩包组件 "约 10 MB"

rem 托盘模式：在后台运行，右下角有图标，不用一直开着这个窗口
.venv\Scripts\python -c "import pystray" >nul 2>&1
if errorlevel 1 goto console
start "" ".venv\Scripts\pythonw.exe" "scripts\tray.pyw" --open
echo.
echo 文渊已在后台运行：右下角托盘有图标，浏览器会自动打开。
echo 以后可以从开始菜单打开「文渊」。这个窗口 5 秒后自动关闭。
timeout /t 5 >nul
exit /b 0

:console
echo 托盘组件没装上，改用窗口模式运行：关闭此窗口即退出。
start "" http://127.0.0.1:%PORT%
.venv\Scripts\python -m app.main
pause
exit /b 0

rem 可选组件：装不上不影响其他功能，下次启动再试
:optional
fc /b requirements-%1.txt .venv\.installed-%1 >nul 2>&1
if not errorlevel 1 exit /b 0
echo 正在安装%2，%~3，只需一次...
.venv\Scripts\python -m pip install -q --retries 1 --timeout 30 -r requirements-%1.txt -i %MIRROR% || .venv\Scripts\python -m pip install -q -r requirements-%1.txt
if errorlevel 1 (
  echo %2没装上，不影响其他功能，下次启动会再试。
  exit /b 0
)
copy /y requirements-%1.txt .venv\.installed-%1 >nul
if "%1"=="ocr" .venv\Scripts\python -m pip install -q pillow-heif -i %MIRROR% >nul 2>&1
echo %2安装完成。
exit /b 0
