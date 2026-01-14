# transcribe

YouTube transcription CLI using [Parakeet V3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) on Apple Silicon.

## Features

- Fast local transcription (~1 min for 1 hour of audio on M4)
- Auto-paragraphing based on speech pauses
- Optional timestamps
- Markdown output with video metadata

## Installation

**Dependencies:**
```bash
# yt-dlp (via brew, nix, or pipx)
brew install yt-dlp

# parakeet-mlx
pipx install parakeet-mlx
```

**Install script:**
```bash
git clone https://github.com/flowerornament/transcribe.git
cd transcribe
./ship.sh  # symlinks to ~/.nix-config/scripts/transcribe
```

## Usage

```bash
transcribe "https://youtube.com/watch?v=..."           # basic
transcribe "https://youtube.com/watch?v=..." -t        # with timestamps
transcribe "https://youtube.com/watch?v=..." -k        # kebab-case filename
transcribe "https://youtube.com/watch?v=..." -o out.md # custom output
transcribe "https://youtube.com/watch?v=..." -f        # force overwrite
```

## Output

Default filename: `Video Title Transcript.md`

```markdown
# Transcript: Video Title

**Source:** https://youtube.com/watch?v=...
**Duration:** 5:32
**Transcribed:** 2026-01-14

---

## Transcript

First paragraph of transcribed speech, automatically
grouped by natural pauses in the audio.

Second paragraph begins after a pause of 1.5+ seconds.
```

With `-t` timestamps:
```markdown
[00:00] First segment with timestamp.

[00:15] Another segment with timestamp.
```

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3
- ~2.3GB disk space for Parakeet model (downloads on first run)
