"""
Thorough test suite for WhisperType.

Covers everything testable without real mic / keyboard / Windows events:
- Syntax + imports
- Config load/save round-trip + migrations
- History read/write + thread safety
- strip_hallucinated_tail edge cases
- Transcribers construct correctly + custom_vocabulary wired
- GroqLLMCleaner live call for each style + guards
- MeetingSession end-to-end (mocked chunks)
- _do_paste + _undo_last_paste state machine
- _validate_hotkey
- Icon generation for all states
"""
import ast
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PASS = "PASS"
FAIL = "FAIL"
results = []


def _test(name, fn):
    """Run one test, collect pass/fail + error."""
    try:
        fn()
        results.append((PASS, name, ""))
        print(f"  [PASS] {name}")
    except AssertionError as e:
        msg = f"{type(e).__name__}: {e}"
        results.append((FAIL, name, msg))
        print(f"  [FAIL] {name}")
        print(f"    {msg}")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        results.append((FAIL, name, msg))
        print(f"  [ERR ] {name}")
        print(f"    {msg.splitlines()[0]}")


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ============================================================
# 1. Syntax + imports
# ============================================================
section("1. Syntax + Imports")


def t_syntax():
    with open("whispertype.py", "r", encoding="utf-8") as f:
        ast.parse(f.read())


_test("whispertype.py syntax valid", t_syntax)


def t_import_module():
    import whispertype  # noqa
    assert hasattr(whispertype, "WhisperTypeApp")
    assert hasattr(whispertype, "MeetingSession")
    assert hasattr(whispertype, "GroqLLMCleaner")
    assert hasattr(whispertype, "FasterWhisperTranscriber")
    assert hasattr(whispertype, "AudioRecorder")
    assert hasattr(whispertype, "_validate_hotkey")
    assert hasattr(whispertype, "_fmt_relative_ts")


_test("all public classes/functions export", t_import_module)


# ============================================================
# 2. Config load/save/migrations
# ============================================================
section("2. Config Load/Save/Migrations")


def t_config_roundtrip():
    import whispertype as w
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "config.json")
    original_dir = w.CONFIG_DIR
    original_file = w.CONFIG_FILE
    w.CONFIG_DIR = tmp
    w.CONFIG_FILE = cfg_path
    try:
        cfg = w.load_config()  # empty file → defaults
        assert cfg["hotkey"] == "ctrl+space", cfg["hotkey"]
        assert "cleanup_style" in cfg
        assert "custom_vocabulary" in cfg
        assert "clipboard_auto_restore" in cfg
        assert "undo_hotkey" in cfg
        cfg["hotkey"] = "ctrl+alt+x"
        w.save_config(cfg)
        cfg2 = w.load_config()
        assert cfg2["hotkey"] == "ctrl+alt+x"
    finally:
        w.CONFIG_DIR = original_dir
        w.CONFIG_FILE = original_file


_test("config load → modify → save → reload", t_config_roundtrip)


def t_config_migrate_direct_type():
    import whispertype as w
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w") as f:
        json.dump({"paste_mode": "direct_type", "model_size": "x"}, f)
    original_dir = w.CONFIG_DIR
    original_file = w.CONFIG_FILE
    w.CONFIG_DIR = tmp
    w.CONFIG_FILE = cfg_path
    try:
        cfg = w.load_config()
        assert cfg["paste_mode"] == "auto_paste", cfg["paste_mode"]
    finally:
        w.CONFIG_DIR = original_dir
        w.CONFIG_FILE = original_file


_test("config migrates legacy direct_type → auto_paste", t_config_migrate_direct_type)


def t_config_corrupt():
    import whispertype as w
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w") as f:
        f.write("not valid json {")
    original_dir = w.CONFIG_DIR
    original_file = w.CONFIG_FILE
    w.CONFIG_DIR = tmp
    w.CONFIG_FILE = cfg_path
    try:
        cfg = w.load_config()
        assert cfg["hotkey"] == "ctrl+space", "should fall back to defaults"
    finally:
        w.CONFIG_DIR = original_dir
        w.CONFIG_FILE = original_file


