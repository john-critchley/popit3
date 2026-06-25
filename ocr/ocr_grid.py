#!/usr/bin/env python3
"""
ocr_grid.py — OCR the glyph grid and output the text.
Reads glyphs/, applies norm_hash, looks up in manual_labels.json.
Skips row 53 (encoder summary). Outputs one row per line to stdout.
"""
import hashlib, json, sys
import numpy as np
from PIL import Image
from pathlib import Path

GLYPHS_DIR   = Path.home() / 'py/popit3/ocr/glyphs'
LABELS_FILE  = Path('/tmp/manual_labels.json')
GRID_META    = Path.home() / 'py/popit3/ocr/grid_meta.json'
NORM_W, NORM_H = 8, 17


def norm_hash(arr):
    binary = arr < 128
    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any():
        return 'blank'
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    cropped = arr[r0:r1+1, c0:c1+1]
    resized = Image.fromarray(cropped, 'L').resize((NORM_W, NORM_H), Image.NEAREST)
    return hashlib.sha256((np.array(resized) < 128).astype(np.uint8).tobytes()).hexdigest()[:16]


def main():
    meta   = json.load(open(GRID_META))
    labels = json.load(open(LABELS_FILE))
    labels['blank'] = ' '

    n_cols = meta['n_cols']
    n_rows = meta['n_rows']

    missing = set()
    lines = []
    for row in range(n_rows):
        if row == 53:
            continue
        line = []
        for col in range(n_cols):
            path = GLYPHS_DIR / f'{col}-{row}.png'
            if not path.exists():
                line.append('?')
                continue
            arr = np.array(Image.open(path).convert('L'))
            h = norm_hash(arr)
            ch = labels.get(h)
            if ch is None:
                missing.add(h)
                line.append('?')
            else:
                line.append(ch)
        lines.append(''.join(line))

    if missing:
        print(f'WARNING: {len(missing)} unknown hashes: {missing}', file=sys.stderr)

    for line in lines:
        print(line)


if __name__ == '__main__':
    main()
