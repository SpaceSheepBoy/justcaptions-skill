"""Offline emoji picks for the Emoji style (the API's AI picks are better)."""

import json
import re
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from .grouping import Caption, is_compact_script

TABLE = Path(__file__).resolve().parents[2] / "assets" / "emoji-keywords.json"
# Every group gets an emoji, as in the app: when no word matches, pick a
# stable one from this set by the caption's text.
MOOD = ["✨", "🔥", "💡", "👀", "🎯", "💬", "🙌", "⭐"]


@lru_cache(maxsize=1)
def _table() -> Dict[str, Dict[str, str]]:
    return json.loads(TABLE.read_text(encoding="utf-8"))


# Providers spell languages several ways ("eng", "english", "en").
ALIASES = {
    "eng": "en", "english": "en", "zho": "zh", "chi": "zh", "chinese": "zh", "cmn": "zh", "yue": "zh-hant",
    "jpn": "ja", "japanese": "ja", "kor": "ko", "korean": "ko", "spa": "es", "spanish": "es",
    "fra": "fr", "fre": "fr", "french": "fr", "deu": "de", "ger": "de", "german": "de",
    "por": "pt", "portuguese": "pt", "ara": "ar", "arabic": "ar", "ind": "id", "indonesian": "id",
    "tha": "th", "thai": "th",
}


def _language_key(language: Optional[str], text: str) -> str:
    lang = (language or "").lower().replace("_", "-")
    lang = ALIASES.get(lang, lang)
    table = _table()
    if lang.startswith("zh"):
        return "zh-Hant" if any(t in lang for t in ("hant", "tw", "hk")) else "zh-Hans"
    base = lang.split("-")[0]
    if base in table:
        return base
    if is_compact_script(text):
        return "ja" if re.search(r"[぀-ヿ]", text) else "zh-Hans"
    return "en"


def _match(text: str, words: Dict[str, str]) -> Optional[str]:
    lowered = text.lower()
    if is_compact_script(text):
        for key in sorted(words, key=len, reverse=True):
            if key in lowered:
                return words[key]
        return None
    for token in re.findall(r"[\w']+", lowered):
        if token in words:
            return words[token]
        if token.endswith("s") and token[:-1] in words:
            return words[token[:-1]]
    return None


def pick(text: str, context: str = "", language: Optional[str] = None) -> str:
    words = _table().get(_language_key(language, text), {})
    return (
        _match(text, words)
        or (context and _match(context, words))
        or MOOD[zlib.crc32(text.encode("utf-8")) % len(MOOD)]
    )


def fill_local(captions: List[Caption], language: Optional[str]) -> None:
    for i, c in enumerate(captions):
        if not c.emoji:
            # Three words rarely name a thing; the neighbours help.
            context = " ".join(x.text for x in captions[max(0, i - 1) : i + 2])
            c.emoji = pick(c.text, context, language)
