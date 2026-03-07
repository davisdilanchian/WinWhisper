"""WinWhisper - Local Whisper-based dictation for Windows.

Replaces Win+H native dictation with fast local Whisper transcription.
"""

import ctypes
import ctypes.wintypes
import sys
import threading
import time
import numpy as np
import sounddevice as sd
import pyperclip
import pyautogui
import whisper

from config import MODEL_SIZE, SAMPLE_RATE, CHANNELS, DEVICE, LANGUAGE
from tray import TrayIcon

# Windows API constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_H = 0x48

# Structures for low-level keyboard hook
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

HOOKPROC = ctypes.CFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM,
    ctypes.POINTER(KBDLLHOOKSTRUCT)
)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class WinWhisper:
    def __init__(self):
        self.recording = False
        self.audio_data = []
        self.stream = None
        self.model = None
        self.tray = TrayIcon(on_quit=self.quit)
        self.running = True
        self.hook = None
        self.win_pressed = False
        self._hook_proc_ref = None  # prevent GC of callback

    def load_model(self):
        print(f"Loading Whisper '{MODEL_SIZE}' model on {DEVICE}...")
        self.model = whisper.load_model(MODEL_SIZE, device=DEVICE)
        print("Model loaded.")

    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.audio_data = []
        self.tray.set_recording(True)
        print("Recording...")

        def callback(indata, frames, time_info, status):
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
        )
        self.stream.start()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.tray.set_recording(False)
        print("Recording stopped.")

        if not self.audio_data:
            print("No audio captured.")
            return

        # Transcribe in background thread to keep message loop responsive
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        self.tray.set_transcribing(True)
        print("Transcribing...")

        audio = np.concatenate(self.audio_data, axis=0).flatten()
        result = self.model.transcribe(
            audio,
            language=LANGUAGE,
            fp16=(DEVICE == "cuda"),
            condition_on_previous_text=False,
            compression_ratio_threshold=None,
            no_speech_threshold=0.45,
        )
        # Join all segments to avoid truncation
        text = " ".join(seg["text"].strip() for seg in result["segments"]).strip()
        print(f"Transcribed: {text}")

        self.tray.set_transcribing(False)

        if text:
            self._type_text(text)

    def _type_text(self, text):
        """Paste transcribed text into the focused application."""
        old_clipboard = None
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)

        # Restore previous clipboard
        if old_clipboard is not None:
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        """Low-level keyboard hook that intercepts Win+H."""
        if nCode >= 0 and lParam:
            kb = lParam.contents
            vk = kb.vkCode

            # Track Win key state
            if vk in (VK_LWIN, VK_RWIN):
                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self.win_pressed = True
                elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                    self.win_pressed = False

            # Intercept Win+H
            if vk == VK_H and self.win_pressed:
                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    # Suppress key and toggle recording
                    if not self.recording:
                        self.start_recording()
                    else:
                        self.stop_recording()
                    return 1  # Block the keypress from reaching Windows
                elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                    return 1  # Also block key-up

        return user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

    def _install_hook(self):
        """Install the low-level keyboard hook."""
        self._hook_proc_ref = HOOKPROC(self._low_level_keyboard_proc)
        self.hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc_ref,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self.hook:
            print("ERROR: Failed to install keyboard hook. Run as administrator?")
            sys.exit(1)
        print("Keyboard hook installed. Win+H will now trigger WinWhisper.")

    def _message_loop(self):
        """Run the Windows message loop (required for low-level hooks)."""
        msg = ctypes.wintypes.MSG()
        while self.running:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
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
        # Post quit message to break the message loop
        user32.PostQuitMessage(0)
        print("WinWhisper stopped.")

    def run(self):
        print("WinWhisper starting...")
        self.load_model()
        self._install_hook()

        # Run tray icon in a background thread
        tray_thread = threading.Thread(target=self.tray.run, daemon=True)
        tray_thread.start()

        print("Ready! Press Win+H to start/stop dictation.")
        try:
            self._message_loop()
        except KeyboardInterrupt:
            self.quit()


if __name__ == "__main__":
    app = WinWhisper()
    app.run()
