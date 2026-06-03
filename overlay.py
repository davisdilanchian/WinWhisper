"""Always-on-top recording indicator overlay.

A small frameless banner near the top of the screen that's hard to miss:
blinking red "Recording" while capturing, blue "Transcribing..." while the
model is working, hidden when idle. Runs its own Tk event loop on a daemon
thread; all widget access happens on that thread (driven by a state flag).

The window is marked WS_EX_NOACTIVATE so it never steals keyboard focus -- if
it did, dictated text would land in the banner instead of your app.
"""

import ctypes
import threading

try:
    import tkinter as tk
    _TK_OK = True
except Exception:
    _TK_OK = False

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008


class RecordingOverlay:
    def __init__(self):
        self._state = "idle"   # "idle" | "rec" | "busy"
        self._shown = False
        self._root = None
        self._label = None
        self._blink = True

    def start(self):
        if not _TK_OK:
            print("tkinter unavailable; on-screen overlay disabled.")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        root = tk.Tk()
        self._root = root
        root.overrideredirect(True)              # no title bar / border
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.92)
        except Exception:
            pass
        root.configure(bg="#101010")
        w, h = 200, 46
        sw = root.winfo_screenwidth()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+16")
        self._label = tk.Label(root, text="", bg="#101010",
                               font=("Segoe UI", 15, "bold"))
        self._label.pack(expand=True, fill="both")
        root.withdraw()
        root.update_idletasks()
        self._make_noactivate()
        self._tick()
        root.mainloop()

    def _make_noactivate(self):
        """Stop the banner from ever taking focus (so paste/typing stays in the
        user's app) and from appearing in alt-tab."""
        try:
            hwnd = self._root.winfo_id()
            u = ctypes.windll.user32
            ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                             ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        except Exception as e:
            print(f"Overlay no-activate setup skipped: {e}")

    def _tick(self):
        try:
            st = self._state
            if st == "idle":
                if self._shown:
                    self._root.withdraw()
                    self._shown = False
            else:
                if not self._shown:
                    self._root.deiconify()
                    self._root.attributes("-topmost", True)
                    self._shown = True
                if st == "rec":
                    self._blink = not self._blink
                    self._label.config(text="●  Recording",
                                       fg="#ff3b30" if self._blink else "#5a1512")
                else:  # busy
                    self._label.config(text="…  Transcribing", fg="#3b82f6")
        except Exception:
            pass
        if self._root is not None:
            self._root.after(450, self._tick)

    # Thread-safe: just flip the state flag; _tick applies it on the Tk thread.
    def set_recording(self, on):
        self._state = "rec" if on else "idle"

    def set_transcribing(self, on):
        self._state = "busy" if on else "idle"
