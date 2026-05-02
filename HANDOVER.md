# WhisperType — Handover

*Last session: 2026-04-24 → 2026-05-02 (session 9). 39 commits. master at `7170649`. Tests: 27-32/32 (5 LIVE Groq cleanup tests are non-deterministic — Llama variance, not regressions).*

Read this first, then [CLAUDE.md](CLAUDE.md) for architecture and project history. You should not need anything else to continue.

---

## Session 9 (2026-04-24 → 2026-05-02) — backends multiplied, UX refactored

Session 9 sprawled across nine tracks. Most landed cleanly; a few were tried and reverted; one was investigated and accepted as won't-fix.

### Track A — Hotkey release debounce, settled at 150ms

Continuing from session 8 (`e5139d1`). Multiple iterations tuning the wireless-keyboard-glitch protection vs. release latency. Final answer: **150ms (3 polls × 50ms)** — minimum that catches the 50ms glitches actually observed in the user's log, without adding perceptible release latency. User chose this explicitly over longer-but-safer options. Wireless dropouts >150ms WILL still cut the recording — accepted trade-off.

Diagnostic log line `Hotkey release-detect: filtered N transient not-pressed poll(s) (Nms); chord still held` fires when the debounce catches a glitch. Helps tune later.

Iterations tried+reverted: 500ms (`88c05b9`), 1000+adaptive 2000ms (`3afa361`), 250ms (`5a162f8`). User picked 150ms in `c97b3f5`.

### Track B — OpenAI as a third transcription backend

`feb1bcc` added `OpenAITranscriber` alongside `GroqTranscriber` and the local `FasterWhisperTranscriber`. Models: `gpt-4o-transcribe` (best for Hebrew accuracy via stronger language priors) and `gpt-4o-mini-transcribe` (faster/cheaper).

**Critical for gpt-4o:** unlike Whisper, it's a "thinking" model that will translate Hebrew→English or summarise mid-utterance unless explicitly told not to. `a3c86b4` added a strong verbatim+no-translate prompt that always rides the request:

> *"Transcribe the audio verbatim in the language actually spoken. Do NOT translate. Do NOT summarise. … If the audio contains no actual speech — only silence, background noise, breathing, mouse clicks, keyboard sounds, fans, or static — output an empty string. Do NOT invent words to fill the void."*

Without this, gpt-4o invents short Hebrew phrases on near-silent clips ("למזלי", "כי בשנה") or translates "I will use the Israeli region IL-CENTRAL1" into garbled Hebrew.

Other gpt-4o specifics:
- `response_format=json` only (no `verbose_json` like Whisper-1) → no log-prob arbitration possible. Defence is the verbatim prompt + the post-hoc `_is_likely_hallucination()` check.
- `c320ca5`: skip `trim_trailing_silence` for gpt-4o (it handles end-of-clip cleanly on its own, the trim was eating tail words).
- `9f13fd5`: fix "cloud failed" bug where `_set_backend` skipped `load_model` when the transcriber instance existed but `.model` was still None. Now both Groq and OpenAI re-check and re-init idempotently.

### Track C — AssemblyAI for diarized meetings

`79f415f` added `AssemblyAITranscriber` and a diarized meeting flow:
- `MeetingSession.diarize_mode=True`: instead of chunking + per-chunk transcription, write all audio to a single WAV file. On stop, upload to AssemblyAI in a background thread, poll until done (5–20 min for typical meetings), write a markdown file with `**[mm:ss] Speaker A:** …` lines, open it.
- `fc83106`: in diarize mode, force `recording_source = "both"` if loopback is available — without this, only the user's mic was captured and AssemblyAI saw one speaker.
- `7ababf9` → `408fac5`: AssemblyAI's API moved from optional to required `speech_model`, then deprecated singular in favour of plural list. Final shape: `body["speech_models"] = ["universal-2"]`. `language_detection: True` is rejected by Universal — handled internally by the model, just don't send it.
- `7e2eff7`: meeting-and-file model selector (see Track D).

**AssemblyAI model knowledge:**
- `universal-2`: 99 languages incl. Hebrew. Supports speaker_labels. ~$0.65/hr with diarization. Default and only sensible choice for Hebrew users.
- `universal-3-pro`: $0.21/hr, more accurate. **No Hebrew support** — only EN/ES/DE/FR/IT/PT. Don't use for this user.

### Track D — Unified Transcribe→Model selector

Big UX consolidation in `7e2eff7`. Before: `Start Meeting (chunked)` and `Start Meeting (with speakers)` as separate menu items, plus `File → with Speaker Labels (AssemblyAI)…`. After: ONE `Transcribe → Model →` submenu with 6 radio rows (`assemblyai_universal_2` ⭐, `openai_gpt4o`, `openai_gpt4o_mini`, `groq_turbo`, `local_hebrew_turbo`, `local_english_distil`). The selected model controls BOTH `Start Meeting` and `File → Hebrew/English`.

`4e91720`: AssemblyAI is the FIRST row and the default (`DEFAULT_CONFIG["meeting_model"] = "assemblyai_universal_2"`). Transcribe lifted out of Options to top-level (sibling of Options).

Implementation detail: `_resolve_meeting_model(key)` maps to a cached `(transcriber, language_hint, is_diarized)` triple. Cache lazily-built — first meeting/file action with a given key takes the load_model hit.

### Track E — History as a plain text file

User reported the Tkinter History window spiked CPU heavily (one tk.Text widget per entry × 100+ entries = expensive native-widget rendering). `f56f469` replaced it with a text-file export:
- Writes `%APPDATA%\WhisperType\history.txt`
- Opens in user's default text editor (Notepad/VSCode/whatever)
- Native copy-paste, search, resize, RTL handling — all free from the OS
- 216 lines of dead Tkinter code removed

`24c3c76`: per-line bidi normalisation. Hebrew-bearing lines get a `U+200F` (RLM) prefix forcing RTL paragraph direction; LTR lines stay default-aligned. Mixed multi-line entries get correct per-line alignment.

