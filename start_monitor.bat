@echo off
cd /d "%~dp0"

if "%1"=="/menu" goto menu
if "%1"=="menu" goto menu

call :check_python
call :check_deps
cls
echo.
echo  ============================================
echo    FinFeed Monitor - Running
echo  ============================================
echo.
echo   Port: 8866
echo   Dashboard: http://localhost:8866
echo   Big Screen: http://localhost:8866/dashboard
echo   Stop: Ctrl+C
echo.
echo  ============================================
echo.
python "%~dp0main.py" %*
echo.
echo  [Done] Monitor stopped
pause
goto menu

:menu
cls
echo.
echo  ============================================
echo    FinFeed News Monitor
echo  ============================================
echo.
echo   [1] Start Monitor (default)
echo   [2] Fetch once then exit
echo   [3] Export data
echo   [4] Install dependencies
echo   [5] Clean cache and export files
echo   [0] Exit
echo.
set /p choice=  Select option [1]: 
if "%choice%"=="" set choice=1

if "%choice%"=="1" goto start
if "%choice%"=="2" goto once
if "%choice%"=="3" goto export
if "%choice%"=="4" goto install
if "%choice%"=="5" goto clean
if "%choice%"=="0" goto end
goto menu

:check_python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found, please install Python 3.10+
    echo  Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
goto :eof

:check_deps
python -c "import httpx; import rich; import bs4" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [INFO] Installing dependencies...
    pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo  [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo  [OK] Dependencies installed
)
goto :eof

:start
call :check_python
call :check_deps
cls
echo.
echo  ============================================
echo    FinFeed Monitor - Running
echo  ============================================
echo.
echo   Port: 8866
echo   Dashboard: http://localhost:8866
echo   Big Screen: http://localhost:8866/dashboard
echo   Stop: Ctrl+C
echo.
echo  ============================================
echo.
python "%~dp0main.py" %*
echo.
echo  [Done] Monitor stopped
pause
goto menu

:once
call :check_python
call :check_deps
cls
echo.
echo  [INFO] Running single fetch...
echo.
python "%~dp0main.py" --once
echo.
echo  [Done] Fetch completed
pause
goto menu

:export
call :check_python
call :check_deps
cls
echo.
echo  ============================================
echo    Export Data
echo  ============================================
echo.
echo   [1] JSON
echo   [2] CSV (open with Excel)
echo   [3] Excel (need openpyxl)
echo   [4] Markdown
echo   [0] Back
echo.
set /p fmt=  Select format [2]: 
if "%fmt%"=="" set fmt=2

if "%fmt%"=="0" goto menu
if "%fmt%"=="1" set fmt_name=json
if "%fmt%"=="2" set fmt_name=csv
if "%fmt%"=="3" set fmt_name=excel
if "%fmt%"=="4" set fmt_name=markdown

echo.
set /p start_date=  Start date (YYYY-MM-DD, empty=all): 
set /p end_date=  End date (YYYY-MM-DD, empty=all): 

set args=--export %fmt_name%
if not "%start_date%"=="" set args=%args% --start %start_date%
if not "%end_date%"=="" set args=%args% --end %end_date%

echo.
echo  [INFO] Exporting...
python "%~dp0main.py" %args%
echo.
pause
goto menu

:install
call :check_python
echo.
echo  [INFO] Installing/updating dependencies...
echo.
pip install -r "%~dp0requirements.txt" --upgrade
if errorlevel 1 (
    echo.
    echo  [ERROR] Install failed
) else (
    echo.
    echo  [Done] Dependencies updated
)
pause
goto menu

:clean
cls
echo.
echo  ============================================
echo    Clean Files
echo  ============================================
echo.
echo  Will clean:
echo   - Python cache (__pycache__, *.pyc)
echo   - Export files (news_export_*)
echo   - Log files (*.log)
echo.
echo  [Safe] database file will NOT be deleted
echo.
set /p confirm=  Confirm clean? (y/N): 
if /i not "%confirm%"=="y" goto menu

echo.
echo  [INFO] Cleaning...

for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d"
        echo    Deleted: __pycache__ dir
    )
)

for /r "%~dp0" %%f in (*.pyc) do (
    if exist "%%f" del /q "%%f"
)
for /r "%~dp0" %%f in (*.pyo) do (
    if exist "%%f" del /q "%%f"
)

if exist "%~dp0news_export_*.json" del /q "%~dp0news_export_*.json"
if exist "%~dp0news_export_*.csv" del /q "%~dp0news_export_*.csv"
if exist "%~dp0news_export_*.xlsx" del /q "%~dp0news_export_*.xlsx"
if exist "%~dp0news_export_*.xls" del /q "%~dp0news_export_*.xls"
if exist "%~dp0news_export_*.markdown" del /q "%~dp0news_export_*.markdown"
if exist "%~dp0news_export_*.md" del /q "%~dp0news_export_*.md"

if exist "%~dp0*.log" del /q "%~dp0*.log"

echo.
echo  [Done] Clean complete
pause
goto menu

:end
echo.
echo  Bye!
timeout /t 1 >nul
exit /b 0