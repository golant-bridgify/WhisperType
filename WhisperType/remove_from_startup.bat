@echo off
:: Remove WhisperType from Windows startup

set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WhisperType.lnk

if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo  WhisperType removed from Windows startup.
) else (
    echo  WhisperType is not in startup.
)
pause
