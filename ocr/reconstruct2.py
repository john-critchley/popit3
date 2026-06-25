#!/usr/bin/env python3
"""
reconstruct2.py  –  Reconstruct Base45 string from labeled glyph patterns.

Reads hash→char mapping from /tmp/final_hash_labels.json,
builds text row by row, outputs to stdout.
"""

import hashlib, json, sys
from pathlib import Path
import numpy as np
from PIL import Image


def binarize(path, threshold=128):
    arr = np.array(Image.open(path).convert('L'))
    return (arr >= threshold).astype(np.uint8)


def ghash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--glyphs',    default='glyphs')
    ap.add_argument('--labels',    default='/tmp/final_hash_labels.json')
    ap.add_argument('--data-rows', type=int, default=53,
                    help='Number of data rows (exclude last/encoder row)')
    ap.add_argument('--cols',      type=int, default=185)
    ap.add_argument('--show-grid', action='store_true',
                    help='Show text as grid (one row per line)')
    args = ap.parse_args()

    hash_to_char = json.load(open(args.labels))

    glyph_dir = Path(args.glyphs)
    grid = {}  # (row, col) -> char

    unknown_hashes = set()
    for f in sorted(glyph_dir.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row >= args.data_rows:
            continue
        arr = binarize(f)
        h = ghash(arr)
        ch = hash_to_char.get(h, '?')
        if ch == '?':
            unknown_hashes.add(h)
        grid[(row, col)] = ch

    if unknown_hashes:
        print(f'Warning: {len(unknown_hashes)} unknown hashes', file=sys.stderr)

    # Build text: row 0..data_rows-1, col 0..cols-1
    lines = []
    for row in range(args.data_rows):
        line = ''
        for col in range(args.cols):
            line += grid.get((row, col), '?')
        lines.append(line)

    if args.show_grid:
        for i, line in enumerate(lines):
            print(f'Row {i:2d}: {line}')
    else:
        text = ''.join(lines)
        print(text, end='')


if __name__ == '__main__':
    main()
