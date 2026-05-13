"""Build WhisperType into a standalone .exe using PyInstaller."""
import PyInstaller.__main__
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    os.path.join(HERE, "whispertype.py"),
    "--onefile",
    "--noconsole",
    "--name", "WhisperType",
    "--icon", os.path.join(HERE, "whispertype.ico"),
    # Hidden imports that PyInstaller misses
    "--hidden-import", "faster_whisper",
    "--hidden-import", "pyaudio",
    "--hidden-import", "pyaudiowpatch",
    "--hidden-import", "keyboard",
    "--hidden-import", "pyperclip",
    "--hidden-import", "pyautogui",
    "--hidden-import", "pystray",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL._tkinter_finder",
    "--hidden-import", "ctranslate2",
    # Collect all data files for faster-whisper / ctranslate2
    "--collect-data", "faster_whisper",
    "--collect-data", "ctranslate2",
    # NOTE: --uac-admin removed deliberately. We rely on the WhisperType
    # Scheduled Task (/rl HIGHEST) to provide admin elevation when launched
    # from the desktop shortcut / launch.bat. Combining --uac-admin with
    # a /rl HIGHEST task caused Windows to silently refuse the launch.
    # Direct double-click on this exe will run non-admin; global hotkeys
    # need admin, so always launch via the desktop shortcut or the task.
    # Clean build
    "--clean",
    # Output directory
    "--distpath", os.path.join(HERE, "dist"),
    "--workpath", os.path.join(HERE, "build"),
    "--specpath", HERE,
])

print("\nBuild complete! EXE is at: WhisperType/dist/WhisperType.exe")
