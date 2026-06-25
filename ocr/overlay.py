#!/usr/bin/env python3

import json
from PIL import Image, ImageDraw


IMAGE_PATH = "s.png"
META_PATH = "grid_meta.json"
OUT_PATH = "overlay.png"

GAP_RED = (255, 0, 0, 80)
EDGE_RED = (255, 0, 0, 180)


def main():
    img = Image.open(IMAGE_PATH).convert("RGBA")
    w, h = img.size

    with open(META_PATH, "r") as f:
        meta = json.load(f)

    text_lines = meta["text_lines"]
    char_col_runs = meta["char_col_runs"]

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Horizontal gap bands between text lines
    for (r0a, r1a), (r0b, r1b) in zip(text_lines, text_lines[1:]):
        gap0 = r1a + 1
        gap1 = r0b - 1
        if gap0 <= gap1:
            draw.rectangle([0, gap0, w - 1, gap1], fill=GAP_RED)

    # Vertical gap bands between character columns
    for (c0a, c1a), (c0b, c1b) in zip(char_col_runs, char_col_runs[1:]):
        gap0 = c1a + 1
        gap1 = c0b - 1
        if gap0 <= gap1:
            draw.rectangle([gap0, 0, gap1, h - 1], fill=GAP_RED)

    # Thin red lines at top/bottom of each text line band
    for r0, r1 in text_lines:
        if 0 <= r0 < h:
            draw.line([(0, r0), (w - 1, r0)], fill=EDGE_RED, width=1)
        if 0 <= r1 < h:
            draw.line([(0, r1), (w - 1, r1)], fill=EDGE_RED, width=1)

    # Thin red lines at left/right of each character column run
    for c0, c1 in char_col_runs:
        if 0 <= c0 < w:
            draw.line([(c0, 0), (c0, h - 1)], fill=EDGE_RED, width=1)
        if 0 <= c1 < w:
            draw.line([(c1, 0), (c1, h - 1)], fill=EDGE_RED, width=1)

    out = Image.alpha_composite(img, overlay)
    out.save(OUT_PATH)


if __name__ == "__main__":
    main()
