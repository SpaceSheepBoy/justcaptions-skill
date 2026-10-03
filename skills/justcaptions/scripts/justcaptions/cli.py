"""justcaptions: caption videos from the command line.

  python3 scripts/jc.py talk.mp4 --burn
  python3 scripts/jc.py clips/ --style emoji --burn
  python3 scripts/jc.py talk.mp4 --translate es --formats srt,vtt
"""

import hashlib
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from . import api, emoji, formats, media, styles, execution
from .grouping import Caption, Word, group_words, split_into_words, words_from_segments
from .transcribe import transcribe


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jc", description="Add captions to videos, styled like the Just Captions app.")
    p.add_argument("inputs", nargs="*", help="video files or folders (folders are captioned in batch)")
    p.add_argument("--demo", action="store_true", help="caption the bundled human narration sample without an API key")
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
                   help="auto = API when an API key is set, else local faster-whisper")
    p.add_argument("--model", default="small", help="faster-whisper model for local transcription")
    p.add_argument("--captions", help="use an existing .srt/.vtt/.json instead of transcribing (one input only)")
    p.add_argument("--correct", action="store_true", help="AI-correct the transcript (API key required)")
    p.add_argument("--translate", metavar="LANG", help="translate captions, e.g. es, ja, zh-Hans (API key required)")
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--keep-frames", action="store_true", help="keep the rendered PNGs (for debugging)")
    p.add_argument("--list-styles", action="store_true")
    p.add_argument("--json", action="store_true", help="structured results on stdout")
    p.add_argument("--style-config", help="JSON file with validated style overrides")
    p.add_argument("--safe-area", choices=["none", "tiktok", "reels", "shorts"], default="none")
    p.add_argument("--overwrite", action="store_true", help="replace existing output files")
    p.add_argument("--signup", metavar="EMAIL", help="create a free API key and save it to ~/.config/justcaptions/api_key")
    p.add_argument("--account", "--usage", dest="account", action="store_true",
                   help="show this month's API usage and estimated charge")
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
        raise SystemExit(f"{feature} uses the Just Captions API. Create a free key with "
                         "`jc.py --signup YOUR_EMAIL` (30 audio minutes and 50,000 caption characters free each month).")


def signup(email: str) -> int:
    if api.api_key():
        where = "JUSTCAPTIONS_API_KEY" if os.environ.get("JUSTCAPTIONS_API_KEY", "").strip() else str(api.KEY_FILE)
        print(f"An API key is already set ({where}). Remove it first to sign up again.", file=sys.stderr)
        return 1
    result = api.signup(email)
    path = api.save_key(result["key"])
    print(f"Created API key {api.mask(result['key'])} (plan: {result.get('plan', 'free')})")
    print(f"Saved to {path}")
    print("Free every month: 30 audio minutes, 50,000 caption characters.")
    print(f"Add a card for pay-as-you-go beyond that: {api.ACCOUNT_URL}")
    return 0


def format_account(u: dict) -> str:
    minutes = lambda s: f"{(s or 0) / 60:.1f}"  # noqa: E731
    dollars = lambda c: f"${(c or 0) / 100:.2f}"  # noqa: E731
    lines = [
        f"Account   {u.get('email') or '-'}  (plan: {u.get('plan', '-')})",
        f"Month     {u.get('month', '-')}",
        f"Audio     {minutes(u.get('audio_seconds'))} min used, {minutes(u.get('free_audio_seconds'))} min free",
        f"Text      {u.get('text_chars', 0):,} chars used, {u.get('free_text_chars', 0):,} chars free",
        f"Estimated charge  {dollars(u.get('estimated_charge_cents'))}"
        + (f"  (spend cap {dollars(u['spend_cap_cents'])})" if u.get("spend_cap_cents") else ""),
        f"Card, invoices, spend cap: {api.ACCOUNT_URL}",
    ]
    return "\n".join(lines)


