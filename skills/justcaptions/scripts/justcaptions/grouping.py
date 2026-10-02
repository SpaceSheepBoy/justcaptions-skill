"""Turns timed words into on-screen caption groups."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from .styles import COMPACT_LINE_CHARS, LATIN_CAPTION_CHARS

SENTENCE_END = re.compile(r"[.!?。！？…]$")
CLAUSE_END = re.compile(r"[,;:，、；：]$")
PAUSE_SECONDS = 0.8
# A caption stays up through a short silence instead of flickering off.
HOLD_SECONDS = 1.0


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Caption:
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    emoji: Optional[str] = None


def is_compact_script(text: str) -> bool:
    """True for scripts written without spaces between words."""
    for ch in text:
        name = unicodedata.name(ch, "")
        if name.startswith(("CJK", "HIRAGANA", "KATAKANA", "THAI")):
            return True
    return False


def join_words(words: List[Word]) -> str:
    out = ""
    for w in words:
        t = w.text.strip()
        if not t:
            continue
        if out and not (is_compact_script(out[-1]) and is_compact_script(t[0])):
            out += " "
        out += t
    return out


def words_from_segments(segments: List[dict]) -> List[Word]:
    """Spreads each segment's time evenly over its words, for transcripts
    that only have segment timing (SRT files, some providers)."""
    words: List[Word] = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start, end = float(seg["start"]), float(seg["end"])
        tokens = list(text) if is_compact_script(text) and " " not in text else text.split()
        weights = [max(len(t), 1) for t in tokens]
        total = sum(weights)
        t = start
        for token, weight in zip(tokens, weights):
            d = (end - start) * weight / total
            words.append(Word(token, t, t + d))
            t += d
    return words


def group_words(
    words: List[Word],
    layout: str = "portrait",
    length: str = "medium",
    max_words: Optional[int] = None,
) -> List[Caption]:
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    compact = is_compact_script(join_words(words))
    limit = COMPACT_LINE_CHARS[layout][length] * 2 if compact else LATIN_CAPTION_CHARS[layout][length]

    groups: List[List[Word]] = []
    current: List[Word] = []
    for word in words:
        if current:
            candidate = len(join_words(current + [word]))
            pause = word.start - current[-1].end > PAUSE_SECONDS
            full = candidate > limit or (max_words is not None and len(current) >= max_words)
            last = current[-1].text.strip()
            # Break after a sentence, or after a clause once the group is
            # already most of the way to full.
            sentence = SENTENCE_END.search(last) is not None
            clause = CLAUSE_END.search(last) is not None and len(join_words(current)) > limit * 0.6
            if pause or full or sentence or clause:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)

    captions = [Caption(g[0].start, g[-1].end, join_words(g), g) for g in groups]
    for this, nxt in zip(captions, captions[1:]):
        if nxt.start - this.end < HOLD_SECONDS:
            this.end = nxt.start
    return captions


def split_into_words(caption: Caption) -> Caption:
    """Re-times a caption whose text changed (corrected or translated) by
    spreading its span over the new words."""
    words = words_from_segments([{"start": caption.start, "end": caption.end, "text": caption.text}])
    return Caption(caption.start, caption.end, caption.text, words, caption.emoji)
