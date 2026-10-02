"""ffmpeg / ffprobe helpers."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        raise SystemExit(
            f"{' and '.join(missing)} not found. Install ffmpeg first "
            "(macOS: brew install ffmpeg · Ubuntu: sudo apt install ffmpeg)."
        )


def run(args: List[str]) -> None:
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"{args[0]} failed:\n{tail}")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def video_info(path: Path) -> Tuple[int, int, float, str]:
    """(display width, display height, duration, audio codec or '')."""
    info = probe(path)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError(f"{path} has no video stream")
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
    rotation = int(video.get("tags", {}).get("rotate", rotation))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    duration = float(info["format"].get("duration") or video.get("duration") or 0)
    return w, h, duration, (audio or {}).get("codec_name", "")


def extract_audio(video: Path, out: Path, start: float = 0.0, duration: float = 0.0) -> Path:
    """16 kHz mono AAC: small enough for the API, what Whisper wants anyway."""
    args = ["ffmpeg", "-y", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(video)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "48k", str(out)]
    run(args)
    return out


def expand_inputs(paths: List[str]) -> List[Path]:
    """Files as given, folders expanded to the videos inside them."""
    out: List[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS and ".captioned" not in f.stem)
        elif p.exists():
            out.append(p)
        else:
            raise SystemExit(f"Not found: {p}")
    return out
