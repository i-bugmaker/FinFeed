@echo off
chcp 65001 >nul
cd /d "%~dp0.."

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found, please install Python 3.10+
    echo  Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import httpx, rich, bs4, fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [INFO] Installing dependencies...
    pip install -r "%~dp0..\requirements.txt"
    if errorlevel 1 (
        echo  [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo  [OK] Dependencies installed
)

cls

:: 每次启动前重建前端产物 web/dist —— 源码可能已更新而 dist 过期
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

:run
python "%~dp0..\main.py" %*
if errorlevel 42 (
    echo.
    echo  [Restart] Restarting FinFeed Monitor ...
    goto run
)
echo.
echo  [Done] Monitor stopped
pause
