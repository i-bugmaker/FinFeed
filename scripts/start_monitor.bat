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

:: 确保前端构建产物 web/dist 存在（删缓存/构建产物后可能缺失）
if not exist "%~dp0..\web\dist\index.html" (
    echo.
    echo  [INFO] web/dist 缺失，正在构建前端...
    pushd "%~dp0..\web"
    call npm run build
    if errorlevel 1 (
        echo  [WARN] 前端构建失败，Web 界面可能无法加载（API 仍正常）
    ) else (
        echo  [OK] 前端构建完成
    )
    popd
)

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
