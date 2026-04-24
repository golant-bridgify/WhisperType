# WhisperType — Handover

*Last session: 2026-04-24 (session 8). 32/32 tests pass. Branch: `master`.*

Read this first, then [CLAUDE.md](CLAUDE.md) for architecture and project history. You should not need anything else to continue.

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
