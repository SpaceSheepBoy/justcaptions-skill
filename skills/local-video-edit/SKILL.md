---
name: local-video-edit
description: Cut and join selected ranges from one local video with FFmpeg. Use for jump cuts, highlight reels, trimming false starts, or turning a timestamped transcript into a rough cut without generating any media.
---

# Local Video Edit

Requires Python 3.9+ and a recent FFmpeg build with `libx264`, `ffmpeg` and `ffprobe` on PATH. Tested with FFmpeg 7.1.1. The workflow runs on one SDR source video and a local edit decision list. It needs no API key, model download or upload.

1. Find the source-time ranges to keep from the user's timestamps, an existing timed transcript, or inspection of the source. For speech, start and end on complete thoughts where possible. Verify boundaries against playback if a transcript uses coarse timestamps. Keep original wording and retain context for factual claims.
2. Save the ranges in output order as an array of objects in a local JSON file. Numbers are source seconds with up to six decimal places. Each range should contain a visible source frame. If a cut starts between frames, the first frame in the range fills the opening. Later frames keep their original timing relative to the cut start so they stay aligned with audio and retimed captions. Ranges may be reordered or repeated when the edit calls for it.

   ```json
   [{"start": 2.5, "end": 7}, {"start": 11.2, "end": 16}]
   ```

3. Run the script from this skill directory, passing the source, JSON file and a new MP4 path. Choose a filesystem that supports hard links (for example, APFS or ext4) so the script can publish a finished file atomically. Add `--dry-run` to check the cut list and preview the planned order and total duration. The full render checks that every range contains a frame. If it reports an empty range or FFmpeg reports an empty video, adjust the selection and retry.

   ```sh
   python3 scripts/edit.py input.mp4 cuts.json edited.mp4
   ```

4. Check the output duration against the plan to within frame/encoder rounding. Preview each cut and verify picture, sound and transitions. Both the source and existing outputs are protected. The new MP4 contains the primary video encoded as H.264 and the first audio track encoded as AAC if present. The export omits source chapters and file-level tags such as title and GPS location.

## Export a vertical MP4

```sh
python3 scripts/edit.py input.mp4 cuts.json vertical.mp4 --portrait
```

The output is 1080×1920 with square pixels. The picture is centered and fitted
using its display proportions, with black padding where needed to keep the
whole picture visible. Reuse the same cut list for the SRT.

## Keep existing SRT captions

After exporting the video, pass the original video, the same cut list and a UTF-8 SRT timed to the original video. Use a new SRT path next to the edited MP4.

```sh
python3 scripts/retime_srt.py input.mp4 cuts.json source.srt edited.srt
```

Cues are clipped at cut boundaries and shifted to the edited timeline. Repeated cuts repeat their captions. Cue text, including multiple lines, is preserved. Timestamps are rounded down to whole milliseconds, and any result with zero duration at that precision is dropped. If no cues remain, the script writes an empty SRT. Use a different output path if an SRT already exists. If there is no source subtitle file, caption the edited MP4 with the separate Just Captions skill.

## Find quiet passages

Copy the whole skill directory so the scripts can share source probing. Run
the detector from that directory before making a cut list:

```sh
python3 scripts/detect_silence.py input.mp4 --noise-db -45 --min-duration 0.5
```

It reads the first audio track with FFmpeg and prints JSON such as
`{"silence":[{"start":2.1,"end":3.2}]}`. Times are source seconds. The defaults
are −45 dBFS and 0.5 seconds. Audio gaps and a quiet tail can be reported up
to the end of the picture. With no qualifying ranges the array is empty.
A video without an audio track returns an error.

Review the candidates against playback, especially around quiet speech and
intentional pauses. Put the ranges you want to **keep** into the cut list
for `edit.py`, then reuse that list with `retime_srt.py` if you have source
captions.
