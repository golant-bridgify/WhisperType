# WhisperType 🎤

Personal speech-to-text for Windows. Lives in your system tray. Press a hotkey, talk, release — cleaned-up text pastes into whatever window you had focused.

Built as a SuperWhisper alternative for Windows, with Hebrew+English mixed-speech support, cloud+local transcription, AI-powered cleanup, custom vocabulary, meeting recording, and undo.

![icon](whispertype.ico)

---

## What it does

### The core flow (~1 second)
```
1. Press Ctrl+Space           →  Tray icon turns RED
2. Talk                       →  Mic (+ system audio) captured
3. Release                    →  Tray turns AMBER (transcribing)
4. Cleaned text pastes        →  Into your focused window
5. Tray turns GREEN again     →  Ready for the next one
```

### Beyond that
- **AI Cleanup** — Removes "um / יעני / בעצם", fixes punctuation + typos, corrects mis-heard homophones. 4 styles: Casual / Proofread / Email polish / Technical.
- **Custom Vocabulary** — Your personal term list (programming terms, product names, coworkers). Whisper gets biased toward these, so `"git push"` stops becoming `"בגד פושע"`.
- **Meeting Mode** — Start a continuous recording, talk for minutes or hours, click stop to get a markdown file with AI-generated summary, action items, and the full timestamped transcript.
- **Undo** — Ctrl+Alt+Z removes the last paste and restores your previous clipboard content.
- **Clipboard Preserve** — After a paste, your old clipboard content is automatically restored (~2s later). No more "I had something copied and dictation erased it."
- **Cloud or local** — Groq's LPU Whisper (fast, ~500ms) OR local `faster-whisper` on CPU (slower but free + offline).
- **Hebrew + English** — Auto-detect per transcription, RTL handling preserved.

---

## Installation