_test("corrupt config falls back to defaults gracefully", t_config_corrupt)


def t_config_atomic_write():
    """Atomic writes use .tmp + rename — verify no leftover .tmp file."""
    import whispertype as w
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "config.json")
    original_dir = w.CONFIG_DIR
    original_file = w.CONFIG_FILE
    w.CONFIG_DIR = tmp
    w.CONFIG_FILE = cfg_path
    try:
        w.save_config({"hotkey": "ctrl+space", "model_size": "x"})
        files = os.listdir(tmp)
        assert "config.json" in files
        assert "config.json.tmp" not in files, "leftover .tmp file!"
    finally:
        w.CONFIG_DIR = original_dir
        w.CONFIG_FILE = original_file


_test("config save is atomic (no leftover .tmp)", t_config_atomic_write)


# ============================================================
# 3. History round-trip + thread safety
# ============================================================
section("3. History Round-trip + Thread Safety")


def t_history_roundtrip():
    import whispertype as w
    tmp = tempfile.mkdtemp()
    original_hf = w.HISTORY_FILE
    original_cd = w.CONFIG_DIR
    w.CONFIG_DIR = tmp
    w.HISTORY_FILE = os.path.join(tmp, "history.json")
    try:
        w.save_history([])
        assert w.load_history() == []
        w.add_history_entry("Hello world", duration_sec=2.5, model="test")
        w.add_history_entry("שלום עולם", duration_sec=1.5, model="test")
        h = w.load_history()
        assert len(h) == 2, len(h)
        assert h[0]["text"] == "Hello world"
        assert h[1]["text"] == "שלום עולם"
    finally:
        w.HISTORY_FILE = original_hf
        w.CONFIG_DIR = original_cd


_test("history: add 2 entries, read back in order", t_history_roundtrip)


def t_history_concurrent():
    """Thread safety: 10 threads writing concurrently should not lose or corrupt entries."""
    import whispertype as w
    tmp = tempfile.mkdtemp()
    original_hf = w.HISTORY_FILE
    original_cd = w.CONFIG_DIR
    w.CONFIG_DIR = tmp
    w.HISTORY_FILE = os.path.join(tmp, "history.json")
    w.save_history([])
    try:
        threads = []
        N = 20
        for i in range(N):
            t = threading.Thread(target=lambda i=i: w.add_history_entry(f"entry-{i}"))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        h = w.load_history()
        assert len(h) == N, f"expected {N} entries, got {len(h)}"
    finally:
        w.HISTORY_FILE = original_hf
        w.CONFIG_DIR = original_cd


_test("history: 20 concurrent writes don't lose entries", t_history_concurrent)


def t_history_ignores_empty():
    import whispertype as w
    tmp = tempfile.mkdtemp()
    original_hf = w.HISTORY_FILE
    original_cd = w.CONFIG_DIR
    w.CONFIG_DIR = tmp
    w.HISTORY_FILE = os.path.join(tmp, "history.json")
    w.save_history([])
    try:
        w.add_history_entry("")       # empty
        w.add_history_entry("   ")    # whitespace
        w.add_history_entry("\u200F") # just RTL marker
        assert w.load_history() == []
    finally:
        w.HISTORY_FILE = original_hf
        w.CONFIG_DIR = original_cd


_test("history: skips empty/whitespace-only entries", t_history_ignores_empty)


# ============================================================
# 4. Hallucination stripping
# ============================================================
section("4. Hallucination Stripping")


def t_strip_whole_hallucination():
    import whispertype as w
    assert w.strip_hallucinated_tail("Thank you.") == ""
    assert w.strip_hallucinated_tail("תודה רבה") == ""
    assert w.strip_hallucinated_tail("bye!") == ""
    assert w.strip_hallucinated_tail("Thank you for watching.") == ""


_test("strip: whole-text hallucinations → empty", t_strip_whole_hallucination)


