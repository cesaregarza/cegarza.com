#!/usr/bin/env python3
"""Deterministically generate first-party static brand assets.

Outputs (all committed under ``src/static``):
- ``img/og-default.png``      1200x630 default social card
- ``icons/apple-touch-icon.png`` 180x180 iOS home-screen icon
- ``icons/icon-192.png``      192x192 web-app-manifest icon
- ``icons/icon-512.png``      512x512 web-app-manifest icon (also used maskable)

These reuse the Console palette (``src/static/css/site.css``) and the favicon
mark (``src/static/icons/favicon.svg``); no new visual language is introduced.

TODO(design): the OG card and icons are functional PLACEHOLDERS rendered with
Pillow's bundled font (the display face, Archivo, ships only as woff2 which
Pillow cannot load). Replace with a designed card/icon set in Archivo when
available. This script is not wired into release automation.

Run: ``uv run python ops/generate_brand_assets.py``
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Console palette (mirrors src/static/css/site.css and favicon.svg).
BG = (11, 16, 32)  # --color-bg #0b1020
MARK_BG = (9, 9, 17)  # favicon rect #090911
ACCENT = (217, 70, 239)  # --accent #d946ef
ACCENT_2 = (255, 197, 140)  # favicon orbit dot #ffc58c
TEXT_PRIMARY = (255, 255, 255)  # --color-text-primary
TEXT_MUTED = (139, 148, 158)  # --color-text-muted #8b949e

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Best-effort scalable font; falls back to Pillow's bitmap default."""
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_mark(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    """Echo the favicon: an orbit ring, a chord, and two nodes."""
    ring = int(radius * 0.62)
    draw.ellipse(
        [cx - ring, cy - ring, cx + ring, cy + ring],
        outline=ACCENT,
        width=max(2, radius // 20),
    )
    draw.line(
        [cx - ring, cy + int(ring * 0.55), cx + ring, cy - int(ring * 0.55)],
        fill=ACCENT,
        width=max(2, radius // 20),
    )
    core = max(4, radius // 8)
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=ACCENT)
    node = max(4, radius // 9)
    nx, ny = cx + ring, cy - int(ring * 0.55)
    draw.ellipse([nx - node, ny - node, nx + node, ny + node], fill=ACCENT_2)


def generate_og_card(path: Path) -> None:
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)

    # Accent rule along the top, echoing the site chrome.
    draw.rectangle([0, 0, width, 8], fill=ACCENT)

    _draw_mark(draw, cx=150, cy=150, radius=150)

    title_font = _font(96)
    sub_font = _font(44)
    draw.text((96, 320), "cegarza.com", font=title_font, fill=TEXT_PRIMARY)
    draw.text((100, 452), "Cesar Garza", font=sub_font, fill=TEXT_MUTED)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def generate_icon(path: Path, size: int) -> None:
    image = Image.new("RGB", (size, size), MARK_BG)
    draw = ImageDraw.Draw(image)
    _draw_mark(draw, cx=size // 2, cy=size // 2, radius=int(size * 0.5))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def main() -> None:
    generate_og_card(STATIC_DIR / "img" / "og-default.png")
    generate_icon(STATIC_DIR / "icons" / "apple-touch-icon.png", 180)
    generate_icon(STATIC_DIR / "icons" / "icon-192.png", 192)
    generate_icon(STATIC_DIR / "icons" / "icon-512.png", 512)
    print("Wrote og-default.png + apple-touch-icon/icon-192/icon-512 PNGs.")


if __name__ == "__main__":
    main()