### Prerequisites
- Windows 10 or 11
- Python 3.11+ (checked "Add Python to PATH" during install)
- ~2GB disk space for the Whisper model
- (Optional) Free Groq API key from [console.groq.com/keys](https://console.groq.com/keys) — much faster than local

### Setup

```bash
git clone https://github.com/Danaor/WhisperType.git
cd WhisperType/WhisperType
pip install -r requirements.txt
```

**PyAudio install trouble?**
```bash
pip install pipwin
pipwin install pyaudio
```

### Run it

```bash
# Standard launch
python whispertype.py

# With admin (recommended — global hotkeys work more reliably)
run.bat
```

First run downloads the Whisper model (~1.6GB for the default turbo). Cached afterwards.

---

## Usage

| Action | How |
|--------|-----|
| **Record & transcribe** | Hold `Ctrl+Space`, talk, release |
| **Undo last paste** | `Ctrl+Alt+Z` |
| **Start meeting** | Right-click tray → `🎙  Start Meeting` |
| **Stop meeting** | Right-click tray → `⏹  Stop Meeting` |
| **Change hotkey** | Tray → Options → `Hotkey: ctrl+space...` |
| **Pick AI cleanup style** | Tray → Options → AI Cleanup (Groq) |
| **Edit custom vocabulary** | Tray → Options → Custom Vocabulary... |
| **View transcription history** | Tray → Options → History |
| **Switch model / cloud ↔ local** | Tray → Model |
| **Quit** | Tray → Quit |

### Recording modes
- **Hold mode (default):** hold the hotkey while speaking
- **Toggle mode:** press once to start, press again to stop — good for longer dictations

Switch between them via Tray → Options.

### Recording sources
- **Microphone only** — just your voice
- **System audio only** — whatever is playing (videos, calls, etc.) — uses WASAPI loopback
- **Both (default for meetings)** — your voice mixed with system audio

Pick from Tray → Audio Input. "System audio" is useful for meeting recording; "Microphone" is faster for normal dictation.

---

## The tray icon tells you everything

The icon colour is always the single source of truth about state — hover it for a text tooltip too.

| Colour | Icon | Meaning |
|--------|------|---------|
| 🟢 Green | Microphone | Ready to record |
| 🔴 Red | Microphone | Currently recording |
| 🟡 Amber | Sound bars | Transcribing / AI cleanup running |
| 🔵 Blue | Hourglass | Loading model (startup) |
| ❌ Dark red | X mark | Error (silent mic, clipboard busy, model fail) — flashes for ~3 seconds |
| 🟣 Purple | Red dot + bars | Meeting in progress |

---

## AI Cleanup styles

After every transcription, your text is (optionally) sent through a Groq LLM to clean up speech patterns. Styles:

| Style | What it does | When to use |
|---|---|---|
| **Off** | No LLM pass | When you want raw Whisper output |
| **Casual ⭐** (default) | Removes filler words, fixes typos/homophones, light grammar | Day-to-day dictation |
| **Proofread** | Aggressive — full spelling + grammar polish, fixes awkward phrasing | Emails, LinkedIn posts, docs |
| **Email polish** | Email-ready prose with paragraph breaks | Drafting emails |
| **Technical/Code** | Preserves code terms exactly (React, OAuth, async, Kubernetes) | Dictating technical notes |

**Anti-injection guards** (the LLM won't "help" you by expanding your request):
1. System prompt locks it into "text-cleaning function, not a chatbot"
2. Your input is wrapped in `<transcription>` tags — signals "this is DATA, not instructions to you"
3. If output exceeds 1.5× the input length, we throw it away and use the raw transcription

Cost per cleanup: ~$0.00005 on Groq. Latency: ~500-900ms added.

---

## Custom Vocabulary

Open Tray → Options → Custom Vocabulary..., paste your personal terms:

```
git, push, pull, commit, merge, branch, rebase, checkout,
React, Python, TypeScript, Kubernetes, OAuth, JWT, async, await,
Naor, Jabra, Focusrite, DJ
```

These are:
- Fed to Whisper as its recognition-bias prompt → `"git push"` no longer becomes `"בגד פושע"`
- Included in the AI Cleanup system prompt → any mis-transcriptions that still leak through get fixed

---

## Meeting Mode

Long-form continuous capture:

1. Tray → `🎙  Start Meeting (long recording)` — recording starts with "both" source (mic + system audio)
2. The icon turns 🟣 purple. The main Ctrl+Space hotkey is blocked while active (you don't need it — the meeting captures everything).
3. Talk / hold the meeting as long as you want. Audio is chunked every 45 seconds and transcribed in the background. Memory stays bounded regardless of meeting length.
4. Tray → `⏹  Stop Meeting`
5. Wait ~10-30 seconds for the final chunk + LLM summary
6. A markdown file opens automatically:

```markdown
# Meeting — 2026-04-17 14:43
*Duration: 42m 15s · 57 chunks · source: both*

## Summary
- Discussed Q3 roadmap — deadline is Oct 15
- OAuth integration needs review from security team
- ...

## Action Items
- [ ] Naor to prepare API docs by Friday
- [ ] Schedule security review for OAuth flow
- ...

---

## Full Transcript

### 0:00
[first 45 seconds of transcript]

### 0:45
[next chunk]

### 2:15
[etc...]
```

Saved to `%APPDATA%\WhisperType\meetings\`.

---

## Configuration

Settings file: `%APPDATA%\WhisperType\config.json`

You can edit it directly (restart the app to apply some changes — hotkey/vocab update live from their dialogs).

Key settings you might want to tweak:

```json
{
  "model_size": "large-v3-turbo",
  "hotkey": "ctrl+space",
  "cleanup_style": "casual",
  "custom_vocabulary": "git, push, Kubernetes, ...",
  "recording_source": "both",
  "transcription_backend": "groq",
  "silent_mode": false,
  "clipboard_auto_restore": true,
  "undo_hotkey": "ctrl+alt+z",
  "use_subprocess_mic": true,
  "auto_restart_idle_hours": 4,
  "auto_restart_on_wake_idle_min": 10
}
```

### Reliability knobs (Session 6 additions)

WhisperType runs each mic recording in an isolated Python subprocess by default (`use_subprocess_mic: true`). This is the primary fix for the "silent capture after long idle" problem some setups exhibit. Plus two watchdogs as defense-in-depth:

- `auto_restart_idle_hours: 4` — If the app has been running for 4+ hours without a recording, silently restart in the background. Set to `0` to disable.
- `auto_restart_on_wake_idle_min: 10` — If you return to the computer after ≥10 min of keyboard/mouse idle, WhisperType silently restarts to ensure fresh audio state. Particularly useful if your mic is powered through a monitor that sleeps. Set to `0` to disable.

---

## Models

| Model | Where | Speed | Accuracy | Hebrew |
|-------|-------|-------|----------|--------|
| `ivrit-ai/whisper-large-v3-turbo-ct2` ⭐ | Local (CPU) | ~3.5s/sec | Great | Excellent |
| `ivrit-ai/whisper-large-v3-ct2` | Local (CPU) | ~8s/sec | Best | Best |
| `distil-large-v3` ⭐ | Local (CPU) | ~2s/sec | Great | — |
| `large-v3-turbo` | Local or Groq | ~2s local / ~0.5s cloud | Great | Good |
| `whisper-large-v3` | Groq only | ~1s cloud | Best | Best |

Pick via Tray → Model. Use Groq if you've set an API key — it's 5-10× faster.

---

## Troubleshooting

**"Hotkey not working"**
- Run as Administrator. The `keyboard` library needs elevated privileges for global hotkeys. `run.bat` does this.

**"Model loading is slow"**
- First run downloads the model. Subsequent starts are ~3-5s.

**"Transcription gives 'Thank you' in Hebrew documents"**
- Whisper hallucinates "Thank you" / "תודה רבה" on silent audio. The app now detects this pattern and shows a red X in the tray instead of pasting. If you see the red X, check that your mic is active and try again.

**"`git push` gets transcribed as `בגד פושע`"**
- Add `git, push` to Custom Vocabulary (Tray → Options → Custom Vocabulary...).

**"I just tried transcribing after my laptop woke from sleep and got garbage"**
- Each recording now runs in an isolated Python subprocess with fresh PortAudio state (`use_subprocess_mic: true`), so this shouldn't happen. If it still does: three layers of safety follow — a display-wake watchdog that pre-emptively restarts the app on return from ≥10 min idle, a silent-audio detector that flashes a red tray icon instead of pasting garbage, and an auto-restart if two consecutive recordings come back silent. Worst case: Tray → Options → `🔄 Restart WhisperType`.

**"My clipboard got overwritten"**
- Not anymore — `clipboard_auto_restore` is on by default. Your previous clipboard content is restored ~2s after the paste.

**"I pasted something wrong and want to undo it"**
- Press `Ctrl+Alt+Z` within 60s of the paste. It sends Ctrl+Z to remove the paste AND restores your previous clipboard.

**"Hebrew pasting direction is weird"**
- Whisper-transcribed Hebrew text has a U+200F RTL marker prepended. If a specific app ignores it, try changing the paste mode to "Clipboard Only" and paste manually.

---

## Running tests

```bash
cd WhisperType
python run_tests.py
```

29 tests covering config, history, hallucination stripping, transcriber construction, live Groq calls, meeting output, undo/paste state, hotkey validation, icon rendering.

Section 6 (live Groq tests) requires a valid API key in config.json.

---

## Credits

- OpenAI Whisper — the model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CPU-optimised inference
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) — WASAPI loopback
- [Groq](https://groq.com) — cloud inference + llama-3.3-70b for cleanup
- [ivrit-ai](https://github.com/ivrit-ai) — Hebrew-optimised Whisper models

## License

MIT — see [LICENSE](../LICENSE)
