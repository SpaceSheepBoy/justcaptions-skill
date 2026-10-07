# Just Captions for agents

Caption videos from Codex, Claude Code, any MCP client, or your terminal. This skill transcribes the speech, makes SRT/VTT/JSON files, and burns TikTok/Reels-style captions into the video. It does one video or a whole folder at a time.

15 animated portable presets follow the [Just Captions](https://apps.apple.com/app/id6770354079) app style families. Typography and sampled animations can differ from native iOS. Rendering runs on your machine with Pillow and ffmpeg.

[Choose a style and copy a task](https://justcaptions.com/agents/) · [API docs](https://justcaptions.com/api/) · [OpenAPI](https://justcaptions.com/openapi.json) · [Style catalog](https://justcaptions.com/styles.json)

| Emoji | Mega | Reveal |
| --- | --- | --- |
| ![Emoji](docs/styles/emoji.webp) | ![Mega](docs/styles/mega.webp) | ![Reveal](docs/styles/reveal.webp) |

| Neon | White box | Yellow box |
| --- | --- | --- |
| ![Neon](docs/styles/neon.webp) | ![White box](docs/styles/white-box.webp) | ![Yellow box](docs/styles/yellow-box.webp) |

| Gray box | Yellow outline | Word Highlight |
| --- | --- | --- |
| ![Gray box](docs/styles/gray-box.webp) | ![Yellow outline](docs/styles/yellow-outline.webp) | ![Word Highlight](docs/styles/word-highlight.webp) |

| Highlight Box | Impact | Pop In |
| --- | --- | --- |
| ![Highlight Box](docs/styles/highlight-box.webp) | ![Impact](docs/styles/impact.webp) | ![Pop In](docs/styles/pop-in.webp) |

| Typewriter | Cinema | Editorial |
| --- | --- | --- |
| ![Typewriter](docs/styles/typewriter.webp) | ![Cinema](docs/styles/cinematic.webp) | ![Editorial](docs/styles/editorial.webp) |

## MCP quickstart

Python 3.10+, [uv](https://docs.astral.sh/uv/getting-started/installation/) and ffmpeg are required for the packaged MCP/CLI. The plain skill still works with Python 3.9+ and Pillow.

**Codex** — add to `~/.codex/config.toml`:

```toml
[mcp_servers.justcaptions]
command = "uvx"
args = ["--from", "https://github.com/SpaceSheepBoy/justcaptions-skill/releases/download/v1.3.1/justcaptions_agent-1.3.1-py3-none-any.whl", "justcaptions-mcp"]
startup_timeout_sec = 120

[mcp_servers.justcaptions_cloud]
url = "https://api.justcaptions.com/mcp"
bearer_token_env_var = "JUSTCAPTIONS_API_KEY"
```

**Claude Code** — merge into your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "justcaptions": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "https://github.com/SpaceSheepBoy/justcaptions-skill/releases/download/v1.3.1/justcaptions_agent-1.3.1-py3-none-any.whl", "justcaptions-mcp"]
    },
    "justcaptions_cloud": {
      "type": "http",
      "url": "https://api.justcaptions.com/mcp",
      "headers": {"Authorization": "Bearer ${JUSTCAPTIONS_API_KEY}"}
    }
  }
}
```

Set `JUSTCAPTIONS_API_KEY`, or save a key with the CLI's `--signup YOUR_EMAIL`. The local MCP also reads `~/.config/justcaptions/api_key`. Never put keys in prompts or commits. For recognition without a key, add `"--with", "faster-whisper"` before `"--from"` in the `uvx` arguments. The offline model downloads on first use.

Ask: **“Caption `~/Movies/intro.mp4` with Word Highlight for TikTok. Save MP4, SRT, VTT and JSON in `./captioned/`, and preserve the original.”**

| Tool | Purpose |
| --- | --- |
| `check_environment` | Media tools and recognition/key availability; never reveals credentials |
| `list_styles` | 15 presets, accepted overrides, aliases and safe-area margins |
| `preview_style` | An inline PNG rendered from the selected settings, without a paid API call |
| `caption_video` | Start a video/folder job; returns a job ID immediately |
| `get_job` | Poll stages and per-file verified output paths |
| `get_usage` | Current API usage and estimated monthly charge |

`caption_video` takes `input_path`, `output_dir`, `style_id`, `size`, `position`, `safe_area`, `length`, `overrides`, `captions_path`, `engine`, `language`, `translate_to`, `correct`, `glossary`, `burn`, and `overwrite`. See MCP discovery for typed schemas. Up to 100 files per folder job, two concurrent jobs. Jobs persist locally across process restarts; use `list_jobs` and `resume_job` to recover. Existing outputs are protected unless explicitly overwritten; folder jobs use per-source output directories.

### Remote MCP

`https://api.justcaptions.com/mcp` uses Streamable HTTP and your API key. It handles **audio and caption text**. It does not access local files, preview styles or render MP4.

