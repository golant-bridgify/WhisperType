# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('faster_whisper')
datas += collect_data_files('ctranslate2')


a = Analysis(
    ['C:\\Users\\agas\\Projects\\WhisperType-Golan\\WhisperType\\whispertype.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['faster_whisper', 'pyaudio', 'pyaudiowpatch', 'keyboard', 'pyperclip', 'pyautogui', 'pystray', 'PIL', 'PIL._tkinter_finder', 'ctranslate2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WhisperType',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['C:\\Users\\agas\\Projects\\WhisperType-Golan\\WhisperType\\whispertype.ico'],
)
