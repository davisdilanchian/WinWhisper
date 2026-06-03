"""WinWhisper configuration."""

# Whisper model: tiny, base, small, medium, large
MODEL_SIZE = "base"

# Hotkey to toggle recording (Win+H replaces native dictation)
HOTKEY = "win+h"

# Audio settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1

# Input device for recording:
#   None  - use the Windows default input device
#   int   - a specific sounddevice device index
#   str   - a name substring, matched against input-capable devices (prefers the
#           WDM-KS path). The Windows default ("USB Audio CODEC" on MME) delivers
#           SILENCE here, so we pin the USB interface via its working WDM-KS path.
INPUT_DEVICE = "USB Audio CODEC"

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

# Long-form mode: for long dictation. Every FLUSH_INTERVAL seconds it transcribes
# the audio captured so far, emits the COMPLETED sentences, and discards that
# audio (so memory stays flat and you never lose more than a few seconds even if
# something crashes). Unlike STREAMING it does not re-transcribe everything each
# pass, so it stays cheap no matter how long you talk. Takes priority over
# STREAMING when both are on.
LONG_FORM = True

# How often (seconds) long-form checks for a pause to flush at. Lower = it
# notices pauses sooner (more responsive), at the cost of more GPU passes.
FLUSH_INTERVAL = 0.8

# Long-form cuts the transcript ONLY at silence (pauses), never mid-word.
# A gap counts as a pause if the audio stays below SILENCE_RMS for at least
# MIN_SILENCE_MS. TAIL_KEEP_MS of the most recent audio is never cut (you might
# still be mid-word). Raise SILENCE_RMS if a noisy room never registers a pause;
# lower it if it cuts too eagerly.
SILENCE_RMS = 0.012
MIN_SILENCE_MS = 320
TAIL_KEEP_MS = 250

# Hard safety cap (seconds): only if you talk this long with NO detectable pause
# at all, it cuts at the quietest point to bound memory. Set high so normal
# speech (which always has gaps between phrases) is never cut mid-word.
FLUSH_MAX_BUFFER = 18.0
