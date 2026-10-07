"""Portable caption presets and layout metrics inspired by the Just Captions app.

The versioned catalog controls the renderer; fonts and sampled animations may
differ from native iOS exports.
"""

import json
import re
from dataclasses import dataclass, replace
from .assets import ASSETS
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
    animation: str = "none"
    highlight_box: bool = False
    font_family: str = "sans"
    font_id: Optional[str] = None
    glow: bool = False


def catalog() -> dict:
    return json.loads((ASSETS / "styles.json").read_text(encoding="utf-8"))


def font_catalog() -> dict:
    data = catalog()
    return {"catalog_version": data["catalog_version"], "rendering": "local", "fonts": data["fonts"]}


def color(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Colors must be #RRGGBB.")
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _style(row):
    fields = {k: v for k, v in row.items() if k in Style.__dataclass_fields__}
    fields["name"] = row["id"]
    for key in ("text_color", "background", "outline_color", "highlight_color"):
        if key in fields:
            fields[key] = color(fields[key])
    return Style(**fields)


STYLES = {row["id"]: _style(row) for row in catalog()["styles"]}
for alias in catalog()["aliases"]:
    if "alias_for" in alias:
        STYLES[alias["id"]] = replace(STYLES[alias["alias_for"]], name=alias["id"])
    else:
        STYLES[alias["id"]] = _style(alias)


def resolve(style_id: str, overrides=None) -> Style:
    app_ids = {row["app_style_id"]: row["id"] for row in catalog()["styles"]}
    key = app_ids.get(style_id, style_id)
    if key not in STYLES:
        raise ValueError(f"Unknown style {style_id!r}. Call list_styles first.")
    changes = dict(overrides or {})
    unknown = set(changes) - set(catalog()["overrides"])
    if unknown:
        raise ValueError(f"Unknown style overrides: {', '.join(sorted(unknown))}")
    ranges = {"background_opacity": (0, 1), "outline_scale": (0, 3), "shadow_strength": (0, 2), "font_multiplier": (.5, 2)}
    for k, (low, high) in ranges.items():
        if k in changes and (type(changes[k]) not in (int, float) or not low <= changes[k] <= high):
            raise ValueError(f"{k} must be between {low} and {high}.")
    for k in ("text_color", "background", "outline_color", "highlight_color"):
        if k in changes:
            if changes[k] is None and k in ("text_color", "outline_color"):
                raise ValueError(f"{k} cannot be null.")
            changes[k] = color(changes[k])
    if "font_family" in changes and changes["font_family"] not in ("sans", "regular", "serif"):
        raise ValueError("font_family must be sans, regular or serif.")
    if "font_id" in changes and changes["font_id"] is not None:
        if not isinstance(changes["font_id"], str) or changes["font_id"] not in {f["id"] for f in catalog()["fonts"]}:
            raise ValueError("Unknown font_id. Call list_fonts for supported named fonts.")
    if "uppercase" in changes and type(changes["uppercase"]) is not bool:
        raise ValueError("uppercase must be boolean.")
    if "max_words" in changes and changes["max_words"] is not None and (type(changes["max_words"]) is not int or not 1 <= changes["max_words"] <= 20):
        raise ValueError("max_words must be an integer from 1 to 20, or null.")
    return replace(STYLES[key], **changes)


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
