#!/usr/bin/env python3
"""Render the animated CLI example used by the project README.

Run with: uv run --with pillow scripts/render_cli_demo.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1120
HEIGHT = 630
FPS = 8
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "cli-demo.gif"

PAGE = "#f1f2ef"
SHADOW = "#d9dcd6"
TERMINAL = "#101311"
HEADER = "#151815"
DIVIDER = "#30342f"
TEXT = "#e4e7e1"
MUTED = "#a8ada6"
BLUE = "#6f8cff"
GREEN = "#c5ff55"
RED = "#ff6b61"
YELLOW = "#d8ff55"


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    linux_name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    windows_name = "consolab.ttf" if bold else "consola.ttf"
    candidates = [
        (Path("/System/Library/Fonts/Menlo.ttc"), 1 if bold else 0),
        (Path("/usr/share/fonts/truetype/dejavu") / linux_name, 0),
        (Path("C:/Windows/Fonts") / windows_name, 0),
    ]
    for path, index in candidates:
        if path.exists():
            return ImageFont.truetype(path, size, index=index)
    raise RuntimeError("A supported monospace font was not found")


FONT = load_font(18)
BOLD = load_font(18, bold=True)
SMALL = load_font(13)


def draw_segments(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    segments: list[tuple[str, str, ImageFont.FreeTypeFont]],
) -> None:
    cursor = x
    for value, color, font in segments:
        draw.text((cursor, y), value, fill=color, font=font)
        cursor += int(draw.textlength(value, font=font))


def visible_text(value: str, progress: float) -> str:
    count = max(0, min(len(value), round(len(value) * progress)))
    return value[:count]


def render_frame(time: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAGE)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((62, 61, 1094, 605), radius=6, fill=SHADOW)
    draw.rounded_rectangle((44, 44, 1076, 586), radius=6, fill=TERMINAL)
    draw.rounded_rectangle((44, 44, 1076, 99), radius=6, fill=HEADER)
    draw.rectangle((44, 92, 1076, 99), fill=HEADER)
    draw.line((44, 98, 1076, 98), fill=DIVIDER, width=1)

    draw.ellipse((65, 67, 75, 77), fill=RED)
    draw.ellipse((83, 67, 93, 77), fill=YELLOW)
    draw.ellipse((101, 67, 111, 77), fill="#646965")
    title = "meta-sonata \u00b7 dry run by default"
    title_width = draw.textlength(title, font=SMALL)
    draw.text((1056 - title_width, 65), title, fill="#8d928c", font=SMALL)

    left = 75
    top = 130
    line = 27
    command = 'meta-sonata enrich "~/Music/Nine Inch Nails - The Slip"'
    command_progress = min(1.0, max(0.0, (time - 0.35) / 1.65))
    if time >= 0.35:
        draw_segments(
            draw,
            left,
            top,
            [
                ("$ ", GREEN, BOLD),
                (visible_text(command, command_progress), TEXT, BOLD),
            ],
        )

    events: list[tuple[float, int, list[tuple[str, str, ImageFont.FreeTypeFont]]]] = [
        (2.30, 1, [("scan: files=10  album_groups=1  loose_tracks=0  max_depth=3", MUTED, FONT)]),
        (2.95, 2, [("resolve: 1/1  Nine Inch Nails - The Slip", TEXT, FONT)]),
        (3.55, 3, [("lyrics:  1/1  Nine Inch Nails - The Slip", TEXT, FONT)]),
        (4.10, 4, [("dry run: 1 plan", MUTED, FONT)]),
        (
            4.55,
            5,
            [
                ("album", BLUE, FONT),
                ("  Nine Inch Nails / The Slip  ", TEXT, FONT),
                ("year", BLUE, FONT),
                ("  2008  ", TEXT, FONT),
                ("tracks", BLUE, FONT),
                ("  10", TEXT, FONT),
            ],
        ),
        (
            4.95,
            6,
            [
                ("label", BLUE, FONT),
                ("  The Null Corporation  ", TEXT, FONT),
                ("confidence", BLUE, FONT),
                ("  1.00", TEXT, BOLD),
            ],
        ),
        (5.35, 7, [("Nothing written. Add --write to apply.", GREEN, FONT)]),
    ]
    for starts_at, row, segments in events:
        if time >= starts_at:
            draw_segments(draw, left, top + row * line, segments)

    second_command = command + " --write"
    second_progress = min(1.0, max(0.0, (time - 6.10) / 1.35))
    if time >= 6.10:
        draw_segments(
            draw,
            left,
            top + 9 * line,
            [
                ("$ ", GREEN, BOLD),
                (visible_text(second_command, second_progress), TEXT, BOLD),
            ],
        )
    if time >= 7.80:
        draw.text((left, top + 10.5 * line), "metadata \u00b7 cover \u00b7 lyrics", fill=TEXT, font=FONT)
    if time >= 8.55:
        message = "write complete: changed=10  skipped=0"
        text_width = int(draw.textlength(message, font=BOLD))
        y = int(top + 12 * line)
        draw.rectangle((left, y - 5, left + text_width + 20, y + 32), fill=GREEN)
        draw.text((left + 10, y), message, fill=TERMINAL, font=BOLD)
        if int(time * 2) % 2 == 0:
            draw.rectangle((left + 3, y + 40, left + 12, y + 58), fill=GREEN)

    return image


def main() -> None:
    frame_count = 88
    frames = [render_frame(index / FPS) for index in range(frame_count)]
    palette = frames[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    gif_frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    gif_frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=gif_frames[1:],
        duration=round(1000 / FPS),
        loop=0,
        optimize=True,
        disposal=1,
    )
    print(f"Rendered {OUTPUT} ({WIDTH}x{HEIGHT}, {frame_count / FPS:.1f}s)")


if __name__ == "__main__":
    main()
