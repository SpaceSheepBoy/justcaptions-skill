"""Local MCP: inspect, preview, caption and verify videos without uploading footage."""
import asyncio
import importlib.util
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from . import api, cli, media, styles, jobs, execution, metrics
from .assets import ASSETS
from .grouping import group_words, words_from_segments
from .render import Renderer

mcp = FastMCP("Just Captions", instructions="Use list_styles, list_fonts and check_environment first. For local videos call caption_video, then poll get_job until completed, failed or cancelled. Jobs persist across restarts; use list_jobs and resume_job to recover. Rendering stays local. API transcription sends extracted audio; AI edits send caption text. Keep API keys out of tool arguments. Existing output files are protected unless overwrite is explicitly requested.")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)
TASKS = set()


@mcp.tool(annotations=READ, structured_output=True)
def check_environment() -> dict[str, Any]:
    """Check media tools, fonts, API-key availability and offline recognition. Never returns the key."""
    metrics.record("mcp_connected")
    return {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
            "api_key_configured": bool(api.api_key()), "offline_transcription_installed": importlib.util.find_spec("faster_whisper") is not None,
            "rendering": "local", "job_store": str(jobs.directory()), "catalog_version": styles.catalog()["catalog_version"],
            "setup": "Install ffmpeg; use a Just Captions API key or install justcaptions-agent[local] for offline recognition."}


@mcp.tool(annotations=READ, structured_output=True)
def list_styles() -> dict[str, Any]:
    """Return 15 portable presets, supported overrides, aliases and conservative platform safe areas."""
    return styles.catalog()


@mcp.tool(annotations=READ, structured_output=True)
def list_fonts() -> dict[str, Any]:
    """List bundled named fonts, IDs, licenses and script coverage for local rendering.
    Pass overrides={"font_id": "anton"} to preview_style or caption_video.
    """
    return styles.font_catalog()


@mcp.tool(annotations=READ, structured_output=True)
def get_usage() -> dict[str, Any]:
    """Read cloud API usage and estimated monthly charges. Requires a locally configured API key."""
    return api.usage()


