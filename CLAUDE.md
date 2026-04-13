# WhisperType - Development Context

## Project Overview
**WhisperType** is a local Windows speech-to-text application (SuperWhisper alternative). Single-file Python app running as a system tray icon with global hotkey recording, Whisper transcription, and auto-paste.

**User:** Naor, running Windows with Intel Core Ultra 7 265K (20 cores, Intel Arc iGPU, NPU). No NVIDIA GPU.

## File Structure
```
C:\Users\Naor\Downloads\WhisperType\WhisperType\
  whispertype.py          # Main app (~1800 lines, monolithic)
  requirements.txt        # Dependencies
  build.py                # PyInstaller build script → dist/WhisperType.exe
  run.bat                 # Launcher (admin elevation)
  install.bat             # Full installer
  add_to_startup.bat      # Creates startup shortcut with icon
  create_desktop_shortcut.bat  # Desktop shortcut with icon
  generate_icon.py        # Generates whispertype.ico
  whispertype.ico         # App icon (multi-resolution)
  download_models.py      # Pre-downloads models
  README.md               # Original docs (not updated with new features)
  dist/WhisperType.exe    # Standalone executable (358MB, built with PyInstaller)

Config: C:\Users\Naor\AppData\Roaming\WhisperType\config.json
Logs:   C:\Users\Naor\AppData\Roaming\WhisperType\whispertype.log
```

## Architecture (whispertype.py)

### Class Hierarchy
- `BaseTranscriber` - Abstract interface: `load_model()`, `transcribe()`, `transcribe_file()`
- `FasterWhisperTranscriber(BaseTranscriber)` - Default CPU backend using faster-whisper/CTranslate2
- `OpenVINOTranscriber(BaseTranscriber)` - Optional Intel GPU/NPU backend (code exists but removed from UI)
- `WhisperTranscriber = FasterWhisperTranscriber` - Backward compat alias
- `AudioRecorder` - Microphone recording via PyAudio (16kHz mono int16)
- `LoopbackRecorder` - System audio capture via PyAudioWPatch WASAPI loopback (supports device selection)
- `OverlayNotification` - Tkinter floating overlay with waveform visualization
- `WhisperTypeApp` - Main app (tray icon, hotkey listener, recording/transcription orchestration)

### Key Helpers
- `clipboard_paste(text)` - Paste via clipboard using `keyboard.send('ctrl+v')`
- `output_text(text, mode)` - Output modes: auto_paste, clipboard_only (direct_type removed from UI)
- `list_input_devices()` - Lists input devices filtered by default host API, deduped
- `list_loopback_devices()` - Lists WASAPI loopback output devices for device selection
- `resample_audio()` - Linear interpolation resampler for loopback audio
- `mix_audio()` - Mixes two audio arrays with normalization
- `MODEL_LANGUAGE` - Maps model → language automatically (no manual language selection)

### Threading Model
- **Main thread:** pystray tray icon event loop
- **Daemon threads:**
  - Model loader
  - Hotkey listener (keyboard library polling)
  - Overlay notification (tkinter mainloop)
  - Streaming transcription worker (background transcription during recording)
  - Waveform updater (~20 FPS audio level visualization, shows both mic + loopback)

### Recording Flow
```
Hotkey press → _start_recording()
  ├── Start recorder(s) based on recording_source (mic / loopback / both)
  ├── Show waveform overlay
  ├── Start _waveform_updater thread (real-time audio visualization)
  └── Start _streaming_worker thread (starts transcribing after 5s of audio)

Hotkey release → _stop_and_transcribe()
  ├── Stop streaming worker (wait for completion)
  ├── Stop recorder(s), get audio numpy array
  ├── Short recording (<5s): single fast transcription, beam_size=1
  ├── Long recording with streaming partial: use partial (+ optional tail)
  ├── source="both": always full re-transcription on mixed audio
  └── Show Done overlay + beep
```

### Transcribe File Flow
- Tray menu: "Transcribe File" → Hebrew/English
- Uses `BatchedInferencePipeline` for speed (batch_size=16)
- Accuracy-optimized: beam_size=5, condition_on_previous_text=True, VAD 500ms
- Saves .txt file next to source, opens in default editor

### Config Keys (config.json)
```json
{
  "model_size": "ivrit-ai/whisper-large-v3-turbo-ct2",
  "language": "he",              // legacy - now auto-detected from model via MODEL_LANGUAGE
  "hotkey": "ctrl+space",
  "beam_size": 3,                // used for long recordings, short uses 1
  "paste_mode": "auto_paste",    // "auto_paste" or "clipboard_only"
  "play_sound": true,
  "cpu_threads": 16,
  "input_device_index": 1,       // null=default, or PyAudio device index
  "loopback_device_index": null,  // null=default output, or specific WASAPI loopback index
  "recording_mode": "hold",      // "hold" or "toggle"
  "recording_source": "both",    // "microphone", "stereo_mix", "both"
  "engine": "faster_whisper",    // only faster_whisper in UI now
  "streaming_mode": "preview"    // always "preview" (no UI toggle)
}
```

