# WinWhisper - Project Status

## What we are doing
Building a local Whisper-based dictation tool for Windows that replaces the native Win+H dictation with GPU-accelerated local transcription.

## Current progress
- Initial version complete with all core features
- Win+H interception via low-level keyboard hook (blocks native dictation)
- Audio recording via sounddevice
- Whisper transcription on GPU (CUDA)
- Auto-paste via clipboard into focused app
- System tray icon with status colors

## Completed steps
- Project structure created
- Dependencies installed (openai-whisper, sounddevice, pystray, pyautogui, etc.)
- Core app: winwhisper.py, tray.py, config.py
- Win+H keyboard hook that blocks native Windows dictation
- README with setup and usage docs
- 2026-06-02: Consolidated to a single canonical copy at C:\Users\18187\Documents\WinWhisper
  (old E:\WinWhisper and ~\github_audit_public\WinWhisper clones are stale). Startup-folder
  launcher (winwhisper.vbs) repointed here and switched to pythonw (no console window).
- 2026-06-02: Fixed three bugs:
  1. Hook never installed -> ctypes argtypes/restype were unset, so 64-bit HMODULE/HHOOK
     handles were truncated to 32 bits. Now all Win32 prototypes are declared.
  2. Hook silently died (Win+H stopped working) -> audio start/stop ran inside the hook
     callback, exceeding Windows' ~300ms LowLevelHooksTimeout. Work moved to a control thread;
     the hook now only signals a queue and returns instantly.
  3. Erratic toggling / dictations stomping each other -> key auto-repeat fired repeated
     toggles. Now guarded with an _h_consumed latch (toggle once per physical press).
  Also: dummy-key injection to suppress the lone-Win Start menu, hardened clipboard
  paste/restore timing, pyautogui FAILSAFE disabled, transcription wrapped in try/except.
- 2026-06-02: Added Unicode SendInput output (OUTPUT_MODE "type") + live streaming
  (STREAMING) using LocalAgreement-2: re-transcribe the growing buffer every
  STREAM_INTERVAL (0.4s) and only type words two consecutive passes agree on, so the
  unstable tail isn't typed then corrected. Warmup transcribe at startup kills the slow
  first-inference. TYPE_CHAR_DELAY=0 (typewriter delay felt sluggish while streaming).
- 2026-06-02: Fixed pythonw crash -> under pythonw (the .vbs launcher) sys.stdout is None,
  so the first print() crashed the app. _setup_logging() now redirects stdout/stderr to
  winwhisper.log when there's no console. This is also the app's log file.

## GOTCHAS (read before debugging "it won't run" / "behaves like an old version")
- Microsoft Store Python: the process is named **python3.11.exe / pythonw3.11.exe**, NOT
  python.exe/pythonw.exe. `Stop-Process -Name python` silently matches nothing. To kill
  WinWhisper, match on command line:
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%winwhisper%'" |
      Where-Object { $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Multiple stale instances stacking up (each with its own Win+H hook) was the cause of
  "buggy"/duplicate behavior. ALWAYS confirm exactly ONE instance after launching.
- Launch detached like startup does: `Start-Process wscript.exe winwhisper.vbs` (pythonw,
  hidden). Logs go to winwhisper.log. A `python -u winwhisper.py` console launch is only for
  live-debug visibility.

## Next steps
- DECISION 2026-06-02: User chose instant batch over streaming (streaming always lags batch
  because openai-whisper pads every clip to 30s, so each pass is ~full cost). Shipping config:
  STREAMING=False, OUTPUT_MODE="paste". Streaming code retained but off.
- If we ever want fast live streaming: switch to faster-whisper (CTranslate2) + transcribe
  only the unconfirmed tail instead of the whole growing buffer.
- Commit + push to GitHub (davisdilanchian/WinWhisper).

## Future goals
- Configurable hotkey via tray menu
- Multiple language support toggle
- Audio level indicator in tray
- faster-whisper backend for lower-latency streaming on long dictation