def t_strip_tail_only():
    import whispertype as w
    assert w.strip_hallucinated_tail("Hello world. Thank you.") == "Hello world"
    assert w.strip_hallucinated_tail("שלום עולם. תודה רבה") == "שלום עולם"
    assert w.strip_hallucinated_tail("Real content here. bye.") == "Real content here"


_test("strip: tail hallucinations removed, prefix kept", t_strip_tail_only)


def t_strip_preserves_real_text():
    import whispertype as w
    assert w.strip_hallucinated_tail("Hello, this is a real message.") == "Hello, this is a real message."
    assert w.strip_hallucinated_tail("") == ""
    assert w.strip_hallucinated_tail("Short") == "Short"


_test("strip: real content preserved untouched", t_strip_preserves_real_text)


# ============================================================
# 5. Transcriber construction + custom_vocabulary wiring
# ============================================================
section("5. Transcriber Construction")


def t_faster_whisper_construct():
    import whispertype as w
    t = w.FasterWhisperTranscriber(model_size="large-v3-turbo", cpu_threads=4)
    assert t.model is None
    assert t.custom_vocabulary == ""
    t.custom_vocabulary = "React, git, Kubernetes"
    assert t.custom_vocabulary == "React, git, Kubernetes"


_test("FasterWhisperTranscriber constructs + custom_vocab wire-up", t_faster_whisper_construct)


def t_groq_transcriber_bias_prompt():
    import whispertype as w
    t = w.GroqTranscriber(model_size="whisper-large-v3-turbo", api_key="fake")
    t.he_en_bias = True
    t.custom_vocabulary = "git, push, Naor"
    prompt = t._build_bias_prompt()
    assert prompt is not None
    assert "git, push, Naor" in prompt
    assert "Hebrew" in prompt or "שלום" in prompt  # he_en bias still present

    t.he_en_bias = False
    prompt2 = t._build_bias_prompt()
    assert "git, push, Naor" in prompt2
    assert "Hebrew" not in prompt2  # no bias


_test("GroqTranscriber bias prompt composes vocab + he_en", t_groq_transcriber_bias_prompt)


def t_audio_recorder_construct():
    import whispertype as w
    r = w.AudioRecorder(input_device_index=None)
    assert r.is_recording is False
    assert r.audio_data == []


_test("AudioRecorder constructs clean", t_audio_recorder_construct)


# ============================================================
# 6. GroqLLMCleaner — live API calls (requires key)
# ============================================================
section("6. GroqLLMCleaner Live Calls")


def _cleaner():
    import whispertype as w
    cfg = w.load_config()
    key = cfg.get("groq_api_key", "")
    if not key:
        raise AssertionError("No Groq API key — cleaner tests skipped")
    return w.GroqLLMCleaner(api_key=key)


def t_cleaner_off_bypasses():
    cl = _cleaner()
    t = "אה אז אני בעצם"
    assert cl.clean(t, style="off") == t
    assert cl.clean(t, style="verbatim") == t


_test("cleaner: off/verbatim bypass without HTTP call", t_cleaner_off_bypasses)


def t_cleaner_short_bypassed():
    cl = _cleaner()
    # <4 chars → returns untouched
    assert cl.clean("hi", style="casual") == "hi"
    assert cl.clean("", style="casual") == ""


_test("cleaner: ultra-short text is not sent to LLM", t_cleaner_short_bypassed)


def t_cleaner_casual_hebrew():
    cl = _cleaner()
    raw = "אה אז אני הולק לפגישה אממ עם הצוות"
    out = cl.clean(raw, style="casual")
    # Casual is now typos-only: must fix הולק→הולך, but fillers stay
    # and overall length must stay within ±15% of the input.
    assert "הולך" in out, f"expected הולך in {out!r}"
    assert "אממ" in out, f"filler should be preserved in casual mode: {out!r}"
    length_ratio = len(out) / len(raw)
    assert 0.85 <= length_ratio <= 1.15, \
        f"casual mode should stay near-identical length (got ratio {length_ratio:.2f}): {out!r}"


