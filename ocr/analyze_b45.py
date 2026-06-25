#!/usr/bin/env python3
"""
Analyze B45 text triple by triple, reporting failures with alternatives.
"""
import json, hashlib, sys
import numpy as np
from PIL import Image
from pathlib import Path
from match_fixed import load_ref, compare_normalized

B45_ALPHA = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
B45_MAP = {c: i for i, c in enumerate(B45_ALPHA)}

labels = json.load(open('/tmp/final_hash_labels_r2.json'))

def binarize(p, threshold=128):
    return (np.array(Image.open(p).convert('L')) >= threshold).astype(np.uint8)
def ghash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]

refs = load_ref('r2.png')
glyph_dir = Path('glyphs')

hash_to_arr = {}
hash_to_scores = {}
grid = {}
grid_hash = {}

for f in sorted(glyph_dir.glob('*.png')):
    col, row = map(int, f.stem.split('-'))
    if row >= 53:
        continue
    arr = binarize(f)
    h = ghash(arr)
    grid_hash[(row, col)] = h
    grid[(row, col)] = labels.get(h, '?')
    if h not in hash_to_arr:
        hash_to_arr[h] = arr.astype(np.float32)

print("Computing scores...", file=sys.stderr)
for h, arr in hash_to_arr.items():
    scores = compare_normalized(arr, refs, 17, 8)
    hash_to_scores[h] = scores
print(f"Done ({len(hash_to_scores)} patterns)", file=sys.stderr)

lines = []
for row in range(53):
    lim = 147 if row == 52 else 185
    line = ''.join(grid.get((row, col), '?') for col in range(lim))
    lines.append(line)
text = ''.join(lines)

def get_pos(i):
    """Convert linear position to (row, col)."""
    return divmod(i, 185)

def valid_alts(h, a_val, b_val, max_results=5):
    """Return valid alternatives for 3rd-position char given fixed a, b values."""
    result = []
    if h not in hash_to_scores:
        return result
    for ssd, ch in hash_to_scores[h]:
        if ch not in B45_MAP:
            continue
        c_val = B45_MAP[ch]
        if c_val > 32:
            continue
        if a_val + b_val*45 + c_val*2025 <= 0xFFFF:
            result.append((ssd, ch, c_val))
        if len(result) >= max_results:
            break
    return result

failures = []
ok = 0
for i in range(0, len(text)-2, 3):
    a_ch, b_ch, c_ch = text[i], text[i+1], text[i+2]
    if a_ch not in B45_MAP or b_ch not in B45_MAP or c_ch not in B45_MAP:
        continue
    a, b, c = B45_MAP[a_ch], B45_MAP[b_ch], B45_MAP[c_ch]
    n = a + b*45 + c*2025
    if n <= 0xFFFF:
        ok += 1
        continue
    r0, c0 = get_pos(i)
    h2_row, h2_col = divmod(i+2, 185)
    h2 = grid_hash.get((h2_row, h2_col))
    alts = valid_alts(h2, a, b)
    alt_str = '  '.join(f"{ch}(v={v},ssd={ssd:.0f})" for ssd, ch, v in alts)
    failures.append((i, r0, c0, a_ch, b_ch, c_ch, n, h2, alts))
    print(f"pos={i:5d} ({r0},{c0:3d})  {a_ch!r}{b_ch!r}{c_ch!r}={n}  3rd_hash={h2[:8] if h2 else '?'}  alts: {alt_str or 'NONE'}")

print(f"\nOK: {ok}  Failed: {len(failures)}", file=sys.stderr)