@mcp.tool(annotations=READ)
def preview_style(style_id: str = "word-highlight", text: str = "Make your next video stand out", width: int = 540,
                  height: int = 960, size: Literal["small", "medium", "large"] = "large",
                  position: str = "bottom", safe_area: Literal["none", "tiktok", "reels", "shorts"] = "tiktok",
                  overrides: Optional[dict] = None) -> Image:
    """Return a caption PNG preview with a neutral backdrop. Does not call a paid API."""
    if not 64 <= width <= 1920 or not 64 <= height <= 1920 or not 1 <= len(text.strip()) <= 200:
        raise ValueError("Preview dimensions must be 64..1920; text must contain 1..200 characters.")
    style = styles.resolve(style_id, overrides)
    words = words_from_segments([{"start": 0, "end": 2, "text": text}])
    layout = styles.layout_for(width, height)
    caption = group_words(words, layout, max_words=style.max_words)[0]
    caption.emoji = "✨"
    renderer = Renderer(width, height, style, size, cli.position_value(position), safe_area)
    states = renderer.states(caption)
    state = states[len(states) // 2][2]
    from PIL import Image as PILImage
    import io
    backdrop = PILImage.new("RGBA", (width, height), (43, 48, 60, 255))
    backdrop.alpha_composite(renderer.frame(caption, state))
    out = io.BytesIO()
    backdrop.convert("RGB").save(out, format="PNG")
    return Image(data=out.getvalue(), format="png")


@mcp.tool(annotations=WRITE, structured_output=True)
async def caption_video(input_path: str, output_dir: str, style_id: str = "word-highlight",
                        captions_path: Optional[str] = None, engine: Literal["auto", "api", "local"] = "auto",
                        language: Optional[str] = None, translate_to: Optional[str] = None, correct: bool = False,
                        glossary: Optional[list[str]] = None, size: Literal["small", "medium", "large"] = "medium",
                        position: str = "bottom", safe_area: Literal["none", "tiktok", "reels", "shorts"] = "tiktok",
                        length: Literal["short", "medium", "long"] = "medium", overrides: Optional[dict] = None,
                        burn: bool = True, overwrite: bool = False) -> dict[str, Any]:
    """Start captioning one local video or a folder. Returns a job ID immediately; poll get_job.
    API recognition sends audio, AI edits send text, and MP4 rendering remains local.
    captions_path reuses an existing SRT/VTT/JSON without recognition. Original video is preserved.
    """
    media.require_ffmpeg()
    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise ValueError("Input path does not exist.")
    videos = media.expand_inputs([str(source)])
    if not videos or len(videos) > 100:
        raise ValueError("Choose 1..100 video files.")
    destination = Path(output_dir).expanduser().resolve()
    if captions_path and (len(videos) != 1 or not Path(captions_path).expanduser().is_file()):
        raise ValueError("captions_path requires one input video and an existing caption file.")
    styles.resolve(style_id, overrides)
    cli.position_value(position)
    if (correct or translate_to or engine == "api") and not api.api_key():
        raise ValueError("Configure JUSTCAPTIONS_API_KEY or ~/.config/justcaptions/api_key first.")
    if not captions_path and engine != "api" and not api.api_key() and importlib.util.find_spec("faster_whisper") is None:
        raise ValueError("Configure an API key or install the local transcription extra.")
    destination.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    params = dict(style_id=style_id, captions_path=captions_path, engine=engine, language=language,
                  translate_to=translate_to, correct=correct, glossary=glossary or [], size=size,
                  position=position, safe_area=safe_area, length=length, overrides=overrides,
                  burn=burn, overwrite=overwrite, offline_demo=(source == (ASSETS / "demo/story.mp4").resolve() and bool(captions_path) and Path(captions_path).expanduser().resolve() == (ASSETS / "demo/story.json").resolve()))
    row = {"job_id": job_id, "status": "queued", "stage": "queued", "total": len(videos), "finished": 0, "results": [],
           "params": params, "sources": [jobs.fingerprint(video) for video in videos], "destination": str(destination),
           "caption_source": jobs.fingerprint(Path(captions_path).expanduser()) if captions_path else None}
    jobs.claim(row)
    _schedule(job_id)
    return {"job_id": job_id, "status": "queued", "next": "Poll get_job. Jobs are saved locally; after interruption use resume_job. cancel_job stops local work; a cloud request already sent may finish and be charged."}


def _schedule(job_id):
    task = asyncio.create_task(_run_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


async def _run_job(job_id):
    def run():
        job = jobs.get(job_id)
        params = job['params']
        destination = Path(job['destination'])
        job['status'] = 'running'
        jobs.save(job)
        def stage(value):
            execution.check()
            job['stage'] = value
            jobs.save(job)
        try:
            for index, source in enumerate(job['sources']):
                video = Path(source['path'])
                if any(row['input'] == str(video) and row['status'] == 'completed' for row in job['results']):
                    continue
                work = jobs.directory() / 'work' / job_id / str(index)
                work.mkdir(parents=True, exist_ok=True, mode=0o700)
                token = execution.context.set({'work': work, 'cancelled': lambda: jobs.cancelled(job_id)})
                try:
                    execution.check()
                    if jobs.fingerprint(video) != source or (job['caption_source'] and jobs.fingerprint(Path(job['caption_source']['path'])) != job['caption_source']):
                        raise ValueError('Source changed since this job started. Start a new job instead of replaying its cloud requests.')
                    out = destination / video.name if job['total'] > 1 else destination
                    out.mkdir(parents=True, exist_ok=True)
                    args = cli.parse_args([])
                    args.style, args.style_overrides = params['style_id'], params['overrides']
                    args.captions = job['caption_source']['path'] if job['caption_source'] else None
                    args.engine, args.language, args.translate = params['engine'], params['language'], params['translate_to']
                    args.correct, args.glossary = params['correct'], ', '.join(params['glossary'])
                    args.size, args.position, args.safe_area = params['size'], params['position'], params['safe_area']
                    args.length, args.burn, args.overwrite = params['length'], params['burn'], params['overwrite']
                    args.formats, args.progress = 'srt,vtt,json', stage
                    args.demo = params.get('offline_demo',False)
                    row = {'input': str(video)}
                    try:
                        paths = cli.caption_video(video, args, out)
                        row.update(status='completed', outputs=[str(path.resolve()) for path in paths], media_verified=params['burn'],
                                   timing_note='Edited, translated and subtitle-only text uses estimated word timing.')
                    except execution.JobCancelled:
                        raise
                    except Exception as error:
                        row.update(status='failed', error=api.explain(error) if isinstance(error, api.APIError) else str(error))
                    job['results'] = [old for old in job['results'] if old['input'] != str(video)] + [row]
                    job['finished'] = len(job['results'])
                    jobs.save(job)
                    if row['status'] == 'completed':
                        shutil.rmtree(work / 'frames',ignore_errors=True)
                        shutil.rmtree(work / 'outputs',ignore_errors=True)
                        for audio in work.glob('*.m4a'):
                            audio.unlink(missing_ok=True)
                finally:
                    execution.context.reset(token)
            job['status'] = 'failed' if any(row['status'] == 'failed' for row in job['results']) else 'completed'
        except execution.JobCancelled:
            job['status'] = 'cancelled'
        except BaseException as error:
            job.update(status='interrupted', error=str(error))
        job['stage'] = job['status']
        jobs.save(job)
        if job['status'] == 'completed' and params['burn']:
            metrics.record('export_completed', params['style_id'], job_id)
    await asyncio.to_thread(run)


@mcp.tool(annotations=READ, structured_output=True)
def get_job(job_id: str) -> dict[str, Any]:
    """Read a saved caption job, including verified outputs and per-file failures."""
    return jobs.public(jobs.get(job_id))


@mcp.tool(annotations=READ, structured_output=True)
def list_jobs(limit: int = 20) -> dict[str, Any]:
    """Find durable jobs after reconnecting, including jobs interrupted by a process restart."""
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100.')
    return {'jobs': [jobs.public(row) for row in jobs.list_all(limit)]}


@mcp.tool(annotations=WRITE, structured_output=True)
def cancel_job(job_id: str) -> dict[str, Any]:
    """Stop owned local rendering and pending files. An in-flight cloud request may finish and be charged; its response is cached for resume."""
    return jobs.public(jobs.cancel(job_id))


@mcp.tool(annotations=WRITE, structured_output=True)
async def resume_job(job_id: str) -> dict[str, Any]:
    """Resume an interrupted/cancelled/failed job. Completed files are skipped, failed files alone are retried, and successful cloud responses are reused."""
    row = jobs.get(job_id)
    if row['status'] == 'completed':
        return jobs.public(row)
    jobs.claim(row, resume=True)
    _schedule(job_id)
    return jobs.public(row)


@mcp.tool(annotations=READ, structured_output=True)
def estimate_video(input_path: str, text_chars: int = 0) -> dict[str, Any]:
    """Estimate cloud cost before transcription. Audio is measured locally; supply known text_chars for editing/translation, otherwise their cost is excluded. Does not reserve credit."""
    media.require_ffmpeg()
    videos = media.expand_inputs([str(Path(input_path).expanduser().resolve())])
    if not videos or len(videos) > 100 or text_chars < 0:
        raise ValueError('Choose 1..100 videos and a nonnegative text_chars value.')
    seconds = sum(media.video_info(video)[2] for video in videos)
    result = api.estimate(seconds, text_chars)
    return {**result, 'files': len(videos), 'audio_seconds': seconds, 'text_chars': text_chars, 'note': 'Unknown future caption text is excluded. Rendering and imported-caption jobs cost nothing unless AI edits are requested.'}


@mcp.tool(annotations=WRITE, structured_output=True)
async def run_demo(output_dir: str, style_id: str = 'word-highlight') -> dict[str, Any]:
    """Export the bundled 6-second human-narration sample with animated captions. No API key, upload or model download required. Credits are bundled with the sample."""
    return await caption_video(input_path=str(ASSETS / 'demo/story.mp4'), captions_path=str(ASSETS / 'demo/story.json'),
                               output_dir=output_dir, style_id=style_id, size='large', safe_area='tiktok')


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
