"""Speech to timed words: Just Captions API when a key is set, else local
faster-whisper."""

import math
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import api, media
from .grouping import Word, words_from_segments

NO_ENGINE = """No transcription engine available. Pick one:

  1. Just Captions API (no install, best accuracy; free beta key):
       https://justcaptions.com/api/
       export JUSTCAPTIONS_API_KEY=jc_live_...

  2. Local, offline, free:
       pip install faster-whisper
"""


def _api_words(result: dict, offset: float) -> List[Word]:
    words = [Word(w["word"], w["start"] + offset, w["end"] + offset) for w in result.get("words") or []]
    if words:
        return words
    segs = [{**s, "start": s["start"] + offset, "end": s["end"] + offset} for s in result.get("segments") or []]
    return words_from_segments(segs)


def transcribe_api(video: Path, workdir: Path, duration: float, language: Optional[str], glossary: List[str]) -> Tuple[List[Word], Optional[str]]:
    audio = media.extract_audio(video, workdir / "audio.m4a")
    size = audio.stat().st_size
    if size <= api.MAX_AUDIO_BYTES:
        result = api.transcribe(audio.read_bytes(), audio.name, language, glossary)
        return _api_words(result, 0.0), result.get("language")

    # Over the per-request limit: send it in equal slices, then shift each
    # slice's timestamps back onto the full timeline.
    slices = math.ceil(size / (api.MAX_AUDIO_BYTES * 0.9))
    span = duration / slices
    words: List[Word] = []
    detected = language
    for i in range(slices):
        part = media.extract_audio(video, workdir / f"audio-{i}.m4a", start=i * span, duration=span)
        print(f"  transcribing part {i + 1}/{slices}", file=sys.stderr)
        result = api.transcribe(part.read_bytes(), part.name, language or detected, glossary)
        detected = detected or result.get("language")
        words += _api_words(result, i * span)
    return words, detected


def transcribe_local(video: Path, workdir: Path, model_name: str, language: Optional[str], glossary: List[str]) -> Tuple[List[Word], Optional[str]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit(NO_ENGINE) from None
    audio = media.extract_audio(video, workdir / "audio.m4a")
    print(f"  loading faster-whisper '{model_name}' (first run downloads it)", file=sys.stderr)
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        initial_prompt=", ".join(glossary) if glossary else None,
    )
    words: List[Word] = []
    for seg in segments:
        for w in seg.words or []:
            words.append(Word(w.word.strip(), float(w.start), float(w.end)))
    return words, info.language


def transcribe(video: Path, workdir: Path, duration: float, engine: str, model_name: str, language: Optional[str], glossary: List[str]):
    if engine == "auto":
        engine = "api" if api.api_key() else "local"
    if engine == "api":
        return transcribe_api(video, workdir, duration, language, glossary)
    return transcribe_local(video, workdir, model_name, language, glossary)
