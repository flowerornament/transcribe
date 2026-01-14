#!/usr/bin/env python3
"""
YouTube video transcription tool using Parakeet V3 (MLX) on Apple Silicon.

Usage:
    transcribe URL                     # basic transcription
    transcribe URL -t                  # with timestamps
    transcribe URL -k                  # kebab-case filename
    transcribe URL -o out.md           # custom output path
    transcribe URL -f                  # force overwrite
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()

# Paragraph break threshold (seconds of silence between segments)
PARAGRAPH_GAP_SECONDS = 1.5


def _format_time(seconds: float, brackets: bool = False) -> str:
    """Convert seconds to MM:SS or HH:MM:SS format."""
    total = int(seconds)
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
    return f"[{time_str}]" if brackets else time_str


def format_timestamp(seconds: float) -> str:
    """Convert seconds to [MM:SS] or [HH:MM:SS] format."""
    return _format_time(seconds, brackets=True)


def format_duration(seconds: float) -> str:
    """Convert seconds to human-readable duration."""
    return _format_time(seconds, brackets=False)


def is_youtube_url(url: str) -> bool:
    """Check if URL looks like a YouTube video URL."""
    patterns = [
        r'youtube\.com/watch\?v=',
        r'youtu\.be/',
        r'youtube\.com/embed/',
        r'youtube\.com/v/',
    ]
    return any(re.search(p, url) for p in patterns)


def sanitize_filename(title: str, kebab: bool = False) -> str:
    """Convert video title to safe filename."""
    # Remove dangerous filesystem characters
    safe = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    if kebab:
        safe = re.sub(r'\s+', '-', safe.lower())
    return safe[:80]


def get_video_info(url: str) -> dict:
    """Get video metadata using yt-dlp."""
    print("Fetching video info...")
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-download",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error getting video info: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    return json.loads(result.stdout)


def download_audio(url: str, output_path: Path) -> None:
    """Download audio from YouTube video."""
    print("Downloading audio...")
    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "wav",
        "--audio-quality", "0",  # Best quality
        "-o", str(output_path),
        "--progress",
        "--no-warnings",
        url
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Error downloading audio", file=sys.stderr)
        print("Tip: Try running with browser cookies: yt-dlp --cookies-from-browser chrome ...", file=sys.stderr)
        sys.exit(1)


def parse_srt_timestamp(timestamp: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    # Format: 00:00:01,234 -> 1.234
    time_part, ms_part = timestamp.split(',')
    h, m, s = time_part.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms_part) / 1000


def parse_srt(content: str) -> list:
    """Parse SRT content into list of segments with timestamps."""
    segments = []
    blocks = content.strip().split('\n\n')

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            # Line 0: sequence number
            # Line 1: timestamps (start --> end)
            # Line 2+: text
            try:
                timestamp_line = lines[1]
                start_ts, end_ts = timestamp_line.split(' --> ')
                start = parse_srt_timestamp(start_ts.strip())
                end = parse_srt_timestamp(end_ts.strip())
                text = ' '.join(lines[2:]).strip()
                if text:
                    segments.append({
                        'start': start,
                        'end': end,
                        'text': text
                    })
            except (ValueError, IndexError):
                continue

    return segments


def transcribe_audio(audio_path: Path) -> dict:
    """Transcribe audio using parakeet-mlx."""
    import threading
    from rich.live import Live
    from rich.text import Text

    cmd = [
        "parakeet-mlx",
        str(audio_path),
        "--output-format", "srt",
        "--output-dir", str(audio_path.parent),
    ]

    result = None
    def run_transcription():
        nonlocal result
        result = subprocess.run(cmd, capture_output=True, text=True)

    thread = threading.Thread(target=run_transcription)
    thread.start()

    # Marquee animation (stock ticker style)
    marquee_text = "TRANSCRIBING • "
    width = 24
    pos = 0

    with Live(Text(""), refresh_per_second=10, transient=True) as live:
        while thread.is_alive():
            display = (marquee_text * 3)[pos:pos + width]
            live.update(Text(display, style="bold blue"))
            pos = (pos + 1) % len(marquee_text)
            thread.join(timeout=0.1)

    if result.returncode != 0:
        console.print(f"[red]Transcription error:[/red] {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Find the SRT output file
    srt_files = list(audio_path.parent.glob("*.srt"))
    if not srt_files:
        print(f"Looking for output in {audio_path.parent}:")
        for f in audio_path.parent.iterdir():
            print(f"  {f.name}")
        print("Error: Could not find transcription output file", file=sys.stderr)
        sys.exit(1)

    content = srt_files[0].read_text()
    segments = parse_srt(content)

    # Always return segments (needed for paragraph grouping)
    return {"segments": segments}


def generate_markdown(
    video_info: dict,
    transcription: dict,
    url: str,
    include_timestamps: bool
) -> str:
    """Generate markdown output from transcription."""
    title = video_info.get("title", "Untitled Video")
    duration = video_info.get("duration", 0)

    lines = [
        f"# Transcript: {title}",
        "",
        f"**Source:** {url}",
        f"**Duration:** {format_duration(duration)}",
        f"**Transcribed:** {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "---",
        "",
        "## Transcript",
        "",
    ]

    segments = transcription.get("segments", [])

    if include_timestamps:
        # Format with timestamps per segment
        for segment in segments:
            start = segment.get("start", 0)
            text = segment.get("text", "").strip()
            if text:
                timestamp = format_timestamp(start)
                lines.append(f"{timestamp} {text}")
                lines.append("")
    else:
        # Group into paragraphs based on timing gaps (>1.5s = new paragraph)
        paragraphs = []
        current_para = []
        last_end = 0

        for segment in segments:
            start = segment.get("start", 0)
            end = segment.get("end", start)
            text = segment.get("text", "").strip()
            if not text:
                continue

            # New paragraph if gap exceeds threshold
            if current_para and (start - last_end) > PARAGRAPH_GAP_SECONDS:
                paragraphs.append(' '.join(current_para))
                current_para = []

            current_para.append(text)
            last_end = end

        if current_para:
            paragraphs.append(' '.join(current_para))

        for para in paragraphs:
            lines.append(para)
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe YouTube videos using Parakeet V3 on Apple Silicon"
    )
    parser.add_argument(
        "url",
        help="YouTube video URL"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output markdown file path (default: <video-title>.md)"
    )
    parser.add_argument(
        "-t", "--timestamps",
        action="store_true",
        help="Include timestamps at start of each segment"
    )
    parser.add_argument(
        "-k", "--kebab",
        action="store_true",
        help="Use kebab-case filename (lowercase-with-dashes)"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Overwrite existing file without prompting"
    )

    args = parser.parse_args()

    # Validate URL
    if not is_youtube_url(args.url):
        print(f"Error: doesn't look like a YouTube URL: {args.url}", file=sys.stderr)
        sys.exit(1)

    # Get video info
    video_info = get_video_info(args.url)
    title = video_info.get("title", "video")

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        safe_title = sanitize_filename(title, kebab=args.kebab)
        suffix = "-transcript.md" if args.kebab else " Transcript.md"
        output_path = Path(f"{safe_title}{suffix}")

    # Check if file exists
    if output_path.exists() and not args.force:
        print(f"\nFile already exists: {output_path}")
        print("  [o] Overwrite")
        print("  [r] Rename (add number)")
        print("  [c] Cancel")
        choice = input("\nChoice [o/r/c]: ").strip().lower()

        if choice == 'c':
            print("Cancelled.")
            sys.exit(0)
        elif choice == 'r':
            # Find next available number
            base = output_path.stem
            ext = output_path.suffix
            n = 2
            while True:
                new_path = output_path.parent / f"{base} {n}{ext}"
                if not new_path.exists():
                    output_path = new_path
                    break
                n += 1
            print(f"Will save as: {output_path}")

    # Create temp directory for audio
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir) / "audio.wav"

        # Download audio
        download_audio(args.url, audio_path)

        # Find the actual downloaded file (yt-dlp may modify the name)
        wav_files = list(Path(tmpdir).glob("*.wav"))
        if wav_files:
            audio_path = wav_files[0]

        # Transcribe
        transcription = transcribe_audio(audio_path)

    # Generate markdown
    markdown = generate_markdown(
        video_info,
        transcription,
        args.url,
        args.timestamps
    )

    # Write output
    output_path.write_text(markdown)
    console.print(f"\n[green]✓[/green] Saved to: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
