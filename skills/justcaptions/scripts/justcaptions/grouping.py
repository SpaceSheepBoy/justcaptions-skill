"""Turns timed words into on-screen caption groups."""

import re
import math
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
    id: Optional[str] = None


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


def reconcile_caption_text(caption: Caption, text: str) -> Caption:
    """Keep anchored word times for edits; only inserted words use gap timing.

    Multi-character compact-script ASR words cannot be aligned reliably to the
    existing character tokenizer. Bounded or ambiguous cases retain equal-count
    timing only, otherwise use the existing explicit inferred-time fallback.
    Translation deliberately uses split_into_words instead of this function.
    """
    if text == caption.text:
        return caption
    tokens = list(text) if is_compact_script(text) and " " not in text else text.split()
    tokens = [token for token in tokens if token.strip()]
    old = caption.words
    def key(token):
        normalized = unicodedata.normalize("NFC", token).lower()
        value = normalized
        while value and unicodedata.category(value[0]).startswith("P"):
            value = value[1:]
        while value and unicodedata.category(value[-1]).startswith("P"):
            value = value[:-1]
        return value or normalized
    def fallback():
        if old and len(old) == len(tokens):
            return Caption(caption.start, caption.end, text,
                           [Word(t, w.start, w.end, w.id) for w, t in zip(old, tokens)], caption.emoji)
        return split_into_words(Caption(caption.start, caption.end, text, emoji=caption.emoji))
    if any(not math.isfinite(w.start) or not math.isfinite(w.end) or w.end < w.start
           or (i > 0 and w.start < old[i - 1].start) for i, w in enumerate(old)):
        return split_into_words(Caption(caption.start, caption.end, text, emoji=caption.emoji))
    n, m = len(old), len(tokens)
    if not old or (n + 1) * (m + 1) > 262144 or (
        is_compact_script(caption.text) and any(len(w.text.strip()) > 1 for w in old)
    ):
        return fallback()
    keys_old, keys_new = [key(w.text) for w in old], [key(t) for t in tokens]
    dp = [list(range(m + 1))] + [[i] + [0] * m for i in range(1, n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i-1][j-1] + (keys_old[i-1] != keys_new[j-1]),
                           dp[i-1][j] + 1, dp[i][j-1] + 1)
    aligned = []
    i, j = n, m
    while i or j:
        if i and j and keys_old[i-1] == keys_new[j-1] and dp[i][j] == dp[i-1][j-1]:
            aligned.append((tokens[j-1], old[i-1])); i -= 1; j -= 1
        elif i and j and dp[i][j] == dp[i-1][j-1] + 1:
            aligned.append((tokens[j-1], old[i-1])); i -= 1; j -= 1
        elif i and dp[i][j] == dp[i-1][j] + 1:
            i -= 1
        else:
            aligned.append((tokens[j-1], None)); j -= 1
    aligned.reverse()
    result = []
    index = 0
    while index < len(aligned):
        token, source = aligned[index]
        if source is not None:
            result.append(Word(token, source.start, source.end, source.id))
            index += 1
            continue
        end = index
        while end < len(aligned) and aligned[end][1] is None:
            end += 1
        start_time = result[-1].end if result else caption.start
        boundary = aligned[end][1].start if end < len(aligned) else caption.end
        gap = max(0.0, boundary - start_time)
        step = gap / (end - index)
        for offset in range(end - index):
            result.append(Word(aligned[index + offset][0], start_time + step * offset,
                               start_time + step * (offset + 1)))
        index = end
    return Caption(caption.start, caption.end, text, result, caption.emoji)
