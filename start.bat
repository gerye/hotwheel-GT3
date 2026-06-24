@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8000

rem 找可用的 Python:优先 py 启动器,其次 python。
rem 用 "--version 能跑通" 来判断,这样能避开 Microsoft Store 的假 python 占位程序。
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo [错误] 未检测到可用的 Python。
  echo 请安装 Python 3 ^(安装时务必勾选 "Add Python to PATH"^)。
  echo 也可在 PowerShell 里运行:  winget install Python.Python.3.12
  echo 安装完成后重新双击本文件。
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

rem 首次创建虚拟环境
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
call ".venv\Scripts\activate.bat"

rem 缺依赖才安装(首次需联网)
python -c "import fastapi, qrcode" 2>nul || pip install -q -e .

rem 关掉占用该端口的旧服务
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

rem 起来后自动打开浏览器(延时 2 秒)
start "" cmd /c "timeout /t 2 >nul & start http://localhost:%PORT%"

echo.
echo ====== 风火轮 GT3 正在运行 ======
echo 本机访问: http://localhost:%PORT%
echo 手机访问: 扫描网页底部的二维码(需连同一 WiFi)
echo 关闭此窗口即可停止服务。
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
pause
