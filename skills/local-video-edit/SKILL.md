---
name: local-video-edit
description: Cut and join selected ranges from one local video with FFmpeg. Use for jump cuts, highlight reels, trimming false starts, or turning a timestamped transcript into a rough cut without generating any media.
---

# Local Video Edit

Requires Python 3.9+ and a recent FFmpeg build with `libx264`, `ffmpeg` and `ffprobe` on PATH. Tested with FFmpeg 7.1.1. The workflow runs on one SDR source video and a local edit decision list. It needs no API key, model download or upload.

1. Find the source-time ranges to keep from the user's timestamps, an existing timed transcript, or inspection of the source. For speech, start and end on complete thoughts where possible. Verify boundaries against playback if a transcript uses coarse timestamps. Keep original wording and retain context for factual claims.
2. Save the ranges in output order as an array of objects in a local JSON file. Numbers are source seconds with up to six decimal places. Each range should contain a visible source frame. Ranges may be reordered or repeated when the edit calls for it.

   ```json
   [{"start": 2.5, "end": 7}, {"start": 11.2, "end": 16}]
   ```

3. Run the script from this skill directory, passing the source, JSON file and a new MP4 path. Choose a filesystem that supports hard links (for example, APFS or ext4) so the script can publish a finished file atomically. Add `--dry-run` to preview the planned order and total duration.

   ```sh
   python3 scripts/edit.py input.mp4 cuts.json edited.mp4
   ```

4. Check the output duration against the plan to within frame/encoder rounding. Preview each cut and verify picture, sound and transitions. Both the source and existing outputs are protected. The new MP4 contains the primary video encoded as H.264 and the first audio track encoded as AAC if present.

Caption the edited video with the separate Just Captions skill or retime existing subtitles to the new edit. Original subtitle timestamps refer to the uncut source.
