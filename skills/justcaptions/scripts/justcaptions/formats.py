"""SRT / VTT / JSON caption files."""

import json
import re
from typing import List

from .grouping import Caption, Word


def _timestamp(seconds: float, sep: str) -> str:
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(captions: List[Caption]) -> str:
    blocks = []
    for i, c in enumerate(captions, 1):
        blocks.append(f"{i}\n{_timestamp(c.start, ',')} --> {_timestamp(c.end, ',')}\n{c.text}\n")
    return "\n".join(blocks)


def to_vtt(captions: List[Caption]) -> str:
    blocks = ["WEBVTT\n"]
    for c in captions:
        blocks.append(f"{_timestamp(c.start, '.')} --> {_timestamp(c.end, '.')}\n{c.text}\n")
    return "\n".join(blocks)


def to_json(captions: List[Caption], language=None) -> str:
    return json.dumps(
        {
            "language": language,
            "captions": [
                {
                    "start": round(c.start, 3),
                    "end": round(c.end, 3),
                    "text": c.text,
                    "emoji": c.emoji,
                    "words": [{"word": w.text, "start": round(w.start, 3), "end": round(w.end, 3)} for w in c.words],
                }
                for c in captions
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")


def _seconds(text: str) -> float:
    m = _TIME.search(text)
    if not m:
        raise ValueError(f"bad timestamp: {text!r}")
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_subtitles(text: str) -> List[dict]:
    """SRT or VTT → [{start, end, text}]."""
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                left, right = line.split("-->", 1)
                body = " ".join(lines[i + 1 :]).strip()
                body = re.sub(r"<[^>]+>", "", body)
                if body:
                    segments.append({"start": _seconds(left), "end": _seconds(right), "text": body})
                break
    return segments


def load_captions_json(data: dict) -> List[Caption]:
    """Reads this tool's own JSON output back in."""
    out = []
    for c in data.get("captions", []):
        words = [Word(w["word"], float(w["start"]), float(w["end"])) for w in c.get("words", [])]
        out.append(Caption(float(c["start"]), float(c["end"]), c["text"], words, c.get("emoji")))
    return out
