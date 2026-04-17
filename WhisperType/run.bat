@echo off
:: Run WhisperType as Administrator (needed for global hotkeys).
:: Uses WhisperType.exe (a renamed copy of pythonw.exe) so the process shows
:: as "WhisperType.exe" in Task Manager instead of "pythonw.exe".
:: Console window is hidden by the app itself.

net session >nul 2>&1
if errorlevel 1 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

:: If the renamed launcher doesn't exist yet, let the app create it on first run.
if exist "WhisperType.exe" (
    start "" "%~dp0WhisperType.exe" "%~dp0whispertype.py"
) else (
    start "" pythonw whispertype.py
)
