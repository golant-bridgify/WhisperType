@echo off
:: Run WhisperType as Administrator (needed for global hotkeys)
:: Console window is hidden by the app itself.

net session >nul 2>&1
if errorlevel 1 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
python whispertype.py
