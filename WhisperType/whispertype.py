"""
WhisperType - Local Speech-to-Text for Windows
A SuperWhisper alternative that runs entirely on your PC.

Usage:
    Hold Ctrl+Shift+Space to record, release to transcribe and paste.
    Right-click the system tray icon for settings.
"""

import sys
import os
import json
import threading
import time
import wave
import tempfile
import io
import queue
import logging
import numpy as np

# --- Logging (replaces print, no console window needed) ---
LOG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WhisperType")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "whispertype.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("WhisperType")

# Hide console window on Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

# --- Configuration ---
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WhisperType")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "model_size": "ivrit-ai/whisper-large-v3-turbo-ct2",
    "language": "auto",  # "auto", "he", "en", etc.
    "hotkey": "ctrl+space",
    "beam_size": 3,
    "start_minimized": True,
    "paste_mode": "auto_paste",  # "clipboard_only", "auto_paste", "direct_type"
    "play_sound": True,
    "cpu_threads": 16,
    "input_device_index": None,  # None = default system microphone
    "recording_mode": "hold",  # "hold" = hold-to-record, "toggle" = press-to-start/press-to-stop
    "recording_source": "microphone",  # "microphone", "stereo_mix", "both"
    "engine": "faster_whisper",  # "faster_whisper" or "openvino"
    "openvino_device": "GPU",  # "CPU", "GPU", "NPU"
    "streaming_mode": "preview",  # "off", "preview" (overlay only), "live_dictation" (types in real-time)
}


def list_input_devices():
    """Return a list of (index, name) tuples for available input devices.

    Filters to a single host API (the default one on Windows, typically MME)
    to avoid the same physical device appearing multiple times.
    Further deduplicates by name as a safety net.
    """
    devices = []
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            # Prefer the default host API so each device appears only once
            try:
                default_host_api = pa.get_default_host_api_info().get("index")
            except Exception:
                default_host_api = None

            seen_names = set()
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if int(info.get("maxInputChannels", 0)) <= 0:
                    continue
                # Filter by default host API when available
                if default_host_api is not None and info.get("hostApi") != default_host_api:
                    continue
                name = str(info.get("name", f"Device {i}")).strip()
                # Skip generic/virtual aggregators that aren't real devices
                if name.lower() in ("microsoft sound mapper - input", "primary sound capture driver"):
                    continue
                # Deduplicate by name
                if name in seen_names:
                    continue
                seen_names.add(name)
                devices.append((i, name))
        finally:
            pa.terminate()
    except Exception as e:
        log.error("Failed to list input devices: %s", e)
    return devices


def resample_audio(audio, orig_rate, target_rate):
    """Resample audio from orig_rate to target_rate using linear interpolation."""
    if orig_rate == target_rate or len(audio) == 0:
        return audio
    target_len = int(len(audio) * target_rate / orig_rate)
    return np.interp(
        np.linspace(0, len(audio) - 1, target_len),
        np.arange(len(audio)),
        audio,
    ).astype(np.float32)


def mix_audio(audio1, audio2):
    """Mix two audio arrays together, normalizing to prevent clipping."""
    if len(audio1) == 0:
        return audio2
    if len(audio2) == 0:
        return audio1

    # Pad the shorter array
    max_len = max(len(audio1), len(audio2))
    if len(audio1) < max_len:
        audio1 = np.pad(audio1, (0, max_len - len(audio1)))
    if len(audio2) < max_len:
        audio2 = np.pad(audio2, (0, max_len - len(audio2)))

    mixed = audio1 + audio2
    max_val = np.max(np.abs(mixed))
    if max_val > 1.0:
        mixed = mixed / max_val
    return mixed


# Available models with display names
MODELS = {
    # Hebrew-optimized (ivrit.ai) - recommended
    "ivrit-ai/whisper-large-v3-turbo-ct2": "Hebrew Turbo ⭐ (fast + accurate)",
    "ivrit-ai/whisper-large-v3-ct2": "Hebrew Large (best Hebrew)",
    # English-optimized
    "distil-large-v3": "English Distil ⭐ (fast + accurate)",
    # General OpenAI models
    "small": "General Small (fastest)",
    "medium": "General Medium (balanced)",
    "large-v3": "General Large-v3 (best general)",
    "large-v3-turbo": "General Large-v3 Turbo",
}


def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Merge with defaults for any new keys
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            # Migrate old auto_paste boolean to new paste_mode
            if "auto_paste" in cfg and "paste_mode" not in cfg:
                cfg["paste_mode"] = "auto_paste" if cfg["auto_paste"] else "clipboard_only"
            return cfg
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ============================================================
# Audio Recorder
# ============================================================
class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1, input_device_index=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_device_index = input_device_index
        self.is_recording = False
        self.audio_data = []
        self._stream = None
        self._pa = None

    def start(self):
        import pyaudio
        self.audio_data = []
        self.is_recording = True
        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.input_device_index,
                frames_per_buffer=1024,
                stream_callback=self._callback,
            )
        except Exception as e:
            log.error("Failed to open input device %s: %s. Falling back to default.",
                      self.input_device_index, e)
            # Fall back to default device
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=1024,
                stream_callback=self._callback,
            )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudio
        if self.is_recording:
            self.audio_data.append(in_data)
        return (None, pyaudio.paContinue)

    def stop(self) -> np.ndarray:
        self.is_recording = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

        if not self.audio_data:
            return np.array([], dtype=np.float32)

        raw = b"".join(self.audio_data)
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return audio_np


# ============================================================
# WASAPI Loopback Recorder (System Audio)
# ============================================================
class LoopbackRecorder:
    """Record system audio via WASAPI loopback (captures Teams, Zoom, etc.)."""

    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self._stream = None
        self._pa = None
        self._device_info = None
        self._native_rate = None
        self._channels = 1

    @staticmethod
    def is_available():
        """Check if pyaudiowpatch is installed."""
        try:
            import pyaudiowpatch  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def find_loopback_device():
        """Find the WASAPI loopback device for the default output (speakers/headphones).

        Returns a device info dict or None.
        """
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            try:
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = pa.get_device_info_by_index(
                    wasapi_info["defaultOutputDevice"]
                )

                # If the default output already is a loopback device, use it
                if default_speakers.get("isLoopbackDevice"):
                    return default_speakers

                # Otherwise, find the loopback counterpart
                for loopback in pa.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        return loopback
            finally:
                pa.terminate()
        except Exception as e:
            log.error("Failed to find WASAPI loopback device: %s", e)
        return None

    def start(self):
        import pyaudiowpatch as pyaudio

        self.audio_data = []
        self.is_recording = True
        self._pa = pyaudio.PyAudio()

        device = self.find_loopback_device()
        if device is None:
            raise RuntimeError("No WASAPI loopback device found")

        self._device_info = device
        self._native_rate = int(device["defaultSampleRate"])
        self._channels = int(device["maxInputChannels"])

        log.info("Loopback: opening '%s' at %d Hz, %d ch",
                 device.get("name", "?"), self._native_rate, self._channels)

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._native_rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio
        if self.is_recording:
            self.audio_data.append(in_data)
        return (None, pyaudio.paContinue)

    def stop(self) -> np.ndarray:
        self.is_recording = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

        if not self.audio_data:
            return np.array([], dtype=np.float32)

        raw = b"".join(self.audio_data)
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        # Convert multi-channel to mono by averaging
        if self._channels > 1:
            audio_np = audio_np.reshape(-1, self._channels).mean(axis=1)

        # Resample from native rate (e.g. 48000) to 16000 for Whisper
        if self._native_rate and self._native_rate != 16000:
            audio_np = resample_audio(audio_np, self._native_rate, 16000)

        return audio_np


