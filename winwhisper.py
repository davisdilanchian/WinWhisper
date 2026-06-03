"""WinWhisper - Local Whisper-based dictation for Windows.

Replaces Win+H native dictation with fast local Whisper transcription.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import queue
import struct
import sys
import threading
import time
import numpy as np
import sounddevice as sd
import pyperclip
import pyautogui
import whisper

from config import (
    MODEL_SIZE, SAMPLE_RATE, CHANNELS, DEVICE, LANGUAGE,
    OUTPUT_MODE, TYPE_CHAR_DELAY, STREAMING, STREAM_INTERVAL, INPUT_DEVICE,
    LONG_FORM, FLUSH_INTERVAL, FLUSH_MAX_BUFFER,
    SILENCE_RMS, MIN_SILENCE_MS, TAIL_KEEP_MS,
)
from tray import TrayIcon
from overlay import RecordingOverlay


def _resolve_input_device(spec):
    """Resolve INPUT_DEVICE (None / int index / name substring) to a device
    index. Returns None (Windows default) if it can't be matched.

    When matching by name, prefer the WDM-KS host API: on this machine the
    USB interface delivers pure silence through MME/DirectSound but real audio
    through the raw WDM-KS driver path, so we pick that when available."""
    if spec is None or isinstance(spec, int):
        return spec
    spec_l = str(spec).lower()
    matches = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and spec_l in d["name"].lower():
            api = sd.query_hostapis(d["hostapi"])["name"]
            matches.append((i, api))
    if not matches:
        print(f"Input device matching '{spec}' not found; using system default.")
        return None
    for i, api in matches:
        if "WDM-KS" in api:
            return i
    return matches[0][0]

# pyautogui's fail-safe (mouse to a screen corner) raises mid-paste and would
# kill the transcribe thread. A dictation tool shouldn't be hostage to cursor
# position, so disable it and add a tiny pause between synthetic keystrokes.
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.02

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
HC_ACTION = 0
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_H = 0x48
VK_DUMMY = 0xFF  # undefined key, injected to swallow the lone-Win Start menu

# SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# ssize_t-sized result type for hook callbacks/return values
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_void_p


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


# --- SendInput structures (all three input kinds defined so the union is sized
#     correctly; otherwise SendInput rejects the cbSize) ---
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam) -> LRESULT
HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# IMPORTANT: declare argtypes/restype so 64-bit handles are not truncated.
# Without this, ctypes assumes 32-bit int returns and silently chops the high
# 32 bits off HMODULE/HHOOK values -- which is why the hook never installed.
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int  # BOOL, but returns -1 on error

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.keybd_event.argtypes = [
    wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR,
]
user32.keybd_event.restype = None

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _key_down(vk):
    """True if the given virtual key is currently held."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class WinWhisper:
    def __init__(self):
        self.recording = False
        self.audio_data = []
        self.stream = None
        self.model = None
        self.tray = TrayIcon(on_quit=self.quit)
        self.overlay = RecordingOverlay()
        self.running = True
        self.hook = None
        self._hook_proc_ref = None       # prevent GC of the ctypes callback
        self._h_consumed = False         # guard against key auto-repeat
        self._toggle_queue = queue.Queue()
        self._lock = threading.Lock()
        # Streaming state (LocalAgreement-2)
        self._stream_thread = None
        self._prev_words = []            # previous pass's hypothesis
        self._committed = 0              # number of words already typed
        self._typed_any = False          # whether we've emitted the first word
        # Long-form state
        self._pending = None             # un-emitted audio (np.float32), trimmed as we go
        self._emitted_any = False        # whether any chunk has been emitted this utterance
        self._input_device = _resolve_input_device(INPUT_DEVICE)

    def _set_status(self, state):
        """Drive both the tray icon and the on-screen overlay together.
        state: 'idle' | 'rec' | 'busy'."""
        if state == "rec":
            self.tray.set_recording(True)
            self.overlay.set_recording(True)
        elif state == "busy":
            self.tray.set_transcribing(True)
            self.overlay.set_transcribing(True)
        else:
            self.tray.set_recording(False)
            self.overlay.set_recording(False)

    # ------------------------------------------------------------------
    # Model + audio
    # ------------------------------------------------------------------
    def load_model(self):
        print(f"Loading Whisper '{MODEL_SIZE}' model on {DEVICE}...")
        self.model = whisper.load_model(MODEL_SIZE, device=DEVICE)
        # Warm up: the first GPU inference compiles CUDA kernels and is slow
        # (several seconds). Do it now on a short silent buffer so the first
        # real streaming pass is fast and words appear while you're still talking.
        try:
            warm = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self.model.transcribe(warm, language=LANGUAGE, fp16=(DEVICE == "cuda"))
        except Exception as e:
            print(f"Warmup skipped: {e}")
        print("Model loaded.")

    def start_recording(self):
        with self._lock:
            if self.recording:
                return
            self.recording = True
            self.audio_data = []
        # Reset streaming/long-form/commit state for this utterance.
        self._prev_words = []
        self._committed = 0
        self._typed_any = False
        self._pending = None
        self._emitted_any = False
        self._set_status("rec")
        print("Recording...")

        def callback(indata, frames, time_info, status):
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            device=self._input_device,
            callback=callback,
        )
        self.stream.start()

        if LONG_FORM:
            self._stream_thread = threading.Thread(target=self._longform_loop, daemon=True)
            self._stream_thread.start()
        elif STREAMING:
            self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
            self._stream_thread.start()

    def stop_recording(self):
        with self._lock:
            if not self.recording:
                return
            self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        print("Recording stopped.")

        if not self.audio_data and self._pending is None:
            self._set_status("idle")
            print("No audio captured.")
            return

        # Blue (transcribing) until the final pass finishes.
        self._set_status("busy")
        if LONG_FORM or STREAMING:
            # The worker loop sees recording=False, does a final flush, and
            # clears the status itself. Nothing more to do here.
            pass
        else:
            threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        self._set_status("busy")
        print("Transcribing...")
        try:
            audio = np.concatenate(self.audio_data, axis=0).flatten()
            result = self.model.transcribe(
                audio,
                language=LANGUAGE,
                fp16=(DEVICE == "cuda"),
                condition_on_previous_text=False,
                compression_ratio_threshold=None,
                no_speech_threshold=0.45,
            )
            # Join all segments to avoid truncation.
            text = " ".join(seg["text"].strip() for seg in result["segments"]).strip()
            print(f"Transcribed: {text}")
        except Exception as e:
            print(f"Transcription failed: {e}")
            text = ""
        finally:
            self._set_status("idle")

        if text:
            self._type_text(text)

    # ------------------------------------------------------------------
    # Long-form mode: flush completed sentences every few seconds, trim audio
    # ------------------------------------------------------------------
    def _longform_loop(self):
        """Every FLUSH_INTERVAL, transcribe captured audio, emit completed
        sentences, and discard that audio. On stop, flush whatever remains."""
        elapsed = 0.0
        while self.recording:
            time.sleep(0.1)
            elapsed += 0.1
            if elapsed >= FLUSH_INTERVAL:
                elapsed = 0.0
                self._longform_flush(final=False)
        try:
            self._longform_flush(final=True)
        finally:
            self._set_status("idle")
            print("Done.")

    def _transcribe_text(self, audio):
        """Transcribe an audio buffer and return the joined text."""
        result = self.model.transcribe(
            audio,
            language=LANGUAGE,
            fp16=(DEVICE == "cuda"),
            condition_on_previous_text=False,
            compression_ratio_threshold=None,
            no_speech_threshold=0.45,
        )
        return " ".join(s["text"].strip() for s in result.get("segments", [])).strip()

    def _find_silence_cut(self, audio):
        """Return a sample index at a pause (silence) where it's safe to cut
        without splitting a word, or None if no pause has occurred yet. Picks the
        LATEST qualifying pause (so we emit as much as possible), but never within
        the most recent TAIL_KEEP_MS (you might still be mid-word)."""
        sr = SAMPLE_RATE
        frame = int(0.02 * sr)  # 20 ms analysis frames
        n = audio.size // frame
        if n < 5:
            return None
        frames = audio[:n * frame].reshape(n, frame).astype(np.float64)
        rms = np.sqrt((frames ** 2).mean(axis=1))
        silent = rms < SILENCE_RMS
        min_sil = max(1, int((MIN_SILENCE_MS / 1000.0) * sr / frame))
        tail = int((TAIL_KEEP_MS / 1000.0) * sr / frame)
        best = None
        i = 0
        while i < n:
            if silent[i]:
                j = i
                while j < n and silent[j]:
                    j += 1
                if (j - i) >= min_sil and j <= n - tail:
                    best = (i, j)  # keep scanning for the latest one
                i = j
            else:
                i += 1
        if best is None:
            return None
        i, j = best
        return ((i + j) // 2) * frame  # cut in the middle of the pause

    def _longform_flush(self, final):
        # Pull any newly recorded audio into the pending buffer.
        with self._lock:
            chunks = self.audio_data
            self.audio_data = []
        if chunks:
            new = np.concatenate(chunks, axis=0).flatten()
            self._pending = new if self._pending is None else np.concatenate([self._pending, new])

        if self._pending is None or self._pending.size == 0:
            return
        dur = self._pending.size / SAMPLE_RATE

        if final:
            if dur >= 0.2:
                self._emit_chunk(self._transcribe_text(self._pending))
            self._pending = None
            return

        # Cut only at a real pause so we never split a word.
        cut = self._find_silence_cut(self._pending)
        if cut is None:
            # No pause yet. Only as a last resort (you've talked non-stop for a
            # very long time) cut at the quietest recent point to bound memory.
            if dur < FLUSH_MAX_BUFFER:
                return
            tail = int((TAIL_KEEP_MS / 1000.0) * SAMPLE_RATE)
            region = self._pending[:max(1, self._pending.size - tail)]
            cut = int(np.argmin(np.abs(region)))
            if cut < SAMPLE_RATE // 2:
                return  # nothing meaningful to emit yet

        head = self._pending[:cut]
        self._pending = self._pending[cut:]
        if head.size / SAMPLE_RATE >= 0.2:
            text = self._transcribe_text(head)
            if text:
                self._emit_chunk(text)

    def _emit_chunk(self, text):
        """Emit one chunk of finalized text, with a separating space."""
        text = text.strip()
        if not text:
            return
        out = text if not self._emitted_any else " " + text
        self._emitted_any = True
        print(f"  >> {text}", flush=True)
        if OUTPUT_MODE == "type":
            self._type_out(out)
        else:
            self._paste_text(out)

    # ------------------------------------------------------------------
    # Live streaming (LocalAgreement-2)
    # ------------------------------------------------------------------
    def _transcribe_words(self, audio):
        """Run Whisper on an audio buffer and return its words as a list."""
        result = self.model.transcribe(
            audio,
            language=LANGUAGE,
            fp16=(DEVICE == "cuda"),
            condition_on_previous_text=False,
            compression_ratio_threshold=None,
            no_speech_threshold=0.45,
        )
        text = " ".join(seg["text"].strip() for seg in result["segments"]).strip()
        return text.split()

    def _stream_loop(self):
        """While recording, periodically re-transcribe and emit confirmed words.
        On stop, do a final pass that flushes everything still untyped."""
        elapsed = 0.0
        while self.recording:
            time.sleep(0.1)
            elapsed += 0.1
            if elapsed >= STREAM_INTERVAL:
                elapsed = 0.0
                self._stream_pass(final=False)
        # Recording has stopped -> commit the remaining tail.
        try:
            self._stream_pass(final=True)
        finally:
            self._set_status("idle")
            print("Done.")

    def _stream_pass(self, final):
        snapshot = list(self.audio_data)  # shallow copy is safe under the GIL
        if not snapshot:
            return
        try:
            audio = np.concatenate(snapshot, axis=0).flatten()
            words = self._transcribe_words(audio)
        except Exception as e:
            print(f"Stream transcribe error: {e}")
            return

        if final:
            # End of utterance: everything we haven't typed yet is final.
            self._commit_words(words, len(words))
            return

        # LocalAgreement-2: only commit the prefix this pass agrees on with the
        # previous pass. The unstable tail stays uncommitted until it settles.
        agreed = 0
        for a, b in zip(self._prev_words, words):
            if a == b:
                agreed += 1
            else:
                break
        self._commit_words(words, agreed)
        self._prev_words = words

    def _commit_words(self, words, upto):
        """Type out words[self._committed:upto] live."""
        while self._committed < upto and self._committed < len(words):
            word = words[self._committed]
            self._type_out(("" if not self._typed_any else " ") + word)
            print(f"  + {word}", flush=True)
            self._typed_any = True
            self._committed += 1

    def _type_text(self, text):
        """Emit transcribed text into the focused application."""
        if OUTPUT_MODE == "type":
            try:
                self._type_out(text)
                return
            except Exception as e:
                print(f"Typing failed ({e}); falling back to paste.")
        self._paste_text(text)

    def _send_unicode_char(self, ch):
        """Send a single character as a Unicode keystroke (layout-independent).
        Encodes to UTF-16 so astral chars (emoji etc.) send as surrogate pairs."""
        raw = ch.encode("utf-16-le")
        units = struct.unpack(f"<{len(raw) // 2}H", raw)
        events = (INPUT * (len(units) * 2))()
        for idx, code in enumerate(units):
            down = INPUT(type=INPUT_KEYBOARD)
            down.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)
            up = INPUT(type=INPUT_KEYBOARD)
            up.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
            events[idx * 2] = down
            events[idx * 2 + 1] = up
        user32.SendInput(len(events), events, ctypes.sizeof(INPUT))

    def _type_out(self, text):
        """Type the text out one character at a time so each word appears
        progressively. Delay between chars is configurable (TYPE_CHAR_DELAY)."""
        for ch in text:
            self._send_unicode_char(ch)
            if TYPE_CHAR_DELAY:
                time.sleep(TYPE_CHAR_DELAY)

    def _paste_text(self, text):
        """Instant clipboard paste of the whole transcript."""
        old_clipboard = None
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            pass

        try:
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "v")
            # Let the target app finish reading the clipboard before we restore
            # the previous contents -- restoring too early pastes stale text.
            time.sleep(0.4)
        except Exception as e:
            print(f"Paste failed: {e}")

        if old_clipboard is not None:
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Keyboard hook
    # ------------------------------------------------------------------
    def _suppress_start_menu(self):
        """Inject a dummy keystroke so Windows doesn't treat the Win press as a
        lone tap and open the Start menu once we swallow the H key."""
        user32.keybd_event(VK_DUMMY, 0, 0, 0)
        user32.keybd_event(VK_DUMMY, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        """Runs on the message-loop thread. Keep this FAST: Windows silently
        removes a low-level hook whose callback exceeds ~300ms. All real work
        (opening the audio stream, transcribing) is handed to other threads."""
        if nCode == HC_ACTION:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)

            if vk == VK_H and (_key_down(VK_LWIN) or _key_down(VK_RWIN)):
                if is_down:
                    if not self._h_consumed:
                        self._h_consumed = True
                        self._suppress_start_menu()
                        self._toggle_queue.put(None)  # signal toggle
                    return 1  # block H down (and any auto-repeat) from Windows
                if is_up:
                    self._h_consumed = False
                    return 1  # block H up too

        return user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

    def _control_loop(self):
        """Serializes record start/stop off the hook thread."""
        while self.running:
            try:
                self._toggle_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not self.running:
                break
            try:
                if not self.recording:
                    self.start_recording()
                else:
                    self.stop_recording()
            except Exception as e:
                print(f"Toggle error: {e}")

    def _install_hook(self):
        self._hook_proc_ref = HOOKPROC(self._low_level_keyboard_proc)
        self.hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc_ref,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self.hook:
            err = ctypes.get_last_error()
            print(f"ERROR: Failed to install keyboard hook (GetLastError={err}).")
            sys.exit(1)
        print("Keyboard hook installed. Win+H will now trigger WinWhisper.")

    def _message_loop(self):
        """Required to receive low-level hook callbacks."""
        msg = wintypes.MSG()
        while self.running:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:  # 0 = WM_QUIT, -1 = error
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def quit(self):
        """Clean shutdown."""
        self.running = False
        if self.recording:
            self.stop_recording()
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        user32.PostQuitMessage(0)  # break the message loop
        print("WinWhisper stopped.")

    def run(self):
        print("WinWhisper starting...")
        if self._input_device is not None:
            print(f"Input device: [{self._input_device}] "
                  f"{sd.query_devices(self._input_device)['name']}")
        else:
            print("Input device: Windows default")
        self.load_model()
        self._install_hook()

        self.overlay.start()
        threading.Thread(target=self._control_loop, daemon=True).start()
        threading.Thread(target=self.tray.run, daemon=True).start()

        print("Ready! Press Win+H to start/stop dictation.")
        try:
            self._message_loop()
        except KeyboardInterrupt:
            self.quit()


def _setup_logging():
    """When launched with pythonw (e.g. from the startup .vbs) there is no
    console, so sys.stdout/stderr are None and the first print() would crash the
    app. Redirect both to a log file in that case."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "winwhisper.log")
    logf = open(log_path, "a", buffering=1, encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = logf
    if sys.stderr is None:
        sys.stderr = logf


if __name__ == "__main__":
    _setup_logging()
    app = WinWhisper()
    app.run()
