# WhisperType - Development Context

## Project Overview
**WhisperType** is a local Windows speech-to-text application (SuperWhisper alternative). Single-file Python app running as a system tray icon with global hotkey recording, Whisper transcription, and auto-paste.

**User:** Naor, running Windows with Intel Core Ultra 7 265K (20 cores, Intel Arc iGPU, NPU). No NVIDIA GPU.

## File Structure
```
C:\Users\Naor\Downloads\WhisperType\WhisperType\
  whispertype.py          # Main app (~1718 lines, monolithic)
  requirements.txt        # Dependencies
  run.bat                 # Launcher (admin elevation)
  install.bat             # Full installer
  add_to_startup.bat      # Creates startup shortcut with icon
  create_desktop_shortcut.bat  # Desktop shortcut with icon
  generate_icon.py        # Generates whispertype.ico
  whispertype.ico         # App icon (multi-resolution)
  download_models.py      # Pre-downloads models
  README.md               # Original docs (not updated with new features)

Config: C:\Users\Naor\AppData\Roaming\WhisperType\config.json
Logs:   C:\Users\Naor\AppData\Roaming\WhisperType\whispertype.log
```

## Architecture (whispertype.py)

### Class Hierarchy
- `BaseTranscriber` - Abstract interface: `load_model()`, `transcribe()`, `transcribe_file()`
- `FasterWhisperTranscriber(BaseTranscriber)` - Default CPU backend using faster-whisper/CTranslate2
- `OpenVINOTranscriber(BaseTranscriber)` - Optional Intel GPU/NPU backend using openvino-genai
- `WhisperTranscriber = FasterWhisperTranscriber` - Backward compat alias
- `AudioRecorder` - Microphone recording via PyAudio (16kHz mono int16)
- `LoopbackRecorder` - System audio capture via PyAudioWPatch WASAPI loopback
- `OverlayNotification` - Tkinter floating overlay with waveform visualization
- `WhisperTypeApp` - Main app (tray icon, hotkey listener, recording/transcription orchestration)

### Key Helpers
- `clipboard_paste(text)` - Paste via clipboard using `keyboard.send('ctrl+v')` (avoids pyautogui conflict during recording)
- `output_text(text, mode)` - Multi-mode output: auto_paste, clipboard_only, direct_type
- `list_input_devices()` - Lists input devices filtered by default host API, deduped
- `resample_audio()` - Linear interpolation resampler for loopback audio
- `mix_audio()` - Mixes two audio arrays with normalization

### Threading Model
- **Main thread:** pystray tray icon event loop
- **Daemon threads:**
  - Model loader
  - Hotkey listener (keyboard library polling)
  - Overlay notification (tkinter mainloop)
  - Streaming transcription worker (background transcription during recording)
  - Waveform updater (~20 FPS audio level visualization)

### Recording Flow
```
Hotkey press → _start_recording()
  ├── Start recorder(s) based on recording_source (mic / loopback / both)
  ├── Show waveform overlay
  ├── Start _waveform_updater thread (real-time audio visualization)
  └── Start _streaming_worker thread (background transcription if streaming_mode != "off")

Hotkey release → _stop_and_transcribe()
  ├── Stop streaming worker
  ├── Stop recorder(s), get audio numpy array
  ├── If partial result exists from streaming:
  │     Transcribe only the tail audio → combine partial + tail → single paste
  ├── Else: full transcription → paste
  └── Show Done overlay + beep
```

### Transcribe File Flow (separate from live recording)
- Tray menu: "Transcribe File" → Hebrew/English
- Uses `BatchedInferencePipeline` for speed (batch_size=16)
- Optimized settings: beam_size=1, condition_on_previous_text=False, VAD 1000ms
- Saves .txt file next to source, opens in default editor

