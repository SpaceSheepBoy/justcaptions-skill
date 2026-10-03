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

from . import api, cli, media, styles
from .grouping import group_words, words_from_segments
from .render import Renderer

mcp = FastMCP("Just Captions", instructions="Use list_styles and check_environment first. For local videos call caption_video, then poll get_job until completed or failed. Rendering stays local. API transcription sends extracted audio; AI edits send caption text. Keep API keys out of tool arguments. Existing output files are protected unless overwrite is explicitly requested.")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)
JOBS = {}
TASKS = set()


@mcp.tool(annotations=READ, structured_output=True)
def check_environment() -> dict[str, Any]:
    """Check media tools, fonts, API-key availability and offline recognition. Never returns the key."""
    return {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
            "api_key_configured": bool(api.api_key()), "offline_transcription_installed": importlib.util.find_spec("faster_whisper") is not None,
            "rendering": "local", "catalog_version": styles.catalog()["catalog_version"],
            "setup": "Install ffmpeg; use a Just Captions API key or install justcaptions-agent[local] for offline recognition."}


@mcp.tool(annotations=READ, structured_output=True)
def list_styles() -> dict[str, Any]:
    """Return 15 portable presets, supported overrides, aliases and conservative platform safe areas."""
    return styles.catalog()


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
    layout = "portrait" if height > width else "landscape" if width > height else "square"
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
    if sum(j["status"] in ("queued", "running") for j in JOBS.values()) >= 2:
        raise ValueError("Two jobs are already active. Wait for one to finish.")
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
    if len(JOBS) >= 100:
        for old_id in list(JOBS):
            if JOBS[old_id]["status"] in ("completed", "failed"):
                del JOBS[old_id]
                break
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": "queued", "total": len(videos), "finished": 0, "results": []}
    params = dict(style_id=style_id, captions_path=captions_path, engine=engine, language=language,
                  translate_to=translate_to, correct=correct, glossary=glossary or [], size=size,
                  position=position, safe_area=safe_area, length=length, overrides=overrides,
                  burn=burn, overwrite=overwrite)
    task = asyncio.create_task(_run_job(job_id, videos, destination, params))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {"job_id": job_id, "status": "queued", "next": "Poll get_job with this job_id every few seconds. Jobs live while this MCP process is running."}


async def _run_job(job_id, videos, destination, params):
    def run():
        job = JOBS[job_id]
        job["status"] = "running"
        def stage(value):
            job["stage"] = value
        for video in videos:
            row = {"input": str(video.resolve())}
            # Folders can contain clip.mov and clip.mp4; each gets its own output folder.
            out = destination / video.name if len(videos) > 1 else destination
            out.mkdir(parents=True, exist_ok=True)
            args = cli.parse_args([])
            args.style = params["style_id"]
            args.style_overrides = params["overrides"]
            args.captions = str(Path(params["captions_path"]).expanduser().resolve()) if params["captions_path"] else None
            args.engine, args.language, args.translate = params["engine"], params["language"], params["translate_to"]
            args.correct, args.glossary = params["correct"], ", ".join(params["glossary"])
            args.size, args.position, args.safe_area = params["size"], params["position"], params["safe_area"]
            args.length, args.burn, args.overwrite = params["length"], params["burn"], params["overwrite"]
            args.formats, args.progress = "srt,vtt,json", stage
            try:
                paths = cli.caption_video(video, args, out)
                row.update(status="completed", outputs=[str(p.resolve()) for p in paths], media_verified=params["burn"],
                           timing_note="Recognition word timestamps are retained; edited, translated or imported subtitle-only text uses estimated word timing.")
            except Exception as error:
                row.update(status="failed", error=api.explain(error) if isinstance(error, api.APIError) else str(error))
            job["results"].append(row)
            job["finished"] += 1
        job["status"] = "failed" if any(r["status"] == "failed" for r in job["results"]) else "completed"
        job["stage"] = job["status"]
    await asyncio.to_thread(run)


@mcp.tool(annotations=READ, structured_output=True)
def get_job(job_id: str) -> dict[str, Any]:
    """Return progress, per-file failures and verified output paths for a caption job. No repeated paid work."""
    if job_id not in JOBS:
        raise ValueError("Unknown job ID. Jobs live only in the current MCP process.")
    return json.loads(json.dumps(JOBS[job_id]))


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
