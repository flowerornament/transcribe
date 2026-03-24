#!/usr/bin/env python3
"""
Audio transcription tool using Parakeet V3 (MLX) on Apple Silicon.

Usage:
    transcribe URL                     # YouTube video
    transcribe file.opus               # single audio file
    transcribe a.opus b.mp3            # multiple files
    transcribe ./folder/               # all audio in folder
    transcribe ./folder/ -r            # recursive folder scan
    transcribe file.opus -t            # with timestamps
    transcribe file.opus -k            # kebab-case filename
    transcribe file.opus -o out.md     # custom output path
    transcribe file.opus -f            # force overwrite
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
err_console = Console(stderr=True)

# Paragraph break threshold (seconds of silence between segments)
PARAGRAPH_GAP_SECONDS = 1.5

AUDIO_EXTENSIONS = {'.opus', '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma', '.webm'}


def _format_time(seconds: float, brackets: bool = False) -> str:
    """Convert seconds to MM:SS or HH:MM:SS format."""
    total = int(seconds)
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
    return f"[{time_str}]" if brackets else time_str


def format_timestamp(seconds: float) -> str:
    return _format_time(seconds, brackets=True)


def format_duration(seconds: float) -> str:
    return _format_time(seconds, brackets=False)


def is_youtube_url(url: str) -> bool:
    patterns = [
        r'youtube\.com/watch\?v=',
        r'youtu\.be/',
        r'youtube\.com/embed/',
        r'youtube\.com/v/',
    ]
    return any(re.search(p, url) for p in patterns)


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS


def collect_audio_files(path: Path, recursive: bool = False) -> list[Path]:
    if path.is_file():
        if is_audio_file(path):
            return [path]
        console.print(f"[yellow]Skipping non-audio file:[/yellow] {path}")
        return []
    elif path.is_dir():
        if recursive:
            return sorted(f for f in path.rglob('*') if is_audio_file(f))
        return sorted(f for f in path.iterdir() if is_audio_file(f))
    console.print(f"[red]Not found:[/red] {path}")
    return []


def sanitize_filename(title: str, kebab: bool = False) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    if kebab:
        safe = re.sub(r'\s+', '-', safe.lower())
    return safe[:80]


def get_video_info(url: str) -> dict:
    print("Fetching video info...")
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", "chrome",
        "--no-check-formats",
        "--dump-json",
        "--no-download",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error getting video info: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    return 0


def convert_to_wav(input_path: Path, output_dir: Path) -> Path:
    if input_path.suffix.lower() == '.wav':
        return input_path
    wav_path = output_dir / f"{input_path.stem}.wav"
    console.print(f"  Converting {input_path.suffix} to wav...")
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-ar", "16000",  # 16kHz (optimal for speech recognition)
        "-ac", "1",      # mono
        "-y",
        str(wav_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")
    return wav_path


def download_audio(url: str, output_path: Path) -> None:
    print("Downloading audio...")
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", "chrome",
        "--no-check-formats",
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
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
    time_part, ms_part = timestamp.split(',')
    h, m, s = time_part.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms_part) / 1000


def parse_srt(content: str) -> list:
    segments = []
    blocks = content.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                timestamp_line = lines[1]
                start_ts, end_ts = timestamp_line.split(' --> ')
                start = parse_srt_timestamp(start_ts.strip())
                end = parse_srt_timestamp(end_ts.strip())
                text = ' '.join(lines[2:]).strip()
                if text:
                    segments.append({'start': start, 'end': end, 'text': text})
            except (ValueError, IndexError):
                continue
    return segments


def transcribe_audio(audio_path: Path) -> dict:
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

    marquee_text = "TRANSCRIBING \u2022 "
    width = 24
    pos = 0

    with Live(Text(""), refresh_per_second=10, transient=True) as live:
        while thread.is_alive():
            display = (marquee_text * 3)[pos:pos + width]
            live.update(Text(display, style="bold blue"))
            pos = (pos - 1) % len(marquee_text)
            thread.join(timeout=0.1)

    if result.returncode != 0:
        raise RuntimeError(f"parakeet-mlx failed: {result.stderr.strip()}")

    srt_files = list(audio_path.parent.glob("*.srt"))
    if not srt_files:
        listing = ", ".join(f.name for f in audio_path.parent.iterdir())
        raise RuntimeError(f"No SRT output found (dir contains: {listing})")

    content = srt_files[0].read_text()
    segments = parse_srt(content)

    # Clean up so subsequent transcriptions in same dir don't collide
    srt_files[0].unlink()

    return {"segments": segments}


def generate_markdown(
    title: str,
    source: str,
    duration: float,
    transcription: dict,
    include_timestamps: bool,
) -> str:
    lines = [
        f"# Transcript: {title}",
        "",
        f"**Source:** {source}",
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
        for segment in segments:
            start = segment.get("start", 0)
            text = segment.get("text", "").strip()
            if text:
                lines.append(f"{format_timestamp(start)} {text}")
                lines.append("")
    else:
        paragraphs = []
        current_para = []
        last_end = 0

        for segment in segments:
            start = segment.get("start", 0)
            end = segment.get("end", start)
            text = segment.get("text", "").strip()
            if not text:
                continue

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


def _handle_existing_file(output_path: Path) -> Path | None:
    print(f"\nFile already exists: {output_path}")
    print("  [o] Overwrite")
    print("  [r] Rename (add number)")
    print("  [c] Cancel")
    choice = input("\nChoice [o/r/c]: ").strip().lower()

    if choice == 'c':
        print("Cancelled.")
        return None
    elif choice == 'r':
        base = output_path.stem
        ext = output_path.suffix
        n = 2
        while True:
            new_path = output_path.parent / f"{base} {n}{ext}"
            if not new_path.exists():
                print(f"Will save as: {new_path}")
                return new_path
            n += 1
    return output_path


def transcribe_file(file_path: Path, output_path: Path, include_timestamps: bool) -> bool:
    console.print(f"\n[bold]Transcribing:[/bold] {file_path.name}")
    try:
        duration = get_audio_duration(file_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = convert_to_wav(file_path, Path(tmpdir))
            transcription = transcribe_audio(wav_path)

        markdown = generate_markdown(
            title=file_path.stem,
            source=str(file_path),
            duration=duration,
            transcription=transcription,
            include_timestamps=include_timestamps,
        )

        output_path.write_text(markdown)
        console.print(f"[green]\u2713[/green] Saved to: {output_path}")
        return True
    except RuntimeError as e:
        err_console.print(f"[red]Failed:[/red] {file_path.name}: {e}")
        return False


def transcribe_youtube(url: str, args) -> bool:
    video_info = get_video_info(url)
    title = video_info.get("title", "video")
    duration = video_info.get("duration", 0)

    if args.output:
        output_path = Path(args.output)
    else:
        safe_title = sanitize_filename(title, kebab=args.kebab)
        suffix = "-transcript.md" if args.kebab else " Transcript.md"
        output_path = Path(f"{safe_title}{suffix}")

    if output_path.exists() and not args.force:
        output_path = _handle_existing_file(output_path)
        if output_path is None:
            return False

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            download_audio(url, audio_path)
            wav_files = list(Path(tmpdir).glob("*.wav"))
            if wav_files:
                audio_path = wav_files[0]
            transcription = transcribe_audio(audio_path)
    except RuntimeError as e:
        err_console.print(f"[red]Transcription failed:[/red] {e}")
        return False

    markdown = generate_markdown(
        title=title,
        source=url,
        duration=duration,
        transcription=transcription,
        include_timestamps=args.timestamps,
    )

    output_path.write_text(markdown)
    console.print(f"\n[green]\u2713[/green] Saved to: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio using Parakeet V3 on Apple Silicon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  transcribe recording.opus              Transcribe a single file
  transcribe a.opus b.mp3 c.m4a         Transcribe multiple files
  transcribe ./voice-notes/             All audio in a folder (flat)
  transcribe ./voice-notes/ -r          Recursive folder scan
  transcribe recording.opus -t          Include [MM:SS] timestamps
  transcribe recording.opus -o out.md   Custom output path
  transcribe ./folder/ -o ./out/ -f     Batch to output dir, no prompts
  transcribe https://youtu.be/...       YouTube video (requires yt-dlp)

supported formats: .opus .mp3 .wav .m4a .ogg .flac .aac .wma .webm"""
    )
    parser.add_argument(
        "inputs",
        nargs='+',
        help="YouTube URL(s), audio file(s), or directory"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (single input) or directory (multiple inputs)"
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
        help="Overwrite existing files without prompting"
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively scan directories for audio files"
    )

    args = parser.parse_args()

    # Partition inputs into URLs and file paths
    audio_files = []
    youtube_urls = []

    for inp in args.inputs:
        if is_youtube_url(inp):
            youtube_urls.append(inp)
        else:
            path = Path(inp).resolve()
            audio_files.extend(collect_audio_files(path, recursive=args.recursive))

    total = len(audio_files) + len(youtube_urls)
    if total == 0:
        console.print("[red]No audio files or YouTube URLs found.[/red]")
        sys.exit(1)

    # Confirm when processing multiple files from directory scan
    if len(audio_files) > 1 and not args.force:
        console.print(f"\n[bold]Found {len(audio_files)} audio files:[/bold]")
        for f in audio_files:
            console.print(f"  {f}")
        confirm = input(f"\nTranscribe all {len(audio_files)} files? [y/N]: ").strip().lower()
        if confirm not in ('y', 'yes'):
            print("Cancelled.")
            sys.exit(0)

    # Determine output directory for file transcriptions
    output_dir = Path.cwd()
    if args.output and (len(audio_files) > 1 or Path(args.output).is_dir()):
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Process YouTube URLs
    for url in youtube_urls:
        transcribe_youtube(url, args)

    # Process audio files
    succeeded = 0
    for file_path in audio_files:
        safe_name = sanitize_filename(file_path.stem, kebab=args.kebab)
        suffix = "-transcript.md" if args.kebab else ".md"

        if args.output and len(audio_files) == 1 and not Path(args.output).is_dir():
            out_path = Path(args.output)
        else:
            out_path = output_dir / f"{safe_name}{suffix}"

        if out_path.exists() and not args.force:
            out_path = _handle_existing_file(out_path)
            if out_path is None:
                continue

        if transcribe_file(file_path, out_path, args.timestamps):
            succeeded += 1

    if len(audio_files) > 1:
        console.print(f"\n[bold green]Done:[/bold green] {succeeded}/{len(audio_files)} files transcribed")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