### Config Keys (config.json)
```json
{
  "model_size": "ivrit-ai/whisper-large-v3-turbo-ct2",  // or any MODELS/OPENVINO_MODELS key
  "language": "he",           // "auto", "he", "en"
  "hotkey": "ctrl+space",
  "beam_size": 3,             // 1=fast, 5=accurate
  "paste_mode": "direct_type", // "auto_paste", "clipboard_only", "direct_type"
  "play_sound": true,
  "cpu_threads": 16,
  "input_device_index": 1,    // null=default, or PyAudio device index
  "recording_mode": "hold",   // "hold" (hold-to-record) or "toggle" (press start/stop)
  "recording_source": "microphone",  // "microphone", "stereo_mix" (WASAPI loopback), "both"
  "engine": "faster_whisper",  // "faster_whisper" or "openvino"
  "openvino_device": "GPU",   // "CPU", "GPU", "NPU"
  "streaming_mode": "preview"  // "off", "preview" (background transcription), "live_dictation"
}
```

### Tray Menu Structure
- Language (Auto/Hebrew/English)
- Microphone (dynamic list, filtered by host API)
- Model (dynamic, engine-aware: MODELS or OPENVINO_MODELS)
- Engine (faster-whisper CPU / OpenVINO GPU/NPU/CPU)
- After Recording (Auto-Paste / Clipboard / Direct Type)
- Recording Mode (Hold / Toggle)
- Recording Source (Mic / System Audio / Both)
- Background Processing (Off / On)
- Transcribe File (Hebrew / English)
- Quit

## Features Added This Session (chronological)

1. **Transcribe File** - Pick mp4/audio file, transcribe to Hebrew/English, save .txt
2. **Microphone Picker** - Dynamic tray submenu, deduped by host API
3. **Performance: BatchedInferencePipeline** for file transcription
4. **cpu_threads: 16** default (was 8)
5. **App Icon** - whispertype.ico, desktop/startup shortcuts with icon
6. **Toggle Recording Mode** - Press-to-start, press-to-stop (for calls)
7. **WASAPI Loopback Recording** - System audio via pyaudiowpatch (Stereo Mix was broken)
8. **Dual Source Recording** - Mic + System Audio mixed
9. **BaseTranscriber Refactor** - Interface + FasterWhisperTranscriber + OpenVINOTranscriber
10. **OpenVINO Backend** - openvino-genai for Intel iGPU/NPU (installed, available)
11. **Streaming Transcription** - Background transcription during recording, paste only on stop
12. **Waveform Visualization** - Real-time 30-bar audio level display in overlay during recording
13. **clipboard_paste()** helper - Uses keyboard.send to avoid pyautogui conflicts

## Known Issues / Things to Improve

1. **paste_mode: "direct_type"** - User prefers this but it's slow for long text and breaks RTL. Consider nudging toward "auto_paste".
2. **Live Dictation mode** - Exists in code (`streaming_mode: "live_dictation"`) but unreliable. Removed from tray menu, code still present. Could be cleaned up or improved.
3. **WASAPI Loopback** - Works for system audio. User tested with Teams - transcription works but needs more testing. Loopback device is auto-detected from default output (Focusrite USB Audio).
4. **OpenVINO** - Installed and working. No ivrit-ai Hebrew models for OpenVINO exist, so standard whisper-large-v3 is used (less accurate for Hebrew). Best for English workloads.
5. **Config gets overwritten** - When user changes settings via tray menu, config.json is saved. But model_size sometimes reverts to old value if tray menu writes before the new session reads.
6. **README.md** - Not updated with all the new features.
7. **Waveform overlay** - New feature, needs user feedback on look/feel.
8. **No git repo** - Project has no version control.

## Dependencies
- faster-whisper>=1.1.0 (core transcription)
- pyaudio>=0.2.14 (microphone recording)
- PyAudioWPatch>=0.2.12.7 (WASAPI loopback for system audio)
- keyboard>=0.13.5 (global hotkey, clipboard_paste)
- pyperclip>=1.8.2 (clipboard access)
- pyautogui>=0.9.54 (paste simulation in output_text)
- pystray>=0.19.5 (system tray)
- Pillow>=10.0.0 (icon generation)
- numpy>=1.24.0
- Optional: openvino-genai, huggingface-hub (Intel GPU/NPU acceleration, already installed)

## Hardware
- Intel Core Ultra 7 265K (8P + 12E cores, 20 threads)
- Intel Arc iGPU (4 Xe cores - small, CPU is usually faster)
- Intel NPU
- Audio: Focusrite USB Audio (default output), Jabra EVOLVE LINK headset, DJI MIC MINI
- No NVIDIA GPU
