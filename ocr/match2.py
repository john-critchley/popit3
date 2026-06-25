#!/usr/bin/env python3
"""
match2.py  –  Match s2.png glyph patterns against r2.png reference.

r2.png: binary, 756×17, 8px/char, ASCII 33-126 (!..~) in order.
s2.png: binary, glyphs 16×30, 2× scale.

Strategy:
  1. Extract 8×17 chars from r2, scale to 16×17 (2× width).
  2. For each s2 pattern (16×30), slide the 16×17 ref vertically (offsets 0-13).
  3. Best (ref, offset) pair by SSD → character label.
"""

import hashlib, json
from pathlib import Path
from collections import defaultdict

import numpy as np
from PIL import Image

# ASCII 33-126 = ! through ~
REF_CHARS = [chr(c) for c in range(33, 127)]   # 94 chars

CHAR_W = 8    # r2 char width
CHAR_H = 17   # r2 image height
S2_W   = 16   # s2 cell width
S2_H   = 30   # s2 cell height
REF_CHARS_N = 94


def load_ref(path):
    """Load r2.png, return list of (char, 16×17 binary array)."""
    img = Image.open(path).convert('L')
    arr = (np.array(img) > 50).astype(np.float32)
    refs = []
    for idx, ch in enumerate(REF_CHARS):
        c0 = idx * CHAR_W
        c1 = c0 + CHAR_W
        cell = arr[:, c0:c1]           # 17×8
        # Scale width 2×: repeat each column
        scaled = np.repeat(cell, 2, axis=1)  # 17×16
        refs.append((ch, scaled))
    return refs


def binarize(p, threshold=128):
    return (np.array(Image.open(p).convert('L')) >= threshold).astype(np.float32)


def glyph_hash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


def load_s2_patterns(glyph_dir, skip_row=None):
    patterns = defaultdict(lambda: {'files': [], 'arr': None})
    for f in sorted(Path(glyph_dir).glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if skip_row is not None and row == skip_row:
            continue
        arr = binarize(f)
        h = glyph_hash(arr)
        patterns[h]['files'].append(f.name)
        patterns[h]['arr'] = arr
    return dict(patterns)


def best_match(s2_arr, refs):
    """Return (char, ssd, offset) of best reference match."""
    best = (None, float('inf'), 0)
    for ch, ref in refs:
        # Slide ref (17×16) over s2 (30×16) vertically
        for off in range(S2_H - CHAR_H + 1):
            window = s2_arr[off:off + CHAR_H, :]
            ssd = np.sum((window - ref) ** 2)
            if ssd < best[1]:
                best = (ch, ssd, off)
    return best


def ascii_art(arr):
    return '\n'.join(''.join('#' if v > 0.5 else '.' for v in row) for row in arr)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref',       default='r2.png')
    ap.add_argument('--glyphs',    default='glyphs')
    ap.add_argument('--skip-row',  type=int, default=53)
    ap.add_argument('--out',       default='char_map2.json')
    ap.add_argument('--show-art',  action='store_true')
    ap.add_argument('--top-k',     type=int, default=3)
    args = ap.parse_args()

    print("Loading reference chars from", args.ref)
    refs = load_ref(args.ref)
    print(f"  {len(refs)} reference chars (!..~)")

    print("Loading s2 patterns...")
    patterns = load_s2_patterns(args.glyphs, skip_row=args.skip_row)
    print(f"  {len(patterns)} unique patterns")

    print("Matching...")
    results = {}
    for h, info in sorted(patterns.items(), key=lambda x: -len(x[1]['files'])):
        arr = info['arr']
        count = len(info['files'])

        # Get top-k matches
        scores = []
        for ch, ref in refs:
            best_ssd = float('inf')
            for off in range(S2_H - CHAR_H + 1):
                ssd = np.sum((arr[off:off+CHAR_H, :] - ref) ** 2)
                if ssd < best_ssd:
                    best_ssd = ssd
            scores.append((best_ssd, ch))
        scores.sort()

        best_char = scores[0][1]
        results[h] = {
            'char': best_char,
            'count': count,
            'top_k': [(ch, float(ssd)) for ssd, ch in scores[:args.top_k]],
            'example': info['files'][0],
        }

    print("\nResults (sorted by count):")
    print(f"{'char':6} {'count':6}  {'top-k matches'}")
    print("-" * 70)
    for h, r in sorted(results.items(), key=lambda x: -x[1]['count']):
        top = '  '.join(f"{ch}:{ssd:.0f}" for ch, ssd in r['top_k'])
        note = ''
        if r['top_k'][0][1] > 40:
            note = ' ← uncertain'
        print(f"  {r['char']!r:4} {r['count']:6d}  {top}{note}")

    if args.show_art:
        print("\nASCII art of each pattern:")
        for h, r in sorted(results.items(), key=lambda x: -x[1]['count']):
            print(f"\n=== char={r['char']!r} count={r['count']} ===")
            print(ascii_art(patterns[h]['arr']))

    # Build file→char mapping
    hash_to_char = {h: r['char'] for h, r in results.items()}
    file_mapping = {}
    for f in sorted(Path(args.glyphs).glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row == args.skip_row:
            continue
        arr = binarize(f)
        h = glyph_hash(arr)
        file_mapping[f.name] = hash_to_char.get(h, '?')

    with open(args.out, 'w') as fh:
        json.dump({'hash_to_char': hash_to_char,
                   'results': results,
                   'file_mapping': file_mapping}, fh, indent=2)
    print(f"\nSaved {args.out}")


if __name__ == '__main__':
    main()
