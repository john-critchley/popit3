#!/usr/bin/env python3
"""
match_fixed.py - Match s2 patterns against r2 reference by scaling both to same size.

Instead of sliding a 17-row reference over a 30-row s2 pattern (which creates
bias toward sparse chars like '.'), we:
1. Find the content bounding box of the s2 pattern
2. Crop to content rows only
3. Scale both reference and s2 content to a fixed size (17x16)
4. Compare by SSD

This avoids the "slide into blank region" artifact.
"""
import hashlib, json
import numpy as np
from PIL import Image
from pathlib import Path

B45_ALPHA = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
B45_MAP = {c: i for i, c in enumerate(B45_ALPHA)}
B45_SET = set(B45_ALPHA)

REF_CHARS = [chr(c) for c in range(33, 127)]
CHAR_W, CHAR_H = 8, 17


def load_ref(path):
    """Load r2.png reference chars. Returns list of (char, 17x8 binary array)."""
    img = Image.open(path).convert('L')
    arr = (np.array(img) > 50).astype(np.float32)
    refs = []
    for idx, ch in enumerate(REF_CHARS):
        if ch not in B45_SET:
            continue
        c0 = idx * CHAR_W
        cell = arr[:, c0:c0+CHAR_W]  # 17x8
        refs.append((ch, cell))
    return refs


def content_rows(arr, threshold=0.5):
    """Return indices of rows with any content."""
    row_sums = arr.sum(axis=1)
    return np.where(row_sums > threshold)[0]


def normalize_pattern(arr, target_h=17, target_w=8):
    """
    Crop to content bounding box, then resize to target_h x target_w.
    If no content, return zeros.
    Only used for glyph patterns (not reference chars).
    """
    rows = content_rows(arr)
    if len(rows) == 0:
        return np.zeros((target_h, target_w), dtype=np.float32)
    r0, r1 = rows[0], rows[-1] + 1
    col_sums = arr[r0:r1].sum(axis=0)
    cols = np.where(col_sums > 0.5)[0]
    if len(cols) == 0:
        return np.zeros((target_h, target_w), dtype=np.float32)
    c0, c1 = cols[0], cols[-1] + 1
    cropped = arr[r0:r1, c0:c1]
    img = Image.fromarray((cropped * 255).astype(np.uint8), 'L')
    resized = img.resize((target_w, target_h), Image.NEAREST)
    return np.array(resized).astype(np.float32) / 255.0


def compare_normalized(s2_arr, refs, target_h=17, target_w=8):
    """
    Score glyph against each reference char.  Error is L1 difference
    divided by the number of lit pixels in the reference — sparse refs
    like '.' (1 pixel) and ':' (2 pixels) are penalised proportionally
    for each mismatch, so they can't win by matching blank glyph regions.
    """
    s2_norm = normalize_pattern(s2_arr.astype(np.float32), target_h, target_w)
    scores = []
    for ch, ref_arr in refs:
        ref_on = max(1, int(ref_arr.sum()))
        err = float(np.sum(np.abs(s2_norm - ref_arr))) / ref_on
        scores.append((err, ch))
    scores.sort()
    return scores


def binarize(p):
    return (np.array(Image.open(p).convert('L')) >= 128).astype(np.uint8)


def ghash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', default='r2.png')
    ap.add_argument('--glyphs', default='glyphs')
    ap.add_argument('--skip-row', type=int, default=53)
    ap.add_argument('--out', default='/tmp/final_hash_labels_fixed.json')
    ap.add_argument('--top-k', type=int, default=5)
    ap.add_argument('--target-h', type=int, default=17)
    ap.add_argument('--target-w', type=int, default=8)
    args = ap.parse_args()

    print("Loading reference chars from", args.ref)
    refs = load_ref(args.ref)
    print(f"  {len(refs)} B45 reference chars")

    # Load all unique s2 patterns
    glyph_dir = Path(args.glyphs)
    hash_counts = {}
    hash_to_arr = {}
    hash_to_example = {}

    for f in sorted(glyph_dir.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row == args.skip_row:
            continue
        arr = binarize(f)
        h = ghash(arr)
        hash_counts[h] = hash_counts.get(h, 0) + 1
        if h not in hash_to_arr:
            hash_to_arr[h] = arr.astype(np.float32)
            hash_to_example[h] = f.name

    print(f"  {len(hash_counts)} unique patterns")

    results = {}
    print("\nMatching with normalized comparison:")
    print(f"{'hash':18} {'count':6} {'char':4} {'top-k'}")
    print("-" * 80)

    for h in sorted(hash_counts, key=lambda x: -hash_counts[x]):
        count = hash_counts[h]
        arr = hash_to_arr[h]
        scores = compare_normalized(arr, refs, args.target_h, args.target_w)
        best_char = scores[0][1]
        top_k = [(ch, f"{ssd:.1f}") for ssd, ch in scores[:args.top_k]]
        results[h] = {
            'char': best_char,
            'count': count,
            'top_k': top_k,
            'example': hash_to_example[h],
        }
        top_str = '  '.join(f"{ch}:{ssd}" for ch, ssd in top_k)
        print(f"  {h} {count:6d} {best_char!r:4} {top_str}")

    # Save
    hash_to_char = {h: r['char'] for h, r in results.items()}
    with open(args.out, 'w') as f:
        json.dump(hash_to_char, f, indent=2)
    print(f"\nSaved {args.out}")

    # Show invalid triple count
    print("\nChecking invalid triples...")
    grid = {}
    for f in sorted(glyph_dir.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row >= 53:
            continue
        arr = binarize(f)
        h = ghash(arr)
        grid[(row, col)] = hash_to_char.get(h, '?')

    lines = []
    for row in range(53):
        line = ''.join(grid.get((row, col), '?') for col in range(185))
        lines.append(line)
    lines[52] = lines[52].rstrip()
    text = ''.join(lines)

    bad = sum(1 for i in range(0, len(text)-2, 3)
              if B45_MAP.get(text[i], 0) + B45_MAP.get(text[i+1], 0)*45 +
              B45_MAP.get(text[i+2], 0)*2025 > 0xFFFF)
    print(f"Invalid triples: {bad}/{len(text)//3} ({100*bad/(len(text)//3):.1f}%)")


if __name__ == '__main__':
    main()
