#!/usr/bin/env python3
"""Developer tool: draw each wallpaper's placement maps as overlays, to judge the analysis.

    .venv/bin/python tools/heatmaps.py out.png [wallpaper-folder]

One row per wallpaper: the image, then where it is busy (red) and where its subject is (yellow).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from ricer.paths import Paths
from ricer.wallpapers import Library

TILE = (480, 270)


def overlay(image, values, cols, rows, colour):
    tile = image.copy().convert("RGBA")
    layer = Image.new("RGBA", TILE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cw, ch = TILE[0] / cols, TILE[1] / rows
    for index, value in enumerate(values):
        row, col = divmod(index, cols)
        draw.rectangle([col * cw, row * ch, (col + 1) * cw, (row + 1) * ch],
                       fill=(*colour, int(210 * value)))
    return Image.alpha_composite(tile, layer)


def main():
    out = sys.argv[1]
    paths = Paths.from_env()
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else paths.wallpapers
    found = Library(folder, paths.wallpaper_cache).scan()
    sheet = Image.new("RGB", (TILE[0] * 3, TILE[1] * len(found)), "black")
    for y, wallpaper in enumerate(found):
        image = Image.open(wallpaper.path).convert("RGB").resize(TILE)
        grid = wallpaper.grid
        sheet.paste(image, (0, y * TILE[1]))
        sheet.paste(overlay(image, grid.busy, grid.cols, grid.rows, (255, 40, 40)).convert("RGB"),
                    (TILE[0], y * TILE[1]))
        sheet.paste(overlay(image, grid.subject, grid.cols, grid.rows, (255, 230, 0)).convert("RGB"),
                    (TILE[0] * 2, y * TILE[1]))
    sheet.save(out)
    print(f"{out}: {len(found)} wallpapers (image | busy | subject)")


if __name__ == "__main__":
    main()
