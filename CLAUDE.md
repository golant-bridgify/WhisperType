# WhisperType — Development Context

## Project Overview
**WhisperType** is a Windows speech-to-text app — a SuperWhisper alternative that runs as a system-tray icon with global-hotkey recording, local/cloud Whisper transcription, AI-powered cleanup, and auto-paste. Single-file Python app (~5,100 lines, monolithic by design).

**User:** Naor. Windows, Intel Core Ultra 7 265K (20 cores, Intel Arc iGPU, NPU). No NVIDIA GPU. Hebrew-speaking developer; dictates mixed Hebrew + English including programming/product terms. Prefers minimal UI — runs with `silent_mode: true`, `beep_device_index: "off"`.

**GitHub:** https://github.com/Danaor/WhisperType

## File Structure
```
C:\Users\Naor\Downloads\WhisperType\
  CLAUDE.md              # This file
  LICENSE
  README.md              # User-facing docs
  .gitignore             # Ignores WhisperType.exe (auto-generated launcher)
  WhisperType\
    whispertype.py       # Main app (~5,100 lines)
    run_tests.py         # Test suite (29 tests, all pass)
    requirements.txt     # Dependencies
    build.py             # PyInstaller → dist/WhisperType.exe
    run.bat              # Launcher (admin elevation)
    install.bat          # Full installer
    add_to_startup.bat   # Creates startup .lnk
    create_desktop_shortcut.bat
    generate_icon.py     # Regenerates whispertype.ico
    whispertype.ico      # Multi-size app icon (dark slate + cyan neon mic)
    download_models.py   # Pre-downloads Whisper models
    dist/WhisperType.exe # Standalone executable (~358MB if built)

Config:   %APPDATA%\WhisperType\config.json
Logs:     %APPDATA%\WhisperType\whispertype.log  (RotatingFileHandler, 2MB × 3)
History:  %APPDATA%\WhisperType\history.json     (max 1000 entries)
Meetings: %APPDATA%\WhisperType\meetings\        (one .md file per meeting)
Beep:     %APPDATA%\WhisperType\beep.wav         (48kHz stereo, regenerated on startup)
```

## Architecture (whispertype.py)

### Class Hierarchy
- `BaseTranscriber` — Abstract: `load_model`, `transcribe`, `transcribe_file`
- `FasterWhisperTranscriber(BaseTranscriber)` — CPU backend (faster-whisper / CT2). Has `custom_vocabulary` passed as `initial_prompt`.
- `OpenVINOTranscriber(BaseTranscriber)` — Intel GPU/NPU code path, hidden from UI, still present for future use.
- `WhisperTranscriber = FasterWhisperTranscriber` — Backward-compat alias
- `GroqTranscriber(BaseTranscriber)` — Cloud backend via api.groq.com. Supports `task=transcribe/translate`, `he_en_bias`, `custom_vocabulary`.
- `GroqLLMCleaner` — Post-transcription polish via llama-3.3-70b-versatile. 4 styles + 3-layer injection guard.
- `AudioRecorder` — Mic capture via PyAudio (16kHz mono int16)
- `LoopbackRecorder` — System audio via PyAudioWPatch WASAPI loopback
- `MeetingSession` — Long-form chunked capture (45s rotating recorder) + LLM summary
- `OverlayNotification` — Tkinter floating overlay + waveform
- `WhisperTypeApp` — Main orchestrator (tray, hotkey, recording, transcription, meeting, undo)

### Key Helpers
- `clipboard_paste(text)` → bool — Paste via clipboard with retry + readback verification
- `output_text(text, mode)` → bool — Top-level paste; modes: `auto_paste`, `clipboard_only`, (legacy `direct_type` migrated out)
- `_copy_with_retry(text, retries=3)` → (ok, msg) — Handles clipboard contention silently
- `strip_hallucinated_tail(text)` — Removes "Thank you"/"תודה רבה" etc. Whole-text matches → empty (the caller flashes tray-icon error).
- `trim_trailing_silence(audio)` — Pre-transcribe hallucination prevention
- `_validate_hotkey(str)` → bool — Rejects bare keys without modifier (or F-keys alone OK)
- `_fmt_relative_ts(sec)` → "mm:ss" / "h:mm:ss" — Meeting transcript timestamps
- `list_input_devices()`, `list_output_devices()`, `list_loopback_devices()` — Device enumeration, deduped by name
- `resample_audio()`, `mix_audio()` — Audio utilities
- `is_user_admin()` — Windows admin check (warns at startup if not)

