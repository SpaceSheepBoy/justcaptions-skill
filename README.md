# Just Captions skill

Caption videos from Claude Code, or from your terminal. This skill transcribes the speech, makes SRT/VTT/JSON files, and burns TikTok/Reels-style captions into the video. It does one video or a whole folder at a time.

The caption styles are ported from the [Just Captions](https://apps.apple.com/app/id6770354079) iPhone app, using the same font sizes, padding, corner radius and colours. Rendering runs on your own machine with Pillow and ffmpeg.

| yellow-box (default) | white-outline | black-box |
| --- | --- | --- |
| ![yellow-box](docs/styles/yellow-box.png) | ![white-outline](docs/styles/white-outline.png) | ![black-box](docs/styles/black-box.png) |

| karaoke | emoji |
| --- | --- |
| ![karaoke](docs/styles/karaoke.png) | ![emoji](docs/styles/emoji.png) |

## Install

You need `ffmpeg` and Python 3.9+ with Pillow:

```bash
brew install ffmpeg          # or: sudo apt install ffmpeg
pip install Pillow
pip install faster-whisper   # optional: offline transcription
```

**As a Claude Code plugin**

```
/plugin marketplace add SpaceSheepBoy/justcaptions-skill
/plugin install justcaptions@justcaptions
```

**As a plain skill**

```bash
git clone https://github.com/SpaceSheepBoy/justcaptions-skill
cp -r justcaptions-skill/skills/justcaptions ~/.claude/skills/
```

Then ask Claude something like *"caption interview.mp4 with the emoji style"* or *"burn Spanish subtitles into everything in ./clips"*.

## Use it without Claude

```bash
S=skills/justcaptions/scripts
python3 $S/jc.py talk.mp4 --burn                      # talk.srt, talk.json, talk.captioned.mp4
python3 $S/jc.py clips/ --style karaoke --burn        # batch: every video in the folder
python3 $S/jc.py talk.mp4 --style emoji --burn
python3 $S/jc.py talk.mp4 --formats srt,vtt           # subtitle files only
python3 $S/jc.py talk.mp4 --captions talk.srt --burn  # burn a subtitle file you edited
python3 $S/jc.py --help
```

| option | values |
| --- | --- |
| `--style` | `yellow-box`, `white-outline`, `black-box`, `karaoke`, `emoji` |
| `--position` | `top`, `middle`, `bottom`, or a fraction like `0.7` |
| `--size` | `small`, `medium`, `large` |
| `--length` | `short`, `medium`, `long`: how many words go on screen |
| `--language` | spoken-language hint, e.g. `en`, `zh`, `es` |
| `--glossary` | names and terms to spell right: `"Kila Labs, Just Captions"` |
| `--engine` | `api` or `local` (by default the API is used when a key is set) |
| `--correct` | AI fix for recognition mistakes (needs an API key) |
| `--translate LANG` | translate the captions (needs an API key) |

To change the wording before you burn: run the script without `--burn`, edit `NAME.json` or `NAME.srt`, then run it again with `--captions NAME.json --burn`. The JSON file keeps per-word timing for karaoke and emoji.

## Just Captions API

Without a key, everything runs offline with faster-whisper. With a key you get:

- cloud transcription (better on accents, noisy audio and many languages)
- `--correct` and `--translate`
- AI emoji picks for the Emoji style (the offline fallback is a keyword table)

The key is free during the beta. Get one at **https://justcaptions.com/api/**, then:

```bash
export JUSTCAPTIONS_API_KEY=jc_live_...
python3 skills/justcaptions/scripts/jc.py --usage   # minutes used this month
```

The API takes audio only. The script pulls a small mono track out of your video, so the video itself is never uploaded, and burning always happens on your machine. API reference: https://justcaptions.com/api/

## Want this on your iPhone?

[Just Captions on the App Store](https://apps.apple.com/app/id6770354079) gives you the same captions on your phone, with on-device transcription, more styles, editing and batch export.

## Development

```bash
python3 -m unittest discover -s tests
python3 tools/gallery.py   # regenerate docs/styles/*.png
```

How burning works: each caption state (one per word for karaoke and emoji) is drawn as a full-frame transparent PNG. The concat demuxer plays the PNGs back as a single image stream with exact durations, and one `overlay` filter puts it over the video. That keeps the ffmpeg command the same size no matter how many captions there are.

## License

The code is MIT. The bundled [Geist](https://github.com/vercel/geist-font) font is SIL OFL 1.1 (`skills/justcaptions/assets/fonts/OFL.txt`).
