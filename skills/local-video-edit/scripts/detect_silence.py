#!/usr/bin/env python3
"""Report quiet source ranges for review before making a local cut list."""

import argparse
from decimal import InvalidOperation
import json
import math
from pathlib import Path
import re
import subprocess

from edit import probe


SILENCE_EVENT = re.compile(
    r"^\[(?:Parsed_)?silencedetect[^\]]*\] \[info\] silence_(start|end): (\S+)",
    re.MULTILINE,
)


def detect(source, duration, audio, noise_db, min_duration):
    filters = (
        f"aresample=async=1:first_pts=0,apad,atrim=end={duration:.6f},"
        f"silencedetect=n={noise_db}dB:d={min_duration:.6f}"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "repeat+level+info",
            "-xerror", "-i", str(source),
            "-map", f"0:{audio}", "-af", filters, "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True,
    )

    ranges = []
    start = None
    for event, value in SILENCE_EVENT.findall(result.stderr):
        if event == "start":
            start = max(0.0, round(float(value), 6))
        elif start is not None:
            end = min(float(duration), round(float(value), 6))
            if end > start:
                ranges.append({"start": start, "end": end})
            start = None
    return ranges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source video with an audio track")
    parser.add_argument("--noise-db", type=float, default=-45, help="Quiet threshold in dBFS (default: -45)")
    parser.add_argument("--min-duration", type=float, default=0.5, help="Minimum quiet seconds (default: 0.5)")
    args = parser.parse_args()
    if not math.isfinite(args.noise_db) or args.noise_db >= 0:
        parser.error("--noise-db must be a finite negative number.")
    if not math.isfinite(args.min_duration) or args.min_duration < 0.000001:
        parser.error("--min-duration must be at least one microsecond and finite.")

    source = args.source.absolute()
    try:
        duration, _, audio = probe(source)
        if audio is None:
            raise ValueError("The source needs an audio track to detect silence.")
        ranges = []
        if args.min_duration <= float(duration):
            ranges = detect(source, duration, audio, args.noise_db, args.min_duration)
        print(json.dumps({"silence": ranges}, indent=2))
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr or f"{error.cmd[0]} exited with status {error.returncode}.\n")
    except (OSError, ValueError, InvalidOperation) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