For Codex:

```toml
[mcp_servers.justcaptions_cloud]
url = "https://api.justcaptions.com/mcp"
bearer_token_env_var = "JUSTCAPTIONS_API_KEY"
```

For Claude Code, a project `.mcp.json` entry:

```json
{"mcpServers":{"justcaptions_cloud":{"type":"http","url":"https://api.justcaptions.com/mcp","headers":{"Authorization":"Bearer ${JUSTCAPTIONS_API_KEY}"}}}}
```

Tools: `list_styles`, `get_pricing`, `get_usage`, `transcribe_audio`, `correct_captions`, `translate_captions`, `pick_emojis`. Cloud operations use the existing API pricing and limits. Supply a unique `request_id` and reuse it only for identical retries. Request hashes and completed replies have a 24-hour replay window, then are removed on a subsequent request or daily cleanup (within 48 hours). The replay store does not retain audio.

## Styles and customization

All 15 presets animate in video exports and the website previews, using spoken-word highlights/reveals, pop entrances, fades, typewriting or a pulsing glow.

The authoritative versioned catalog is [`skills/justcaptions/assets/styles.json`](skills/justcaptions/assets/styles.json): Emoji, Mega, Reveal, Neon, White box, Yellow box, Gray box, Yellow outline, Word Highlight, Highlight Box, Impact, Pop In, Typewriter, Cinema and Editorial. Historical `karaoke`, `black-box` and `white-outline` CLI names remain supported. App IDs such as `wordHighlight` resolve to their portable preset IDs.

The local MCP accepts `overrides`, for example:

```json
{"highlight_color":"#1A9E7A","text_color":"#FFFFFF","font_multiplier":1.2,"max_words":3}
```

Named fonts are bundled for predictable local rendering. Run `justcaptions --list-fonts` or call MCP `list_fonts`; the public `GET /v1/fonts` endpoint returns the same catalog. Set `{"font_id":"anton"}` in overrides or a style config file. The 13 choices include Inter, Poppins, Montserrat, Merriweather, Bebas Neue, Oswald, Roboto Flex, Anton, Barlow Condensed, Nunito, Caveat, Patrick Hand and Permanent Marker. Variable fonts use the catalog's bold axis settings. A named font takes precedence over `font_family`; `"font_id":null` restores generic family selection. These named fonts target Latin captions; other scripts retain the renderer's system font fallback. SRT/VTT remain plain subtitles and do not embed fonts.

The CLI takes the same object in `--style-config FILE.json`. Unknown keys and invalid values are rejected. Colors, backgrounds, outlines, font families, size, word count and letter case are configurable. Use `--safe-area tiktok|reels|shorts|none`; conservative margins keep captions horizontally centered. Platform UI layouts can vary.

