# WhisperType

> **Push-to-talk speech-to-text for Windows. Local or cloud, Hebrew-first, zero friction.**

Hold a hotkey, speak, release — your words appear wherever your cursor is. Works fully offline with local Whisper, or lightning-fast via Groq Cloud. No subscription, no telemetry, no catch.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Whisper](https://img.shields.io/badge/AI-OpenAI%20Whisper-10a37f.svg)](https://github.com/openai/whisper)

---

## Why WhisperType?

Most dictation tools are either expensive subscriptions (SuperWhisper, Wispr Flow), cloud-locked (Otter, Rev), or mediocre at Hebrew. WhisperType is different:

- **Local-first.** Runs on your CPU with `faster-whisper`. Your audio never leaves the machine unless you want it to.
- **Hebrew that actually works.** Uses the excellent [ivrit-ai](https://huggingface.co/ivrit-ai) fine-tuned models alongside OpenAI's Whisper.
- **Cloud option for speed.** Plug in a [Groq API key](https://console.groq.com/keys) and get ~0.5s transcription for a sentence instead of 3.5s locally.
- **Auto-fallback.** If Groq fails (network down, rate-limited), it automatically falls back to local — zero manual switching.
- **Free & open source.** MIT licensed. No accounts, no tracking, no payment wall.

## Features

| | |
|---|---|
| **Push-to-talk** | Hold `Ctrl+Alt+Space` to record, release to transcribe and paste |
| **Toggle mode** | Or click once to start, click again to stop |
| **Local transcription** | `faster-whisper` on CPU (int8 quantized for speed) |
| **Cloud transcription** | Optional Groq Cloud backend — 5–10x faster |
| **Auto-fallback** | Network fails → automatically uses local backend |
| **Hebrew-optimized** | ivrit-ai models for natural Hebrew output |
| **English-optimized** | Distil-Whisper for fast English |
| **Translate to English** | Speak any language → get English output |
| **System audio capture** | Transcribe what's playing (Teams calls, YouTube, etc.) via WASAPI loopback |
| **Mic + System mix** | Record both at once (for meeting notes where both sides matter) |
| **Transcription history** | Searchable, click-to-copy, dark themed |
| **Auto-paste** | Text appears wherever your cursor is (like native dictation) |
| **File transcription** | Right-click any audio file → transcribe to `.txt` |
| **Runs in system tray** | Minimal UI, stays out of the way |
| **Start with Windows** | One-click auto-start toggle |
| **Real-time waveform** | Visual feedback while you speak |

## Demo

> *Insert GIF/video here — recommended: 30s clip showing hotkey → speaking → text appearing in Notepad.*

## Quick Start

### Option 1 — Run from source (Python)

```bash
git clone https://github.com/Danaor/WhisperType.git
cd WhisperType/WhisperType
pip install -r requirements.txt
python whispertype.py
```

On first run, the Hebrew Turbo model (~1.6 GB) downloads automatically.

### Option 2 — Standalone .exe

```bash
cd WhisperType
python build.py
# Output: WhisperType/dist/WhisperType.exe (~360 MB)
```

### Using Groq Cloud (optional, much faster)

1. Get a free API key at [console.groq.com/keys](https://console.groq.com/keys).
2. Right-click the tray icon → **Recording Options** → **Set Groq API Key...**
3. Paste the key → **Save & Verify**.
4. In the **Model** menu, pick **Groq Turbo**.

## Usage

| Action | How |
|---|---|
| **Record** | Hold `Ctrl + Alt + Space` (or configure any hotkey in `config.json`) |
| **Stop & paste** | Release the key |
| **Switch model** | Tray icon → Model |
| **Switch source** | Tray icon → Recording Source (mic / system audio / both) |
| **Translate to English** | Tray icon → Translate to English (toggle) |
| **View history** | Tray icon → Recording Options → History |
| **Transcribe a file** | Tray icon → Recording Options → Transcribe File |

## Models

### Local (via `faster-whisper`)

| Menu Name | Model ID | Language | Quality | Speed on CPU |
|---|---|---|---|---|
| **Hebrew Turbo** | `ivrit-ai/whisper-large-v3-turbo-ct2` | Hebrew | Great | ~3.5s / 10s audio |
| **English Distil** | `distil-large-v3` | English | Near-best | ~2s / 10s audio |
| **General Turbo** | `large-v3-turbo` | Auto-detect | Great | ~3.5s / 10s audio |

### Cloud (via Groq)

| Menu Name | Model | Speed |
|---|---|---|
| **Groq Turbo** | `whisper-large-v3-turbo` | ~0.5s / 10s audio |
| *(translation mode)* | `whisper-large-v3` | Auto-switches when Translate is on |

## Requirements

- **OS**: Windows 10/11 (uses WASAPI for system audio)
- **Python**: 3.11+ (if running from source)
- **RAM**: 4 GB minimum, 8 GB recommended
- **CPU**: Any modern x86_64; an Intel Core Ultra / Ryzen 7+ runs Hebrew Turbo comfortably
- **Disk**: ~2 GB for local models (first download), ~400 MB for standalone .exe
- **Internet**: Only for initial model download and optional Groq Cloud mode

No NVIDIA GPU required. No AVX-512 required. No internet required (after first-run model download).

## Configuration

Settings live in `%APPDATA%\WhisperType\config.json`. Most options are controlled via the tray menu, but you can edit the file directly.

```json
{
  "model_size": "ivrit-ai/whisper-large-v3-turbo-ct2",
  "hotkey": "ctrl+alt+space",
  "beam_size": 3,
  "paste_mode": "auto_paste",
  "play_sound": true,
  "cpu_threads": 16,
  "recording_mode": "hold",
  "recording_source": "microphone",
  "translate_mode": false,
  "transcription_backend": "local",
  "groq_model": "whisper-large-v3-turbo",
  "auto_start": false
}
```

## Architecture

Single-file Python app (`whispertype.py`, ~2400 lines), organized around these building blocks:

- **`FasterWhisperTranscriber`** — local CPU transcription via `faster-whisper` / CTranslate2
- **`GroqTranscriber`** — cloud transcription via Groq's OpenAI-compatible API
- **`AudioRecorder`** / **`LoopbackRecorder`** — PyAudio mic + PyAudioWPatch WASAPI system audio
- **`OverlayNotification`** — Tkinter floating status window with real-time waveform
- **`WhisperTypeApp`** — tray icon orchestration + hotkey listener + streaming worker

Audio is captured at 16 kHz mono int16, resampled if needed, VAD-filtered before transcription, and subject to a hallucination filter that strips Whisper's classic "thank you" / "תודה רבה" end-of-clip artifacts.

## Comparison

| | WhisperType | SuperWhisper | Wispr Flow | Windows Dictation |
|---|---|---|---|---|
| Price | Free | $8/mo | $15/mo | Free |
| Local (no cloud) | ✅ | ✅ | ❌ | ❌ |
| Cloud option | ✅ (Groq) | ❌ | ✅ | ❌ |
| Hebrew | ✅ Excellent | ⚠️ OK | ⚠️ OK | ❌ Poor |
| System audio capture | ✅ | ❌ | ❌ | ❌ |
| Open source | ✅ MIT | ❌ | ❌ | ❌ |
| Windows native | ✅ | macOS only | ✅ | ✅ |

## Roadmap

- [ ] macOS + Linux support (pystray already works on Linux; mic/loopback need work)
- [ ] Custom hotkey picker UI (currently requires editing config.json)
- [ ] Voice commands (e.g. "new line", "period")
- [ ] Streaming partial results typed in real-time
- [ ] OpenAI Whisper API as a second cloud backend option

## Contributing

PRs and issues welcome! Areas I'd love help on:
- macOS / Linux ports
- Better UI for settings (currently tray menu only)
- Additional Whisper-compatible cloud backends
- Benchmarks on different hardware

## License

MIT — do whatever you want, attribution appreciated.

## Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) — the model that makes this possible
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — fast CPU inference via CTranslate2
- [ivrit-ai](https://huggingface.co/ivrit-ai) — Hebrew-fine-tuned Whisper models
- [Groq](https://groq.com) — blazing-fast Whisper inference on LPUs
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) — WASAPI loopback recording

---

*Built because I wanted SuperWhisper on Windows with good Hebrew support and no subscription. Turns out the ingredients were all open source — they just needed gluing together.*
