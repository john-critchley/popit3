#!/usr/bin/env python3
"""
ocr_patterns.py  –  Use Tesseract to OCR each unique glyph pattern from s2.png.

Each pattern is scaled up 6× (to ~96×180px), padded with white border,
then Tesseract is run in single-character mode.
"""

import hashlib, json, subprocess, tempfile, os
from pathlib import Path
from collections import defaultdict

import numpy as np
from PIL import Image


def binarize(p, threshold=128):
    return (np.array(Image.open(p).convert('L')) >= threshold).astype(np.uint8)

def glyph_hash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


def run_tesseract(arr, scale=6, pad=20, psm=10):
    """Scale up binary glyph, pad, run tesseract, return character string."""
    h, w = arr.shape
    # White background, black text (tesseract expects dark-on-light)
    # Our binary: 1=lit pixel (character), 0=background
    # Invert: character=black(0), background=white(255)
    img_arr = (1 - arr) * 255
    img = Image.fromarray(img_arr.astype(np.uint8), 'L')
    # Scale up
    img_big = img.resize((w * scale, h * scale), Image.NEAREST)
    # Add white padding
    padded = Image.new('L', (w*scale + 2*pad, h*scale + 2*pad), 255)
    padded.paste(img_big, (pad, pad))

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        tmp = f.name
    try:
        padded.save(tmp)
        result = subprocess.run(
            ['tesseract', tmp, 'stdout',
             '--psm', str(psm),
             '-c', 'tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz !"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'],
            capture_output=True, text=True, timeout=10
        )
        text = result.stdout.strip()
        return text
    finally:
        os.unlink(tmp)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--glyphs',   default='glyphs')
    ap.add_argument('--skip-row', type=int, default=53)
    ap.add_argument('--scale',    type=int, default=6)
    ap.add_argument('--psm',      type=int, default=10,
                    help='Tesseract page segmentation mode (10=single char)')
    ap.add_argument('--out',      default='ocr_labels.json')
    args = ap.parse_args()

    glyph_dir = Path(args.glyphs)
    patterns = defaultdict(lambda: {'files': [], 'arr': None})

    for f in sorted(glyph_dir.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row == args.skip_row:
            continue
        arr = binarize(f)
        h = glyph_hash(arr)
        patterns[h]['files'].append(f.name)
        patterns[h]['arr'] = arr

    print(f"Unique patterns: {len(patterns)}")

    results = {}
    for i, (h, info) in enumerate(sorted(patterns.items(), key=lambda x: -len(x[1]['files']))):
        arr = info['arr']
        count = len(info['files'])
        char = run_tesseract(arr, scale=args.scale, psm=args.psm)
        results[h] = {'char': char, 'count': count, 'example': info['files'][0]}
        print(f"  [{i+1:3d}/{len(patterns)}] count={count:5d} → {char!r:6}  {info['files'][0]}")

    # Save
    with open(args.out, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {args.out}")

    # Print summary
    char_map = {h: r['char'] for h, r in results.items()}
    print("\nSummary (char → count):")
    from collections import Counter
    counts = Counter()
    for h, r in results.items():
        counts[r['char']] += r['count']
    for ch, cnt in counts.most_common():
        print(f"  {ch!r:6} → {cnt:6d} glyphs")


if __name__ == '__main__':
    main()
