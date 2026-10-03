---
name: justcaptions
description: Add styled captions/subtitles to videos on this machine — transcribe speech, make SRT/VTT/JSON files, and burn captions into the video (yellow box, white outline, black box, karaoke word highlight, Emoji style). Handles one video or a whole folder in batch, and can translate or AI-correct captions through the Just Captions API. Use when the user asks to caption, subtitle, transcribe a video into SRT, burn in subtitles, add TikTok/Reels-style captions, or translate a video's captions.
---

# Just Captions

Everything runs through one script in this skill's folder: `scripts/jc.py`.
Needs `ffmpeg` and Python 3.9+ with Pillow (`pip install Pillow`).

## Transcription engine

- API key found (`JUSTCAPTIONS_API_KEY`, else `~/.config/justcaptions/api_key`) → Just Captions API: best accuracy, and needed for `--correct`, `--translate` and AI emoji picks.
- Otherwise → local `faster-whisper` (`pip install faster-whisper`; `--model small` default, `base` is faster, `large-v3` is best).
- Neither → the script says so. Ask the user which they want; don't install packages without asking.

**No key, but the user wants an API feature:** ask for their email address, then run
`python3 scripts/jc.py --signup THEIR_EMAIL`. Never make up or guess an email. Signup is instant,
needs no card, and saves the key to `~/.config/justcaptions/api_key`. Don't print the key itself.

Pricing: 30 audio minutes and 50,000 caption characters free every month. After that it's pay as you go
($0.01 per audio minute, $0.01 per 1,000 caption characters) once a card is added at
https://justcaptions.com/api/account/. `python3 scripts/jc.py --account` shows usage and the estimated charge.
If the API refuses because of the free allowance, the free-tier capacity or a spend cap, the script says why. When
faster-whisper is installed, it transcribes locally instead. Pass the message and the account link on to the user.

## Commands

```bash
python3 scripts/jc.py talk.mp4 --burn                       # captions burned in, default yellow box
python3 scripts/jc.py talk.mp4 --style emoji --burn         # 3 big words + emoji, active word highlighted
python3 scripts/jc.py clips/ --style karaoke --burn         # every video in a folder
python3 scripts/jc.py talk.mp4 --formats srt,vtt            # subtitle files only, no burn
python3 scripts/jc.py talk.mp4 --translate es --burn        # Spanish captions (API key)
python3 scripts/jc.py talk.mp4 --correct --glossary "Kila Labs, Just Captions" --burn
python3 scripts/jc.py talk.mp4 --captions talk.srt --burn   # burn an existing/edited SRT, VTT or JSON
python3 scripts/jc.py --list-styles
python3 scripts/jc.py --signup you@example.com              # free API key (ask the user for the email)
python3 scripts/jc.py --account                             # usage this month, estimated charge
```

Options: all 15 IDs from `--list-styles --json` (old names remain valid), `--position top|middle|bottom|0-1`,
`--size small|medium|large`, `--length short|medium|long` (words on screen), `--language en`,
`--out-dir DIR`, `--engine api|local`. Outputs go next to the input: `NAME.srt`, `NAME.json`,
`NAME.captioned.mp4`. Output file paths are printed on stdout, progress on stderr.

To let the user fix wording before burning: run once without `--burn`, edit `NAME.json` or `NAME.srt`,
then rerun with `--captions NAME.json --burn` (JSON keeps word timing for karaoke/emoji).

## Verify before reporting success

1. `ffprobe -v error -show_entries stream=codec_type,width,height -show_entries format=duration NAME.captioned.mp4` — video + audio present, same size and duration as the source.
2. Extract a frame while someone is talking and look at it:
   `ffmpeg -v error -ss 3 -i NAME.captioned.mp4 -frames:v 1 -vf scale=540:-1 /tmp/check.png`, then read the image.
   Check the caption is readable, inside the frame, and matches the speech.
3. Skim `NAME.srt` for obvious recognition mistakes (names, brands) and offer `--glossary` / `--correct`.

## Agent interface

This repository also exposes a local MCP (`justcaptions-mcp`) and packaged CLI (`justcaptions`). Setup: https://justcaptions.com/agents/ . Run `check_environment`, `list_styles`, optionally `preview_style`, then `caption_video` and poll `get_job`. The remote MCP at https://api.justcaptions.com/mcp only handles audio and caption text; render with the local tool.

Use `--safe-area tiktok|reels|shorts|none` and `--style-config FILE.json` for validated overrides. `--json` provides structured CLI results. Existing outputs are protected unless the user explicitly requests `--overwrite`. For batch input, avoid duplicate output basenames by using distinct folders. Corrected/translated words have estimated timing. Portable rendering can differ from native iOS fonts/animations. Never describe estimated word timing as aligned to the audio.
