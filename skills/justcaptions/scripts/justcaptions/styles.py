"""Caption styles and layout metrics, ported from the Just Captions iOS app.

The numbers mirror `CaptionRenderMetrics` and `CaptionStyle` in the app so a
video captioned here looks like one exported from the app.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

RGB = Tuple[int, int, int]

# App palette (`CaptionBackgroundColorOption.uiColor`).
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
YELLOW: RGB = (255, 227, 77)  # 1.0, 0.89, 0.30
GREEN: RGB = (26, 158, 122)


@dataclass(frozen=True)
class Style:
    name: str
    description: str
    text_color: RGB
    background: Optional[RGB] = None  # rounded pill behind the text
    background_opacity: float = 1.0
    outline_color: RGB = BLACK
    outline_scale: float = 0.0  # 0 = no outline
    shadow_strength: float = 0.0
    highlight_color: Optional[RGB] = None  # active-word colour; None = static
    max_words: Optional[int] = None  # short word groups (Emoji style: 3)
    font_multiplier: float = 1.0
    emoji: bool = False
    uppercase: bool = False


STYLES = {
    "yellow-box": Style(
        name="yellow-box",
        description="Black heavy text on a yellow rounded box (the app's default).",
        text_color=BLACK,
        background=YELLOW,
    ),
    "white-outline": Style(
        name="white-outline",
        description="White text with a thick black outline and soft shadow.",
        text_color=WHITE,
        outline_scale=1.5,
        shadow_strength=2.0,
    ),
    "black-box": Style(
        name="black-box",
        description="White text on a translucent black rounded box.",
        text_color=WHITE,
        background=BLACK,
        background_opacity=0.68,
    ),
    "karaoke": Style(
        name="karaoke",
        description="White outlined text; the word being spoken turns yellow.",
        text_color=WHITE,
        outline_scale=1.0,
        shadow_strength=1.0,
        highlight_color=YELLOW,
    ),
    "emoji": Style(
        name="emoji",
        description="Three big words at a time, active word highlighted, an emoji above each group.",
        text_color=WHITE,
        outline_scale=1.6,
        shadow_strength=1.0,
        highlight_color=YELLOW,
        max_words=3,
        font_multiplier=1.3,
        emoji=True,
        uppercase=True,
    ),
}

DEFAULT_STYLE = "yellow-box"

# Vertical position of the caption centre, as a fraction of the frame height.
POSITIONS = {"top": 0.18, "middle": 0.50, "bottom": 0.82}

# `CaptionSizeOption` scales: (portrait, landscape).
SIZE_SCALES = {"small": (0.70, 0.55), "medium": (0.90, 0.80), "large": (1.25, 1.10)}

# `CaptionLengthOption`: max characters per caption (two lines) for Latin
# scripts, and per line for scripts without spaces (Chinese, Japanese, Thai).
LATIN_CAPTION_CHARS = {
    "portrait": {"short": 48, "medium": 68, "long": 88},
    "landscape": {"short": 70, "medium": 98, "long": 128},
}
COMPACT_LINE_CHARS = {
    "portrait": {"short": 12, "medium": 16, "long": 20},
    "landscape": {"short": 18, "medium": 25, "long": 31},
}


def layout_for(width: int, height: int) -> str:
    return "portrait" if height >= width else "landscape"


def font_size(width: int, height: int, size: str = "medium", style: Optional[Style] = None) -> float:
    layout = layout_for(width, height)
    portrait_scale, landscape_scale = SIZE_SCALES[size]
    if layout == "landscape":
        basis = height * 0.086 * landscape_scale
    else:
        basis = width * 0.06 * portrait_scale
    return max(1.0, basis * (style.font_multiplier if style else 1.0))


def max_width_fraction(width: int, height: int) -> float:
    # Vertical videos keep clear of the TikTok/Reels buttons on the right edge.
    return 0.74 if layout_for(width, height) == "portrait" else 0.86


def text_padding(fs: float) -> Tuple[float, float]:
    return fs * 0.70, fs * 0.40


def corner_radius(fs: float) -> float:
    return max(6.0, fs * 0.30)


def outline_width(fs: float, scale: float) -> float:
    return max(1.5, fs * 0.055) * min(max(scale, 0.0), 3.0)


def shadow(fs: float, strength: float) -> Tuple[float, float, float]:
    """(blur radius, y offset, opacity)."""
    s = min(max(strength, 0.0), 2.0)
    blur = fs * 0.11 * s
    y = max(0.5, fs * 0.035 * s) if s > 0 else 0.0
    return blur, y, min(s * 0.36, 0.72)