# ============================================================
# Base Transcriber Interface
# ============================================================
class BaseTranscriber:
    """Interface for speech-to-text transcription backends."""

    def __init__(self, model_size="medium", cpu_threads=8):
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.model = None
        self._loading = False

    def load_model(self, callback=None):
        raise NotImplementedError

    def transcribe(self, audio_np, language=None, beam_size=3):
        raise NotImplementedError

    def transcribe_file(self, file_path, language=None):
        raise NotImplementedError


# ============================================================
# Faster-Whisper Transcriber (CPU, default)
# ============================================================
class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(self, model_size="medium", cpu_threads=8):
        super().__init__(model_size, cpu_threads)
        self._batched_model = None  # Lazy-initialized for fast file transcription

    def load_model(self, callback=None):
        """Load the model (can take a while on first run as it downloads)."""
        self._loading = True
        try:
            from faster_whisper import WhisperModel
            if callback:
                callback(f"Loading Whisper '{self.model_size}' model...")
            self.model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",  # Fastest on CPU
                cpu_threads=self.cpu_threads,
            )
            if callback:
                callback("Model loaded!")
        except Exception as e:
            if callback:
                callback(f"Error loading model: {e}")
            raise
        finally:
            self._loading = False

    def transcribe(self, audio_np, language=None, beam_size=5):
        if self.model is None:
            raise RuntimeError("Model not loaded")
        if len(audio_np) == 0:
            return ""

        lang = language if language and language != "auto" else None
        segments, info = self.model.transcribe(
            audio_np,
            beam_size=beam_size,
            language=lang,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )
        seg_list = [seg.text.strip() for seg in segments if seg.text.strip()]
        if not seg_list:
            return ""

        text = " ".join(seg_list)

        # Detect if the text is primarily RTL (Hebrew/Arabic)
        detected_lang = info.language if info else lang
        rtl_langs = {"he", "ar", "fa", "ur", "yi"}
        is_rtl = detected_lang in rtl_langs if detected_lang else any(
            '\u0590' <= c <= '\u05FF' or  # Hebrew
            '\u0600' <= c <= '\u06FF' or  # Arabic
            '\uFB1D' <= c <= '\uFDFF' or  # Hebrew/Arabic presentation forms
            '\uFE70' <= c <= '\uFEFF'     # Arabic presentation forms
            for c in text
        )

        if is_rtl:
            # Add RTL mark so Windows pastes in correct direction
            text = '\u200F' + text

        return text.strip()

    def transcribe_file(self, file_path, language=None):
        """Transcribe an audio/video file fast.

        Uses BatchedInferencePipeline + aggressive speed settings:
        - beam_size=1 (greedy decoding)
        - condition_on_previous_text=False (prevents error propagation + faster)
        - Larger VAD silence threshold
        - Batched inference when available
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")

        lang = language if language and language != "auto" else None

        # Lazy-initialize the batched pipeline (shares weights with self.model)
        if self._batched_model is None:
            try:
                from faster_whisper import BatchedInferencePipeline
                self._batched_model = BatchedInferencePipeline(model=self.model)
                log.info("BatchedInferencePipeline initialized for fast file transcription")
            except Exception as e:
                log.warning("BatchedInferencePipeline unavailable (%s), falling back to standard model", e)
                self._batched_model = False  # sentinel: tried and failed

        common_kwargs = dict(
            beam_size=1,
            language=lang,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=1000,
            ),
        )

        if self._batched_model:
            segments, info = self._batched_model.transcribe(
                file_path,
                batch_size=16,
                **common_kwargs,
            )
        else:
            segments, info = self.model.transcribe(
                file_path,
                **common_kwargs,
            )

        seg_list = [seg.text.strip() for seg in segments if seg.text.strip()]
        if not seg_list:
            return ""

        text = "\n".join(seg_list)
        return text


# Backward compatibility alias
WhisperTranscriber = FasterWhisperTranscriber


# ============================================================
# OpenVINO Transcriber (Intel GPU/NPU acceleration)
# ============================================================
OPENVINO_MODELS = {
    "OpenVINO/whisper-large-v3-int8-ov": "OV Large-v3 INT8 (Intel GPU/NPU)",
    "OpenVINO/whisper-large-v3-fp16-ov": "OV Large-v3 FP16 (Intel GPU)",
}


class OpenVINOTranscriber(BaseTranscriber):
    """Transcription backend using OpenVINO GenAI for Intel GPU/NPU acceleration."""

    def __init__(self, model_size="OpenVINO/whisper-large-v3-int8-ov",
                 cpu_threads=8, device="GPU"):
        super().__init__(model_size, cpu_threads)
        self.device = device  # "CPU", "GPU", or "NPU"

    @staticmethod
    def is_available():
        """Check if openvino-genai is installed."""
        try:
            import openvino_genai  # noqa: F401
            return True
        except ImportError:
            return False

    def load_model(self, callback=None):
        self._loading = True
        try:
            import openvino_genai as ov_genai

            if callback:
                callback(f"Loading OpenVINO model '{self.model_size}' on {self.device}...")

            model_path = self._resolve_model_path()
            self.model = ov_genai.WhisperPipeline(model_path, self.device)

            if callback:
                callback("OpenVINO model loaded!")
        except Exception as e:
            if callback:
                callback(f"Error loading OpenVINO model: {e}")
            raise
        finally:
            self._loading = False

    def _resolve_model_path(self):
        """Download/locate the OpenVINO model directory from HuggingFace."""
        from huggingface_hub import snapshot_download
        local_dir = snapshot_download(self.model_size)
        return local_dir

    def transcribe(self, audio_np, language=None, beam_size=3):
        if self.model is None:
            raise RuntimeError("Model not loaded")
        if len(audio_np) == 0:
            return ""

        import openvino_genai as ov_genai

        config = self.model.get_generation_config()
        config.max_new_tokens = 448

        if language and language != "auto":
            config.language = f"<|{language}|>"

        # openvino-genai expects raw float32 samples at 16kHz
        result = self.model.generate(audio_np, config)
        text = str(result).strip()
        if not text:
            return ""

        # RTL detection (same logic as FasterWhisperTranscriber)
        rtl_langs = {"he", "ar", "fa", "ur", "yi"}
        is_rtl = language in rtl_langs if language and language != "auto" else any(
            '\u0590' <= c <= '\u05FF' or
            '\u0600' <= c <= '\u06FF' or
            '\uFB1D' <= c <= '\uFDFF' or
            '\uFE70' <= c <= '\uFEFF'
            for c in text
        )
        if is_rtl:
            text = '\u200F' + text

        return text.strip()

    def transcribe_file(self, file_path, language=None):
        """Transcribe a file using OpenVINO."""
        if self.model is None:
            raise RuntimeError("Model not loaded")

        try:
            from faster_whisper.audio import decode_audio
            audio_np = decode_audio(file_path, sampling_rate=16000)
        except ImportError:
            import subprocess
            cmd = [
                "ffmpeg", "-i", file_path,
                "-ar", "16000", "-ac", "1", "-f", "f32le", "-"
            ]
            proc = subprocess.run(cmd, capture_output=True, check=True)
            audio_np = np.frombuffer(proc.stdout, dtype=np.float32)

        return self.transcribe(audio_np, language=language, beam_size=1)


# ============================================================
# Text Paster - types text into active window
# ============================================================
def clipboard_paste(text):
    """Paste text via clipboard using keyboard library (avoids conflicts with pyautogui)."""
    import pyperclip
    import keyboard as kb
    pyperclip.copy(text)
    time.sleep(0.05)
    kb.send('ctrl+v')
    time.sleep(0.05)


def output_text(text, mode="auto_paste"):
    """Output transcribed text based on the selected mode."""
    import pyperclip

    if mode == "clipboard_only":
        # Just copy to clipboard, don't paste
        pyperclip.copy(text)
        log.info("Copied to clipboard")

    elif mode == "direct_type":
        # Also copy to clipboard as backup, then type directly
        pyperclip.copy(text)
        import keyboard
        time.sleep(0.05)
        keyboard.write(text, delay=0.01)
        log.info("Typed directly")

    else:  # "auto_paste" (default)
        # Copy to clipboard and simulate Ctrl+V
        import pyautogui
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        log.info("Pasted via Ctrl+V")


# ============================================================
# Visual Overlay Notification
# ============================================================
class OverlayNotification:
    """A floating overlay window for visual feedback and waveform visualization."""

    NUM_BARS = 30
    BAR_WIDTH = 4
    BAR_GAP = 2
    CANVAS_HEIGHT = 36

    def __init__(self):
        self._root = None
        self._label = None
        self._canvas = None
        self._bars = []
        self._waveform_mode = False
        self._visible = False
        self._tk_queue = queue.Queue()
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        # Wait for tk to be ready
        time.sleep(0.3)

    def _run_tk(self):
        """Run the tkinter mainloop in its own thread."""
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.attributes('-topmost', True)
        self._root.attributes('-alpha', 0.85)
        self._root.configure(bg='#1a1a2e')

        self._label = tk.Label(
            self._root,
            text="",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg="#1a1a2e",
            padx=20,
            pady=10,
        )
        self._label.pack()

        # Canvas for waveform visualization
        canvas_w = self.NUM_BARS * (self.BAR_WIDTH + self.BAR_GAP) + 20
        self._canvas = tk.Canvas(
            self._root,
            width=canvas_w,
            height=self.CANVAS_HEIGHT,
            bg='#1a1a2e',
            highlightthickness=0,
        )
        # Pre-create bar rectangles
        cy = self.CANVAS_HEIGHT // 2
        for i in range(self.NUM_BARS):
            x = i * (self.BAR_WIDTH + self.BAR_GAP) + 10
            bar = self._canvas.create_rectangle(
                x, cy - 1, x + self.BAR_WIDTH, cy + 1,
                fill='#4ade80', outline='',
            )
            self._bars.append(bar)

        self._check_queue()
        self._root.mainloop()

    def _check_queue(self):
        """Process pending commands from other threads."""
        try:
            while not self._tk_queue.empty():
                cmd = self._tk_queue.get_nowait()
                cmd()
        except Exception:
            pass
        if self._root:
            self._root.after(50, self._check_queue)

    def show(self, text, bg_color="#e63946", fg_color="white", duration=0):
        """Show the overlay. duration=0 means stay until hidden."""
        def _do():
            if not self._root or not self._label:
                return
            self._label.config(text=text, bg=bg_color, fg=fg_color)
            self._root.configure(bg=bg_color)

            # Update size and center at top of screen
            self._root.update_idletasks()
            w = self._label.winfo_reqwidth() + 10
            h = self._label.winfo_reqheight() + 6
            screen_w = self._root.winfo_screenwidth()
            x = (screen_w - w) // 2
            y = 18
            self._root.geometry(f"{w}x{h}+{x}+{y}")
            self._root.deiconify()
            self._root.attributes('-alpha', 0.9)
            self._visible = True

            if duration > 0:
                self._root.after(duration, self._fade_out)

        self._tk_queue.put(_do)

    def hide(self):
        """Hide the overlay."""
        def _do():
            if self._root:
                self._root.withdraw()
                self._visible = False
        self._tk_queue.put(_do)

    def _fade_out(self):
        """Gradually fade out the overlay."""
        if not self._root or not self._visible:
            return
        try:
            current = self._root.attributes('-alpha')
            if current > 0.1:
                self._root.attributes('-alpha', current - 0.15)
                self._root.after(40, self._fade_out)
            else:
                self._root.withdraw()
                self._visible = False
        except Exception:
            pass

    def show_waveform(self):
        """Switch overlay to waveform visualization mode."""
        def _do():
            if not self._root or not self._canvas:
                return
            self._label.pack_forget()
            self._canvas.pack(padx=10, pady=4)
            self._waveform_mode = True
            self._root.configure(bg='#1a1a2e')

            # Size and position
            canvas_w = self.NUM_BARS * (self.BAR_WIDTH + self.BAR_GAP) + 40
            w = canvas_w
            h = self.CANVAS_HEIGHT + 8
            screen_w = self._root.winfo_screenwidth()
            x = (screen_w - w) // 2
            self._root.geometry(f"{w}x{h}+{x}+18")
            self._root.deiconify()
            self._root.attributes('-alpha', 0.92)
            self._visible = True
        self._tk_queue.put(_do)

    def update_waveform(self, levels):
        """Update bar heights. levels: list of floats 0.0-1.0."""
        def _do():
            if not self._canvas or not self._waveform_mode:
                return
            cy = self.CANVAS_HEIGHT // 2
            for i, bar in enumerate(self._bars):
                if i < len(levels):
                    h = max(1, int(levels[i] * (self.CANVAS_HEIGHT // 2 - 2)))
                    x = i * (self.BAR_WIDTH + self.BAR_GAP) + 10
                    self._canvas.coords(bar, x, cy - h, x + self.BAR_WIDTH, cy + h)
                    # Color gradient: green → yellow → red
                    lv = levels[i]
                    if lv > 0.7:
                        color = '#ef4444'
                    elif lv > 0.4:
                        color = '#fbbf24'
                    else:
                        color = '#4ade80'
                    self._canvas.itemconfig(bar, fill=color)
        self._tk_queue.put(_do)

    def hide_waveform(self):
        """Switch back from waveform to label mode."""
        def _do():
            if not self._root:
                return
            self._waveform_mode = False
            if self._canvas:
                self._canvas.pack_forget()
            if self._label:
                self._label.pack()
        self._tk_queue.put(_do)

    def show_recording(self):
        self.show_waveform()

    def show_processing(self):
        self.hide_waveform()
        self.show("  ⏳  Transcribing...  ", bg_color="#f77f00")

    def show_done(self, char_count=0):
        self.hide_waveform()
        msg = f"  ✅  Done! ({char_count} chars)  " if char_count else "  ✅  Done!  "
        self.show(msg, bg_color="#2d6a4f", duration=1500)

    def show_error(self, msg="Error"):
        self.show(f"  ❌  {msg}  ", bg_color="#6b0f1a", duration=2000)


# ============================================================
# Sound Effects
# ============================================================
def play_beep(freq=800, duration_ms=150):
    """Play a short beep sound."""
    try:
        import winsound
        winsound.Beep(freq, duration_ms)
    except Exception:
        pass


# ============================================================
# System Tray Application
# ============================================================
class WhisperTypeApp:
    def __init__(self):
        self.config = load_config()
        self.recorder = AudioRecorder(
            input_device_index=self.config.get("input_device_index"),
        )
        # Loopback recorder for system audio (WASAPI loopback)
        if LoopbackRecorder.is_available():
            loopback_info = LoopbackRecorder.find_loopback_device()
            if loopback_info:
                self._loopback_recorder = LoopbackRecorder()
                self._loopback_device_name = loopback_info.get("name", "System Audio")
                log.info("WASAPI loopback available: %s", self._loopback_device_name)
            else:
                self._loopback_recorder = None
                self._loopback_device_name = None
                log.warning("WASAPI loopback device not found")
        else:
            self._loopback_recorder = None
            self._loopback_device_name = None
            log.warning("pyaudiowpatch not installed - system audio capture unavailable. "
                        "Install with: pip install PyAudioWPatch")

        # Initialize transcriber based on engine selection
        engine = self.config.get("engine", "faster_whisper")
        if engine == "openvino" and OpenVINOTranscriber.is_available():
            self.transcriber = OpenVINOTranscriber(
                model_size=self.config["model_size"],
                cpu_threads=self.config["cpu_threads"],
                device=self.config.get("openvino_device", "GPU"),
            )
        else:
            if engine == "openvino":
                log.warning("OpenVINO requested but openvino-genai not installed. "
                            "Falling back to faster-whisper.")
                self.config["engine"] = "faster_whisper"
                save_config(self.config)
            self.transcriber = FasterWhisperTranscriber(
                model_size=self.config["model_size"],
                cpu_threads=self.config["cpu_threads"],
            )
        self.is_recording = False
        self.model_loaded = False
        self.status_text = "Loading model..."
        self.tray_icon = None
        self._hotkey_registered = False
        self.overlay = OverlayNotification()

        # Streaming transcription state
        self._streaming_thread = None
        self._streaming_stop_event = threading.Event()
        self._transcribe_lock = threading.Lock()
        self._last_partial_text = ""
        self._last_snapshot_sample_count = 0

    def run(self):
        """Main entry point."""
        import pystray
        from PIL import Image

        # Load model in background
        model_thread = threading.Thread(target=self._load_model, daemon=True)
        model_thread.start()

        # Create tray icon
        icon_image = self._create_icon("idle")
        menu = pystray.Menu(
            pystray.MenuItem("WhisperType", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status: Loading...", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Language",
                pystray.Menu(
                    pystray.MenuItem("Auto Detect", lambda: self._set_language("auto"),
                                    checked=lambda item: self.config["language"] == "auto"),
                    pystray.MenuItem("Hebrew", lambda: self._set_language("he"),
                                    checked=lambda item: self.config["language"] == "he"),
                    pystray.MenuItem("English", lambda: self._set_language("en"),
                                    checked=lambda item: self.config["language"] == "en"),
                ),
            ),
            pystray.MenuItem(
                "Microphone",
                pystray.Menu(self._build_microphone_menu),
            ),
            pystray.MenuItem(
                "Model",
                pystray.Menu(self._build_model_menu),
            ),
            pystray.MenuItem(
                "Engine",
                pystray.Menu(
                    pystray.MenuItem(
                        "faster-whisper (CPU)",
                        lambda: self._set_engine("faster_whisper"),
                        checked=lambda item: self.config.get("engine", "faster_whisper") == "faster_whisper",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "OpenVINO (Intel GPU)",
                        lambda: self._set_engine("openvino", "GPU"),
                        checked=lambda item: (self.config.get("engine") == "openvino"
                                              and self.config.get("openvino_device") == "GPU"),
                        radio=True,
                        enabled=OpenVINOTranscriber.is_available(),
                    ),
                    pystray.MenuItem(
                        "OpenVINO (Intel NPU)",
                        lambda: self._set_engine("openvino", "NPU"),
                        checked=lambda item: (self.config.get("engine") == "openvino"
                                              and self.config.get("openvino_device") == "NPU"),
                        radio=True,
                        enabled=OpenVINOTranscriber.is_available(),
                    ),
                    pystray.MenuItem(
                        "OpenVINO (CPU)",
                        lambda: self._set_engine("openvino", "CPU"),
                        checked=lambda item: (self.config.get("engine") == "openvino"
                                              and self.config.get("openvino_device") == "CPU"),
                        radio=True,
                        enabled=OpenVINOTranscriber.is_available(),
                    ),
                ),
            ),
            pystray.MenuItem(
                "After Recording",
                pystray.Menu(
                    pystray.MenuItem("Auto-Paste (Ctrl+V)", lambda: self._set_paste_mode("auto_paste"),
                                    checked=lambda item: self.config["paste_mode"] == "auto_paste"),
                    pystray.MenuItem("Clipboard Only", lambda: self._set_paste_mode("clipboard_only"),
                                    checked=lambda item: self.config["paste_mode"] == "clipboard_only"),
                    pystray.MenuItem("Direct Type", lambda: self._set_paste_mode("direct_type"),
                                    checked=lambda item: self.config["paste_mode"] == "direct_type"),
                ),
            ),
            pystray.MenuItem(
                "Recording Mode",
                pystray.Menu(
                    pystray.MenuItem("Hold to Record", lambda: self._set_recording_mode("hold"),
                                    checked=lambda item: self.config.get("recording_mode", "hold") == "hold",
                                    radio=True),
                    pystray.MenuItem("Toggle (press start/stop)", lambda: self._set_recording_mode("toggle"),
                                    checked=lambda item: self.config.get("recording_mode") == "toggle",
                                    radio=True),
                ),
            ),
            pystray.MenuItem(
                "Recording Source",
                pystray.Menu(
                    pystray.MenuItem("Microphone Only", lambda: self._set_recording_source("microphone"),
                                    checked=lambda item: self.config.get("recording_source", "microphone") == "microphone",
                                    radio=True),
                    pystray.MenuItem(
                        "System Audio Only",
                        lambda: self._set_recording_source("stereo_mix"),
                        checked=lambda item: self.config.get("recording_source") == "stereo_mix",
                        radio=True,
                        enabled=self._loopback_recorder is not None,
                    ),
                    pystray.MenuItem(
                        "Both (Mic + System Audio)",
                        lambda: self._set_recording_source("both"),
                        checked=lambda item: self.config.get("recording_source") == "both",
                        radio=True,
                        enabled=self._loopback_recorder is not None,
                    ),
                ),
            ),
            pystray.MenuItem(
                "Background Processing",
                pystray.Menu(
                    pystray.MenuItem("Off (transcribe after stop)", lambda: self._set_streaming_mode("off"),
                                    checked=lambda item: self.config.get("streaming_mode", "preview") == "off",
                                    radio=True),
                    pystray.MenuItem("On (transcribe while recording)", lambda: self._set_streaming_mode("preview"),
                                    checked=lambda item: self.config.get("streaming_mode", "preview") == "preview",
                                    radio=True),
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Transcribe File",
                pystray.Menu(
                    pystray.MenuItem("Hebrew", lambda: self._transcribe_file("he")),
                    pystray.MenuItem("English", lambda: self._transcribe_file("en")),
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

        self.tray_icon = pystray.Icon("WhisperType", icon_image, "WhisperType", menu)

        # Start hotkey listener in background
        hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        hotkey_thread.start()

        log.info("WhisperType is running! Hotkey: %s", self.config["hotkey"])
        log.info("Right-click the tray icon for options.")
        self.tray_icon.run()

    def _create_icon(self, state="idle"):
        """Create a simple icon using PIL."""
        from PIL import Image, ImageDraw, ImageFont
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if state == "idle":
            # Green microphone circle
            draw.ellipse([4, 4, size - 4, size - 4], fill=(34, 139, 34), outline=(255, 255, 255), width=2)
            # Mic shape
            draw.rounded_rectangle([22, 14, 42, 38], radius=8, fill=(255, 255, 255))
            draw.arc([18, 28, 46, 52], start=0, end=180, fill=(255, 255, 255), width=3)
            draw.line([32, 52, 32, 58], fill=(255, 255, 255), width=3)
        elif state == "recording":
            # Red recording circle
            draw.ellipse([4, 4, size - 4, size - 4], fill=(220, 20, 20), outline=(255, 255, 255), width=2)
            draw.rounded_rectangle([22, 14, 42, 38], radius=8, fill=(255, 255, 255))
            draw.arc([18, 28, 46, 52], start=0, end=180, fill=(255, 255, 255), width=3)
            draw.line([32, 52, 32, 58], fill=(255, 255, 255), width=3)
        elif state == "processing":
            # Yellow processing circle
            draw.ellipse([4, 4, size - 4, size - 4], fill=(255, 165, 0), outline=(255, 255, 255), width=2)
            draw.text((16, 16), "...", fill=(255, 255, 255))
        elif state == "loading":
            # Blue circle - model is loading
            draw.ellipse([4, 4, size - 4, size - 4], fill=(30, 100, 200), outline=(255, 255, 255), width=2)
            # Hourglass shape
            draw.rounded_rectangle([22, 14, 42, 38], radius=8, fill=(255, 255, 255))
            draw.arc([18, 28, 46, 52], start=0, end=180, fill=(255, 255, 255), width=3)
            draw.line([32, 52, 32, 58], fill=(255, 255, 255), width=3)

        return img

    def _load_model(self):
        try:
            # Show blue icon while loading
            if self.tray_icon:
                self.tray_icon.icon = self._create_icon("loading")
            model_label = MODELS.get(self.config["model_size"], self.config["model_size"])
            self.overlay.show(f"  🔄  Loading: {model_label}  ", bg_color="#1e64c8")
            self.transcriber.load_model(callback=lambda msg: log.info(msg))
            self.model_loaded = True
            self.status_text = "Ready"
            log.info("Model loaded. Ready to transcribe!")
            if self.tray_icon:
                self.tray_icon.icon = self._create_icon("idle")
            self.overlay.show_done()
            if self.config["play_sound"]:
                play_beep(600, 100)
        except Exception as e:
            self.status_text = f"Error: {e}"
            log.error("Failed to load model: %s", e)
            if self.tray_icon:
                self.tray_icon.icon = self._create_icon("idle")
            self.overlay.show_error("Model load failed")

    def _hotkey_listener(self):
        """Listen for the hotkey using keyboard library."""
        import keyboard

        hotkey = self.config["hotkey"]
        # Parse hotkey parts
        parts = hotkey.lower().split("+")

        log.info("Hotkey registered: %s", hotkey)

        while True:
            try:
                # Wait for hotkey press
                keyboard.wait(hotkey)

                if not self.model_loaded:
                    log.info("Model still loading, please wait...")
                    continue

                if self.config.get("recording_mode") == "toggle":
                    # Toggle mode: press to start, press again to stop
                    if self.is_recording:
                        self._stop_and_transcribe()
                    else:
                        self._start_recording()
                    # Wait for key release (debounce) before listening again
                    while any(keyboard.is_pressed(p.strip()) for p in parts):
                        time.sleep(0.05)
                    time.sleep(0.2)  # extra debounce
                else:
                    # Hold mode (default): hold to record, release to stop
                    self._start_recording()
                    while all(keyboard.is_pressed(p.strip()) for p in parts):
                        time.sleep(0.05)
                    self._stop_and_transcribe()

            except Exception as e:
                log.error("Hotkey error: %s", e)
                time.sleep(0.5)

    def _start_recording(self):
        if self.is_recording:
            return
        self.is_recording = True
        source = self.config.get("recording_source", "microphone")
        source_label = {"microphone": "Mic", "stereo_mix": "System Audio", "both": "Mic + System"}.get(source, "Mic")
        log.info("Recording (%s)...", source_label)
        self.overlay.show_recording()
        if self.config["play_sound"]:
            threading.Thread(target=lambda: play_beep(800, 100), daemon=True).start()
        if self.tray_icon:
            self.tray_icon.icon = self._create_icon("recording")

        if source == "stereo_mix" and self._loopback_recorder:
            self._loopback_recorder.start()
        elif source == "both" and self._loopback_recorder:
            self.recorder.start()
            self._loopback_recorder.start()
        else:
            self.recorder.start()

        # Start streaming transcription worker (if streaming is enabled)
        streaming_mode = self.config.get("streaming_mode", "preview")
        if self.model_loaded and streaming_mode != "off":
            self._streaming_stop_event.clear()
            self._last_partial_text = ""
            self._last_snapshot_sample_count = 0
            self._last_dictated_text = ""  # tracks what's already been typed in live mode
            self._live_char_count = 0     # how many visible chars we've output
            self._streaming_thread = threading.Thread(
                target=self._streaming_worker, daemon=True
            )
            self._streaming_thread.start()

        # Start waveform visualization updater
        self._waveform_thread = threading.Thread(
            target=self._waveform_updater, daemon=True
        )
        self._waveform_thread.start()

    def _waveform_updater(self):
        """Update the waveform visualization with real-time audio levels."""
        NUM_BARS = OverlayNotification.NUM_BARS

        while self.is_recording:
            try:
                source = self.config.get("recording_source", "microphone")
                if source == "stereo_mix" and self._loopback_recorder:
                    recorder = self._loopback_recorder
                else:
                    recorder = self.recorder

                if not recorder.audio_data:
                    time.sleep(0.05)
                    continue

                # Get the last few chunks (~200ms of audio)
                chunks = list(recorder.audio_data[-4:])
                if not chunks:
                    time.sleep(0.05)
                    continue

                raw = b"".join(chunks)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                if len(samples) < NUM_BARS:
                    time.sleep(0.05)
                    continue

                # Split into segments, one per bar
                seg_size = len(samples) // NUM_BARS
                levels = []
                for i in range(NUM_BARS):
                    seg = samples[i * seg_size:(i + 1) * seg_size]
                    peak = float(np.max(np.abs(seg)))
                    level = min(1.0, peak * 3.5)  # amplify for visibility
                    levels.append(level)

                self.overlay.update_waveform(levels)
            except Exception:
                pass

            time.sleep(0.05)  # ~20 FPS

    def _streaming_worker(self):
        """Periodically transcribe accumulated audio during recording.

        In 'preview' mode: shows partial text in overlay only.
        In 'live_dictation' mode: types new text into the active window in real-time.
        """
        streaming_mode = self.config.get("streaming_mode", "preview")
        INTERVAL = 1.0        # check every second
        MIN_NEW_SECONDS = 3   # wait for 3 seconds of NEW audio before transcribing a chunk
        MIN_NEW_SAMPLES = 16000 * MIN_NEW_SECONDS

        # For live dictation: track where we left off so we only transcribe NEW audio
        last_transcribed_pos = 0

        while not self._streaming_stop_event.wait(timeout=INTERVAL):
            try:
                # Pick the active recorder for snapshots
                source = self.config.get("recording_source", "microphone")
                if source == "stereo_mix" and self._loopback_recorder:
                    recorder = self._loopback_recorder
                else:
                    recorder = self.recorder

                # Snapshot the audio buffer (GIL-safe list copy)
                snapshot_chunks = list(recorder.audio_data)
                if not snapshot_chunks:
                    continue

                raw = b"".join(snapshot_chunks)
                total_samples = len(raw) // 2  # int16 = 2 bytes per sample

                if streaming_mode == "live_dictation":
                    # ---- LIVE DICTATION: transcribe only NEW audio, APPEND ----
                    new_samples = total_samples - last_transcribed_pos
                    if new_samples < MIN_NEW_SAMPLES:
                        continue

                    # Extract only the new chunk
                    all_audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                    # Handle loopback: multi-channel to mono + resample
                    if source == "stereo_mix" and self._loopback_recorder:
                        channels = getattr(self._loopback_recorder, '_channels', 1)
                        if channels > 1:
                            all_audio = all_audio.reshape(-1, channels).mean(axis=1)
                        native_rate = getattr(self._loopback_recorder, '_native_rate', 16000)
                        if native_rate and native_rate != 16000:
                            all_audio = resample_audio(all_audio, native_rate, 16000)

                    chunk_audio = all_audio[last_transcribed_pos:]

                    with self._transcribe_lock:
                        chunk_text = self.transcriber.transcribe(
                            chunk_audio,
                            language=self.config["language"],
                            beam_size=1,
                        )

                    if chunk_text:

                        clean_chunk = chunk_text.replace('\u200F', '').replace('\u200E', '').strip()

                        # Add a space separator between chunks (unless first chunk)
                        if last_transcribed_pos > 0:
                            paste_text = " " + chunk_text.strip()
                        else:
                            paste_text = chunk_text.strip()

                        # Paste via clipboard (using keyboard lib to avoid pyautogui conflict)
                        clipboard_paste(paste_text)

                        self._last_dictated_text += paste_text
                        log.info("Live dictation: appended %d chars: %s", len(clean_chunk), clean_chunk)

                    # Move position forward regardless (even if no speech detected in chunk)
                    last_transcribed_pos = len(all_audio)
                    self._last_snapshot_sample_count = last_transcribed_pos

                else:
                    # ---- PREVIEW MODE: transcribe ALL audio, show in overlay only ----
                    if total_samples < 16000:
                        continue

                    audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                    if source == "stereo_mix" and self._loopback_recorder:
                        channels = getattr(self._loopback_recorder, '_channels', 1)
                        if channels > 1:
                            audio_np = audio_np.reshape(-1, channels).mean(axis=1)
                        native_rate = getattr(self._loopback_recorder, '_native_rate', 16000)
                        if native_rate and native_rate != 16000:
                            audio_np = resample_audio(audio_np, native_rate, 16000)

                    with self._transcribe_lock:
                        text = self.transcriber.transcribe(
                            audio_np,
                            language=self.config["language"],
                            beam_size=1,
                        )

                    self._last_partial_text = text if text else ""
                    self._last_snapshot_sample_count = len(audio_np) if source == "stereo_mix" else total_samples
                    # No overlay update - waveform handles visual feedback

            except Exception as e:
                log.error("Streaming transcription error: %s", e)

    def _stop_and_transcribe(self):
        if not self.is_recording:
            return
        self.is_recording = False
        streaming_mode = self.config.get("streaming_mode", "preview")
        log.info("Processing...")
        self.overlay.show_processing()
        if self.tray_icon:
            self.tray_icon.icon = self._create_icon("processing")

        # Stop streaming worker first
        self._streaming_stop_event.set()
        if self._streaming_thread and self._streaming_thread.is_alive():
            self._streaming_thread.join(timeout=2.0)

        # Capture streaming results before stopping recorders
        last_partial = self._last_partial_text
        last_snapshot_samples = self._last_snapshot_sample_count
        last_dictated = getattr(self, '_last_dictated_text', "")

        source = self.config.get("recording_source", "microphone")

        if source == "stereo_mix" and self._loopback_recorder:
            audio = self._loopback_recorder.stop()
        elif source == "both" and self._loopback_recorder:
            mic_audio = self.recorder.stop()
            loopback_audio = self._loopback_recorder.stop()
            audio = mix_audio(mic_audio, loopback_audio)
            log.info("Mixed mic (%d samples) + loopback (%d samples)", len(mic_audio), len(loopback_audio))
        else:
            audio = self.recorder.stop()

        if len(audio) < 1600:  # Less than 0.1 seconds
            log.info("Recording too short, ignoring.")
            self.overlay.hide()
            if self.tray_icon:
                self.tray_icon.icon = self._create_icon("idle")
            return

        # Transcribe in background to not block
        def do_transcribe():
            try:
                if streaming_mode == "live_dictation":
                    # Live dictation: text was appended incrementally during recording.
                    # Just transcribe the remaining tail and append it.
                    if last_snapshot_samples > 0 and len(audio) > last_snapshot_samples:
                        tail_audio = audio[last_snapshot_samples:]
                        if len(tail_audio) >= 1600:  # at least 0.1s
                            with self._transcribe_lock:
                                tail_text = self.transcriber.transcribe(
                                    tail_audio,
                                    language=self.config["language"],
                                    beam_size=self.config["beam_size"],
                                )
                            if tail_text:
                                clean_tail = tail_text.replace('\u200F', '').replace('\u200E', '').strip()
                                if clean_tail:
                                    paste_text = " " + tail_text.strip() if last_dictated else tail_text.strip()
                                    clipboard_paste(paste_text)
                                    log.info("Live dictation tail: %d chars", len(clean_tail))
                    elif not last_dictated:
                        # Nothing was typed during recording (too short) - do full transcription
                        with self._transcribe_lock:
                            text = self.transcriber.transcribe(
                                audio,
                                language=self.config["language"],
                                beam_size=self.config["beam_size"],
                            )
                        if text:
                            clipboard_paste(text)

                    total = len((last_dictated or "").replace('\u200F', '').replace('\u200E', ''))
                    self.overlay.show_done(char_count=total)
                    if self.config["play_sound"]:
                        play_beep(1000, 100)
                    return

                # Standard mode (preview or off)
                if last_partial and last_snapshot_samples > 0:
                    # Partial exists from background streaming.
                    # Transcribe only the tail, combine, paste ONCE.
                    text = last_partial

                    if len(audio) > last_snapshot_samples and source != "both":
                        tail_audio = audio[last_snapshot_samples:]
                        if len(tail_audio) >= 1600:
                            log.info("Transcribing tail (%d samples)...", len(tail_audio))
                            with self._transcribe_lock:
                                tail_text = self.transcriber.transcribe(
                                    tail_audio,
                                    language=self.config["language"],
                                    beam_size=self.config["beam_size"],
                                )
                            if tail_text:
                                clean_partial = last_partial.rstrip('\u200F\u200E').rstrip()
                                clean_tail = tail_text.lstrip('\u200F\u200E').lstrip()
                                if clean_tail:
                                    combined = clean_partial + " " + clean_tail
                                else:
                                    combined = clean_partial
                                # Preserve RTL mark
                                if last_partial.startswith('\u200F'):
                                    text = '\u200F' + combined.lstrip('\u200F')
                                else:
                                    text = combined

                    # Single paste of complete text
                    if text:
                        display_text = text.replace('\u200F', '').replace('\u200E', '')
                        log.info("Transcribed (%d chars): %s", len(display_text), display_text)
                        output_text(text, mode=self.config.get("paste_mode", "auto_paste"))
                        self.overlay.show_done(char_count=len(display_text))
                        if self.config["play_sound"]:
                            play_beep(1000, 100)
                    else:
                        self.overlay.show_error("No speech detected")
                else:
                    # --- NO PARTIAL: full transcription (short recording or streaming=off) ---
                    with self._transcribe_lock:
                        text = self.transcriber.transcribe(
                            audio,
                            language=self.config["language"],
                            beam_size=self.config["beam_size"],
                        )

                    if text:
                        display_text = text.replace('\u200F', '').replace('\u200E', '')
                        log.info("Transcribed (%d chars): %s", len(display_text), display_text)
                        output_text(text, mode=self.config.get("paste_mode", "auto_paste"))
                        self.overlay.show_done(char_count=len(display_text))
                        if self.config["play_sound"]:
                            play_beep(1000, 100)
                    else:
                        log.info("No speech detected")
                        self.overlay.show_error("No speech detected")
            except Exception as e:
                log.error("Transcription error: %s", e)
                self.overlay.show_error("Transcription failed")
            finally:
                if self.tray_icon:
                    self.tray_icon.icon = self._create_icon("idle")

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _transcribe_file(self, language):
        """Open a file dialog, pick a video/audio file, and transcribe it."""
        if not self.model_loaded:
            self.overlay.show_error("Model still loading...")
            return

        def do_pick_and_transcribe():
            import tkinter as tk
            from tkinter import filedialog

            # Create a hidden root for the file dialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            file_path = filedialog.askopenfilename(
                title="Select a file to transcribe",
                filetypes=[
                    ("Video/Audio files", "*.mp4 *.mp3 *.wav *.m4a *.mkv *.avi *.webm *.ogg *.flac *.wma"),
                    ("All files", "*.*"),
                ],
                parent=root,
            )
            root.destroy()

            if not file_path:
                return

            lang_label = "Hebrew" if language == "he" else "English"
            log.info("Transcribing file (%s): %s", lang_label, file_path)
            self.overlay.show(f"  ⏳  Transcribing ({lang_label})...  ", bg_color="#f77f00")
            if self.tray_icon:
                self.tray_icon.icon = self._create_icon("processing")

            try:
                text = self.transcriber.transcribe_file(
                    file_path,
                    language=language,
                )
                if text:
                    # Save to .txt file next to the source file
                    base, _ = os.path.splitext(file_path)
                    out_path = base + f"_transcription_{language}.txt"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(text)

                    log.info("Transcription saved to: %s (%d chars)", out_path, len(text))
                    self.overlay.show_done(char_count=len(text))
                    if self.config["play_sound"]:
                        play_beep(1000, 100)

                    # Open the file in the default text editor
                    os.startfile(out_path)
                else:
                    log.info("No speech detected in file")
                    self.overlay.show_error("No speech detected")
            except Exception as e:
                log.error("File transcription error: %s", e)
                self.overlay.show_error("Transcription failed")
            finally:
                if self.tray_icon:
                    self.tray_icon.icon = self._create_icon("idle")

        threading.Thread(target=do_pick_and_transcribe, daemon=True).start()

    def _set_language(self, lang):
        self.config["language"] = lang
        save_config(self.config)
        log.info("Language set to: %s", lang)

    def _build_microphone_menu(self):
        """Dynamically build the microphone selection submenu."""
        import pystray

        items = [
            pystray.MenuItem(
                "System Default",
                lambda: self._set_input_device(None),
                checked=lambda item: self.config.get("input_device_index") is None,
                radio=True,
            ),
            pystray.Menu.SEPARATOR,
        ]

        devices = list_input_devices()
        if not devices:
            items.append(pystray.MenuItem("(no devices found)", None, enabled=False))
        else:
            for idx, name in devices:
                # Truncate long names for the menu
                display_name = name if len(name) <= 40 else name[:37] + "..."
                label = f"{display_name}"
                items.append(
                    pystray.MenuItem(
                        label,
                        (lambda i: lambda: self._set_input_device(i))(idx),
                        checked=(lambda i: lambda item: self.config.get("input_device_index") == i)(idx),
                        radio=True,
                    )
                )
        return items

    def _set_input_device(self, device_index):
        self.config["input_device_index"] = device_index
        save_config(self.config)
        # Update the current recorder instance so next recording uses it
        self.recorder.input_device_index = device_index
        if device_index is None:
            log.info("Input device set to: System Default")
        else:
            log.info("Input device set to index: %s", device_index)

    def _set_paste_mode(self, mode):
        self.config["paste_mode"] = mode
        save_config(self.config)
        labels = {"auto_paste": "Auto-Paste", "clipboard_only": "Clipboard Only", "direct_type": "Direct Type"}
        log.info("Paste mode set to: %s", labels.get(mode, mode))

    def _set_recording_mode(self, mode):
        self.config["recording_mode"] = mode
        save_config(self.config)
        labels = {"hold": "Hold to Record", "toggle": "Toggle (press start/stop)"}
        log.info("Recording mode set to: %s", labels.get(mode, mode))

    def _set_recording_source(self, source):
        if source in ("stereo_mix", "both") and self._loopback_recorder is None:
            self.overlay.show_error("Stereo Mix not available")
            return
        self.config["recording_source"] = source
        save_config(self.config)
        labels = {"microphone": "Microphone", "stereo_mix": "Stereo Mix", "both": "Both (Mic + Stereo Mix)"}
        log.info("Recording source set to: %s", labels.get(source, source))

    def _set_streaming_mode(self, mode):
        self.config["streaming_mode"] = mode
        save_config(self.config)
        labels = {"off": "Off", "preview": "Preview", "live_dictation": "Live Dictation"}
        log.info("Streaming mode set to: %s", labels.get(mode, mode))

    def _build_model_menu(self):
        """Dynamically build Model submenu based on active engine."""
        import pystray
        engine = self.config.get("engine", "faster_whisper")
        model_dict = OPENVINO_MODELS if engine == "openvino" else MODELS
        return [
            pystray.MenuItem(
                label,
                (lambda m: lambda: self._set_model(m))(model_id),
                checked=(lambda m: lambda item: self.config["model_size"] == m)(model_id),
            )
            for model_id, label in model_dict.items()
        ]

    def _set_model(self, model):
        if model != self.config["model_size"]:
            self.config["model_size"] = model
            save_config(self.config)
            self.model_loaded = False

            engine = self.config.get("engine", "faster_whisper")
            if engine == "openvino" and OpenVINOTranscriber.is_available():
                self.transcriber = OpenVINOTranscriber(
                    model_size=model,
                    cpu_threads=self.config["cpu_threads"],
                    device=self.config.get("openvino_device", "GPU"),
                )
            else:
                self.transcriber = FasterWhisperTranscriber(
                    model_size=model,
                    cpu_threads=self.config["cpu_threads"],
                )
            threading.Thread(target=self._load_model, daemon=True).start()
            log.info("Switching to model: %s", model)

    def _set_engine(self, engine, device=None):
        changed = False
        if engine != self.config.get("engine", "faster_whisper"):
            self.config["engine"] = engine
            changed = True
        if device and device != self.config.get("openvino_device"):
            self.config["openvino_device"] = device
            changed = True
        if not changed:
            return

        save_config(self.config)
        self.model_loaded = False

        if engine == "openvino":
            # Switch to an OpenVINO model if current model isn't one
            if self.config["model_size"] not in OPENVINO_MODELS:
                self.config["model_size"] = "OpenVINO/whisper-large-v3-int8-ov"
                save_config(self.config)
            self.transcriber = OpenVINOTranscriber(
                model_size=self.config["model_size"],
                cpu_threads=self.config["cpu_threads"],
                device=device or self.config.get("openvino_device", "GPU"),
            )
        else:
            # Switch back to faster-whisper
            if self.config["model_size"] in OPENVINO_MODELS:
                self.config["model_size"] = "ivrit-ai/whisper-large-v3-turbo-ct2"
                save_config(self.config)
            self.transcriber = FasterWhisperTranscriber(
                model_size=self.config["model_size"],
                cpu_threads=self.config["cpu_threads"],
            )

        threading.Thread(target=self._load_model, daemon=True).start()
        log.info("Switched engine to: %s (device: %s)", engine, device)

    def _quit(self):
        log.info("Quitting WhisperType...")
        if self.tray_icon:
            self.tray_icon.stop()
        os._exit(0)


# ============================================================
# Entry Point
# ============================================================
if __name__ == "__main__":
    log.info("WhisperType starting...")
    app = WhisperTypeApp()
    app.run()
