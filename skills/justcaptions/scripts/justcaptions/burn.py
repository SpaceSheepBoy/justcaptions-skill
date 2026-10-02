"""Burns rendered captions into a video with a single ffmpeg overlay.

Every caption state becomes one full-frame transparent PNG. The concat
demuxer plays them back as one image stream with exact durations (a blank
frame fills the gaps), so ffmpeg runs one overlay filter no matter how many
captions there are.
"""

from pathlib import Path
from typing import List

from PIL import Image

from . import media
from .grouping import Caption
from .render import Renderer

COPY_AUDIO = {"aac", "mp3", "alac"}


def build_timeline(captions: List[Caption], renderer: Renderer, frames_dir: Path, duration: float) -> Path:
    frames_dir.mkdir(parents=True, exist_ok=True)
    blank = frames_dir / "blank.png"
    Image.new("RGBA", (renderer.W, renderer.H), (0, 0, 0, 0)).save(blank)

    entries = []  # (file, seconds)
    cursor = 0.0
    n = 0
    for caption in sorted(captions, key=lambda c: c.start):
        for start, end, active in renderer.states(caption):
            start, end = max(start, cursor), min(end, duration or end)
            if end - start < 0.001:
                continue
            if start > cursor:
                entries.append((blank, start - cursor))
            n += 1
            path = frames_dir / f"c{n:05d}.png"
            renderer.frame(caption, active).save(path, compress_level=1)
            entries.append((path, end - start))
            cursor = end
    tail = max(duration - cursor, 0.0) + 1.0
    entries.append((blank, tail))

    listing = ["ffconcat version 1.0"]
    for path, seconds in entries:
        listing += [f"file '{path.name}'", f"duration {seconds:.3f}"]
    # The concat demuxer ignores the last entry's duration unless the file
    # is listed once more.
    listing.append(f"file '{entries[-1][0].name}'")
    concat = frames_dir / "captions.ffconcat"
    concat.write_text("\n".join(listing) + "\n")
    return concat


def burn(video: Path, concat: Path, out: Path, audio_codec: str, crf: int = 20) -> Path:
    args = [
        "ffmpeg", "-y", "-v", "error", "-stats",
        "-i", str(video),
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-filter_complex", "[0:v][1:v]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
    ]
    if audio_codec in COPY_AUDIO:
        args += ["-c:a", "copy"]
    elif audio_codec:
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += ["-movflags", "+faststart", str(out)]
    media.run(args)
    return out
