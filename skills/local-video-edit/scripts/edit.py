#!/usr/bin/env python3
"""Assemble source-time video ranges into a new local MP4."""

import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def probe(source):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "format=start_time,duration:stream=index,codec_type,start_time,duration:stream_disposition=attached_pic",
            "-of", "json", str(source),
        ],
        check=True, capture_output=True, text=True,
    )
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])
    video = next(
        (s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if video is None:
        raise ValueError("The source needs a video track.")
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    container = metadata.get("format", {})
    duration = Decimal(container.get("duration", "NaN"))
    if "duration" in video:
        video_start = Decimal(video.get("start_time", "0")) - Decimal(container.get("start_time", "0"))
        video_end = video_start + Decimal(video["duration"])
        if video_end.is_finite() and (not duration.is_finite() or video_end < duration):
            duration = video_end
    if not duration.is_finite() or duration <= 0:
        raise ValueError("The source duration is unavailable.")
    return duration, video["index"], audio["index"] if audio else None


def read_cuts(path, duration):
    cuts = json.loads(path.read_text(encoding="utf-8"), parse_int=Decimal, parse_float=Decimal)
    if not isinstance(cuts, list) or not 1 <= len(cuts) <= 100:
        raise ValueError("The edit list must contain 1 to 100 ranges.")
    for index, cut in enumerate(cuts, start=1):
        if not isinstance(cut, dict) or cut.keys() != {"start", "end"}:
            raise ValueError(f"Range {index} needs start and end in source seconds.")
        times = (cut["start"], cut["end"])
        if any(
            not isinstance(t, Decimal) or t < 0 or t > duration
            or (t and t.normalize().as_tuple().exponent < -6)
            for t in times
        ) or times[0] >= times[1]:
            raise ValueError(f"Range {index} must satisfy 0 <= start < end <= {duration}, with microsecond precision.")
    return cuts


def verify_cut_frames(partial, cut_starts):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "packet=pts", "-of", "csv=p=0", str(partial),
        ],
        check=True, capture_output=True, text=True,
    )
    # All video timestamps are in microseconds. Each nonempty cut starts at its exact offset.
    missing = {str(start): index for index, start in enumerate(cut_starts, start=1)}
    for line in result.stdout.splitlines():
        missing.pop(line.partition(",")[0], None)
    if missing:
        index = next(iter(missing.values()))
        raise ValueError(f"Range {index} contains no video frame. Adjust its start or end time.")


def render(source, output, cuts, video, audio):
    filters = []
    video_inputs = []
    audio_inputs = []
    if audio is not None:
        # Fill leading or intermediate audio gaps on the source timeline.
        labels = "".join(f"[input_audio{i}]" for i in range(len(cuts)))
        filters.append(f"[0:{audio}]aresample=async=1:first_pts=0,apad,asplit={len(cuts)}{labels}")

    offset = Decimal(0)
    cut_starts = []
    for index, cut in enumerate(cuts):
        start, end = (format(cut[key], ".6f") for key in ("start", "end"))
        cut_starts.append(int(offset * 1_000_000))
        filters.append(
            f"[0:{video}]settb=AVTB,trim=start={start}:end={end},"
            f"setpts=PTS-STARTPTS+{cut_starts[-1]}[v{index}]"
        )
        video_inputs.append(f"[v{index}]")
        offset += cut["end"] - cut["start"]
        if audio is not None:
            filters.append(f"[input_audio{index}]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]")
            audio_inputs.append(f"[a{index}]")

    # Position each cut explicitly so a single-frame segment advances the timeline.
    filters.append(f"{''.join(video_inputs)}interleave=n={len(cuts)}[joined]")
    filters.append("[joined]pad=ceil(iw/2)*2:ceil(ih/2)*2[video]")
    if audio is not None:
        filters.append(f"{''.join(audio_inputs)}concat=n={len(cuts)}:v=0:a=1[audio]")
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-filter_complex", ";".join(filters),
        "-map", "[video]", "-map_chapters", "-1", "-c:v", "libx264", "-crf", "18", "-bf", "0",
        "-pix_fmt", "yuv420p", "-fps_mode", "vfr", "-enc_time_base:v", "1:1000000",
        "-video_track_timescale", "1000000",
    ]
    # Interleave sets frame timestamps but can leave the last packet duration unset.
    packet_duration = f"if(eq(NEXT_PTS,NOPTS),{offset:.6f}/TB-PTS,NEXT_PTS-PTS)"
    command.extend(["-bsf:v", f"setts=duration='{packet_duration}'"])
    if audio is not None:
        command.extend(["-map", "[audio]", "-c:a", "aac", "-b:a", "192k"])
    command.extend(["-movflags", "+faststart"])

    with TemporaryDirectory(prefix=".local-video-edit-", dir=output.parent) as stage:
        partial = Path(stage) / "edited.mp4"
        subprocess.run([*command, str(partial)], check=True)
        verify_cut_frames(partial, cut_starts)
        os.link(partial, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source video")
    parser.add_argument("cuts", type=Path, help="JSON array of source ranges to keep")
    parser.add_argument("output", type=Path, help="New MP4 output")
    parser.add_argument("--dry-run", action="store_true", help="Check the cut list and print the plan without rendering")
    args = parser.parse_args()

    source, output = args.source.absolute(), args.output.absolute()
    try:
        if output.suffix.lower() != ".mp4" or not output.parent.is_dir():
            raise ValueError("Choose a new .mp4 path in an existing directory.")
        if output.exists() or output.is_symlink():
            raise ValueError(f"Output already exists: {output}")
        duration, video, audio = probe(source)
        cuts = read_cuts(args.cuts, duration)
        if args.dry_run:
            for count, cut in enumerate(cuts, start=1):
                print(f"{count}. {cut['start']:.6f}–{cut['end']:.6f} s")
            print(f"Planned duration: {sum(cut['end'] - cut['start'] for cut in cuts):f} s")
        else:
            render(source, output, cuts, video, audio)
            print(output)
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr or f"{error.cmd[0]} exited with status {error.returncode}.\n")
    except (OSError, ValueError, InvalidOperation) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
