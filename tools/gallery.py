"""Renders docs/styles/*.png, the style gallery in the README.

  python3 tools/gallery.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "justcaptions" / "scripts"))

from justcaptions import styles  # noqa: E402
from justcaptions.grouping import Caption, Word  # noqa: E402
from justcaptions.render import Renderer  # noqa: E402

W, H = 1080, 1920
TEXT = "make money with coffee and pizza"


def background() -> Image.Image:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=(int(40 + 60 * t), int(70 + 40 * t), int(110 - 30 * t)))
    return img


def main() -> None:
    out = ROOT / "docs" / "styles"
    out.mkdir(parents=True, exist_ok=True)
    for name, style in styles.STYLES.items():
        tokens = TEXT.split()[:3] if style.max_words else TEXT.split()
        words = [Word(t, i * 0.3, i * 0.3 + 0.3) for i, t in enumerate(tokens)]
        caption = Caption(0, 2, " ".join(tokens), words, "💰" if style.emoji else None)
        frame = Renderer(W, H, style, position=0.5).frame(caption, active=1 if style.highlight_color else None)
        img = background().convert("RGBA")
        img.alpha_composite(frame)
        crop = img.crop((0, H // 2 - 330, W, H // 2 + 270)).convert("RGB").resize((540, 300))
        crop.save(out / f"{name}.png", optimize=True)
        print(out / f"{name}.png")


if __name__ == "__main__":
    main()
