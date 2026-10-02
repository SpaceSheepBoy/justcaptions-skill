"""Draws captions to transparent PNGs with Pillow."""

import math
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import styles
from .grouping import Caption, is_compact_script

FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Geist-Black.ttf"
# Geist covers Latin, Greek and Cyrillic. Other scripts use a system font;
# an entry with "#n" picks face n of a collection (Hiragino face 2 is W6).
FALLBACK_FONTS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc#2",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]
# (path, bitmap strike size). Colour emoji fonts only render at these sizes.
EMOJI_FONTS = [
    ("/System/Library/Fonts/Apple Color Emoji.ttc", 160),
    ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
    ("/usr/share/fonts/noto/NotoColorEmoji.ttf", 109),
    ("C:/Windows/Fonts/seguiemj.ttf", 109),
]
LINE_HEIGHT = 1.18
_warned = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        print(f"  warning: {message}", file=sys.stderr)


def needs_fallback(text: str) -> bool:
    for ch in text:
        if ord(ch) < 0x250 or not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if not name.startswith(("LATIN", "GREEK", "CYRILLIC")):
            return True
    return False


@lru_cache(maxsize=32)
def _font(size: int, fallback: bool) -> ImageFont.FreeTypeFont:
    if fallback:
        for entry in FALLBACK_FONTS:
            path, _, index = entry.partition("#")
            if Path(path).exists():
                return ImageFont.truetype(path, size, index=int(index or 0))
        _warn_once("no font for this script found; install Noto Sans CJK")
    return ImageFont.truetype(str(FONT), size)


@lru_cache(maxsize=1)
def _emoji_font():
    for path, strike in EMOJI_FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, strike), strike
            except OSError:
                continue
    return None


@lru_cache(maxsize=256)
def emoji_image(emoji: str, side: int) -> Optional[Image.Image]:
    loaded = _emoji_font()
    if not loaded:
        _warn_once("no colour emoji font found; emojis are skipped")
        return None
    font, strike = loaded
    canvas = Image.new("RGBA", (strike * 2, strike * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((strike // 2, strike // 2), emoji, font=font, embedded_color=True)
    box = canvas.getbbox()
    if not box:
        return None
    glyph = canvas.crop(box)
    scale = side / max(glyph.size)
    return glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))), Image.LANCZOS)


def _tokens(caption: Caption, style: styles.Style) -> List[str]:
    raw = [w.text.strip() for w in caption.words if w.text.strip()] or caption.text.split()
    return [t.upper() for t in raw] if style.uppercase else raw


def _wrap(tokens: List[str], widths: List[float], space: float, max_width: float, joiner: bool) -> List[List[int]]:
    """Token indexes per line. One line when it fits, else the most balanced
    two-line split, else greedy."""
    gap = space if joiner else 0.0

    def width(idx: List[int]) -> float:
        return sum(widths[i] for i in idx) + gap * max(len(idx) - 1, 0)

    every = list(range(len(tokens)))
    if width(every) <= max_width or len(tokens) == 1:
        return [every]
    best = None
    for cut in range(1, len(tokens)):
        a, b = every[:cut], every[cut:]
        wa, wb = width(a), width(b)
        if max(wa, wb) <= max_width:
            score = abs(wa - wb) + (max_width if min(len(a), len(b)) == 1 and len(tokens) > 3 else 0)
            if best is None or score < best[0]:
                best = (score, [a, b])
    if best:
        return best[1]
    lines, line = [], []
    for i in every:
        if line and width(line + [i]) > max_width:
            lines.append(line)
            line = []
        line.append(i)
    return lines + [line] if line else lines


