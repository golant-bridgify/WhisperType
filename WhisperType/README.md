# WhisperType 🎤

A local, free alternative to SuperWhisper. Runs entirely on your PC — no cloud, no subscription.

## Features

- **100% Local** — Whisper AI runs on your CPU, nothing leaves your machine
- **Hold-to-Record** — Hold `Ctrl+Shift+Space`, speak, release to transcribe
- **Auto-Paste** — Transcribed text is automatically pasted wherever your cursor is
- **Hebrew + English** — Full support with auto language detection
- **System Tray** — Runs quietly in the background
- **Model Selection** — Choose between speed and accuracy

## Installation

### Step 1: Install Python
Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
> ⚠️ During install, check **"Add Python to PATH"**

### Step 2: Install dependencies

Open a terminal (PowerShell or CMD) in the WhisperType folder and run:

```bash
pip install -r requirements.txt
```

**Note about PyAudio:** If `pip install pyaudio` fails, install it manually:
```bash
pip install pipwin
pipwin install pyaudio
```
Or download the `.whl` file from [here](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio).

### Step 3: Run WhisperType

```bash
python whispertype.py
```

On first run, it will **download the Whisper model** (~1.5GB for medium). This only happens once.

## Usage

| Action | How |
|--------|-----|
| **Record** | Hold `Ctrl + Shift + Space` |
| **Stop & Transcribe** | Release the keys |
| **Change Language** | Right-click tray icon → Language |
| **Change Model** | Right-click tray icon → Model |
| **Quit** | Right-click tray icon → Quit |

### Sound Feedback
- **Low beep** — Recording started
- **High beep** — Text pasted

## Models

| Model | Size | Speed* | Accuracy | Hebrew |
|-------|------|--------|----------|--------|
| `small` | ~460 MB | ~2s | Good | OK |
| `medium` | ~1.5 GB | ~4s | Great | Good |
| `large-v3` | ~3 GB | ~8s | Best | Best |
| `large-v3-turbo` | ~1.6 GB | ~5s | Near-best | Great |

*Speed = approximate transcription time for 10 seconds of audio on Intel 265K CPU

**Recommendation:** Start with `medium`. If Hebrew accuracy isn't enough, switch to `large-v3-turbo`.

## Configuration

Settings are saved in `%APPDATA%\WhisperType\config.json`. You can edit it directly:

```json
{
  "model_size": "medium",
  "language": "auto",
  "hotkey": "ctrl+shift+space",
  "beam_size": 5,
  "cpu_threads": 8,
  "auto_paste": true,
  "play_sound": true
}
```

### Tips for your Intel 265K:
- Set `cpu_threads` to `8` or `12` for best performance (don't set it to all cores, diminishing returns)
- `int8` compute type is already set for fastest CPU inference
- With 96GB RAM, you can run any model size without issues

## Start with Windows (Optional)

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to `whispertype.py` in that folder
3. Or create a `.bat` file:
   ```bat
   @echo off
   cd /d "C:\path\to\whispertype"
   pythonw whispertype.py
   ```

## Packaging as .exe (Optional)

To create a standalone executable:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name WhisperType --icon=icon.ico whispertype.py
```

The `.exe` will be in the `dist` folder.

## Troubleshooting

**"Model loading is slow"**
First run downloads the model. Subsequent runs load from cache (~10-20 seconds for medium on CPU).

**"PyAudio won't install"**
Try: `pip install pipwin && pipwin install pyaudio`

**"Hotkey not working"**
Run as Administrator — the `keyboard` library needs elevated permissions for global hotkeys.

**"Hebrew transcription is poor"**
Switch to `large-v3` model via the tray menu. Also try setting language to `he` instead of `auto`.

**"Transcription is too slow"**
Switch to `small` model, or reduce `beam_size` to 3 in config.json.
