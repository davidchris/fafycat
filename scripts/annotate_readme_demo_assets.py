#!/usr/bin/env python3
"""Turn raw README demo captures into final annotated assets."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (13, 13, 13, 235)
TEXT = (240, 240, 240, 255)
BLUE = (30, 95, 175, 255)
YELLOW = (245, 197, 24, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


FONT = load_font(28)


def fit_width(image: Image.Image, width: int = 1200) -> Image.Image:
    if image.width == width:
        return image
    height = int(image.height * width / image.width)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def draw_callout(
    image: Image.Image, text: str, box_xy: tuple[int, int], arrow_to: tuple[int, int], color: tuple[int, int, int, int]
) -> Image.Image:
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    text_bbox = draw.textbbox((0, 0), text, font=FONT)
    padding_x = 18
    padding_y = 14
    x0, y0 = box_xy
    x1 = x0 + (text_bbox[2] - text_bbox[0]) + padding_x * 2
    y1 = y0 + (text_bbox[3] - text_bbox[1]) + padding_y * 2

    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=BG, outline=color, width=3)
    draw.text((x0 + padding_x, y0 + padding_y), text, fill=TEXT, font=FONT)

    anchor_x = x0 if arrow_to[0] < x0 else x1
    anchor_y = y0 + (y1 - y0) // 2
    draw.line((anchor_x, anchor_y, arrow_to[0], arrow_to[1]), fill=color, width=4)
    dot_r = 7
    draw.ellipse(
        (arrow_to[0] - dot_r, arrow_to[1] - dot_r, arrow_to[0] + dot_r, arrow_to[1] + dot_r),
        fill=color,
    )
    return canvas


def save_png(image: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, optimize=True)


def build_gif(frames_dir: Path, output_path: Path) -> None:
    frame_paths = sorted(frames_dir.glob("*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"No GIF frames found in {frames_dir}")

    palette_frames: list[Image.Image] = []
    for frame_path in frame_paths:
        image = fit_width(Image.open(frame_path).convert("RGBA"), 1000)
        palette_frames.append(
            image.quantize(colors=96, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    palette_frames[0].save(
        output_path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=100,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: annotate_readme_demo_assets.py RAW_DIR OUTPUT_DIR")

    raw_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    home = fit_width(Image.open(raw_dir / "home-raw.png").convert("RGBA"))
    review = fit_width(Image.open(raw_dir / "review-raw.png").convert("RGBA"))
    analytics = fit_width(Image.open(raw_dir / "analytics-raw.png").convert("RGBA"))

    review = draw_callout(
        review,
        "Review only the uncertain cases",
        box_xy=(650, 205),
        arrow_to=(1010, 440),
        color=BLUE,
    )
    analytics = draw_callout(
        analytics,
        "See spending by category and month",
        box_xy=(630, 90),
        arrow_to=(960, 365),
        color=YELLOW,
    )

    save_png(home, output_dir / "home.png")
    save_png(review, output_dir / "review-queue.png")
    save_png(analytics, output_dir / "analytics.png")
    build_gif(raw_dir / "gif-frames", output_dir / "fafycat-demo.gif")


if __name__ == "__main__":
    main()