### Module-level State
- `_config_lock`, `_history_lock` — threading.Lock serializing JSON writes (atomic via `.tmp` + `os.replace`)
- `MODELS` dict — display names for Whisper models
- `MODEL_LANGUAGE` — auto language from model
- `_HALLUCINATION_PATTERNS` — regex list for strip
- `MEETINGS_DIR` — `%APPDATA%/WhisperType/meetings`

### Threading Model
- **Main thread:** pystray event loop
- **Daemon threads:**
  - `_hotkey_listener` — event-driven, waits on `threading.Event` set by `keyboard.add_hotkey` callback (swappable live)
  - Model loader
  - Overlay Tk mainloop
  - Streaming transcription worker (preview mode, local backend)
  - Waveform updater (~20 FPS, rate-limited on persistent errors)
  - Recording watchdog (auto-stops at 10 min)
  - Meeting rotation loop (`_rotation_loop`, every 45s)
  - Per-chunk transcription workers (meeting)
  - Clipboard auto-restore timer (fire-and-forget 2s)
  - Undo hotkey callback (`keyboard.add_hotkey`, non-blocking)

### Recording Flow (press-to-talk)
```
Hotkey pressed → _hotkey_event.set()
_hotkey_listener wakes:
  ├─ if !model_loaded: wait for release, log rate-limited, continue
  ├─ if meeting active: show "Meeting active" error, wait for release
  ├─ if audio warmup needed (idle >5min): open+close PyAudio once
  ├─ _start_recording() bumps generation, starts recorders
  │   ├─ show_recording overlay + tray='recording' (red)
  │   ├─ recorder.start() [+ loopback.start() if both/stereo_mix]
  │   ├─ spawn _streaming_worker thread (local backend only)
  │   ├─ spawn _waveform_updater thread
  │   └─ spawn _recording_watchdog thread (warn 5min, stop 10min)
  └─ poll is_pressed() → on release → _stop_and_transcribe()
       ├─ tray='processing' (amber)
       ├─ join streaming thread (capture partial)
       ├─ stop recorders, mix if source=both
       ├─ if too short (<1.5s): bail
       ├─ if RMS < 0.003 over 1.5s: "Mic silent — try again" + flash red X
       ├─ pick path: partial+tail OR full transcription
       ├─ transcribe via self.transcriber (_transcribe_with_fallback)
       ├─ _cleanup_if_enabled() → Groq LLM pass
       ├─ _do_paste() → clipboard copy + Ctrl+V + save undo state
       ├─ spawn clipboard auto-restore (2s delay)
       ├─ add_history_entry + show_done + _play_done_beep
       └─ tray='idle' (green) [unless flash_error still active]
```

### Meeting Flow
```
Tray menu → Start Meeting
  ├─ blocks if recording active or model not loaded
  ├─ MeetingSession.start():
  │   ├─ creates AudioRecorder + LoopbackRecorder based on 'both' source
  │   ├─ spawns _rotation_loop thread (every 45s)
  │   └─ tray='meeting' (purple with red dot)
  └─ Main hotkey is BLOCKED via _is_meeting_active() check

Rotation loop (every 45s):
  ├─ stop current recorders → grab audio
  ├─ open fresh recorders (~50ms gap)
  └─ spawn worker to transcribe grabbed chunk → append to self.chunks

Tray menu → Stop Meeting
  ├─ MeetingSession.stop():
  │   ├─ finalise current chunk
  │   ├─ wait for all pending Groq transcription jobs (timeout 60s)
  │   ├─ _summarise() via llama-3.3-70b for summary + action items
  │   └─ _write_output_file() → markdown with timestamps
  └─ os.startfile(path) opens in default editor
```

