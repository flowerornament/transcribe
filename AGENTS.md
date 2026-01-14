# Agent Instructions

## Project Overview

YouTube transcription CLI using **Parakeet V3** (MLX) on Apple Silicon.

```bash
transcribe URL                  # basic transcription
transcribe URL -t               # with timestamps
transcribe URL -k               # kebab-case filename
transcribe URL -o out.md        # custom output path
transcribe URL -f               # force overwrite
```

**Key files:**
- `transcribe.py` - Main script (~350 lines)
- `ship.sh` - Symlinks to `~/.nix-config/scripts/transcribe` for PATH access

**Dependencies:**
- `yt-dlp` - YouTube download (installed via Nix)
- `parakeet-mlx` - Transcription (installed via pipx)
- `rich` - Terminal UI (in Nix Python)

## Issue Tracking (bd)

This project uses **bd** (beads) with a dedicated `beads` branch.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd list               # List all open issues
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd create "Title"     # Create new issue
bd sync               # Sync with remote (auto-enabled)
```

## Development Notes

**Testing changes:**
```bash
# Script is symlinked, changes are immediate
transcribe "https://youtube.com/watch?v=..." -t
```

**Architecture:**
1. `get_video_info()` - Fetches metadata via yt-dlp JSON
2. `download_audio()` - Downloads WAV via yt-dlp
3. `transcribe_audio()` - Calls parakeet-mlx CLI, parses SRT output
4. `generate_markdown()` - Formats transcript with optional timestamps

**Paragraph detection:** Groups SRT segments by timing gaps (>1.5s = new paragraph). Constant: `PARAGRAPH_GAP_SECONDS`

**Progress UI:** Marquee animation using `rich.live.Live` with threading during transcription.

## Landing the Plane (Session Completion)

**When ending a work session**, complete ALL steps:

1. **File issues** for remaining work (`bd create`)
2. **Run quality gates** if code changed (test with a short video)
3. **Update issue status** (`bd close <id>`)
4. **Commit and push:**
   ```bash
   git add -A && git commit -m "Description"
   git push
   bd sync
   ```
5. **Verify** - `git status` shows "up to date with origin"

**CRITICAL:** Work is NOT complete until `git push` succeeds.
