#!/usr/bin/env python3
"""
match_ref.py  –  Match s2.png glyph patterns against ASCII reference image r.png.

r.png: screenshot of ASCII chars 32-126 in order (with extra content on the left).
s2.png glyphs: 16×30px cells, binary (0 or 191).

Strategy:
  1. Segment r.png from the first gap onwards, extract 95 reference glyphs
  2. Scale each reference glyph to 16×30px
  3. For each unique pattern in s2 data rows, find best-match reference char by SSD
  4. Output hash→char mapping
"""

import argparse, hashlib, json, os
from pathlib import Path
from collections import defaultdict

import numpy as np
from PIL import Image


REF_CHARS = ''.join(chr(c) for c in range(32, 127))  # ASCII 32-126


def binarize_arr(arr, threshold=50):
    return (arr > threshold).astype(np.float32)


def glyph_hash(binary_arr):
    return hashlib.sha256(binary_arr.tobytes()).hexdigest()[:16]


def load_s2_patterns(glyph_dir, threshold=128, skip_row=None):
    """Load all s2.png glyphs, hash them, return hash→{arr, files}."""
    patterns = defaultdict(lambda: {'files': [], 'arr': None})
    glyph_path = Path(glyph_dir)
    for f in sorted(glyph_path.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if skip_row is not None and row == skip_row:
            continue
        arr = np.array(Image.open(f).convert('L'))
        binary = (arr >= threshold).astype(np.float32)
        h = glyph_hash(binary)
        patterns[h]['files'].append(f.name)
        patterns[h]['arr'] = binary
    return dict(patterns)


def segment_reference(ref_path, gap_start=449, period=8, n_chars=95, target_h=30, target_w=16, force_period=False):
    """
    Segment r.png into 95 reference glyphs and scale to target_h × target_w.
    Returns list of (char, arr) tuples.
    """
    img = Image.open(ref_path)
    arr = np.array(img.convert('L'))

    # Skip first row (title bar) — text rows are arr[1:]
    text = arr[1:, :]      # shape: (H-1, W)
    H_text, W = text.shape

    # Find where content resumes after the first gap
    col_sums = (text > 50).sum(axis=0)
    text_start = gap_start + 1
    while text_start < W and col_sums[text_start] == 0:
        text_start += 1
    print(f"Reference text region starts at col {text_start}")

    # Use ACF to refine period in this region (unless forced)
    sig = col_sums[text_start:].astype(float)
    sig -= sig.mean()
    if not force_period and sig.std() > 0:
        acf = np.real(np.fft.ifft(np.fft.fft(sig) * np.conj(np.fft.fft(sig))))
        acf /= acf[0]
        peaks = [i for i in range(3, 25) if acf[i] > acf[i-1] and acf[i] > acf[i+1]]
        if peaks:
            period = peaks[0]
            print(f"Detected period: {period}px (ACF peaks: {peaks[:5]})")
    else:
        print(f"Using forced period: {period}px")

    print(f"Using period={period}px, extracting {n_chars} chars from col {text_start}")

    ref_glyphs = []
    for idx in range(n_chars):
        c0 = text_start + idx * period
        c1 = c0 + period - 1
        if c1 >= W:
            print(f"Warning: char {idx} ({REF_CHARS[idx]!r}) out of bounds at col {c0}")
            break
        cell = text[:, c0:c1+1]  # shape (H_text, period)
        # Binarize
        binary = binarize_arr(cell, threshold=50)
        # Scale to target size using PIL
        cell_img = Image.fromarray((binary * 255).astype(np.uint8), 'L')
        scaled = cell_img.resize((target_w, target_h), Image.NEAREST)
        scaled_arr = np.array(scaled) / 255.0
        ref_glyphs.append((REF_CHARS[idx], scaled_arr))

    print(f"Extracted {len(ref_glyphs)} reference glyphs")
    return ref_glyphs


def match_patterns(patterns, ref_glyphs, top_k=3):
    """For each unique s2 pattern, find the best-matching reference char by SSD."""
    results = {}
    for h, info in sorted(patterns.items(), key=lambda x: -len(x[1]['files'])):
        arr = info['arr']
        count = len(info['files'])
        scores = []
        for ch, ref_arr in ref_glyphs:
            if arr.shape != ref_arr.shape:
                continue
            ssd = np.sum((arr - ref_arr) ** 2)
            scores.append((ssd, ch))
        scores.sort()
        best_char = scores[0][1] if scores else '?'
        results[h] = {
            'char': best_char,
            'count': count,
            'top_k': [(ch, f'{ssd:.1f}') for ssd, ch in scores[:top_k]],
            'example': info['files'][0],
        }
    return results


def ascii_art(arr, on='#', off='.'):
    lines = []
    for row in arr:
        lines.append(''.join(on if v > 0.5 else off for v in row))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref',       default='r.png')
    ap.add_argument('--glyphs',    default='glyphs')
    ap.add_argument('--gap-start', type=int, default=449)
    ap.add_argument('--period',    type=int, default=8)
    ap.add_argument('--force-period', action='store_true')
    ap.add_argument('--skip-row',  type=int, default=53)
    ap.add_argument('--out',       default='char_map.json')
    ap.add_argument('--show-art',  action='store_true')
    args = ap.parse_args()

    print("=== Loading s2 patterns ===")
    patterns = load_s2_patterns(args.glyphs, skip_row=args.skip_row)
    print(f"Unique patterns in data rows: {len(patterns)}")

    print("\n=== Segmenting reference image ===")
    ref_glyphs = segment_reference(args.ref, gap_start=args.gap_start, period=args.period,
                                    force_period=args.force_period)

    print("\n=== Matching patterns ===")
    results = match_patterns(patterns, ref_glyphs)

    print("\n=== Results (sorted by count) ===")
    print(f"{'char':6} {'count':6} {'top3':30} {'example'}")
    print("-" * 70)
    for h, r in sorted(results.items(), key=lambda x: -x[1]['count']):
        top = ' '.join(f"{ch}:{s}" for ch, s in r['top_k'])
        print(f"  {r['char']!r:4} {r['count']:6d}  {top:35}  {r['example']}")

    if args.show_art:
        print("\n=== ASCII art of each unique pattern ===")
        for h, r in sorted(results.items(), key=lambda x: -x[1]['count']):
            arr = patterns[h]['arr']
            print(f"\nPattern char={r['char']!r} count={r['count']} top={r['top_k'][:2]}")
            print(ascii_art(arr))

    # Save full filename→char mapping
    hash_to_char = {h: r['char'] for h, r in results.items()}

    file_mapping = {}
    for f in sorted(Path(args.glyphs).glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row == args.skip_row:
            continue
        arr = np.array(Image.open(f).convert('L'))
        binary = (arr >= 128).astype(np.float32)
        h = glyph_hash(binary)
        file_mapping[f.name] = hash_to_char.get(h, '?')

    out = {
        'hash_to_char': hash_to_char,
        'match_details': results,
        'file_mapping': file_mapping,
    }
    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved {args.out} ({len(file_mapping)} file entries)")


if __name__ == '__main__':
    main()
