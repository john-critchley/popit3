#!/usr/bin/env python3
"""
identify.py  –  Group binary glyphs by exact pixel pattern, show ASCII art of each unique glyph,
                and build a position→char mapping.

Usage:
    python3 identify.py [--glyphs glyphs] [--threshold 128] [--out mapping.json]
                        [--known-row 53 --known-text "python3 encode.py ..."]

Steps:
  1. Load all glyph images, binarize
  2. Hash each glyph's pixel pattern
  3. Group files by hash → unique visual patterns
  4. Print ASCII art of each unique pattern
  5. If --known-row given, use those chars to pre-label matching patterns
  6. Save {filename: char} mapping JSON
"""

import argparse, hashlib, json, os, sys
from pathlib import Path
from collections import defaultdict

import numpy as np
from PIL import Image


def binarize(img_path, threshold=128):
    img = Image.open(img_path).convert('L')
    arr = np.array(img)
    return (arr >= threshold).astype(np.uint8)


def glyph_hash(binary_arr):
    return hashlib.sha256(binary_arr.tobytes()).hexdigest()[:16]


def ascii_art(binary_arr, on='#', off='.'):
    lines = []
    for row in binary_arr:
        lines.append(''.join(on if v else off for v in row))
    return '\n'.join(lines)


def parse_filename(fname):
    """Return (col_idx, row_idx) from 'COL-ROW.ext'"""
    stem = Path(fname).stem
    col, row = stem.split('-')
    return int(col), int(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--glyphs',      default='glyphs')
    ap.add_argument('--threshold',   type=int,   default=128)
    ap.add_argument('--out',         default='mapping.json')
    ap.add_argument('--known-row',   type=int,   default=-1,
                    help='Row index (0-based) whose content is known')
    ap.add_argument('--known-text',  default='',
                    help='Text content of known row (left to right)')
    ap.add_argument('--show-art',    action='store_true',
                    help='Print ASCII art of each unique glyph')
    ap.add_argument('--ascii-out',   default='',
                    help='Write ASCII art summary to this file')
    args = ap.parse_args()

    glyph_dir = Path(args.glyphs)
    files = sorted(glyph_dir.glob('*.png'), key=lambda p: parse_filename(p.name))
    print(f"Loading {len(files)} glyphs from '{glyph_dir}/'")

    # Load and hash
    hash_to_files = defaultdict(list)
    hash_to_arr   = {}
    file_to_hash  = {}

    for fpath in files:
        arr = binarize(fpath, args.threshold)
        h = glyph_hash(arr)
        hash_to_files[h].append(fpath.name)
        hash_to_arr[h]  = arr
        file_to_hash[fpath.name] = h

    print(f"Unique glyph patterns: {len(hash_to_files)}")

    # Pre-label from known row
    hash_to_char = {}
    if args.known_row >= 0 and args.known_text:
        row = args.known_row
        text = args.known_text
        labeled = 0
        for col_idx, ch in enumerate(text):
            fname = f"{col_idx}-{row}.png"
            if fname in file_to_hash:
                h = file_to_hash[fname]
                if h not in hash_to_char:
                    hash_to_char[h] = ch
                    labeled += 1
                elif hash_to_char[h] != ch:
                    print(f"  CONFLICT: hash {h} already={hash_to_char[h]!r} new={ch!r}")
        print(f"Pre-labeled {labeled} unique patterns from known row {row}")

    # Sort unique glyphs by frequency descending
    sorted_hashes = sorted(hash_to_files.keys(), key=lambda h: -len(hash_to_files[h]))

    art_lines = []
    for rank, h in enumerate(sorted_hashes):
        fnames = hash_to_files[h]
        arr    = hash_to_arr[h]
        char   = hash_to_char.get(h, '?')
        count  = len(fnames)
        art    = ascii_art(arr)
        label  = f"Pattern {rank:3d} | count={count:5d} | char={char!r} | hash={h}"
        art_lines.append(label)
        art_lines.append(art)
        art_lines.append('')

    if args.show_art or not args.ascii_out:
        for line in art_lines:
            print(line)

    if args.ascii_out:
        with open(args.ascii_out, 'w') as f:
            f.write('\n'.join(art_lines))
        print(f"ASCII art written to {args.ascii_out}")

    # Build filename→char mapping
    mapping = {}
    for fname, h in file_to_hash.items():
        mapping[fname] = hash_to_char.get(h, None)

    unlabeled = sum(1 for v in mapping.values() if v is None)
    print(f"Labeled: {len(mapping)-unlabeled}/{len(mapping)} glyphs")

    # Also save hash→char for manual editing
    hash_labels = {h: hash_to_char.get(h, '?') for h in sorted_hashes}
    out = {
        'mapping': mapping,
        'hash_labels': hash_labels,
        'unique_patterns': len(hash_to_files),
    }
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"Saved {args.out}")

    # Print summary table of unique patterns sorted by char
    labeled_patterns = [(h, hash_to_char[h], len(hash_to_files[h]))
                        for h in sorted_hashes if h in hash_to_char]
    if labeled_patterns:
        print(f"\nLabeled patterns ({len(labeled_patterns)}):")
        for h, ch, cnt in sorted(labeled_patterns, key=lambda x: x[1]):
            print(f"  {ch!r:4s}  count={cnt:5d}  hash={h}")

    unlabeled_patterns = [(h, len(hash_to_files[h]))
                          for h in sorted_hashes if h not in hash_to_char]
    print(f"\nUnlabeled patterns: {len(unlabeled_patterns)}")
    for h, cnt in unlabeled_patterns[:20]:
        print(f"  hash={h}  count={cnt:5d}  example={hash_to_files[h][0]}")


if __name__ == '__main__':
    main()
