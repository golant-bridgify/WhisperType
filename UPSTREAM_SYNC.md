# Upstream Sync

How to pull new commits from the original Danaor/WhisperType repository into
this fork without losing the customisations.

## Remotes

```
origin     https://github.com/golant-bridgify/WhisperType   (this fork, read+write)
upstream   https://github.com/Danaor/WhisperType            (original, read-only)
```

**Never push to `upstream`.**

## Standard sync (merge)

Use merge by default. It preserves the original commit history of both branches
and is safe even after the customisations branch has been pushed.

```bash
# From the project root, on the golan-customizations branch
git fetch upstream
git merge upstream/master

# If there are merge conflicts, open Claude Code and ask it to resolve
# them on this branch. Common conflict zones:
#   WhisperType/whispertype.py around DEFAULT_CONFIG, STYLE_PROMPTS,
#                                    cleanup_style force-reset block,
#                                    CLEANUP_MENU_STYLES, MIN_RATIOS,
#                                    tray menu construction, and the
#                                    SettingsWindow / WhisperTypeApp seam
#   WhisperType/run_tests.py        if upstream tightens cleanup tests

PYTHONIOENCODING=utf-8 python WhisperType/run_tests.py
python WhisperType/build.py

# If tests and build pass, commit the merge
git push origin golan-customizations
```

## Rebase variant (use sparingly)

Only rebase when the customisations branch has NOT been pushed since its last
sync. Rebasing a pushed branch rewrites history and forces collaborators to
reset their local copies.

```bash
git fetch upstream
git rebase upstream/master
# Resolve conflicts, then:
git rebase --continue

PYTHONIOENCODING=utf-8 python WhisperType/run_tests.py
python WhisperType/build.py

# Only push with --force-with-lease, and only if you understand the implications
git push --force-with-lease origin golan-customizations
```

## After a sync

- Re-run the test suite. Target: 34/34 with a Groq API key configured.
- Re-build the standalone exe (`python WhisperType/build.py`). The output is
  `WhisperType/dist/WhisperType.exe`.
- Read upstream's latest HANDOVER.md additions. The author may have added new
  `do NOT re-attempt` entries since the last sync.

## What to do if upstream removes something we depend on

Each customisation lives in a specific spot in `whispertype.py`. If upstream
deletes or moves it:

- **Default hotkey** (Mod 1): `DEFAULT_CONFIG["hotkey"]` in `whispertype.py`.
- **Custom vocabulary default** (Mod 2): `DEFAULT_CONFIG["custom_vocabulary"]`.
- **Email cleanup prompt** (Mod 3): `GroqLLMCleaner.STYLE_PROMPTS["email"]`.
- **WhatsApp cleanup style** (Mod 4): `GroqLLMCleaner.STYLE_PROMPTS["whatsapp"]`,
  `MIN_RATIOS["whatsapp"]`, `CLEANUP_MENU_STYLES` row.
- **No force-reset on startup** (Mod 5): `WhisperTypeApp.__init__` no longer
  contains the `if self.config.get("cleanup_style") != "off"` block.
- **Settings window**: `SettingsWindow` class sits just above `WhisperTypeApp`.
  Tray entry `Settings...` is added between `Model` and `Options`. Method
  `WhisperTypeApp._open_settings_window` is just above `_open_hotkey_dialog`.
- **Cleanup prompt overrides**: `GroqLLMCleaner.__init__` takes a
  `prompt_overrides` arg; `clean()` consults `self.prompt_overrides` before
  `STYLE_PROMPTS`. Both cleaner instantiation sites pass overrides from
  `config["cleanup_prompts_override"]`.

If a sync produces unexplained behaviour, run `git log --oneline upstream/master..HEAD`
to see which fork commits are still applied, and compare against this list.
