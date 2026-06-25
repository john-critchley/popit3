#!/usr/bin/env python3
"""
Walk by_cluster dirs, send up to 5 unique-hash glyphs per cluster to glyph_id GUI.
Saves results to /tmp/manual_labels.json. Stops on backspace/delete.
"""
import hashlib, json, os, socket, sys
import numpy as np
from PIL import Image
from pathlib import Path

SOCK = '/tmp/glyph_id.sock'
OUT  = '/tmp/manual_labels.json'
CLUSTER_DIR = Path.home() / 'py/popit3/ocr/by_cluster'
MAX_PER_DIR = 5

import argparse
ap = argparse.ArgumentParser()
ap.add_argument('--redo', action='store_true', help='Re-identify all patterns, ignoring existing labels')
ap.add_argument('--max', type=int, default=MAX_PER_DIR, help='Max glyphs per cluster')
ARGS = ap.parse_args()
NORM_W, NORM_H = 8, 17


def norm_hash(path):
    arr = np.array(Image.open(path).convert('L'))
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


def send(glyph_path, label, hash_):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    req = json.dumps({"jsonrpc":"2.0","method":"show","params":{
        "glyph_path": str(glyph_path), "label": label, "hash": hash_
    }, "id": 1}) + '\n'
    s.sendall(req.encode())
    s.shutdown(socket.SHUT_WR)
    buf = b''
    while True:
        d = s.recv(4096)
        if not d: break
        buf += d
    s.close()
    return json.loads(buf.split(b'\n')[0]).get('result', {})


# Load existing results
results = {}
if Path(OUT).exists() and not ARGS.redo:
    results = json.load(open(OUT))
    print(f"Loaded {len(results)} existing labels from {OUT}")
elif ARGS.redo:
    print("--redo: ignoring existing labels, re-identifying all patterns")

seen_hashes = set(results.keys())
total_sent = 0

dirs = sorted(CLUSTER_DIR.iterdir())
for d in dirs:
    if not d.is_dir():
        continue
    cluster_name = d.name
    files = sorted(d.iterdir())

    sent_this_dir = 0
    for f in files:
        if not f.name.endswith('.png'):
            continue
        # Resolve symlink to real glyph path
        real = Path(os.path.realpath(f))
        h = norm_hash(real)
        if h in seen_hashes:
            continue

        label = f"cluster={cluster_name}"
        result = send(real, label, h)

        if result.get('done'):
            print(f"\nDone signal — stopping.")
            json.dump(results, open(OUT, 'w'), indent=2)
            print(f"Saved {len(results)} labels to {OUT}")
            sys.exit(0)

        ch = result.get('char')
        if ch:
            results[h] = ch
            seen_hashes.add(h)
            print(f"  {h}  cluster={cluster_name!r}  → {ch!r}")
            total_sent += 1

        sent_this_dir += 1
        if sent_this_dir >= ARGS.max:
            break

print(f"\nAll done. {total_sent} new labels collected.")
json.dump(results, open(OUT, 'w'), indent=2)
print(f"Saved {len(results)} labels to {OUT}")
