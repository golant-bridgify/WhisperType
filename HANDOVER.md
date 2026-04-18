# WhisperType — Handover Notes

*Last updated: 2026-04-18, end of session 6. Repo state: master @ `61c3dbc`, `origin/master` synced.*

This doc is for the next developer (or future you) picking up WhisperType. Read this first, then [CLAUDE.md](CLAUDE.md) for architecture details, then [WhisperType/README.md](WhisperType/README.md) for user-facing usage.

---

## TL;DR of current state

- **Working and stable.** Production-quality for personal use. All 29 automated tests pass.
- **Core features are complete:** recording, transcription (local + cloud), AI cleanup, custom vocabulary, meeting mode, undo, hotkey UI.
- **Session 6 (this one) eliminated the stale-PortAudio silent-capture bug at the architectural level** via per-recording subprocess isolation. That bug was the last critical reliability issue.
- **No known critical bugs.**

---

## Where the work is

```
C:\Users\Naor\Downloads\WhisperType\
├── CLAUDE.md              ← Full dev context. READ FIRST.
├── README.md              ← (legacy, just forwards to WhisperType/README.md)
├── HANDOVER.md            ← This file.
├── LICENSE
├── .gitignore
└── WhisperType\
    ├── whispertype.py     ← Everything. ~5,300 lines. Monolithic on purpose.
    ├── run_tests.py       ← 29 tests. Run before/after any change.
    ├── generate_icon.py   ← Regenerate whispertype.ico
    ├── requirements.txt
    ├── build.py           ← PyInstaller build → dist/WhisperType.exe
    ├── run.bat            ← Admin launcher
    └── (various install/setup .bat files)
```

User data:
```
%APPDATA%\WhisperType\
├── config.json            ← All settings (written atomically under lock)
├── whispertype.log        ← Rotating 2MB × 3 backups
├── history.json           ← Last 1000 transcriptions (written under lock)
├── meetings\              ← *.md files, one per meeting
└── beep.wav               ← Regenerated on startup (48kHz stereo)
```

---

## Quick orientation

### Start dev mode

```bash
cd WhisperType
pip install -r requirements.txt
python whispertype.py         # Run in place
# OR
run.bat                       # Run as admin (proper hotkey support)
```

### Run the test suite

```bash
python run_tests.py
```

Takes ~15 seconds. Section 6 (live Groq tests) needs an API key in `config.json`. If no key → those 6 tests fail with "No Groq API key" — the rest still pass.

### Git / remote

```bash
git log --oneline -10     # recent commits
git push origin master    # push to GitHub
```

Repo: https://github.com/Danaor/WhisperType

---

## The mental model

WhisperType is a single class (`WhisperTypeApp`) that orchestrates:

```
  ┌─────────────────────────────────┐
  │        WhisperTypeApp           │
  │                                 │
  │  ┌───────────┐   ┌───────────┐  │
  │  │ Recorder  │   │ Loopback  │  │        Audio IN
  │  │ (mic)     │   │ Recorder  │  │
  │  └─────┬─────┘   └─────┬─────┘  │
  │        │               │        │
  │        └───────┬───────┘        │
  │                │                │
  │        ┌───────▼──────────┐     │
  │        │   Transcriber    │     │ local (faster-whisper)
  │        │  (Groq / Local)  │─────┼─ or cloud (Groq)
  │        └───────┬──────────┘     │
  │                │                │
  │        ┌───────▼──────────┐     │
  │        │ GroqLLMCleaner   │     │ optional AI polish
  │        └───────┬──────────┘     │
  │                │                │
  │        ┌───────▼──────────┐     │
  │        │    _do_paste     │     │ Ctrl+V + save undo state
  │        └──────────────────┘     │        Text OUT
  │                                 │
  │  MeetingSession (parallel)      │
  │  ├─ rotating recorder every 45s │
  │  └─ chunked transcription       │
  └─────────────────────────────────┘
```

For meetings, `MeetingSession` owns its own recorders and runs a background thread that rotates them every 45 seconds, transcribing each chunk independently.

---

## Features added (chronological, across all sessions)

Each feature links to the relevant commit for diff-level context.

### Session 5 (2026-04-17) — Features + stability
| Feature | Commit | One-line description |
|---|---|---|
| Icon state polish | `46eb2dd` | `processing` + `loading` icons visually distinct |
| Bug sweep | `e85748a` | 15+ stability fixes: silent failures, log rotation, threading, etc. |
| Beep crash fix | `5648826` | PortAudio subprocess isolation — Focusrite no longer kills the app |
| Tray-state-at-startup fix | `0fd2e84` | Starts blue/loading instead of lying about being ready |
| Silent-failure guards | `a723e8c` | `_flash_error_tray`, clipboard retry, log rotation, generation counter |
| "תודה רבה" fix | `777841b` | Whole-text hallucinations are erased + tray flash red X |
| Icon redesign | `4d33834` | Dark slate + cyan neon (Design D) |
| WASAPI wake-from-sleep first-attempt | `f0ad814` | Silent-audio detection + warmup on long idle |
| **AI Cleanup** | `ceaf825` | `GroqLLMCleaner` + 4 styles |
| Cleanup prompt strengthening | `9f006c8` | Added `Proofread` style, better typo correction |
| **Custom Vocabulary** | `edaf65a` | `"git push"` permanent fix |
| Expansion prevention | `f14b716` | `<transcription>` delimiters + 1.5× length cap |
| **Meeting Mode** | `679e738` | `MeetingSession` + LLM summary + markdown output |
| **Undo Last Paste** | `34ab478` | `Ctrl+Alt+Z` + auto-restore clipboard |
| **Hotkey UI + Test Suite** | `a999d61` | Change hotkey from menu + 29 tests |
| Handover docs (first pass) | `87cee08` | CLAUDE.md + HANDOVER.md + README.md refresh |

