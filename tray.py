"""System tray icon for WinWhisper."""

import pystray
from PIL import Image, ImageDraw


def _create_icon(color):
    """Create a simple colored circle icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return img


# Pre-generate icons
ICON_IDLE = _create_icon((100, 100, 100, 255))        # Gray - idle
ICON_RECORDING = _create_icon((220, 40, 40, 255))     # Red - recording
ICON_TRANSCRIBING = _create_icon((40, 120, 220, 255)) # Blue - transcribing


class TrayIcon:
    def __init__(self, on_quit=None):
        self._on_quit = on_quit
        self._icon = None

    def _quit_action(self, icon, item):
        icon.stop()
        if self._on_quit:
            self._on_quit()

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("WinWhisper", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit_action),
        )
        self._icon = pystray.Icon("WinWhisper", ICON_IDLE, "WinWhisper - Idle", menu)
        self._icon.run()

    def set_recording(self, active):
        if self._icon:
            if active:
                self._icon.icon = ICON_RECORDING
                self._icon.title = "WinWhisper - Recording..."
            else:
                self._icon.icon = ICON_IDLE
                self._icon.title = "WinWhisper - Idle"

    def set_transcribing(self, active):
        if self._icon:
            if active:
                self._icon.icon = ICON_TRANSCRIBING
                self._icon.title = "WinWhisper - Transcribing..."
            else:
                self._icon.icon = ICON_IDLE
                self._icon.title = "WinWhisper - Idle"
