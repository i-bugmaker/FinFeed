@echo off
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
echo.
echo  ============================================
echo    FinFeed Monitor - Running
echo  ============================================
echo.
echo   Web:      http://localhost:8866
echo   API Docs: http://localhost:8866/docs
echo   Stop:     Ctrl+C
echo.
echo  ============================================
echo.

python "%~dp0..\main.py" %*
echo.
echo  [Done] Monitor stopped
pause
