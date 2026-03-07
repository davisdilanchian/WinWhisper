# WinWhisper

Local Whisper-based dictation tool for Windows. Replaces the native Win+H dictation with fast, private, GPU-accelerated speech-to-text using OpenAI's Whisper model running entirely on your machine.

Inspired by [MacWhisper](https://goodsnooze.gumroad.com/l/macwhisper).

## Features

- **Win+H hotkey** - intercepts and replaces native Windows dictation
- **Local processing** - all transcription happens on-device, nothing sent to the cloud
- **GPU accelerated** - uses CUDA for fast transcription
- **System tray** - minimal UI with color-coded status (gray=idle, red=recording, blue=transcribing)
- **Auto-paste** - transcribed text is automatically typed into the focused application

## Requirements

- Windows 10/11
- Python 3.11+
- NVIDIA GPU with CUDA support (CPU fallback available)
- A microphone

## Setup

```bash
pip install -r requirements.txt
```

If you don't have PyTorch with CUDA, install it first:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

## Usage

```bash
python winwhisper.py
```

1. Press **Win+H** to start recording (tray icon turns red)
2. Speak your text
3. Press **Win+H** again to stop (icon turns blue while transcribing)
4. Transcribed text is pasted into the focused app

## Configuration

Edit `config.py` to change:

- `MODEL_SIZE` - Whisper model: `tiny`, `base`, `small`, `medium`, `large` (default: `base`)
- `DEVICE` - `cuda` or `cpu` (default: `cuda`)
- `LANGUAGE` - Language code or `None` for auto-detect (default: `en`)
- `HOTKEY` - Hotkey combo (default: `win+h`)

## Quit

Right-click the system tray icon and select **Quit**.
