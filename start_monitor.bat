@echo off
chcp 65001 >nul
echo ============================================
echo   PioneerNews 实时新闻监控
echo ============================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查依赖是否安装
python -c "import httpx; import rich" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装依赖...
    pip install -r "%~dp0requirements.txt"
    echo.
)

:: 运行脚本
echo.
echo   [启动] 实时监控模式（每5秒抓取一次，Ctrl+C 停止）
echo   [网页] http://localhost:8866
echo.
python "%~dp0news_monitor.py" %*
pause
