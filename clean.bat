@echo off
cd /d "%~dp0"

echo.
echo  ============================================
echo    FinFeed Clean Tool
echo  ============================================
echo.
echo  Will clean:
echo   - Python bytecode cache (__pycache__)
echo   - Compiled Python files (*.pyc, *.pyo)
echo   - Export files (news_export_*)
echo   - Log files (*.log)
echo.
echo  [Safe] database files will NOT be deleted
echo.
set /p confirm=  Confirm clean? (y/N): 
if /i not "%confirm%"=="y" (
    echo  Cancelled.
    pause
    exit /b 0
)

echo.
echo  [1/5] Cleaning Python cache directories...
set cache_count=0
for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d"
        set /a cache_count+=1
    )
)
echo        %cache_count% cache dirs cleaned

echo.
echo  [2/5] Cleaning .pyc files...
set pyc_count=0
for /r "%~dp0" %%f in (*.pyc) do (
    if exist "%%f" (
        del /q "%%f"
        set /a pyc_count+=1
    )
)
for /r "%~dp0" %%f in (*.pyo) do (
    if exist "%%f" (
        del /q "%%f"
        set /a pyc_count+=1
    )
)
echo        %pyc_count% bytecode files cleaned

echo.
echo  [3/5] Cleaning export files...
set export_count=0
if exist "news_export_*.json" (
    del /q "news_export_*.json"
    set /a export_count+=1
)
if exist "news_export_*.csv" (
    del /q "news_export_*.csv"
    set /a export_count+=1
)
if exist "news_export_*.xlsx" (
    del /q "news_export_*.xlsx"
    set /a export_count+=1
)
if exist "news_export_*.xls" (
    del /q "news_export_*.xls"
    set /a export_count+=1
)
if exist "news_export_*.markdown" (
    del /q "news_export_*.markdown"
    set /a export_count+=1
)
if exist "news_export_*.md" (
    del /q "news_export_*.md"
    set /a export_count+=1
)
echo        %export_count% export file types cleaned

echo.
echo  [4/5] Cleaning log files...
set log_count=0
if exist "*.log" (
    del /q "*.log"
    set /a log_count+=1
)
echo        %log_count% log files cleaned

echo.
echo  [5/5] Cleaning temp files...
set tmp_count=0
if exist "*.tmp" (
    del /q "*.tmp"
    set /a tmp_count+=1
)
if exist "*.temp" (
    del /q "*.temp"
    set /a tmp_count+=1
)
echo        %tmp_count% temp files cleaned

echo.
echo  ============================================
echo    Clean Complete
echo  ============================================
echo.
echo   Cache dirs: %cache_count%
echo   Bytecode files: %pyc_count%
echo   Export file types: %export_count%
echo   Log files: %log_count%
echo   Temp files: %tmp_count%
echo.
pause