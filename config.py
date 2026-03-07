"""WinWhisper configuration."""

# Whisper model: tiny, base, small, medium, large
MODEL_SIZE = "base"

# Hotkey to toggle recording (Win+H replaces native dictation)
HOTKEY = "win+h"

# Audio settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1

# Device: "cuda" for GPU, "cpu" for CPU
DEVICE = "cuda"

# Language: None for auto-detect, or e.g. "en", "es", "fa"
LANGUAGE = "en"