def caption_video(video: Path, args: argparse.Namespace, out_dir: Path) -> List[Path]:
    from .render import Renderer  # Pillow is only needed for --burn
    overrides = getattr(args, "style_overrides", None)
    if args.style_config:
        overrides = json.loads(Path(args.style_config).read_text(encoding="utf-8"))
    style = styles.resolve(args.style, overrides)
    progress = getattr(args, "progress", lambda stage: None)
    progress("checking")
    expected = [out_dir / f"{video.stem}.{ext}" for ext in args.formats.split(",") if ext]
    if args.burn:
        expected.append(out_dir / f"{video.stem}.captioned.mp4")
    context = execution.context.get()
    checkpoint = context['work'] if context else None
    published_path = checkpoint / 'published.json' if checkpoint else None
    published = json.loads(published_path.read_text()) if published_path and published_path.exists() else {}
    def owned(path):
        allowed = published.get(str(path), [])
        if isinstance(allowed,str):
            allowed = [allowed]
        return path.is_file() and execution.digest(path) in allowed
    if not args.overwrite and any(p.exists() and not owned(p) for p in expected):
        raise RuntimeError("Output already exists. Choose another output directory or explicitly enable overwrite.")
    width, height, duration, audio_codec = media.video_info(video)
    layout = styles.layout_for(width, height)
    glossary = [g.strip() for g in args.glossary.split(",") if g.strip()]
    work = checkpoint or Path(tempfile.mkdtemp(prefix="jc-"))
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    target_dir = out_dir
    if checkpoint:
        out_dir = work / 'outputs'
        out_dir.mkdir(exist_ok=True)
    def cached(name, action):
        execution.check()
        path = work / (name + '.json')
        if checkpoint and path.exists():
            data = json.loads(path.read_text())
            return formats.load_captions_json(data), data.get('language')
        caps, lang = action()
        if checkpoint:
            execution.atomic_json(path, json.loads(formats.to_json(caps, lang)))
        execution.check()
        return caps, lang
    outputs: List[Path] = []
    try:
        language = args.language
        progress("transcribing" if not args.captions else "loading_captions")
        def recognize():
            if args.captions:
                return load_captions(Path(args.captions), layout, args.length, style.max_words), args.language
            words, detected = transcribe(video, work, duration, args.engine, args.model, args.language, glossary)
            return group_words(words, layout, args.length, style.max_words), detected
        captions, language = cached('transcript', recognize)
        if not captions:
            raise RuntimeError("no speech found")
        print(f"  {len(captions)} captions", file=sys.stderr)

        if args.correct:
            progress("correcting")
            need_key("--correct")
            def correction():
                fixed = api.correct([c.text for c in captions], language, glossary)
                return [split_into_words(Caption(c.start, c.end, t)) if t != c.text else c for c, t in zip(captions, fixed)], language
            captions, language = cached('corrected', correction)
        if args.translate:
            progress("translating")
            need_key("--translate")
            def translation():
                translated = api.translate([c.text for c in captions], args.translate, glossary)
                return [split_into_words(Caption(c.start, c.end, t)) for c, t in zip(captions, translated)], args.translate
            captions, language = cached('translated', translation)
        progress("styling")
        if style.emoji:
            if api.api_key() and not args.demo:
                try:
                    for c, e in zip(captions, api.emoji([c.text for c in captions], language)):
                        c.emoji = e
                except api.APIError as e:
                    print(f"  emoji API failed ({api.explain(e)}); using the offline table", file=sys.stderr)
            emoji.fill_local(captions, language)

        stem = out_dir / video.stem
        writers = {"srt": formats.to_srt, "vtt": formats.to_vtt, "json": lambda c: formats.to_json(c, language)}
        for fmt in [f.strip() for f in args.formats.split(",") if f.strip()]:
            if fmt not in writers:
                raise SystemExit(f"unknown format: {fmt}")
            path = out_dir / f"{video.stem}.{fmt}"
            path.write_text(writers[fmt](captions), encoding="utf-8")
            outputs.append(path)

        if args.burn:
            from .burn import build_timeline, burn
            progress("rendering")
            renderer = Renderer(width, height, style, args.size, position_value(args.position), args.safe_area)
            concat = build_timeline(captions, renderer, work / "frames", duration)
            out = out_dir / f"{video.stem}.captioned.mp4"
            print("  burning", file=sys.stderr)
            outputs.append(burn(video, concat, out, audio_codec, args.crf))
            progress("verifying")
            actual = media.video_info(out)
            if actual[:2] != (width, height) or abs(actual[2] - duration) > .25 or (audio_codec and not actual[3]):
                raise RuntimeError("Rendered video failed dimension, duration or audio verification.")
        execution.check()
        if checkpoint:
            final = []
            for path in outputs:
                destination = target_dir / path.name
                digest = execution.digest(path)
                # Save ownership before publication so restart can finish a partially published batch.
                previously_owned = owned(destination)
                if destination.exists() and not args.overwrite and not previously_owned:
                    raise RuntimeError('Output was changed by another process. Choose a new output directory.')
                prior = published.get(str(destination), [])
                if isinstance(prior,str): prior = [prior]
                published[str(destination)] = list(dict.fromkeys(prior + [digest]))
                execution.atomic_json(published_path, published)
                fd, temporary = tempfile.mkstemp(dir=target_dir)
                os.close(fd)
                try:
                    shutil.copyfile(path, temporary)
                    if args.overwrite or previously_owned:
                        os.replace(temporary, destination)
                    else:
                        os.link(temporary, destination)  # fails safely if another writer wins
                    published[str(destination)] = [digest]
                    execution.atomic_json(published_path,published)
                    final.append(destination)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            return final
        return outputs
    finally:
        if args.keep_frames:
            print(f"  frames kept in {work}", file=sys.stderr)
        elif not checkpoint:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.list_styles:
        if args.json:
            print(json.dumps(styles.catalog()))
        else:
            for name, st in styles.STYLES.items():
                print(f"{name:14} {st.description}")
        return 0
    try:
        if args.signup:
            return signup(args.signup)
        if args.account:
            need_key("--account")
            print(format_account(api.usage()))
            return 0
    except api.APIError as e:
        print(api.explain(e), file=sys.stderr)
        return 1
    if args.demo:
        from .assets import ASSETS
        args.inputs = [str(ASSETS / 'demo/story.mp4')]
        args.captions = str(ASSETS / 'demo/story.json')
        args.burn = True
        if not args.out_dir:
            args.out_dir = './justcaptions-demo'
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
    results = []
    for i, video in enumerate(videos, 1):
        out_dir = Path(args.out_dir) if args.out_dir else video.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(videos)}] {video}", file=sys.stderr)
        started = time.time()
        try:
            paths = caption_video(video, args, out_dir)
            results.append({"input": str(video.resolve()), "status": "completed", "outputs": [str(p.resolve()) for p in paths]})
            if not args.json:
                for path in paths:
                    print(path)
            print(f"  done in {time.time() - started:.1f}s", file=sys.stderr)
        except api.APIError as e:
            failures += 1
            results.append({"input": str(video.resolve()), "status": "failed", "code": e.code, "error": api.explain(e)})
            print(f"  failed: {api.explain(e)}", file=sys.stderr)
        except (RuntimeError, ValueError, OSError) as e:
            failures += 1
            results.append({"input": str(video.resolve()), "status": "failed", "error": str(e)})
            print(f"  failed: {e}", file=sys.stderr)
    if len(videos) > 1:
        print(f"{len(videos) - failures}/{len(videos)} videos captioned", file=sys.stderr)
    if args.json:
        print(json.dumps({"results": results, "failed": failures}))
    return 1 if failures else 0