### Session 6 (2026-04-18) — The stale-PortAudio saga
| Feature | Commit | One-line description |
|---|---|---|
| Reactive silent-capture auto-restart | `2504af8` | After 2 consecutive silents, auto-restart; manual 'Restart WhisperType' tray item |
| Long-idle watchdog | `5c78229` | Silent restart after 4h with no recording |
| **Display-wake watchdog** | `7e22320` | `GetLastInputInfo` polling; restart when user returns from ≥10 min idle — catches mic-on-monitor power cycles |
| **⭐ SubprocessAudioRecorder** | `61c3dbc` | Structural fix — every recording in a fresh Python subprocess. Stale-PortAudio bug is now impossible. |

---

## The stale-PortAudio bug — documented in detail

Because this dominated session 6, here's the background for anyone who sees weird silent captures in the future.

**Symptom:** after several hours or a monitor sleep+wake cycle, WhisperType captures recordings where:
- Windows shows the privacy mic indicator (stream opens fine)
- PyAudio callbacks fire (frames are returned)
- But RMS ≈ 0.00002 (frames are zero-filled)

Sound Recorder and a fresh Python process using the same mic at the same moment capture real audio. So the hardware is fine — only the long-running WhisperType process is affected.

**Root cause:** PortAudio (the C library under PyAudio) keeps WASAPI device handles cached at the process level. When the mic's USB power cycles (in this user's case, because the webcam mic is attached to a monitor that goes to sleep), the cached handle becomes stale. Even `pa.terminate() + pa.PyAudio()` cycles within the same process don't clear it — apparently the caching is below the PyAudio reference-count layer.

**Why subprocess works:** a fresh Python process means fresh PortAudio module-level state. No cache to be stale.

**Defence-in-depth stack (from most structural to most reactive):**

1. **`SubprocessAudioRecorder`** (`61c3dbc`) — The fix. Each recording in a fresh subprocess. Bug can't happen.
2. **Display-wake watchdog** (`7e22320`) — polls `GetLastInputInfo` every 10s, restarts when user returns from ≥10 min idle. Still useful if some other class of state-staleness appears.
3. **Long-idle watchdog** (`5c78229`) — 4h silent restart. Belt + suspenders.
4. **Silent-capture detection** (`777841b` + `2504af8`) — `_handle_silent_capture` logs + flashes red X + counts consecutive silents.
5. **Auto-restart on 2 consecutive silents** (`2504af8`) — last-resort recovery.
6. **Manual 'Restart WhisperType' tray item** — always available.

Layer 1 should catch 100% of cases; 2-6 remain as safety nets in case a different process-level state issue ever emerges.

---

## What might surprise you about the code

### 1. Single-file monolith, but consistent structure
~5,300 lines in one file is a deliberate choice — makes the app easier to package, distribute, and debug. Structure is:
1. Imports + config + logging
2. Utility functions (audio, hallucination, config, `find_python_interpreter`, `get_system_idle_seconds`)
3. Recorder classes (AudioRecorder, **SubprocessAudioRecorder**, LoopbackRecorder)
4. Transcriber classes (FasterWhisper, OpenVINO, Groq)
5. GroqLLMCleaner
6. Meeting mode
7. Paste helpers
8. Auto-start + history
9. OverlayNotification
10. Beep helpers
11. WhisperTypeApp (the main class, ~2,800 lines)

### 2. Generation counter for tray icon race
`self._recording_generation` is incremented on every `_start_recording()`. Background transcription threads capture the generation at start; the `finally` block only resets the icon to green if the generation is still current. Without this, a slow transcription from recording #1 could clobber the red icon of an in-progress recording #2.

### 3. Threading.Event-driven hotkey
`_hotkey_listener` doesn't block on `keyboard.wait()` anymore. Instead it waits on `self._hotkey_event`, which is set by a `keyboard.add_hotkey` callback. This lets the hotkey be swapped at runtime (for the "Change Hotkey..." dialog) without killing the listener thread.

### 4. Beep runs in a subprocess on specific-device mode
PortAudio can C-level crash on incompatible audio formats (see the Focusrite 22kHz-mono → 48kHz-stereo-only saga). So `play_beep(device_index=N)` spawns a `pythonw.exe -c "..."` subprocess that does the actual PyAudio work. A driver crash there doesn't kill the main app.