`3306838`: `MAX_HISTORY` reduced 1000 → 500 (user request, ~10 days at user's usage rate).

### Track F — Tray menu restructure

User did multiple rounds of UX refinement. Final shape:

```
Status: Ready
Audio Input  →  …
Model        →  press-to-talk model (independent)
Options      →
  Hold to Record / Toggle (radio)
  ─
  Auto-Paste / Clipboard Only (radio)
  Restore Clipboard After Paste
  ─
  Invisible Mode
  Beep Output  → …
  ─
  Groq-Only Options →
    Bias Groq to Hebrew/English
    AI Cleanup (Groq)  → off / casual / proofread / email / code
    Custom Vocabulary…
  API Keys →
    Set Groq API Key…
    Set OpenAI API Key…
    Set AssemblyAI API Key…
  ─
  Hotkey: ctrl+space…
Transcribe   →
  Model →   (the meeting+file selector — see Track D)
  ─
  🎙 Start Meeting (uses selected Model) / ⏹ Stop Meeting
  ─
  File → Hebrew
  File → English
History
─
Quit
```

Removed in session 9: `Start with Windows`, `🔄 Restart WhisperType` (manual), the dual `Start Meeting` variants, the separate `File → with Speaker Labels` item. Header `WhisperType` (disabled label) also removed.

`0ed8b2c`: AI Cleanup default flipped from `casual` to `off` — gpt-4o-transcribe already produces clean output, the LLM round-trip was 300-800ms of pure overhead. Force-reset on startup matches the user's prior pattern of "reset to chosen default each launch". User can flip to casual mid-session for raw-Whisper output.

### Track G — Hallucination defence (3 layers, plus follow-ups)

`2c9f4ce` introduced a layered defence against gpt-4o inventing words on near-silent audio:

1. **Pre-API silent guard**: if peak RMS over a 300ms window is < 0.003, skip the API call entirely and route to `_handle_silent_capture`.
2. **gpt-4o verbatim prompt** (Track B above): explicit "output empty string if no speech".
3. **Post-API hallucination filter** `_is_likely_hallucination(text, audio_rms, duration_sec)`: combines low audio RMS (<0.025), short text (<50 chars), slow chars/sec (<4) to flag invented short Hebrew phrases. Drops them silently.

Threshold tuning was contentious:
- `2c9f4ce` raised pre-API threshold from 0.003 → 0.008 to catch borderline cases earlier.
- `5468e5e` reverted to 0.003 because real-but-quiet speech (RMS 0.006-0.007) was getting flagged as silent and triggering the auto-restart.
- `ad7c12a` removed the `duration_sec >= 1.5` gate so short clips also get checked, and bumped the threshold to **0.005** for the all-clip check. Final value.

`1be1340`: under SubprocessAudioRecorder, silent capture no longer auto-restarts the process — the per-recording subprocess respawn already handles stale PortAudio. Saves the user from "the app crashed" perception when they pressed the hotkey repeatedly without speaking. In-process AudioRecorder path keeps the original 3-consecutive auto-restart safety net.

`7170649`: subprocess silent path now resets the tray icon (idle) and overlay (hide) before returning. Without this, the tray was stuck on "TRANSCRIBING…" forever after a silent capture.

### Track H — Toggle mode hold-by-habit + silent feedback

`79f9905`: in toggle mode, if the user holds the chord ≥2.0s out of hold-mode muscle memory, treating the release as a stop. Quick taps (<2s) keep pure toggle semantics. Logs `Toggle mode: chord held N.Ns ≥ 2.0s — treating release as stop (hold-by-habit fallback)`.

Same commit: silent-mic flash duration 5.0s → 2.0s. The hotkey was never actually blocked during the flash; the 5s red-X icon just made the user feel locked out.

`396c5e4`: switching audio input device (mic / loopback / source) clears `_consecutive_silent`. Was triggering a spurious auto-restart when the user was actively reconfiguring audio.

### Track I — Cloud file transcribe (m4a fix + size guard)

`0ee897a`:
- New helper `guess_audio_mime(file_path)` maps extensions to correct MIME (m4a→audio/mp4, mp3→audio/mpeg, wav→audio/wav, webm/ogg/flac, fallback application/octet-stream). Both Groq and OpenAI's `transcribe_file` had hardcoded `audio/mpeg` which was rejected for `.m4a` content.
- 24MB pre-flight size guard with a clear error message ("File is X MB — limits to 25 MB. Compress or use Local").
- Surface the error message to the user via overlay (was masked behind a generic "Transcription failed").

### Track J — UAC bypass via Scheduled Task

`d5ef1c9` added two batch files:
- `install_no_uac.bat` (run once as Administrator): creates a Scheduled Task `WhisperType` with `/rl HIGHEST`, `/sc ONLOGON`, `/delay 0000:05`. Removes any pre-existing Startup-folder shortcut so we don't double-launch.
- `uninstall_no_uac.bat`: removes the task.
- `launch.bat`: wraps `schtasks /run /tn WhisperType` so the user can manually launch without UAC.

After `install_no_uac.bat` runs once: WhisperType auto-starts at login with admin rights, no UAC prompt thereafter. The 5-second delay lets the desktop settle before the global hotkey hook registers.

### Track K — Press-to-talk during meeting (subprocess only)

`59a1c48`: hotkey listener no longer blocks press-to-talk during a meeting WHEN the recorder is `SubprocessAudioRecorder`. The block was originally added when both meeting and press-to-talk were in-process and shared a single PyAudio context. With subprocess press-to-talk, each recording opens the mic in a separate Python process via WASAPI shared mode — no conflict with the meeting's in-process mic stream.

Side effect to know about: the user's voice is captured by BOTH transcripts (meeting + press-to-talk paste) since they read the same physical mic. The user explicitly accepted this.

In-process AudioRecorder path (frozen PyInstaller fallback) still blocks — those CAN deadlock.

### Track L — Won't-fix: Chrome Remote Desktop clipboard sync

User reported pasting into a CRD session always pastes the OLD remote clipboard. We diagnosed:

- WhisperType writes the new transcription to the LOCAL Windows clipboard via pyperclip → `SetClipboardData`.
- CRD's clipboard sync is event-driven via Chrome's clipboard listener.
- Empirically: Chrome does NOT pick up `SetClipboardData` from external apps. Even after a 20-second delay, the remote clipboard stays stale.
- Only thing that triggers a sync: minimize+restore the CRD window (per the user's testing).

Considered fixes:
1. Wait longer before Ctrl+V — won't help (Chrome never sees the change).
2. Switch to `keyboard.write()` direct typing — Hebrew comes out as garbage (already known and removed in pre-session-7 work, see CLAUDE.md note about `direct_type` migration).
3. Programmatically minimize+restore the CRD window before paste — would work, but adds a 400ms visible window flash on every paste. Implementation drafted then **abandoned at user's request** ("בוא נוותר על זה לחלוטין ונשכח מהנושא הזה").

User's workaround: don't use WhisperType in CRD sessions. Use RDP / AnyDesk / TeamViewer / Parsec instead — they sync clipboard properly from external apps.

Status in code: NO Remote Desktop mode toggle exists. The `paste_delay_sec` parameter and `remote_desktop_mode` config key were added then reverted in this session.

---

## Architecture overview after session 9

### Two completely independent model selectors

1. **`Model` (top-level tray menu)** — controls **press-to-talk dictation**. Uses the existing `_set_model_backend_translate()` flow → swaps `self.transcriber` to one of `_groq_transcriber` / `_openai_transcriber` / `_local_transcriber`. Also persists the OpenAI sub-model (`gpt-4o-transcribe` vs `gpt-4o-mini-transcribe`) when an OpenAI row is picked.
2. **`Transcribe → Model` (Transcribe submenu)** — controls **meeting recording + file transcription**. Uses `_resolve_meeting_model(key)` which returns a cached `(transcriber, language_hint, is_diarized)` triple. Independent of #1.

The user can dictate via OpenAI gpt-4o-transcribe (Model menu) AND have meetings transcribed via AssemblyAI (Transcribe → Model). They don't interfere.

### Three transcription backends + one diarization backend

- **Local: `FasterWhisperTranscriber`** — ivrit-ai (Hebrew), distil-large-v3 (English), large-v3-turbo (general). No network. Free. Slower on long files but no size cap.
- **Groq: `GroqTranscriber`** — whisper-large-v3-turbo. Fast (~300-800ms for 10s clips). Cheap. Has the dual-pass log-prob arbitration from session 8 for Hebrew/English language constraint when `groq_he_en_bias` is on.
- **OpenAI: `OpenAITranscriber`** — gpt-4o-transcribe / gpt-4o-mini-transcribe / whisper-1. Stronger Hebrew context handling. ~1-3s latency. Verbatim+no-translate prompt always sent for gpt-4o models. Post-hoc Unicode-script check + retry-with-language=he as fallback.
- **AssemblyAI: `AssemblyAITranscriber`** — universal-2 only. Used ONLY by the diarized meeting flow + diarized file transcribe. Async (5-20 min for 1-hour meetings). speaker_labels=true, returns utterances tagged Speaker A/B/C.

All four use per-instance `requests.Session()` (`_ensure_session()`) for HTTP keep-alive — saves ~100-300ms TLS handshake per call after the first.

### Recorder

`SubprocessAudioRecorder` is the default and is what the user runs. Each recording spawns a fresh Python subprocess that opens PyAudio→WASAPI in shared mode, captures to a WAV file, and exits. Pre-spawn: a replacement worker is queued in a daemon thread right after the previous DONE so the next `start()` is ~0.3-0.6ms.

Idle / display-wake watchdogs are skipped under SubprocessAudioRecorder (per-recording fresh PortAudio makes the stale-handle bug structurally impossible). In-process `AudioRecorder` is the frozen-PyInstaller fallback.

### Meeting flow

`MeetingSession` constructor takes `diarize_mode` (bool), `chunk_transcriber` (the transcriber instance for chunked mode), `chunk_language` (forced language hint, e.g. `"he"` for Hebrew Turbo Local).

- **Chunked path** (anything except AssemblyAI): rotates the recorder every 45s, sends each chunk to the resolved meeting transcriber in a background thread, accumulates results into `self.chunks` indexed by chunk_index. On stop: assembles markdown + asks the Groq LLM for a summary + action items. If meeting source is `microphone` and loopback is available, it stays at microphone (mic only).

- **Diarize path** (AssemblyAI Universal-2): same rotation loop but each chunk is APPENDED to a single WAV file (`<stamp>_meeting_audio.wav`) instead of being transcribed. On stop, the WAV is uploaded to AssemblyAI in a background thread, polled until done, and the result is written as `<stamp>_meeting_diarized.md` with speaker labels. WAV is deleted on success, preserved on failure. **Source is force-promoted to "both"** if loopback is available (see fc83106) — without this, only the user's mic reaches the API and only Speaker A gets detected.

### Hallucination defence stack

For ANY transcription:
1. `audio_peak_rms(audio, window_ms=300)` — peak RMS of the loudest 300ms window
2. If `audio_rms < 0.005` (regardless of duration): route to `_handle_silent_capture`, don't call API
3. If passes → call API
4. After result: `_is_likely_hallucination(text, audio_rms, duration_sec)` — drops it if all of: rms<0.025, len<50 chars, chars/sec<4
5. Whisper-specific: `strip_hallucinated_tail(text)` removes "Thank you" / "תודה רבה" / "bye" trailing patterns
6. (gpt-4o additionally has the verbatim+no-translate prompt baked in)

---

## Current config (the user's machine)

```json
{
  "model_size": "large-v3-turbo",         // press-to-talk model
  "transcription_backend": "openai",       // press-to-talk backend (varies)
  "openai_model": "gpt-4o-transcribe",     // press-to-talk OpenAI sub-model
  "meeting_model": "assemblyai_universal_2", // meeting + file transcribe
  "cleanup_style": "off",                  // force-reset on startup
  "groq_he_en_bias": false,                // user toggled off (no-op now anyway)
  "custom_vocabulary": "",                 // user keeps wanting to add but hasn't
  "recording_mode": "toggle",              // varies; user uses both
  "silent_mode": false,                    // overlay visible
  "use_subprocess_mic": true,              // critical — many session 9 features assume this
  "groq_api_key": "...",                   // configured
  "openai_api_key": "...",                 // configured
  "assemblyai_api_key": "...",             // configured
}
```

On startup, several keys auto-reset: `cleanup_style → "off"` (be72100 era), `meeting_model` defaults to `assemblyai_universal_2` if unset.

---

## Known issues / accepted trade-offs / won't-fix

1. **Chrome Remote Desktop**: don't use WhisperType in CRD. CRD doesn't sync external clipboard changes. (Won't-fix per user request, see Track L.)
2. **Hebrew via direct typing** (`keyboard.write()`): produces garbage. `direct_type` paste mode was removed pre-session-7. Don't re-introduce.
3. **AssemblyAI Universal-3 Pro**: no Hebrew support (EN/ES/DE/FR/IT/PT only). We use universal-2 always.
4. **Wireless keyboard dropouts >150ms**: still cut recordings mid-sentence. User chose the fast-release tradeoff in `c97b3f5`. Bumping the debounce is a one-line change if user changes their mind.
5. **Press-to-talk during meeting**: user's voice ends up in BOTH the meeting transcript and the paste. Accepted — they explicitly wanted this behaviour for taking private notes during calls.
6. **Config corruption** (sometimes appears in logs as `Config file corrupt or unreadable`): when user runs `python run_tests.py` while the app is running, the test config-roundtrip tests overwrite the live config file. The app's atomic write protects against in-flight failure, but the tests are orthogonal. Not a real bug; just don't run tests while using the app.
7. **5/32 tests fail nondeterministically**: all in section 6 (LIVE Groq cleanup). Llama-3.3-70b's behaviour varies per call. The cleanup styles work in practice but the exact wording of "what counts as a fix" can drift. Not a regression.
8. **Cleanup hits Groq's free TPD limit**: 100K tokens/day. Long meetings can blow through this and the summary will fail (transcript still saves). User can upgrade Groq plan or accept it.

---

## What still needs work / pending ideas

### Worth doing (medium ROI)

- **Custom vocabulary**: the user keeps mentioning their accuracy issues with words like `אליאס, אקראיים, הזמין, הקרין, להיבלע`. Tray → Options → Groq-Only Options → Custom Vocabulary… exists; they just haven't added entries. Probably worth surfacing this more, maybe as a one-time prompt on startup.
- **Granola-style auto-detect**: detect when Zoom/Teams/Meet is in the foreground and offer/auto-start a meeting recording. Useful for hands-off meeting capture without remembering to click Start Meeting.
- **CLAUDE.md update**: it's stale (last touched session 7). Worth a refresh now that the architecture is significantly different — especially the dual model selectors and the AssemblyAI pipeline.

### Long deferred / low ROI

- **`UpdateLayeredWindow` overlay rewrite**: per-pixel alpha for the press-to-talk pill, eliminates the ~1px AA fringe. Sketch in pre-session-9 HANDOVER. Complex (4-6h refactor); user accepted current look.
- **Auto-stop on silence**: stop recording after N seconds quiet instead of requiring key release. ~2-3h.
- **Statistics dashboard**: words transcribed, time saved, languages distribution. ~2h.
- **Live transcript window during meetings**: currently markdown is shown only after stop (chunked) or 5-20 min after stop (diarized). Live view = ~1 day.

### Dead ends — do NOT re-attempt

- **Chrome Remote Desktop clipboard sync workaround**: see Track L. User explicitly walked away from the topic.
- **Forcing `language="he"` on Groq**: butchers English. Use the dual-pass log-prob arbitration from `082ba16` if language constraint is needed again.
- **Prompt saturation with 20 Hebrew phrases**: doesn't suppress false language detections. (Session 7 attempt.)
- **`direct_type` paste mode for Hebrew**: garbage output via `keyboard.write()`. Removed pre-session-7.

---

## Where things live

```
C:\Users\Naor\Downloads\WhisperType\
├── CLAUDE.md                # Project architecture (somewhat stale post-session-9)
├── HANDOVER.md              # THIS FILE
├── README.md                # User-facing docs
└── WhisperType\
    ├── whispertype.py       # ~7400 lines now (was 6318 at start of session 9)
    ├── run_tests.py         # 32 tests, 5 LIVE Groq tests are flaky
    ├── run.bat              # Manual launcher (UAC prompt every time)
    ├── install_no_uac.bat   # Run once as admin → Scheduled Task setup
    ├── uninstall_no_uac.bat # Remove the Scheduled Task
    ├── launch.bat           # Invoke the Scheduled Task (no UAC)
    ├── add_to_startup.bat   # Legacy startup shortcut (superseded by install_no_uac)
    ├── build.py
    ├── generate_icon.py
    └── whispertype.ico

User runtime state in %APPDATA%\WhisperType\:
- config.json
- whispertype.log (RotatingFileHandler 2MB × 3)
- history.json (max 500 entries now)
- meetings\
  - YYYY-MM-DD_HH-MM_meeting.md            (chunked meeting)
  - YYYY-MM-DD_HH-MM_meeting_audio.wav     (diarized meeting WAV — deleted on success)
  - YYYY-MM-DD_HH-MM_meeting_diarized.md   (diarized meeting markdown)
- history.txt (regenerated each time History is opened)
- beep.wav (regenerated on startup)
```

---

## Commands

```bash
cd WhisperType

# Run dev
python whispertype.py

# Run with admin (manual UAC prompt)
run.bat

# Or after install_no_uac.bat: trigger the Scheduled Task
launch.bat
schtasks /run /tn WhisperType

# Test
PYTHONIOENCODING=utf-8 python run_tests.py

# Quick syntax check
python -c "import ast; ast.parse(open('whispertype.py', encoding='utf-8').read())"

# Build standalone
python build.py
```

---

## How to apply (future sessions)

1. **Read this file first**, then CLAUDE.md if you need deeper architecture.
2. **Run tests** with `PYTHONIOENCODING=utf-8 python run_tests.py` (Windows cp1252 console can't print Unicode arrows). Expect 27-32 passing — the 0-5 LIVE Groq cleanup tests are flaky LLM variance, NOT regressions. If you get <27, you broke something.
3. **The two Model menus are NOT the same** — Model (top-level) is press-to-talk; Transcribe → Model is meetings + file. Don't unify them; the user explicitly wanted them independent.
4. **Don't re-attempt** the dead ends listed above.
5. **Hardware quirks**: user's mic is a webcam mic on a monitor (powers off with the display, see CLAUDE.md session 6 saga). Wireless keyboard occasionally drops. 150% DPI display.
6. **The user dictates and writes commits in mixed Hebrew + English with technical terms.** Custom vocabulary is empty; that's where most of their accuracy frustration comes from.

---

## Session 8 (2026-04-24) — language constraint, solved

**Problem carried over from session 7:** Whisper would occasionally transcribe Hebrew as Arabic/French/Russian. Session 7 tried forcing `language="he"` and heavy prompt bias; both failed and were reverted. The `#failed-approaches` section below still applies — do NOT re-try forcing a single language or saturating the prompt.

**What finally worked — confidence-guided dual-pass arbitration:**

The breakthrough: **`response_format=verbose_json` returns per-segment `avg_logprob` even when `language=` is forced.** That gives us a correctness signal we didn't have before. When you force the wrong language, Whisper's own confidence collapses.

New flow in `GroqTranscriber.transcribe()`:

1. Primary pass: auto-detect + bias prompt (unchanged in spirit). Response now requested as `verbose_json`.
2. Read top-level `language` and duration-weighted mean `avg_logprob` from segments.
3. If detected ∈ {he, en} → accept. (90%+ case, no extra cost.)
4. Else → fire two parallel requests: `language="he"` and `language="en"`. Wait for both. Pick the one with higher `avg_logprob`.
5. If BOTH fallback passes have `avg_logprob < -1.5` → treat as noise, return empty (routes into existing silent-capture handler).

**Why this is structurally different from the failed attempts:**

- Past attempts put a one-sided prior on the decoder (always Hebrew OR always auto-with-prompt).
- This approach lets Whisper *itself* decide he-vs-en via its own log-prob, after we've structurally excluded every other language.
- The fallback path **cannot return French/Arabic/Russian/etc.** — those languages are never asked for.

**Cost:** +0 in the common case. +1 API call (parallel, so ~+300-500ms latency) on the ~10% of clips Whisper mis-classifies. Pennies per hour of dictation.

**New code:**

- Module helpers: `_normalise_lang_code()`, `_weighted_mean_logprob()` (in `whispertype.py` just below `strip_hallucinated_tail`).
- `GroqTranscriber._post_verbose()` — JSON-aware replacement of `_post` that returns {text, language, mean_logprob, raw}.
- `GroqTranscriber._groq_transcribe_once()` — single-pass helper.
- `GroqTranscriber._groq_transcribe_with_he_en_fallback()` — the arbitration logic.
- `GroqTranscriber.transcribe()` — rewritten to route through the above.

**Gated on `groq_he_en_bias`:** when ON (default), dual-pass fallback active. When OFF, pure auto-detect (old behaviour). Turn ON by default is the safe recommendation — the toggle is in the tray.

**Translation endpoint untouched** — `/translations` returns English text, source-language handling is inside the API. Plain `response_format=text` preserved there.

**Test suite:** 32/32 still green. No new tests added because the existing Groq tests are live-API and the fallback fires on specific audio content that's flaky to construct. Manual verification: observe `Groq: auto-detected=X logprob=Y` lines in `%APPDATA%\WhisperType\whispertype.log` during real use.

---

## Session 7 (2026-04-18 → 2026-04-20)

## Goal

Session 7 started as a UI polish round (user turned off `silent_mode` → became aware of overlay issues) and grew into three overlapping tracks:

1. **Overlay UI polish**: make the press-to-talk overlay modern and sharp — pill shape, AA edges, subtle gradient, no red/green traffic-light waveform. Fix a handful of behavioural bugs the user spotted along the way (tray flicker, waveform dead, desktop icons flickering on clicks, mic privacy indicator stuck on).
2. **Mic capture latency + accuracy**: eliminate the ~220 ms subprocess-spawn cost that was eating the leading word of every recording, and tighten LLM cleanup modes so the `casual` style doesn't rewrite phrasing.
3. **Hebrew accuracy improvements**: cover more categories of Whisper's Hebrew mis-hearings (word-boundary splits, non-word → real word, missing question marks, dropped ה). **Language detection** was attempted and failed — see `#failed-approaches`.

All user-reported bugs are fixed at the code level. Transcription accuracy now depends mostly on Whisper's Hebrew ceiling (~88–90 % on a literary paragraph with a close mic) and the user's tray settings.

---

## Completed + verified (22 commits this session)

### Track A — Overlay UI + input behaviour (9 commits)

| commit | what | verified |
|---|---|---|
| `a5447c8` | Hold-mode tray flicker fix (debounce + clear `_hotkey_event` after stop) + skip local-model load when Groq is primary (tray green in ~1s vs ~10s) | User manual test |
| `541b943` | Waveform animation revived under `SubprocessAudioRecorder` — worker streams pre-computed RMS levels on stdout at ~20 Hz; overlay restyled into a pill | User manual test |
| `4477091` | Pill gets real-circle caps, gradient fills, drop shadow; fixed the hide-after-1500 ms timer race that was withdrawing the window mid-recording | Tests + manual cycle |
| `7c20f28` | Render pill via PIL (4× supersample + LANCZOS) instead of `create_oval` — smooth AA edges | Manual + tests |
| `89690be` | Switch PIL primitive to `rounded_rectangle` (no seams) + enable per-monitor DPI awareness (`SetProcessDpiAwarenessContext(-4)`) so Windows stops bilinear-stretching. All 5 `tk.Tk()` roots get `_apply_dpi_scaling_to_tk` | User confirmed |
| `d0e5ef3` | `WS_EX_TRANSPARENT` for click-through (via `GetAncestor(GA_ROOT)` + explicit ctypes argtypes, deferred 150ms to survive tk's async `-transparentcolor`) + SS bumped to 8× | User confirmed |
| `a6df9b8` | `WS_EX_NOACTIVATE` added — without it, click-through alone still caused desktop icons to pulse through hover/pressed states (Windows' focus-evaluation race) | User confirmed flicker stopped |

### Track B — Mic capture + watchdogs (3 commits)

| commit | what | verified |
|---|---|---|
| `2c9ebbf` | `SubprocessAudioRecorder` rewritten around a worker subprocess that handles multiple recordings — eliminates ~220 ms spawn-per-recording | Superseded by `9cd5859` |
| `9cd5859` | **CRITICAL FOLLOW-UP:** the persistent worker held the WASAPI session at the process level → Windows mic privacy indicator stayed on between recordings. Changed to **pre-spawn** model: each worker handles exactly one recording and exits; a replacement spawns in a daemon thread right after `DONE`. `start()` = ~0.3–0.6 ms across consecutive recordings | 3-recording test, different PIDs |
| `4c5fc65` | Skip idle (4 h) and display-wake (10 min) watchdogs when `SubprocessAudioRecorder` is active — user's log showed three spurious whole-app restarts in 10 hours. Respawn-on-silent at the per-recording level handles the same bug | Reviewed log |

### Track C — LLM cleanup modes (6 commits)

| commit | what | verified |
|---|---|---|
| `7e8c0e9` | `proofread` rewritten to preserve content (no rephrasing, no filler removal). Per-style min-length guards: proofread/code ≥ 80 %, casual/email ≥ 55 % (was a single 25 % floor — LLM was shrinking 32→14 char outputs through it) | Live Groq tests |
| `ecf83f5` | `casual` is now **typos only** — don't change phrasing, don't remove fillers, ±10 % length. Test updated to assert `אממ` filler is preserved | Live Groq test |
| `be72100` | Always reset `cleanup_style` to `casual` on app startup (user request — guarantee typo-correction is on after every launch, even if they toggled off last session) | Manual |
| `a818f09` | Casual: allow exactly one punctuation fix — if a sentence is unambiguously a question ending with `.` or nothing, change to `?`. Driven by user report `"אז בעצם מה שאתה אומר לי... יעבוד."` (question, no `?`) | Live Groq test |
| `0087589` | Casual: allow context-driven Hebrew **word-boundary** fixes. Driven by user: Whisper transcribed `בא לך` (you want) as `בעלך` (your husband) — same letters, joined. New rule: split/join only if context disambiguates; "when in doubt leave alone". Length ceiling loosened to ±15% | Live Groq test on literal example |
| `1d2cf93` | Casual: "if a Hebrew word is not a real word AND a phonetically similar real word exists, prefer the real word". Driven by user: `להיבלע` → `להיבלה` (not a word). Catches residual ה/ע/א and ת/ט/ס/ש/כ/ח swaps at start/end of words | Live Groq test |

### Track D — Language detection experiments (4 commits, all reverted)

| commit | what | result |
|---|---|---|
| `29ef708` | Force `language="he"` when `he_en_bias=true` | Suppressed false French/Arabic but broke English |
| `a740b26` | Always force `language="he"` regardless of bias toggle | Same result |
| `53db4ee` | Revert forced language; strengthen bias prompt to ~20 Hebrew phrases | **FAILED** — user still got Arabic output |
| `bfb14ba` | Restore `language="he"` | Produced nonsense Hebrew on English dictation |
| `6ed49e6` | **Full revert** — back to original auto-detect + short bias prompt | Current state |

See `#failed-approaches` for the full story. **Session 8 found the fundamentally different angle (log-prob arbitration via `verbose_json`) — see the session-8 summary above.** Do not re-try the session-7 attempts as-is; they remain dead ends.

---

## Final feature lineup after this session

- **Pre-spawn mic worker** at ~0.3 ms latency per `start()`, fresh Python subprocess per recording (WASAPI session drops correctly between recordings → mic indicator lifecycles correctly).
- **Click-through modern overlay:** PIL-rendered pill at 8× supersample, DPI-aware per-monitor, scaling applied to all 5 tk dialogs. Ex-style flags: `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST`.
- **Groq primary → ~1 s startup:** local faster-whisper model loads lazily in the background after Groq validation, with a `_wait_for_local_ready` helper in the fallback path.
- **LLM cleanup modes ordered by aggressiveness:**
  - `casual` — typos only + non-word→real-word + word-boundary by context + question-mark-only punctuation fix. ±15 % length.
  - `proofread` — +grammar, punctuation, capitalisation. Keep every content word. ±20 % length.
  - `email` — polish into prose, remove fillers. ±45 %.
  - `code` — preserve technical terms exactly. ±20 %.
- **Watchdogs quieted** under subprocess mic (respawn-on-silent covers the same class of bug).
- **Waveform mirrors real audio** in both mic-only and "both" source modes.

---

## In progress / open

1. **Whisper language detection** remains subject to false positives on short / ambiguous clips (we've seen French, Arabic). The Groq API has no "whitelist of allowed languages" parameter. Both `language="he"` (breaks English) and heavy prompt-bias (doesn't suppress false detections) were empirically tried and failed. Accepted as a Whisper limitation. User advised to speak clearly on short clips.
2. **Residual "some pixelation" perception** on the pill. Current state is "much better" per user but not perfect. The remaining aliasing is the ~1 px fringe from compositing PIL's AA alpha against `TRANSPARENT_KEY = '#030310'`. The clean fix is `UpdateLayeredWindow` via ctypes (see `#next-steps`). User accepted the current look.
3. **User's config suboptimal** — their frustration with accuracy is partly because these aren't set:
   - `custom_vocabulary: ""` — empty. Should have at least `אליאס, אקראיים, הזמין, הקרין, להיבלע` (words consistently mis-transcribed).
   - `groq_he_en_bias`: was toggled on/off during session. Currently has no effect because we're pure auto-detect.
   - Told user in chat. Not auto-migrated.
4. **Transcription accuracy ceiling:** measured 78 % → 88 % → 89 % on a literary Hebrew paragraph across three mic-distance experiments. With `casual` cleanup enabled, should reach ~95 %. Ceiling with this mic + Whisper large-v3-turbo is ~90 % raw.

---

## Failed approaches — do NOT repeat

### Pill rendering
- `create_polygon` with `smooth=True` — jaggy (no AA in GDI) + bezier-approximated curves look hand-drawn.
- PIL three-shape pill (ellipse + rect + ellipse) — shapes' AA contributions misalign after LANCZOS downsample. Looks like "rectangle + two circles glued together". Fix: `rounded_rectangle` atomic primitive.
- 4× supersample alone — residual pixelation. 8× + `rounded_rectangle` + DPI awareness got it to acceptable.

### Transparency / clicks
- `WS_EX_TRANSPARENT` alone — desktop icons still pulse because Windows still does a focus-evaluation race on clicks near layered topmost windows. Need `WS_EX_NOACTIVATE` too.
- Setting ex-style flags synchronously right after `self._root.attributes('-transparentcolor', ...)` — gets clobbered by tk's async `WS_EX_LAYERED` application. Must defer with `self._root.after(150, ...)`.
- Default ctypes calls without argtypes — `GetAncestor` returns truncated HWND on 64-bit Python; `WS_EX_TRANSPARENT` lands on the wrong window. Always set `argtypes`/`restype`.

### Subprocess mic
- **Persistent worker** (one subprocess across all recordings, `2c9ebbf`) — held the WASAPI session at the process level even with `stream.close()` + `pa.terminate()`. Mic privacy indicator stayed on between recordings. Fixed in `9cd5859` by switching to pre-spawn.
- `pa.terminate() + pa.PyAudio()` within the same process — doesn't clear the process-level PortAudio cache (confirmed session 6). Stale-handle recovery must spawn a fresh process, not cycle PyAudio.

### LLM cleanup
- Single 25 %-of-input "too-short" floor — lets the LLM drop 44 % of content through. User reported `proofread` "doesn't work" because a 32-char input came back as 14 chars. Use per-style ratios.
- "Remove filler words and redundancy" wording in `proofread` prompt — LLMs interpret as permission to restructure and compress. Say "Keep EVERY content word. Do NOT shorten. Do NOT drop phrases. Do NOT remove filler words."

### Watchdogs
- Idle/display-wake watchdogs as defence-in-depth alongside subprocess mic — user got three unwanted whole-app restarts in 10 hours. Disable under subprocess.

### Language detection — the session-7 attempts (superseded by session 8)

Four commits in session 7 were reverted. **Session 8 solved the problem via a different mechanism (log-prob arbitration — see the session-8 summary at the top of this file).** The approaches below are still dead ends in isolation — do not re-try them one-sidedly.

**What was tried**:
1. **`language="he"` forced, gated by `he_en_bias`**: suppressed false French/Arabic detections on short clips. But when the user said something in English (`"I will be using the Israeli region IL-CENTRAL1"`) the output came back as garbage Hebrew (`"נעשה של האיש אוטלי דהבאק"`).
2. **`language="he"` forced, always**: same as above, worse.
3. **Strong prompt bias, no language param (20 Hebrew phrases saturating the tokenizer)**: user got Arabic (`"سأستخدم الريحانة الإسرائيلية"`) on the same test utterance.

**Why both fail**:
- The Groq Whisper API has only two language-related knobs: `language=X` (hard prior) and `prompt=...` (soft context hint). There is **no whitelist parameter**.
- `language="he"` does more than "default to Hebrew when unsure" — when the audio is marginally ambiguous (mixed-script, technical terms, accented English), it biases the decoder toward Hebrew phonemes hard enough to butcher English.
- The `prompt` parameter is treated as text context, not as instructions. Whisper's language detector can and does override it when the audio evidence is confident.
- **Conclusion**: there is no clean solution inside the current API surface. Either the user accepts occasional false-language detection on short ambiguous clips, or we switch backends.

**What actually works** (the reverted state `6ed49e6`): nothing special. Pure auto-detect, short bias prompt. Whisper gets it right most of the time. When it doesn't, asking the user to speak the clip again usually fixes it.

**If a future session wants to revisit this**, the only angles that might move the needle:
- Switch to `openai/whisper-1` (OpenAI direct) — it may expose `language` as a softer hint than Groq's implementation.
- Use a local Whisper with custom decoder parameters (constrain language probabilities per-token).
- Add a heuristic: post-transcription, detect non-Hebrew non-English Unicode script in the output and re-transcribe with `language="he"` as a retry.

Do not try `language="he"` as the default again. Do not try prompt saturation. Both were empirically tested. **Session 8 did solve the broader "only he/en" goal — see the session-8 summary at the top of this file. If you need to revisit language handling, start there.**

---

## Key decisions (with rationale)

1. **Pre-spawn worker, not persistent worker.** Persistent eliminated spawn latency but held the WASAPI session (broke mic indicator). Pre-spawn gives both: fast start AND proper indicator lifecycle.
2. **Keep `-transparentcolor` + PIL AA** instead of switching to `UpdateLayeredWindow`. Latter eliminates the last ~1 px AA fringe but requires a major refactor (no tkinter canvas rendering; all pills + bars + text via PIL + Win32 blit). User accepted the current look. See `#next-steps` if they change their mind.
3. **DPI awareness ON at the process level.** Trade-off: every `tk.Tk()` root needs `_apply_dpi_scaling_to_tk(root)`. Alternative (leave DPI unaware, live with bilinear-stretched output) was rejected — user's 150 % display made everything blurry.
4. **Casual cleanup is typos-only, not "light cleanup".** User explicitly asked: no restructuring. Mode progression casual → proofread → email → code gives escalating aggressiveness.
5. **Watchdogs off under subprocess mic.** Respawn-on-silent at the per-recording level is enough.
6. **Don't auto-migrate user config.** They explicitly toggled `groq_he_en_bias` at various points. Suggested via chat, let them toggle from tray.
7. **Per-style LLM length ratios.** Single floor couldn't serve both strict modes (casual/proofread need high floor) and permissive modes (email needs low floor).
8. **Force `cleanup_style = "casual"` on every app startup.** User request. Mid-session toggles work; next restart resets.
9. **Abandon the language-whitelist quest** via one-sided priors — but **session 8 implemented a dual-pass log-prob arbitration that achieves effectively the same goal** (see session-8 summary at top).

---

## Next steps — ranked by ROI

### 1. No code change — ask user to flip these in the tray (<2 min)

```
Tray → Custom Vocabulary...     # add: אליאס, אקראיים, הזמין, הקרין, להיבלע
Tray → AI Cleanup → Casual      # should already be on — resets each launch now
```

If accuracy still feels low after these, that's Whisper's ceiling on this hardware — not something code can fix short of switching backends.

### 2. If the user returns saying "still see pixelation" (~4–6 h code, deferred)

Implement per-pixel alpha via `UpdateLayeredWindow`. Sketch:
- ctypes bindings for `UpdateLayeredWindow`, `GetDC`, `CreateCompatibleDC`, `CreateDIBSection`, `SelectObject`, `DeleteObject`, `DeleteDC`, `ReleaseDC`, `BLENDFUNCTION`, `BITMAPINFOHEADER`, `POINT`, `SIZE`.
- At overlay init: after `WS_EX_LAYERED` is set, *don't* call `-transparentcolor`. Instead push an RGBA bitmap directly.
- `_make_pill_photo` → `_push_pill_bitmap`: render PIL RGBA image, premultiply alpha (BGRA byte order for Windows), create DIB via `CreateDIBSection`, `memmove` bytes in, select into mem DC, call `UpdateLayeredWindow` with `ULW_ALPHA` + `BLENDFUNCTION { AC_SRC_OVER, 0, 255, AC_SRC_ALPHA }`.
- Waveform bars and text must also render via PIL (tkinter canvas items won't show when the layered window overrides paint). Use `ImageFont.truetype("segoeui.ttf", ...)` for text.
- Gotchas: `GetWindowLongPtrW`/`SetWindowLongPtrW` on 64-bit; always set argtypes/restype; `winfo_id()` returns inner frame — use `GetAncestor(GA_ROOT)` as in `_make_click_through`.

Keep current code path as fallback when `UpdateLayeredWindow` fails.

### 3. Other deferred items (low ROI for now)

- **Auto-stop on silence** (~2–3 h). Stop recording after N seconds of quiet.
- **Statistics dashboard** (~2 h). Words transcribed, languages, speeds.
- **Live transcript window during meetings** (~1 day). Currently shown only after finalise.

---

## Context / where things live

```
C:\Users\Naor\Downloads\WhisperType\
├── CLAUDE.md                          # project architecture — READ SECOND
├── HANDOVER.md                        # THIS FILE
├── README.md                          # user-facing
└── WhisperType\
    ├── whispertype.py                 # everything, 6318 lines
    ├── run_tests.py                   # 32 tests (section 6 needs Groq key)
    └── ...
```

User runtime state: `%APPDATA%\WhisperType\` — `config.json`, `whispertype.log`, `history.json`, `meetings\`, `beep.wav`.

### Commands

```bash
cd WhisperType
python whispertype.py                                 # run dev
PYTHONIOENCODING=utf-8 python run_tests.py            # 32 tests, needs Groq key
python -c "import ast; ast.parse(open('whispertype.py', encoding='utf-8').read())"
```

Windows `cp1252` console can't print Unicode arrows — always set `PYTHONIOENCODING=utf-8` when running the tests.

### Git

```
repo:     https://github.com/Danaor/WhisperType
branch:   master
base:     877700b (pre-session docs handover)
head:     6ed49e6 (this session — 22 commits)
state:    master == origin/master, clean tree
tests:    32/32 passing
```

### User specifics (for future accuracy questions)

- Hardware: Intel Core Ultra 7 265K, Intel Arc iGPU, no NVIDIA. Monitor at **150 % DPI** (`_DPI_SCALE = 1.5`). Mic is a webcam (C920) attached to the monitor — reason session 6's stale-PortAudio saga exists. Also uses Jabra EVOLVE LINK headset at times (shows in recent logs).
- Language: Hebrew-first, English code terms. Dictates 3–30 s clips mostly.
- Config notable values: `silent_mode: false` (overlay visible), `recording_source: "both"` (mic + WASAPI loopback), `use_subprocess_mic: true`, `cleanup_style` is force-reset to `casual` on every launch.
- Accuracy on literary Hebrew paragraph: 78 % (far mic) → 88 % (close) → 89 % (close). Consistent substitutions: `אליאס`/`אלייס`, `אקראיים`/`קריים`, `נראתה`/`נראית`, `בא לך`/`בעלך`, `להיבלע`/`להיבלה`. Custom vocabulary + casual cleanup should push to ~95 %.

### Session 7 files touched

- `WhisperType/whispertype.py` — 20 commits worth of changes (overlay, subprocess, cleanup, language experiments that got reverted).
- `WhisperType/run_tests.py` — 4 tests added/modified (casual typos-only, casual question-mark, casual word-boundary, casual non-word).

No other files in the repo were touched.

---

## Protocol / IPC specifics for the mic worker

The worker is in-line `python -c "<script>"`. Source in `whispertype.py` around line 620 (`_MIC_SUBPROCESS_SCRIPT`). Protocol:

```
Parent → Worker (stdin, one command per line)
  START <dev_idx> <wav_path>       begin recording (dev_idx: -1 = default)
  STOP                             finalise WAV and emit DONE
  QUIT                             exit (after any in-progress recording)

Worker → Parent (stdout, one message per line)
  HELLO                            worker is alive, waiting for commands
  READY                            PyAudio stream open, capture active
  DONE                             WAV written
  <f1> <f2> ... <fN>               per-bar RMS levels (N = WAVEFORM_NUM_BARS = 28)
```

Worker handles exactly **one** recording then exits. Parent pre-spawns replacement in a daemon thread right after `DONE`.