### Tray Menu Structure (current)
- Microphone (dynamic list)
- Model (Hebrew Turbo ⭐ / Hebrew Large / English Distil ⭐ / General Turbo)
- After Recording (Auto-Paste / Clipboard Only)
- Recording Mode (Hold / Toggle)
- Recording Source (Mic / System Audio / Both + System Audio Device submenu)
- Transcribe File (Hebrew / English)
- Quit

### Models Available
```python
MODELS = {
    "ivrit-ai/whisper-large-v3-turbo-ct2": "Hebrew Turbo ⭐",    # → language: "he"
    "ivrit-ai/whisper-large-v3-ct2": "Hebrew Large",              # → language: "he"
    "distil-large-v3": "English Distil ⭐",                       # → language: "en"
    "large-v3-turbo": "General Turbo",                            # → language: "auto"
}
```

## Changes Made in Session 2 (2026-04-13)

1. **Git initialized** - repo with .gitignore, initial commit
2. **Loopback device selection** - tray menu to pick which output device to capture (fixes Teams on Jabra)
3. **Fixed "תודה רבה" hallucination** - source="both" now does full re-transcription on mixed audio
4. **Waveform shows both sources** - mic + loopback combined (max of both)
5. **Removed Engine menu** - only faster-whisper, OpenVINO code kept but hidden
6. **Simplified models** - 4 models: Hebrew Turbo/Large, English Distil, General Turbo
7. **Auto language from model** - MODEL_LANGUAGE dict, removed Language menu
8. **Fixed auto_paste** - switched from pyautogui to keyboard.send (was broken)
9. **Removed direct_type** - from paste mode menu
10. **Removed Background Processing menu** - always on (preview mode)
11. **PyInstaller build** - build.py → dist/WhisperType.exe (358MB standalone)
12. **Waveform log-scale** - RMS + dB scale for better low-volume visibility
13. **Fixed waveform disappearing** - fade_out now respects waveform_mode
14. **Faster streaming** - INTERVAL=0.5s, min 5s audio before streaming starts
15. **Short recording optimization** - <5s recordings skip streaming, beam_size=1
16. **File transcription accuracy** - beam_size=5, condition_on_previous_text=True
17. **Streaming join fix** - waits for streaming to finish, captures partial after completion

## Known Issues

1. **Live Dictation mode** - Code exists but unreliable, removed from UI
2. **Config migration** - old configs may have stale keys (direct_type, engine, etc.)
3. **README.md** - Not updated with new features
4. **Loopback still shows Focusrite in log** - user set device 26, needs verification
5. **~3.5s for short sentences** - hardware limit for local Whisper on CPU

## Next Session: Planned Features

### 1. Auto-Start with Windows
- Add tray menu toggle "Start with Windows"
- Create/remove shortcut in Windows Startup folder programmatically
- Should launch the exe (or python script) with admin elevation
- Config key: `"auto_start": false`

### 2. Transcription History
- Save every transcription to a history file (JSON or SQLite)
- Fields: timestamp, text, duration, model, language, source (mic/loopback/both)
- Tray menu: "History" → opens a simple viewer window
- Consider: Tkinter window with scrollable list, search, copy-to-clipboard
- Storage: `C:\Users\Naor\AppData\Roaming\WhisperType\history.json`
- Keep last N entries (e.g., 1000) to prevent unlimited growth

### 3. Translation Mode
- Whisper's `task="translate"` outputs English regardless of input language
- Add tray menu option: "Translate to English" toggle
- When enabled: speak Hebrew → get English text
- Config key: `"translate_mode": false`
- Only affects live recording, not file transcription (which already has language choice)

## Dependencies
- faster-whisper>=1.1.0 (core transcription)
- pyaudio>=0.2.14 (microphone recording)
- PyAudioWPatch>=0.2.12.7 (WASAPI loopback for system audio)
- keyboard>=0.13.5 (global hotkey, clipboard_paste)
- pyperclip>=1.8.2 (clipboard access)
- pyautogui>=0.9.54 (legacy, can be removed - auto_paste now uses keyboard)
- pystray>=0.19.5 (system tray)
- Pillow>=10.0.0 (icon generation)
- numpy>=1.24.0
- Optional: openvino-genai, huggingface-hub (code exists, not in UI)

## Hardware
- Intel Core Ultra 7 265K (8P + 12E cores, 20 threads)
- Intel Arc iGPU (4 Xe cores - too small for Whisper)
- Intel NPU (Whisper support not mature)
- Audio: Focusrite USB Audio (default output), Jabra EVOLVE LINK headset, DJI MIC MINI
- No NVIDIA GPU
- Performance: ~3.5s for 2s speech (1.5x real-time, hardware limit)
