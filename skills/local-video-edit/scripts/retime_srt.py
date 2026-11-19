#!/usr/bin/env python3
"""Retime source SRT captions using the same cut list as edit.py."""

import argparse
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from edit import probe, read_cuts


TIME = r"([0-9]{2,}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})"
TIMING = re.compile(rf"{TIME}[ \t]+-->[ \t]+{TIME}")


def seconds(groups):
    hours, minutes, whole_seconds, milliseconds = map(int, groups)
    return Decimal(hours * 3600 + minutes * 60 + whole_seconds) + Decimal(milliseconds) / 1000


def read_cues(path):
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    cues = []
    for index, block in enumerate(re.split(r"\n(?:[ \t]*\n)+", text.strip("\n")), start=1):
        number, _, rest = block.partition("\n")
        timing, _, body = rest.partition("\n")
        match = TIMING.fullmatch(timing.strip())
        if not re.fullmatch(r"[0-9]+", number.strip()) or not match or not body.strip():
            raise ValueError(f"Invalid SRT cue {index}. Expected a number, timing line and caption text.")
        start, end = seconds(match.groups()[:4]), seconds(match.groups()[4:])
        if start >= end:
            raise ValueError(f"SRT cue {index} must end after it starts.")
        cues.append((start, end, body))
    return sorted(cues, key=lambda cue: cue[0])


def timecode(milliseconds):
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def retime(cues, cuts):
    blocks = []
    offset = Decimal(0)
    for cut in cuts:
        cut_start, cut_end = cut["start"], cut["end"]
        for cue_start, cue_end, body in cues:
            if cue_start >= cut_end:
                break
            start, end = max(cut_start, cue_start), min(cut_end, cue_end)
            if start < end:
                start_ms = int((offset + start - cut_start) * 1000)
                end_ms = int((offset + end - cut_start) * 1000)
                if start_ms < end_ms:
                    blocks.append(f"{len(blocks) + 1}\n{timecode(start_ms)} --> {timecode(end_ms)}\n{body}\n")
        offset += cut_end - cut_start
    return "\n".join(blocks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original video")
    parser.add_argument("cuts", type=Path, help="Same JSON edit list used for the video")
    parser.add_argument("subtitles", type=Path, help="Source UTF-8 SRT")
    parser.add_argument("output", type=Path, help="New SRT for the edited MP4")
    args = parser.parse_args()

    output = args.output.absolute()
    try:
        if output.suffix.lower() != ".srt" or not output.parent.is_dir():
            raise ValueError("Choose a new .srt path in an existing directory.")
        if output.exists() or output.is_symlink():
            raise ValueError(f"Output already exists: {output}")
        duration, _, _ = probe(args.source.absolute())
        cuts = read_cuts(args.cuts, duration)
        cues = read_cues(args.subtitles)
        with TemporaryDirectory(prefix=".local-video-edit-", dir=output.parent) as stage:
            partial = Path(stage) / "edited.srt"
            partial.write_text(retime(cues, cuts), encoding="utf-8")
            os.link(partial, output)
        print(output)
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr or f"{error.cmd[0]} exited with status {error.returncode}.\n")
    except (OSError, ValueError, InvalidOperation) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
