@echo off
:: Re-register the WhisperType Scheduled Task to run the PyInstaller-built
:: dist\WhisperType.exe instead of the pythonw.exe + whispertype.py path.
:: The pythonw.exe path crashes silently when local-model load fails on
:: machines without the Hebrew Turbo cache; the PyInstaller exe has its
:: own bundled Python with proper stdio, so it survives that path.
::
:: One-time setup: run this as Administrator.
:: After that, the desktop shortcut + launch.bat keep working unchanged.

setlocal

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo  This script must be run as Administrator.
    echo  Right-click "fix_task_use_pyinstaller.bat" and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

set "TASK_NAME=WhisperType"
set "EXE_PATH=%~dp0dist\WhisperType.exe"

if not exist "%EXE_PATH%" (
    echo.
    echo  Expected exe not found:
    echo    %EXE_PATH%
    echo  Run "python build.py" first.
    echo.
    pause
    exit /b 1
)

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%EXE_PATH%\"" ^
    /sc ONLOGON ^
    /rl HIGHEST ^
    /delay 0000:05 ^
    /f

if errorlevel 1 (
    echo.
    echo  Failed to re-create scheduled task. See errors above.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Task "WhisperType" now points to:
echo     %EXE_PATH%
echo  ============================================================
echo.
echo   Test it: schtasks /run /tn "%TASK_NAME%"
echo   Or double-click the WhisperType desktop shortcut.
echo.
pause