### Undo Flow
```
Any paste:
  ├─ _do_paste(text, mode) grabs clipboard-before
  ├─ output_text() copies + Ctrl+V
  ├─ stores self._last_paste = {text, old_clipboard, timestamp}
  └─ if auto_paste + auto_restore: schedule thread to restore clipboard after 2s
         (only if clipboard is still the pasted text — respects user copy)

Ctrl+Alt+Z pressed (via keyboard.add_hotkey):
  _undo_last_paste():
    ├─ reads self._last_paste (locked, consumes)
    ├─ if stale (>60s): "Last paste too old to undo"
    ├─ pyperclip.copy(old_clipboard)   [restore clipboard immediately]
    ├─ kb.send('ctrl+z')                [remove the paste from focused window]
    └─ show "↩  Undone (N chars)" overlay
```

## Config Keys (config.json)
```json
{
  "model_size": "large-v3-turbo",
  "language": "he",
  "hotkey": "ctrl+space",
  "beam_size": 3,
  "paste_mode": "auto_paste",
  "play_sound": true,
  "cpu_threads": 16,
  "input_device_index": 1,
  "loopback_device_index": null,
  "recording_mode": "hold",
  "recording_source": "both",
  "engine": "faster_whisper",
  "streaming_mode": "preview",
  "translate_mode": false,
  "auto_start": false,
  "transcription_backend": "groq",
  "groq_api_key": "gsk_...",
  "groq_model": "whisper-large-v3-turbo",
  "silent_mode": true,
  "beep_device_index": "off",
  "groq_he_en_bias": true,
  "cleanup_style": "casual",
  "cleanup_llm_model": "llama-3.3-70b-versatile",
  "custom_vocabulary": "git, push, React, Kubernetes, ...",
  "clipboard_auto_restore": true,
  "undo_hotkey": "ctrl+alt+z"
}
```

## Tray Menu Structure
```
WhisperType (disabled header)
Status: Loading... (dynamic)
— Audio Input — (submenu: mics, then loopback devices)
— Model — (5 radio items: Hebrew Turbo/English Distil/General Turbo Local/Groq Turbo/Groq Hebrew→English)
— Options —
  ├─ Hold to Record / Toggle (radio)
  ├─ Auto-Paste / Clipboard Only (radio)
  ├─ Invisible Mode (checkbox)
  ├─ Bias Groq to Hebrew/English (checkbox)
  ├─ AI Cleanup (Groq) → Off / Casual ⭐ / Proofread / Email / Code (radio)
  ├─ Custom Vocabulary... (dialog)
  ├─ Hotkey: ctrl+space... (dialog — dynamic label)
  ├─ Restore Clipboard After Paste (checkbox)
  ├─ ─────
  ├─ 🎙  Start Meeting (long recording)   ←→   ⏹  Stop Meeting  (dynamic)
  ├─ ─────
  ├─ Beep Output → None/System Default/<devices> (radio)
  ├─ Transcribe File → Hebrew / English
  ├─ History (dialog)
  ├─ Set Groq API Key... (dialog)
  └─ Start with Windows (checkbox)
Quit
```

## Tray Icon States
- 🟢 **idle** — Green circle + white mic. Ready to record.
- 🔴 **recording** — Bright red circle + white mic. Active recording.
- 🟡 **processing** — Amber circle + 3 sound bars. Transcribing.
- 🔵 **loading** — Blue circle + hourglass. Model loading.
- ❌ **error** — Dark red circle + white X. Model failed / silent mic / clipboard busy (3s flash).
- 🟣 **meeting** — Deep purple + red dot + horizontal bars. Meeting in progress.

## Dependencies (requirements.txt)
- `faster-whisper>=1.1.0` — Local CPU transcription
- `pyaudio>=0.2.14` — Mic recording
- `PyAudioWPatch>=0.2.12.7` — WASAPI loopback for system audio
- `keyboard>=0.13.5` — Global hotkey + Ctrl+V send
- `pyperclip>=1.8.2` — Clipboard access
- `pystray>=0.19.5` — System tray
- `Pillow>=10.0.0` — Icon gen + overlay
- `numpy>=1.24.0` — Audio math
- `requests>=2.31.0` — Groq HTTP
- Optional: `openvino-genai`, `huggingface-hub` (OpenVINO backend, hidden from UI)

## Test Suite (run_tests.py)
29 tests, `python run_tests.py` runs them all. Covers:
1. Syntax + imports
2. Config roundtrip, migrations, corruption, atomic writes (4)
3. History thread safety with 20 concurrent writes
4. Hallucination stripping (3)
5. Transcriber construction + vocab wire-up
6. **LIVE Groq calls** (requires API key in config): 4 cleanup styles + expansion guard + RTL + vocab fix
7. Meeting end-to-end markdown generation
8. Paste/undo state machine (3)
9. Hotkey validation
10. All 6 icon states render