### 5. Three-layer cleanup injection defense
Because llama-3.3-70b is trained to be helpful, when the raw transcription sounds like an instruction ("I want to review the code..."), it wants to ANSWER instead of cleaning. Defenses:
1. System prompt explicitly says "you are NOT an AI assistant, you are a text-cleaning function"
2. User content wrapped in `<transcription>...</transcription>` tags
3. Hard cap: if output > 1.5× input, throw it away and use raw text

### 6. The `_do_paste` wrapper
Don't call `output_text(text, mode=...)` directly from new code. Use `self._do_paste(text, mode)` instead — it handles clipboard-before snapshotting, undo state recording, and auto-restore scheduling.

### 7. `SubprocessAudioRecorder.audio_data` is always empty
The real audio buffer lives in the subprocess. Anything that reads `self.recorder.audio_data` for live monitoring (`_streaming_worker`, `_waveform_updater`) gets an empty list and no-ops gracefully. That's OK because:
- streaming worker already skips for Groq backend
- waveform updater is hidden in silent_mode anyway
If a future feature genuinely needs live frames from the subprocess, consider upgrading to the "pre-spawned helper with stdin/stdout frame streaming" architecture — designed and considered in session 6 but deferred for simplicity.

### 8. The watchdogs are orthogonal layers, not a chain
Each watchdog fires independently based on its own trigger. They overlap intentionally:
- Idle-watchdog (4h) and display-wake watchdog (10min) both might fire on the same long idle — whichever hits first wins, the other's restart call becomes a no-op (process already exiting).
- Reactive silent-capture auto-restart only fires if the proactive ones missed. With SubprocessAudioRecorder as the structural fix, all watchdogs should now be **rarely used** — they're defense-in-depth, not hot-path.

---

## How to add a new feature

### Small feature (e.g. new option toggle)

1. Add default to `DEFAULT_CONFIG` dict (top of file)
2. Add tray menu item in `run()` where the menu is built
3. Add handler method on `WhisperTypeApp`
4. Call `save_config(self.config)` to persist
5. Add a test to `run_tests.py`

### New transcriber backend

1. Inherit from `BaseTranscriber`
2. Implement `load_model`, `transcribe`, `transcribe_file`
3. Wire into `WhisperTypeApp.__init__` based on a new config key
4. Add to `_set_backend` if switchable

### New tray icon state

1. Add case to `_create_icon()` method (state string → PIL drawing)
2. Call sites update tray icon: `self.tray_icon.icon = self._create_icon("newstate")`
3. Test in `run_tests.py` → `t_icons_all_states`

### New dialog

1. Create a `_open_X_dialog()` method that spawns a daemon thread running `tk.Tk()`. Don't share Tk roots across threads — this is why the overlay has its own dedicated Tk mainloop.
2. Reuse the catppuccin-dark colour scheme (`#1e1e2e` bg, `#cdd6f4` fg, `#313244` accents) for visual consistency
3. Add tray menu item that calls it

---

## Pre-push checklist

Before `git push`:

```bash
cd WhisperType
python -c "import ast; ast.parse(open('whispertype.py').read())"  # syntax
python run_tests.py  # 29 tests should all pass
```

For structural changes (class, menu, etc.):
- Manually test the happy path: start app → model loads → press hotkey → speak → release → paste → Ctrl+Alt+Z → clipboard should be restored.
- If you changed the tray menu, click every menu item and make sure nothing crashes.

---

## Potential next features (ranked by ROI)

From the session-5 discussion, not yet built:

1. **Auto-stop on silence** (~2-3 hr) — Stop recording after 2s of silence instead of requiring hotkey release. Hands-free dictation.
2. **Statistics dashboard** (~2 hr) — Show total words, time saved, languages used. Fun, low utility.
3. **Audio save + re-transcribe** (~half day) — Optionally save raw audio so a failed transcription can be re-tried with a different model. Now less needed — the silent-audio detection + WASAPI warmup cover most failure modes.
4. **Voice commands** (~1 day) — "new line", "period", etc. Low ROI when cleanup is good.
5. **Windows power-state API hook** (~half day) — Proper `PowerRegisterSuspendResumeNotification` integration. Would replace the current warmup heuristic with an event.
6. **Better streaming preview** (~day) — Live transcript window during recording (local backend only).

---

## Known limitations (unlikely to be issues)

1. **Python 3.13 removed `audioop`** — the beep subprocess uses byte slicing instead of `audioop.tomono`. Works, but if Python 3.14 removes `wave`, we'll need a replacement.
2. **`keyboard` library needs admin** — standard on Windows for global hotkeys. `run.bat` elevates. Non-admin shows a warning in the log.
3. **Single-instance via mutex** — duplicate launch returns code 0 (clean exit). User relaunching won't produce zombies.
4. **OpenVINO code is dormant** — still in the source, hidden from UI. Keep for future Intel GPU/NPU use or delete if it bitrots.
5. **File transcription skips AI cleanup** — intentional (long audio + token limits). If we want cleanup for files, need chunked cleanup like meeting mode does.

---

## Support / contact

- Author: Naor (naordaniel1@gmail.com)
- Repo: https://github.com/Danaor/WhisperType
- All session work by Claude (Anthropic Sonnet 4.6) — co-author on every commit.
