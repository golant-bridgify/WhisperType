# WhisperType — Handover

*Last session: 2026-04-18 → 2026-04-20 (session 7). Master at `ecf83f5`, pushed to `origin/master`. 29/29 tests pass.*

Read this first, then [CLAUDE.md](CLAUDE.md) for architecture and project history. You should not need anything else to continue.

---

## Goal

Session 7 started as a UI polish session (user turned off `silent_mode` → became aware of overlay issues) and grew into a broader polish + reliability round:

1. Make the press-to-talk overlay modern and sharp (pill shape, AA edges, subtle gradient, no red/green traffic-light waveform).
2. Fix a slew of user-reported behavioural issues: tray icon flicker on release, waveform not animating, desktop-icon shimmer on clicks near overlay, app silently restarting itself, LLM cleanup rewriting instead of proofreading, mic privacy indicator staying visible between recordings, leading words eaten by subprocess spawn.
3. Improve transcription accuracy within the limits of Whisper on Hebrew.

All four user-visible complaints are fixed at the code level. Transcription accuracy is now bounded by Whisper itself (~88–90 % on a literary Hebrew paragraph with a close mic) and by the user's settings that are still at suboptimal defaults in their config.

---

## Completed + verified

### 12 commits this session, all pushed

| commit | what | verified how |
|---|---|---|
| `a5447c8` | Hold-mode tray flicker fix (debounce + clear `_hotkey_event` after stop) + skip local-model load when Groq is primary (tray goes green in ~1s instead of ~10s) | Manual user test confirmed no flicker + fast startup |
| `541b943` | Waveform animation revived under `SubprocessAudioRecorder` — worker streams pre-computed RMS levels on stdout at ~20 Hz; overlay restyled into a pill | Manual user test confirmed animation visible and responsive |
| `4477091` | Pill gets real-circle caps, gradient fills, drop shadow; fix the hide-after-1500 ms timer race that was withdrawing the window mid-recording | 29/29 tests + manual cycle test |
| `7c20f28` | Render the pill via PIL (4× supersample + LANCZOS) instead of `create_oval` — smooth AA edges | Manual test + full test suite |
| `89690be` | Switch PIL primitive to `rounded_rectangle` (no seams between three shapes) + enable per-monitor DPI awareness (`SetProcessDpiAwarenessContext(-4)`) so Windows stops bilinear-stretching the overlay. All five `tk.Tk()` roots get `_apply_dpi_scaling_to_tk` | User confirmed visual fidelity |
| `d0e5ef3` | `WS_EX_TRANSPARENT` for click-through (using `GetAncestor(GA_ROOT)` + explicit ctypes argtypes, deferred by 150 ms to survive tk's async `-transparentcolor` application) + supersample bumped to 8× | User said looks good |
| `a6df9b8` | `WS_EX_NOACTIVATE` added — without it, click-through alone still caused desktop icons to pulse through hover/pressed states because of Windows' focus-evaluation race | User confirmed flicker stopped |
| `2c9ebbf` | `SubprocessAudioRecorder` rewritten around a worker subprocess that handles multiple recordings — eliminated the ~220 ms spawn-per-recording that was eating leading audio | See `9cd5859` for follow-up |
| `9cd5859` | **CRITICAL FOLLOW-UP:** the persistent worker held the WASAPI session at the process level and the mic privacy indicator stayed on between recordings. Changed to a **pre-spawn** model: each worker handles exactly one recording and exits; a replacement is spawned in a daemon thread right after `DONE`. `start()` measured at ~0.3–0.6 ms across consecutive recordings | 3-recording test with different PIDs each time |
| `4c5fc65` | Skip idle (4 h) and display-wake (10 min) watchdogs when `SubprocessAudioRecorder` is active. User's log showed three spurious whole-app restarts in 10 hours; they're redundant now because the subprocess respawn-on-silent handles the same bug at the per-recording level | Reviewed user's log, verified triggers |
| `7e8c0e9` | `proofread` prompt rewritten to preserve content (no rephrasing, no filler removal). Per-style min-length guards: proofread/code ≥ 80 %, casual ≥ 85 %, email ≥ 55 % (was a single 25 % floor — LLM was shrinking 32→14 char outputs through it) | Live Groq test in run_tests.py |
| `ecf83f5` | `casual` is now **typos only** — don't change phrasing, don't remove fillers, ±10 % length. Test updated to assert `אממ` filler is preserved | Live Groq test confirmed |

### Final feature lineup after this session

- **Pre-spawn mic worker** at ~1 ms latency per `start()`, fresh Python subprocess per recording (so WASAPI session drops between recordings → Windows mic indicator lifecycles correctly).
- **Click-through modern overlay:** PIL-rendered pill at 8× supersample, DPI-aware, per-monitor DPI scaling applied to all 5 tk dialogs. `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST` — the canonical click-through overlay flag set.
- **Groq primary → ~1 s startup:** local faster-whisper model is loaded lazily in a background thread after Groq validation, with a `_wait_for_local_ready` helper in the fallback path.
- **LLM cleanup modes ordered by aggressiveness:** casual (typos only) → proofread (+grammar/punctuation) → email (polish) → code (tech terms preserved).
- **Watchdogs quieted:** no more surprise restarts.
- **Waveform mirrors real audio** in both mic-only and "both" source modes (new mix path in `_waveform_updater` maxes subprocess levels with legacy loopback samples).

---

## In progress / open

1. **Residual "some pixelation" perception on the pill.** The user said the current state is "much better" but not perfect. The remaining aliasing is the ~1 px fringe from compositing PIL's AA alpha against `TRANSPARENT_KEY = '#030310'`. The truly-clean fix is `UpdateLayeredWindow` via ctypes (per-pixel alpha, no color-key trick). It was discussed and deferred — the user accepted the current look.
2. **User's config still has sub-optimal cleanup/bias settings** ([config.json](../AppData/Roaming/WhisperType/config.json) as of 2026-04-19):
   - `"groq_he_en_bias": false` — should be `true` for Hebrew/English auto-detect. Told user to toggle via tray → Options → "Bias Groq to Hebrew/English".
   - `"custom_vocabulary": ""` — told user to add frequently mis-transcribed words (e.g. `אליאס, אקראיים, הזמין, הקרין`) via tray → Custom Vocabulary.
   - `"cleanup_style": "off"` as of last check — user was comparing modes. Casual now does the "light" behaviour they originally wanted.
3. **Transcription accuracy:** measured 78 % → 88 % → 89 % across three mic-distance experiments on a literary Hebrew paragraph. The ceiling with this mic + Whisper large-v3-turbo seems to be ~90 %. `proofread` cleanup should push it to ~95 % but the user hasn't tried it on a real text yet.

---

## Failed approaches — do not repeat

These are all from this session. Each was a dead end or a partial fix that a later commit had to undo.

### Pill rendering
- **`create_polygon` with `smooth=True`** (early iteration of `4477091`): jaggy, because Tkinter's GDI rendering has no AA. Also the smoothed polygon visibly approximates curves with bezier segments — looked like hand-drawn.
- **PIL three-shape pill** (ellipse + rect + ellipse, `7c20f28`): the three shapes' AA contributions didn't align after LANCZOS downsample, so the user saw "rectangle + two circles glued together". Fix was `rounded_rectangle` — one atomic primitive (`89690be`).
- **4× supersample**: user still saw residual pixelation. Bumping to 8× helped; `rounded_rectangle` helped more; DPI awareness helped most.

### Transparency / clicks
- **`WS_EX_TRANSPARENT` alone**: desktop icons still pulse on clicks near the overlay because Windows still does a focus-evaluation race on clicks near a layered topmost window. Needed `WS_EX_NOACTIVATE` in addition.
- **Setting `WS_EX_TRANSPARENT` synchronously right after `self._root.attributes('-transparentcolor', ...)`**: it gets clobbered because tk applies `WS_EX_LAYERED` asynchronously and overwrites the ex-style later. Fix was `self._root.after(150, self._make_click_through)`.
- **Default ctypes calls (no argtypes)**: `GetAncestor` returned truncated HWND values on 64-bit Python, so `WS_EX_TRANSPARENT` was being applied to the inner tkinter frame (which has no effect) instead of the top-level window. Always set `argtypes`/`restype` explicitly for Win32 calls.

### Subprocess mic
- **Persistent worker** (`2c9ebbf` — superseded by `9cd5859` the next commit): held the WASAPI session at the process level. Even with `stream.close()` + `pa.terminate()` between recordings, the Windows mic privacy indicator stayed visible until the subprocess exited. The user noticed this immediately. Pre-spawn (worker exits after each recording, parent spawns the next one in the background) was the fix.
- **`pa.terminate() + pa.PyAudio()` within the same process to refresh PortAudio**: per the session-6 findings, this doesn't clear the process-level cache. That's why the stale-handle recovery is `_kill_worker` → spawn a fresh process, not a `terminate`/`init` cycle.

### LLM cleanup
- **Single 25 %-of-input "too-short" floor**: lets the LLM drop 44 % of content through. User reported `proofread` "doesn't work" because a 32-char input came back as 14 chars. Fixed with per-style ratios (see `7e8c0e9`).
- **Prompt wording "remove filler words and redundancy" in `proofread`**: LLMs interpret this as permission to restructure and compress. The new `proofread` prompt explicitly says "Keep EVERY content word. Do NOT shorten… Do NOT drop phrases… Do NOT remove filler words."

### Watchdogs
- **Keeping idle/display-wake watchdogs on as defence-in-depth alongside subprocess mic**: the user had three unwanted whole-app restarts in 10 hours because of these. Disable them when the subprocess path is active.

---

## Key decisions (with rationale)

1. **Pre-spawn worker, not persistent worker.** The persistent model eliminated spawn latency but held the WASAPI session at the process level, breaking the Windows mic privacy indicator lifecycle. Pre-spawn gives us both: fast start (~0.3 ms) AND proper indicator behaviour.
2. **Keep `-transparentcolor` + PIL AA** instead of switching to `UpdateLayeredWindow` with per-pixel alpha. The latter would eliminate the last ~1 px AA fringe but requires a major refactor (no more tkinter canvas rendering; all pills, bars, text via PIL + Win32 blit). User accepted the current look, so the ctypes path is deferred. If you do take it on, plan ~4–6 hours including font rendering and waveform-bar re-architecture.
3. **DPI awareness ON at the process level.** Trade-off: every `tk.Tk()` root needs `_apply_dpi_scaling_to_tk(root)` so fonts render at physical pixels. Alternative was to leave DPI unaware and live with bilinear-stretched PIL output; rejected because the user's 150 % display made everything obviously blurry.
4. **Casual cleanup is typos-only, not "light cleanup".** The user explicitly asked for this — they didn't want *any* restructuring. The mode progression casual→proofread→email→code gives them escalating aggressiveness.
5. **Watchdogs off under subprocess mic.** Respawn-on-silent at the per-recording level is enough. If a recording comes back silent we already respawn the worker; if two come back silent in 2 minutes, we still fall through to the full-app restart path. No reason to pre-emptively kill the app every 4 hours.
6. **Don't auto-migrate user's `groq_he_en_bias` or `custom_vocabulary`.** They explicitly turned bias off, which may have been intentional. Suggested via chat; let them toggle themselves from the tray.
7. **Per-style LLM length ratios.** A single 25 % floor allowed destructive summarisation in strict modes; a single 80 % floor would break email mode's legitimate filler removal. Map: casual 0.85, proofread 0.80, code 0.80, email 0.55.

---

## Next steps — ranked by ROI

### 1. No action needed from code — ask user to flip these in the tray (<2 min, big accuracy win)

```
Tray → Options → "Bias Groq to Hebrew/English"   # turn ON
Tray → Custom Vocabulary...                      # add: אליאס, אקראיים, הזמין, הקרין
Tray → Options → AI Cleanup → Casual             # typos-only
```

If accuracy still feels low after these, that's Whisper's ceiling on this hardware + audio — not something code can fix short of switching models.

### 2. If the user returns saying "still see pixelation" (~4–6 h code, deferred)

Implement per-pixel alpha via `UpdateLayeredWindow`. Sketch:

- Add ctypes bindings for `UpdateLayeredWindow`, `GetDC`, `CreateCompatibleDC`, `CreateDIBSection`, `SelectObject`, `DeleteObject`, `DeleteDC`, `ReleaseDC`, `BLENDFUNCTION`, `BITMAPINFOHEADER`, `POINT`, `SIZE`.
- At overlay init: after `WS_EX_LAYERED` is set, *don't* call `-transparentcolor`. Instead we'll push an RGBA bitmap directly.
- `_make_pill_photo` becomes `_push_pill_bitmap`: render the PIL RGBA image, premultiply alpha (`BGRA` byte order for Windows), create a DIB section via `CreateDIBSection`, `memmove` the bytes in, select into a memory DC, call `UpdateLayeredWindow` with `ULW_ALPHA` and `BLENDFUNCTION { AC_SRC_OVER, 0, 255, AC_SRC_ALPHA }`.
- Waveform bars and text must also be rendered by PIL into the bitmap (tkinter canvas items won't show once the layered window overrides the paint). Use `ImageFont.truetype("segoeui.ttf", ...)` for text.
- Gotchas: `GetWindowLongPtrW`/`SetWindowLongPtrW` on 64-bit; always set argtypes/restype; `winfo_id()` returns the inner frame — use `GetAncestor(GA_ROOT)` as we already do in `_make_click_through`.

Keep the current code path as a fallback when `UpdateLayeredWindow` fails.

### 3. Other deferred items (~ROI-negative for now)

- **Pre-spawned helper with stdin/stdout frame streaming** (mentioned as a nice-to-have in session 6 handover). Replaced by session 7's pre-spawn worker — latency is already at ~0.3 ms, no action needed.
- **Auto-stop on silence** (~2–3 h).
- **Statistics dashboard** (~2 h).
- **Live transcript window during meetings** (~1 day).

---

## Context / where things live

```
C:\Users\Naor\Downloads\WhisperType\
├── CLAUDE.md                          # project architecture — READ SECOND
├── HANDOVER.md                        # THIS FILE
├── README.md                          # user-facing
└── WhisperType\
    ├── whispertype.py                 # everything, ~5,900 lines
    ├── run_tests.py                   # 29 tests (section 6 needs Groq key)
    └── …
```

User runtime state: `%APPDATA%\WhisperType\` — `config.json`, `whispertype.log`, `history.json`, `meetings\`, `beep.wav`.

### Commands

```bash
cd WhisperType
python whispertype.py                                 # run dev
python run_tests.py                                   # 29 tests, needs Groq key for section 6
python -c "import ast; ast.parse(open('whispertype.py', encoding='utf-8').read())"
```

Console under Windows `cp1252` can't print some Unicode arrows; if `run_tests.py` chokes on that, set `PYTHONIOENCODING=utf-8`.

### Git

```
repo:     https://github.com/Danaor/WhisperType
branch:   master
base:     877700b (pre-session docs handover)
head:     ecf83f5 (this session)
state:    master == origin/master, clean tree
tests:    29/29 passing
```

### User specifics (for future accuracy questions)

- Hardware: Intel Core Ultra 7 265K, Intel Arc iGPU, no NVIDIA. Monitor at **150 % DPI** (`_DPI_SCALE = 1.5`). Mic is a webcam (C920) attached to the monitor — the reason session 6's stale-PortAudio saga exists.
- Language: Hebrew-first, English code terms. Dictates 3–30 s clips mostly.
- Config: `silent_mode: false` (overlay visible), `recording_source: "both"` (mic + WASAPI loopback), `use_subprocess_mic: true`.
- Accuracy measured on a literary Hebrew paragraph: 78 % (farther mic) → 88 % (closer mic) → 89 % (closer again). Consistent substitutions on `אליאס`/`אלייס`, `אקראיים`/`קריים`, `נראתה`/`נראית`. Custom vocabulary + casual cleanup should push to ~95 %.

### Session 7 files touched

- `WhisperType/whispertype.py` — 11 commits worth of change (overlay, subprocess, cleanup)
- `WhisperType/run_tests.py` — one change (casual test assertion in `ecf83f5`)

No other files in the repo were touched.
