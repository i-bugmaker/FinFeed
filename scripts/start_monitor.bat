@echo off
chcp 65001 >nul
cd /d "%~dp0.."

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] 未检测到 Python，请先安装 Python 3.10+
    echo  下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import httpx, rich, bs4, fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [INFO] 正在安装依赖...
    pip install -r "%~dp0..\requirements.txt"
    if errorlevel 1 (
        echo  [ERROR] 依赖安装失败
        pause
        exit /b 1
    )
    echo  [OK] 依赖安装完成
)

cls

:run
:: 每次启动（含 CTRL+R 重启）前重建前端产物 web/dist —— 源码可能已更新而 dist 过期
:: （历史教训：曾因 dist 未重建导致生产界面停留在旧设计）
echo.
echo  [INFO] 正在重建前端 web/dist ...
pushd "%~dp0..\web"
call npm run build
if errorlevel 1 (
    echo  [WARN] 前端构建失败，Web 界面可能无法加载（API 仍正常）
) else (
    echo  [OK] 前端构建完成
)
popd

python "%~dp0..\main.py" %*
if errorlevel 42 (
    echo.
    echo  [重启] Ctrl+R 触发完全重启：关闭当前控制台，另开一个全新实例...
    echo  [重启] 新实例将重新构建前端并启动全新监控进程。
    echo.
    timeout /t 2 /nobreak >nul
    start "" "%~f0" %*
    exit /b 0
)
echo.
echo  [完成] 监控已停止
pause