## Known Issues / Non-Goals
1. **Live Dictation mode** — Code present, removed from UI (unreliable).
2. **No official native-Windows sleep/wake hook** — we mitigate with `_last_recording_time` warmup and silent-audio detection instead.
3. **Multi-instance** — single-instance mutex blocks duplicates (good).
4. **File transcription** — Does NOT go through `_cleanup_if_enabled` (long text, token-limit concerns).
5. **OpenVINO backend** — Still in source, hidden from UI. Keep for potential Intel GPU/NPU use.
6. **Admin rights** — Required on Windows for global keyboard hook; detected at startup, warned if not elevated.

## Session History (chronological)

### Session 1: Initial build
- Tray icon + hotkey + faster-whisper + paste

### Session 2 (2026-04-13): Audio expansion + stability
- WASAPI loopback (mic + system audio mix)
- Multi-model, auto language from model
- Streaming transcription worker
- PyInstaller build
- Admin launcher

### Session 3 (2026-04-13): Features layer 1
- Translation mode
- Auto-start (Windows startup shortcut)
- History viewer (Tkinter)

### Session 4 (2026-04-15): Cloud + reliability
- Groq Cloud backend + Tkinter API key dialog
- Hebrew/English bias for Whisper
- Fallback to local on cloud failure

### Session 5 (2026-04-17): Big intelligence + safety sweep — **this session**
- **Bug hunting (15+ fixes):** hallucination-strip erase fix, hotkey busy-loop, is_recording state bleed, log rotation (RotatingFileHandler), clipboard retry + readback verification, transcription generation counter (race fix), recording watchdog, PyAudio try/finally, error icon state, admin check, silent-audio detection, WASAPI warmup, legacy config migration
- **Feature — AI Cleanup:** `GroqLLMCleaner` class, 4 styles (Casual/Proofread/Email/Code), with 3-layer anti-injection guard (system prompt + `<transcription>` delimiters + 1.5× length cap) after discovering the cleanup LLM was expanding "I want to review the code" into a 2,020-char AWS implementation plan
- **Feature — Custom Vocabulary:** per-user term list fed to Whisper's `prompt`/`initial_prompt` + LLM cleanup system prompt. Fixes "git push" → "בגד פושע" permanently. Dialog in tray menu.
- **Feature — Meeting Mode:** `MeetingSession` class, 45s rotating recorder, per-chunk background Groq transcription, final LLM summary + action-items pass, saves as markdown to `%APPDATA%/WhisperType/meetings/`.
- **Feature — Undo Last Paste:** Ctrl+Alt+Z hotkey via `keyboard.add_hotkey`. Sends Ctrl+Z + restores the clipboard content that was there before the paste.
- **Feature — Clipboard auto-restore:** after every auto-paste, clipboard returns to its pre-paste content (~2s delay). Guarded: won't override a manual copy.
- **Feature — Hotkey UI:** Tkinter dialog to change the press-to-talk hotkey at runtime. Refactored `_hotkey_listener` to event-driven (`keyboard.add_hotkey` + `threading.Event`) so the hotkey can be swapped without restarting the thread.
- **Icon redesign:** dark slate + cyan neon mic (Design D); 6-state icon set for tray.
- **Test suite:** 29 tests in `run_tests.py`, all passing.

## User Preferences (inferred from usage)
- Minimal UI: `silent_mode: true`, `beep: off` — **tray icon colour + tooltip is the primary feedback channel**
- Hebrew-first workflow, code terms in English
- Uses "Both" audio source (mic + loopback) → likely records meetings
- Dictates for 3-30 second clips typically; meetings are longer
- Cares about tool reliability over fancy features — spent a full session fixing bugs before adding new stuff

## How to Run / Dev Quickstart

```bash
# From repo root
cd WhisperType
pip install -r requirements.txt

# Run in dev mode
python whispertype.py

# Run with admin (proper hotkey support)
run.bat

# Run tests (requires Groq API key configured)
python run_tests.py

# Rebuild icon (after generate_icon.py changes)
python generate_icon.py

# Rebuild standalone exe
python build.py  # outputs dist/WhisperType.exe
```
