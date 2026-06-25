#!/usr/bin/env python3
"""Find which glyph hash patterns appear in invalid B45 triples."""
import json, hashlib, collections
import numpy as np
from PIL import Image
from pathlib import Path

B45_ALPHA = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
B45_MAP = {c: i for i, c in enumerate(B45_ALPHA)}

labels = json.load(open('/tmp/final_hash_labels2.json'))

def binarize(p, threshold=128):
    return (np.array(Image.open(p).convert('L')) >= threshold).astype(np.uint8)

def ghash(arr):
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]

glyph_dir = Path('glyphs')
grid_hash = {}
for f in sorted(glyph_dir.glob('*.png')):
    col, row = map(int, f.stem.split('-'))
    if row >= 53:
        continue
    arr = binarize(f)
    h = ghash(arr)
    grid_hash[(row, col)] = h

# Build linear sequence of (char, hash) pairs
seq_chars = []
seq_hashes = []
for row in range(53):
    for col in range(185):
        h = grid_hash.get((row, col))
        ch = labels.get(h, '?') if h else '?'
        seq_chars.append(ch)
        seq_hashes.append(h)

text = ''.join(seq_chars)

# Find all invalid triples and which hashes are involved
hash_bad_count = collections.Counter()
hash_total_count = collections.Counter()
bad_triples = []

i = 0
while i + 2 < len(text):
    a, b, c = B45_MAP[text[i]], B45_MAP[text[i+1]], B45_MAP[text[i+2]]
    n = a + b*45 + c*2025
    h0, h1, h2 = seq_hashes[i], seq_hashes[i+1], seq_hashes[i+2]
    if n > 0xFFFF:
        hash_bad_count[h0] += 1
        hash_bad_count[h1] += 1
        hash_bad_count[h2] += 1
        bad_triples.append((i, text[i], text[i+1], text[i+2], n, h0, h1, h2))
    hash_total_count[h0] += 1
    hash_total_count[h1] += 1
    hash_total_count[h2] += 1
    i += 3

print(f"Total invalid triples: {len(bad_triples)}")
print()
print("Hashes most involved in invalid triples:")
print(f"{'hash':18} {'char':4} {'bad':6} {'total':7} {'%bad':7}")
for h, bad in hash_bad_count.most_common(20):
    total = hash_total_count[h]
    ch = labels.get(h, '?')
    print(f"  {h} {ch!r:4} {bad:6} {total:7} {100*bad/total:7.1f}%")

print()
print("First 20 invalid triples:")
for pos, a, b, c, n, h0, h1, h2 in bad_triples[:20]:
    row, col = divmod(pos, 185)
    print(f"  pos={pos} (row={row},col={col}): {a!r}{b!r}{c!r} → {n} | hashes: {h0[:8]} {h1[:8]} {h2[:8]}")
