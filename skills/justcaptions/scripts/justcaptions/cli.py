"""justcaptions: caption videos from the command line.

  python3 scripts/jc.py talk.mp4 --burn
  python3 scripts/jc.py clips/ --style emoji --burn
  python3 scripts/jc.py talk.mp4 --translate es --formats srt,vtt
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from . import api, emoji, formats, media, styles
from .grouping import Caption, Word, group_words, split_into_words, words_from_segments
from .transcribe import transcribe


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jc", description="Add captions to videos, styled like the Just Captions app.")
    p.add_argument("inputs", nargs="*", help="video files or folders (folders are captioned in batch)")
    p.add_argument("--burn", action="store_true", help="write <name>.captioned.mp4 with the captions burned in")
    p.add_argument("--style", default=styles.DEFAULT_STYLE, choices=sorted(styles.STYLES))
    p.add_argument("--position", default="bottom", help="top, middle, bottom, or a 0-1 fraction of the height")
    p.add_argument("--size", default="medium", choices=sorted(styles.SIZE_SCALES))
    p.add_argument("--length", default="medium", choices=["short", "medium", "long"], help="max words on screen")
    p.add_argument("--formats", default="srt,json", help="comma list of srt, vtt, json (empty for none)")
    p.add_argument("--out-dir", help="where outputs go (default: next to each input)")
    p.add_argument("--language", help="spoken language hint, e.g. en, zh, es")
    p.add_argument("--glossary", default="", help="comma-separated names and terms to spell correctly")
    p.add_argument("--engine", default="auto", choices=["auto", "api", "local"],
                   help="auto = API when JUSTCAPTIONS_API_KEY is set, else local faster-whisper")
    p.add_argument("--model", default="small", help="faster-whisper model for local transcription")
    p.add_argument("--captions", help="use an existing .srt/.vtt/.json instead of transcribing (one input only)")
    p.add_argument("--correct", action="store_true", help="AI-correct the transcript (API key required)")
    p.add_argument("--translate", metavar="LANG", help="translate captions, e.g. es, ja, zh-Hans (API key required)")
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--keep-frames", action="store_true", help="keep the rendered PNGs (for debugging)")
    p.add_argument("--list-styles", action="store_true")
    p.add_argument("--usage", action="store_true", help="show this month's API usage")
    return p.parse_args(argv)


def position_value(text: str) -> float:
    if text in styles.POSITIONS:
        return styles.POSITIONS[text]
    value = float(text)
    if not 0 <= value <= 1:
        raise SystemExit("--position must be top, middle, bottom, or between 0 and 1")
    return value


def load_captions(path: Path, layout: str, length: str, max_words) -> List[Caption]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if "captions" in data:
            captions = formats.load_captions_json(data)
            if not max_words:
                return captions
            # A word-limited style (Emoji) needs its own short groups.
            return group_words([w for c in captions for w in c.words], layout, length, max_words)
        words = data.get("words") or words_from_segments(data.get("segments", []))
        if words and isinstance(words[0], dict):
            words = [Word(w["word"], float(w["start"]), float(w["end"])) for w in words]
        return group_words(words, layout, length, max_words)
    segments = formats.parse_subtitles(text)
    if max_words:
        return group_words(words_from_segments(segments), layout, length, max_words)
    return [split_into_words(Caption(s["start"], s["end"], s["text"])) for s in segments]


def need_key(feature: str) -> None:
    if not api.api_key():
        raise SystemExit(f"{feature} uses the Just Captions API. Get a free beta key at "
                         "https://justcaptions.com/api/ and set JUSTCAPTIONS_API_KEY.")


def caption_video(video: Path, args: argparse.Namespace, out_dir: Path) -> List[Path]:
    from .render import Renderer  # Pillow is only needed for --burn
    style = styles.STYLES[args.style]
    width, height, duration, audio_codec = media.video_info(video)
    layout = styles.layout_for(width, height)
    glossary = [g.strip() for g in args.glossary.split(",") if g.strip()]
    work = Path(tempfile.mkdtemp(prefix="jc-"))
    outputs: List[Path] = []
    try:
        language = args.language
        if args.captions:
            captions = load_captions(Path(args.captions), layout, args.length, style.max_words)
        else:
            words, language = transcribe(video, work, duration, args.engine, args.model, args.language, glossary)
            captions = group_words(words, layout, args.length, style.max_words)
        if not captions:
            raise RuntimeError("no speech found")
        print(f"  {len(captions)} captions", file=sys.stderr)

        if args.correct:
            need_key("--correct")
            fixed = api.correct([c.text for c in captions], language, glossary)
            captions = [split_into_words(Caption(c.start, c.end, t)) if t != c.text else c for c, t in zip(captions, fixed)]
        if args.translate:
            need_key("--translate")
            translated = api.translate([c.text for c in captions], args.translate, glossary)
            captions = [split_into_words(Caption(c.start, c.end, t)) for c, t in zip(captions, translated)]
            language = args.translate
        if style.emoji:
            if api.api_key():
                try:
                    for c, e in zip(captions, api.emoji([c.text for c in captions], language)):
                        c.emoji = e
                except api.APIError as e:
                    print(f"  emoji API failed ({e}); using the offline table", file=sys.stderr)
            emoji.fill_local(captions, language)

        stem = out_dir / video.stem
        writers = {"srt": formats.to_srt, "vtt": formats.to_vtt, "json": lambda c: formats.to_json(c, language)}
        for fmt in [f.strip() for f in args.formats.split(",") if f.strip()]:
            if fmt not in writers:
                raise SystemExit(f"unknown format: {fmt}")
            path = stem.with_suffix(f".{fmt}")
            path.write_text(writers[fmt](captions), encoding="utf-8")
            outputs.append(path)

        if args.burn:
            from .burn import build_timeline, burn
            renderer = Renderer(width, height, style, args.size, position_value(args.position))
            concat = build_timeline(captions, renderer, work / "frames", duration)
            out = out_dir / f"{video.stem}.captioned.mp4"
            print("  burning", file=sys.stderr)
            outputs.append(burn(video, concat, out, audio_codec, args.crf))
        return outputs
    finally:
        if args.keep_frames:
            print(f"  frames kept in {work}", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.list_styles:
        for name, st in styles.STYLES.items():
            print(f"{name:14} {st.description}")
        return 0
    if args.usage:
        need_key("--usage")
        print(json.dumps(api.usage(), indent=2))
        return 0
    if not args.inputs:
        print("give at least one video (or --list-styles). See --help.", file=sys.stderr)
        return 2
    media.require_ffmpeg()
    videos = media.expand_inputs(args.inputs)
    if args.captions and len(videos) != 1:
        raise SystemExit("--captions works with exactly one video")
    if not videos:
        raise SystemExit("no videos found")

    failures = 0
    for i, video in enumerate(videos, 1):
        out_dir = Path(args.out_dir) if args.out_dir else video.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(videos)}] {video}", file=sys.stderr)
        started = time.time()
        try:
            for path in caption_video(video, args, out_dir):
                print(path)
            print(f"  done in {time.time() - started:.1f}s", file=sys.stderr)
        except (RuntimeError, api.APIError) as e:
            failures += 1
            print(f"  failed: {e}", file=sys.stderr)
    if len(videos) > 1:
        print(f"{len(videos) - failures}/{len(videos)} videos captioned", file=sys.stderr)
    return 1 if failures else 0