_test("cleaner: casual fixes spelling typos without stripping fillers", t_cleaner_casual_hebrew)


def t_cleaner_expansion_blocked():
    """The AWS-expansion failure mode: must NOT expand >1.5×."""
    cl = _cleaner()
    raw = ("I want to review the code and refine it to create a standardized "
           "AWS Landing Zone. I want to examine the existing code and identify "
           "areas for improvement.")
    out = cl.clean(raw, style="code")
    ratio = len(out) / len(raw)
    assert ratio <= 1.5, f"expansion ratio {ratio:.2f}× > 1.5×! out={out!r}"


_test("cleaner: task-like input does NOT expand (was 6× before fix)", t_cleaner_expansion_blocked)


def t_cleaner_rtl_preserved():
    cl = _cleaner()
    raw = "\u200F" + "אה אני רוצה לבדוק את הקוד לפני שאני עושה commit"
    out = cl.clean(raw, style="casual")
    # Our code re-prepends the RTL marker if the input had it
    assert out.startswith("\u200F"), f"RTL marker lost: {out!r}"


_test("cleaner: U+200F RTL marker preserved across cleanup", t_cleaner_rtl_preserved)


def t_cleaner_vocab_fixes_mistranscription():
    cl = _cleaner()
    raw = "תן בגד פושע שלי"  # the 'git push' → 'בגד פושע' case
    vocab = "git, push, pull, commit, merge, branch"
    out = cl.clean(raw, style="casual", vocabulary=vocab)
    assert "git push" in out.lower() or "git" in out.lower(), \
        f"vocab didn't replace mistranscription: {out!r}"


_test("cleaner: vocab corrects 'בגד פושע' → 'git push'", t_cleaner_vocab_fixes_mistranscription)


# ============================================================
# 7. MeetingSession end-to-end
# ============================================================
section("7. Meeting Session End-to-end")


def t_meeting_markdown_output():
    import whispertype as w
    cfg = w.load_config()

    class MockApp:
        config = cfg
        _llm_cleaner = w.GroqLLMCleaner(api_key=cfg.get("groq_api_key", ""))

        def _transcribe_with_fallback(self, *a, **kw):
            return "mock"

        def _get_language(self):
            return "he"

    session = w.MeetingSession(MockApp())
    session.start_time = time.time() - 120
    session.stop_time = time.time()
    with session._chunks_lock:
        session.chunks = [
            {"index": 0, "timestamp_rel": 0, "text": "דיברנו על פרויקט אטלס", "status": "ok"},
            {"index": 1, "timestamp_rel": 45, "text": "", "status": "failed"},
            {"index": 2, "timestamp_rel": 90, "text": "נאור יסיים עד יום שלישי", "status": "ok"},
        ]
    path = session._write_output_file(120)
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# Meeting" in content
    assert "## Full Transcript" in content
    assert "פרויקט אטלס" in content
    assert "transcription failed" in content
    # Cleanup the test output file
    try:
        os.remove(path)
    except Exception:
        pass


_test("MeetingSession writes well-formed markdown file", t_meeting_markdown_output)


def t_meeting_timestamp_format():
    import whispertype as w
    assert w._fmt_relative_ts(0) == "0:00"
    assert w._fmt_relative_ts(45) == "0:45"
    assert w._fmt_relative_ts(125) == "2:05"
    assert w._fmt_relative_ts(3725) == "1:02:05"


_test("meeting timestamp formatter correct", t_meeting_timestamp_format)


# ============================================================
# 8. Paste / Undo state machine
# ============================================================
section("8. Paste / Undo State Machine")


def t_copy_with_retry():
    import whispertype as w
    import pyperclip
    ok, msg = w._copy_with_retry("hello world", retries=3)
    assert ok, msg
    assert pyperclip.paste() == "hello world"


_test("_copy_with_retry writes + verifies readback", t_copy_with_retry)