class Renderer:
    def __init__(self, width: int, height: int, style: styles.Style, size: str = "medium", position: float = 0.82):
        self.W, self.H = width, height
        self.style = style
        self.fs = styles.font_size(width, height, size, style)
        self.position = position
        self.max_width = width * styles.max_width_fraction(width, height)

    def frame(self, caption: Caption, active: Optional[int] = None) -> Image.Image:
        """A full-frame transparent image with the caption drawn in place.
        `active` is the index of the word being spoken (highlight styles)."""
        st = self.style
        tokens = _tokens(caption, st)
        text = " ".join(tokens)
        fallback = needs_fallback(text) or is_compact_script(text)
        joiner = not is_compact_script(text)
        # Like the app's fitting pass: a caption that would need a third line
        # shrinks (to at most 60%) until it fits on two.
        fs = self.fs
        while True:
            font = _font(round(fs), fallback)
            widths = [font.getlength(t) for t in tokens]
            space = font.getlength(" ")
            pad_x, pad_y = styles.text_padding(fs) if st.background else (0.0, 0.0)
            lines = _wrap(tokens, widths, space, self.max_width - 2 * pad_x, joiner)
            if len(lines) <= 2 or fs <= self.fs * 0.6:
                break
            fs *= 0.92

        line_h = fs * LINE_HEIGHT
        gap = space if joiner else 0.0
        line_widths = [sum(widths[i] for i in l) + gap * (len(l) - 1) for l in lines]
        block_w, block_h = max(line_widths), line_h * len(lines)
        stroke = round(styles.outline_width(fs, st.outline_scale)) if st.outline_scale else 0
        blur, shadow_y, shadow_alpha = styles.shadow(fs, st.shadow_strength)
        margin = math.ceil(stroke + blur * 2 + shadow_y + fs * 0.12)

        box_w = math.ceil(block_w + 2 * pad_x)
        box_h = math.ceil(block_h + 2 * pad_y)
        tile = Image.new("RGBA", (box_w + 2 * margin, box_h + 2 * margin), (0, 0, 0, 0))
        if st.background:
            r, g, b = st.background
            ImageDraw.Draw(tile).rounded_rectangle(
                (margin, margin, margin + box_w, margin + box_h),
                radius=styles.corner_radius(fs),
                fill=(r, g, b, round(255 * st.background_opacity)),
            )

        ascent, descent = font.getmetrics()
        placed: List[Tuple[int, float, float]] = []  # (token index, x, baseline)
        for n, line in enumerate(lines):
            x = margin + pad_x + (block_w - line_widths[n]) / 2
            baseline = margin + pad_y + n * line_h + (line_h - (ascent + descent)) / 2 + ascent
            for i in line:
                placed.append((i, x, baseline))
                x += widths[i] + gap

        if shadow_alpha > 0:
            mask = Image.new("L", tile.size, 0)
            md = ImageDraw.Draw(mask)
            for i, x, y in placed:
                md.text((x, y + shadow_y), tokens[i], font=font, anchor="ls", fill=255, stroke_width=stroke, stroke_fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(max(blur, 0.5)))
            shade = Image.new("RGBA", tile.size, (0, 0, 0, 255))
            shade.putalpha(mask.point(lambda v: round(v * shadow_alpha)))
            # Over the box (if any), under the text.
            tile = Image.alpha_composite(tile, shade)

        draw = ImageDraw.Draw(tile)
        for i, x, y in placed:
            color = st.highlight_color if (st.highlight_color and i == active) else st.text_color
            draw.text((x, y), tokens[i], font=font, anchor="ls", fill=color,
                      stroke_width=stroke, stroke_fill=st.outline_color if stroke else None)

        frame = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        edge = round(self.H * 0.04)
        top = round(self.position * self.H - tile.height / 2)
        top = min(max(top, edge - margin), self.H - tile.height - edge + margin)
        left = round((self.W - tile.width) / 2)
        frame.alpha_composite(tile, (max(left, 0), max(top, 0)))

        if st.emoji and caption.emoji:
            side = math.ceil(fs * 1.8)
            glyph = emoji_image(caption.emoji, side)
            if glyph:
                box_top = top + margin
                above = round(box_top - fs * 0.1 - glyph.height)
                y = above if above >= 0 else round(box_top + box_h + fs * 0.1)
                frame.alpha_composite(glyph, (round((self.W - glyph.width) / 2), y))
        return frame

    def states(self, caption: Caption) -> List[Tuple[float, float, Optional[int]]]:
        """(start, end, active word) spans for one caption."""
        n = len([w for w in caption.words if w.text.strip()])
        if not self.style.highlight_color or n == 0:
            return [(caption.start, caption.end, None)]
        words = [w for w in caption.words if w.text.strip()]
        spans = []
        for k, w in enumerate(words):
            start = caption.start if k == 0 else w.start
            end = words[k + 1].start if k + 1 < n else caption.end
            if end > start:
                spans.append((start, end, k))
        return spans or [(caption.start, caption.end, None)]
