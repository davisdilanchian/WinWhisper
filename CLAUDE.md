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
- 2026-06-02: MIC FIX (was capturing silence!) -> Windows feeds apps pure silence on the
  default MME/DirectSound path for the user's USB interface (Shure); only the WDM-KS path
  carries real audio. INPUT_DEVICE="USB Audio CODEC" + _resolve_input_device() prefers the
  WDM-KS host API. Without this, every transcription came back empty.
- 2026-06-02: LONG-FORM mode (now the shipping default) -> for dictating continuously. Every
  FLUSH_INTERVAL it transcribes captured audio, emits finished text, and trims it (memory
  stays flat, never lose more than the buffer). Cuts ONLY at detected silence
  (_find_silence_cut: >=MIN_SILENCE_MS below SILENCE_RMS, never within last TAIL_KEEP_MS) so
  words are never split. FLUSH_MAX_BUFFER is just a no-pause hard cap.
- 2026-06-02: On-screen recording indicator (overlay.py) -> frameless top-center banner,
  blinking red "Recording" / blue "Transcribing", WS_EX_NOACTIVATE so it never steals focus
  (critical: otherwise dictated text would land in the banner). Tray icon was too easy to miss.

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
- SHIPPING CONFIG 2026-06-02: LONG_FORM=True, OUTPUT_MODE="paste", INPUT_DEVICE="USB Audio
  CODEC". FLUSH_INTERVAL=0.8, MIN_SILENCE_MS=320, SILENCE_RMS=0.012, FLUSH_MAX_BUFFER=18.
  STREAMING code retained but off (LONG_FORM takes priority).
- Tuning if user reports issues: laggy in quiet room -> lower MIN_SILENCE_MS; cuts on micro-
  pauses -> raise it; noisy room never flushes -> raise SILENCE_RMS.
- If we ever want fast word-by-word live: switch to faster-whisper (CTranslate2).

## Future goals
- Configurable hotkey via tray menu
- Multiple language support toggle
- Audio level indicator in tray
- faster-whisper backend for lower-latency streaming on long dictation