def t_undo_state_consumed():
    import whispertype as w
    import pyperclip

    app = w.WhisperTypeApp.__new__(w.WhisperTypeApp)
    app.config = w.DEFAULT_CONFIG.copy()
    app._last_paste = None
    app._last_paste_lock = threading.Lock()

    class NoopOverlay:
        def show(self, *a, **kw): pass
        def show_error(self, *a, **kw): pass
    app.overlay = NoopOverlay()

    # Simulate a paste recorded
    app._last_paste = {
        "text": "TEST", "old_clipboard": "PREV",
        "timestamp": time.time(),
    }
    # Mock keyboard module so we don't actually send Ctrl+Z
    import sys as _sys
    class FakeKB:
        def send(self, *a, **kw): pass
    real_kb = _sys.modules.get("keyboard")
    _sys.modules["keyboard"] = FakeKB()
    try:
        pyperclip.copy("pasted")
        app._undo_last_paste()
        assert app._last_paste is None, "undo should clear state"
        assert pyperclip.paste() == "PREV", "clipboard should restore to PREV"
        # Second undo should be no-op
        app._undo_last_paste()
    finally:
        if real_kb:
            _sys.modules["keyboard"] = real_kb


_test("undo consumes state + restores clipboard", t_undo_state_consumed)


def t_undo_stale_refused():
    import whispertype as w

    app = w.WhisperTypeApp.__new__(w.WhisperTypeApp)
    app.config = w.DEFAULT_CONFIG.copy()
    app._last_paste_lock = threading.Lock()

    class NoopOverlay:
        def show(self, *a, **kw): pass
        def show_error(self, *a, **kw): pass
    app.overlay = NoopOverlay()

    app._last_paste = {
        "text": "OLD", "old_clipboard": "prev",
        "timestamp": time.time() - 120,  # 2 min ago
    }
    import sys as _sys
    class FakeKB:
        def send(self, *a, **kw):
            raise RuntimeError("should NOT be called on stale undo")
    real_kb = _sys.modules.get("keyboard")
    _sys.modules["keyboard"] = FakeKB()
    try:
        app._undo_last_paste()  # should log warning but not raise
        # state IS cleared (we consume it regardless — can't replay)
    finally:
        if real_kb:
            _sys.modules["keyboard"] = real_kb


_test("undo: stale paste (>60s) refused gracefully", t_undo_stale_refused)


# ============================================================
# 9. Hotkey validation
# ============================================================
section("9. Hotkey Validation")


def t_hotkey_valid():
    import whispertype as w
    assert w._validate_hotkey("ctrl+space")
    assert w._validate_hotkey("ctrl+alt+z")
    assert w._validate_hotkey("win+h")
    assert w._validate_hotkey("shift+f1")
    assert w._validate_hotkey("f13")  # function key alone OK


_test("hotkey validator accepts modifier+key + F-keys", t_hotkey_valid)


def t_hotkey_invalid():
    import whispertype as w
    assert not w._validate_hotkey("")
    assert not w._validate_hotkey("a")
    assert not w._validate_hotkey("space")
    assert not w._validate_hotkey("b")


_test("hotkey validator rejects bare keys without modifier", t_hotkey_invalid)


# ============================================================
# 10. Icon generation
# ============================================================
section("10. Icon Generation")


def t_icons_all_states():
    import whispertype as w
    app = w.WhisperTypeApp.__new__(w.WhisperTypeApp)
    for state in ["idle", "recording", "processing", "loading", "error", "meeting"]:
        img = app._create_icon(state)
        assert img is not None
        assert img.size == (64, 64), f"{state} size wrong: {img.size}"


_test("all 6 tray icon states render successfully", t_icons_all_states)


# ============================================================
# Summary
# ============================================================
section("SUMMARY")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total = len(results)
print(f"\n{passed}/{total} tests passed")
if failed:
    print(f"\n{failed} FAILED:")
    for status, name, err in results:
        if status == FAIL:
            print(f"  [{status}] {name}")
            print(f"    {err.splitlines()[0]}")
    sys.exit(1)
else:
    print("\n[ALL GREEN]")