Recognition word timestamps are retained when text is unchanged. Corrected/translated text and imported subtitle-only files use **estimated word timing**, not forced alignment. Serif/regular families use available system fonts, with a bundled Geist fallback.

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
python3 $S/jc.py talk.mp4 --style word-highlight --safe-area tiktok --burn --json
python3 $S/jc.py --help
```

| option | values |
| --- | --- |
| `--style` | All 15 preset IDs plus legacy names; `--list-styles --json` returns the catalog |
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

Getting a key is instant and needs no card:

```bash
python3 skills/justcaptions/scripts/jc.py --signup you@example.com
```

The key is saved to `~/.config/justcaptions/api_key` (readable only by you). If `JUSTCAPTIONS_API_KEY` is set, it is used instead.

```bash
python3 skills/justcaptions/scripts/jc.py --account   # usage this month and estimated charge
```

### Pricing

| | price | free every month |
| --- | --- | --- |
| Transcription | $0.01 per audio minute, billed per second | 30 minutes |
| Correct, translate, emoji | $0.01 per 1,000 caption characters sent | 50,000 characters |

- **Free plan** (no card): stops when the free allowance runs out. When faster-whisper is installed, transcription carries on locally.
- **Pay as you go**: add a card at https://justcaptions.com/api/account/ to keep going past the free allowance. Stripe invoices you monthly, and the default spend cap is $100 a month.
- Failed requests are not billed.

The API takes audio only. The script pulls a small mono track out of your video, so the video itself is never uploaded, and burning always happens on your machine. API reference: https://justcaptions.com/api/

## Want this on your iPhone?

[Just Captions on the App Store](https://apps.apple.com/app/id6770354079) provides native caption styling on your phone, with on-device transcription, editing and batch export.

## Development

Install in an isolated environment with `uv pip install -e .`. The worker MCP adapter is open source in `remote/mcp.mjs`; the host injects its existing authenticated API handler. `tools/sync-agent-assets.py --site SITE_DIR --backend BACKEND_DIR` publishes the canonical catalog, OpenAPI and adapter to the site and Worker source. Generated copies should not be edited independently.


```bash
python3 -m unittest discover -s tests
python3 tools/smoke-mcp.py  # exercise the installed MCP with synthetic media
python3 tools/agent-previews.py --site SITE_DIR  # regenerate videos/posters and animated README previews
python3 tools/gallery.py   # regenerate the legacy five-style PNG gallery
```

How burning works: each caption state (one per word for karaoke and emoji) is drawn as a full-frame transparent PNG. The concat demuxer plays the PNGs back as a single image stream with exact durations, and one `overlay` filter puts it over the video. That keeps the ffmpeg command the same size no matter how many captions there are.

## License

The code is MIT. Named font licenses and original source URLs are recorded in the catalog; license texts are included in `assets/fonts/licenses/` (SIL OFL 1.1, plus Apache 2.0 for Permanent Marker). The bundled [Geist](https://github.com/vercel/geist-font) font is SIL OFL 1.1 (`skills/justcaptions/assets/fonts/OFL.txt`).


## Complete first export

After installing Python 3.10+, ffmpeg and the package, run `justcaptions --demo --out-dir ./demo --style word-highlight`. The bundled human-narration sample includes word timestamps and needs no API key or model download. In MCP use `run_demo`, then `get_job`. Narration is attributed in [demo credits](skills/justcaptions/assets/demo/CREDITS.md).

## Durable jobs and account controls

`list_jobs`, `get_job`, `cancel_job` and `resume_job` operate on saved jobs in `~/.local/share/justcaptions` (override with `JUSTCAPTIONS_STATE_DIR`). Resume skips completed files and reuses successful cloud responses. Source files must remain unchanged. An in-flight cloud request can finish and be charged after cancellation. Uncertain cloud requests older than the server replay window require manual usage review rather than silently repeating paid work.

Use `estimate_video` before recognition, supplying known `text_chars` for edits. Estimates exclude unknown future text and do not reserve credit. The API reserves capacity atomically for concurrent requests and all dedicated keys share one account's allowance. Manage monthly spend limits, scoped keys, expiry and revocation at https://justcaptions.com/api/account/. Existing charges and running holds are not removed by lowering a limit.

Setup/export statistics are optional. `JUSTCAPTIONS_METRICS_ID` enables the counters included in copied configurations only when a website visitor opts in. No file paths, captions or API keys are sent by these counters. To disable an installed client's reporting, remove that variable and restart the MCP server.

## Distribution

Install a standard wheel from the latest GitHub release:

```sh
pip install https://github.com/SpaceSheepBoy/justcaptions-skill/releases/download/v1.3.1/justcaptions_agent-1.3.1-py3-none-any.whl
```

GitHub Actions builds and checks wheel/sdist artifacts, attaches them to releases and publishes `server.json` to the official MCP Registry using GitHub OIDC. PyPI publishing uses a trusted publisher when the owner enables it; the website uses the release wheel until that registration is completed.

PyPI pending trusted publisher configuration: project `justcaptions-agent`; GitHub owner `SpaceSheepBoy`; repository `justcaptions-skill`; workflow `release.yml`; environment `pypi`. After registration, enable repository variable `PYPI_PUBLISH_ENABLED=true` and rerun the release workflow.

<!-- mcp-name: io.github.SpaceSheepBoy/justcaptions -->
