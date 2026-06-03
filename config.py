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

# Output mode:
#   "type"  - types the text out so each word appears progressively (typewriter feel)
#   "paste" - instant clipboard paste of the whole transcript at once (fastest)
OUTPUT_MODE = "paste"

# Delay between characters when OUTPUT_MODE == "type" (seconds). Larger = slower,
# more visible typing. 0 types as fast as possible. In streaming mode keep this
# at 0 -- the "live" feel comes from words arriving as you speak, not from a
# per-character animation, and any delay just makes it feel sluggish.
TYPE_CHAR_DELAY = 0

# Live streaming: when True, words are typed out AS YOU SPEAK (after the first
# Win+H) instead of all at once when you stop. Works by re-transcribing the
# growing audio every STREAM_INTERVAL seconds and committing only words that two
# consecutive passes agree on. When False, transcription happens once on stop
# and the whole transcript is emitted at once (fastest; no live preview).
STREAMING = False

# How often (seconds) to re-transcribe while recording in streaming mode. Lower
# = words appear sooner but more GPU work each second. 0.5 keeps it feeling live;
# a word still needs to appear in two consecutive passes before it's typed, so
# the first words land ~1s after you start speaking.
STREAM_INTERVAL = 0.4
