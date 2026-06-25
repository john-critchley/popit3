#!/usr/bin/env python3
"""
cluster_glyphs.py - Group glyphs into by_cluster/CHAR/ folders using GPT vision.
Skips row 53 (encoder summary line). Blank glyphs auto-labelled as space.
"""
import os, json, hashlib, warnings, base64
from io import BytesIO
import numpy as np
from PIL import Image
from pathlib import Path
import openai

B45_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
B45_SET = set(B45_CHARS)

FOLDER_NAMES = {
    ' ': '_space_', '$': '_dollar_', '%': '_percent_', '*': '_star_',
    '+': '_plus_',  '-': '_minus_',  '.': '_dot_',    '/': '_slash_',
    ':': '_colon_',
}

def folder_for(ch):
    return FOLDER_NAMES.get(ch, ch)
GLYPHS_DIR = Path.home() / 'py/popit3/ocr/glyphs'
OUTPUT_DIR = Path.home() / 'py/popit3/ocr/by_cluster'
NORM_W, NORM_H = 8, 17

SYSTEM_PROMPT = (
    "You are identifying characters from a Base45 terminal font. "
    "The Base45 alphabet is: 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./: (45 chars). "
    "Each image shows one glyph scaled 8x from a monospace terminal screenshot. "
    "Return a JSON object mapping each hash to the single correct Base45 character. "
    "Every hash shown must appear in your output. Be very precise — pay close attention "
    "to special characters like / + - . : $ % * and space."
)


def normalize(arr):
    binary = arr < 128
    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any():
        return None
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    cropped = arr[r0:r1+1, c0:c1+1]
    img = Image.fromarray(cropped, 'L')
    resized = img.resize((NORM_W, NORM_H), Image.NEAREST)
    return np.array(resized)


def ghash(arr):
    norm = normalize(arr)
    if norm is None:
        return 'blank'
    return hashlib.sha256((norm < 128).astype(np.uint8).tobytes()).hexdigest()[:16]


def to_data_uri(arr):
    img = Image.fromarray(arr.astype(np.uint8), 'L')
    scaled = img.resize((img.width * 8, img.height * 8), Image.NEAREST)
    buf = BytesIO()
    scaled.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f"data:image/png;base64,{b64}"


def identify_glyphs_vision(hash_to_arr, client, batch_size=20):
    results = {}
    items = list(hash_to_arr.items())
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start:batch_start + batch_size]
        content = []
        for h, arr in batch:
            content.append({"type": "text", "text": f"hash:{h}"})
            content.append({"type": "image_url", "image_url": {"url": to_data_uri(arr)}})

        print(f"  Batch {batch_start//batch_size + 1}: {len(batch)} patterns...")
        response = client.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        for h, ch in parsed.items():
            if not isinstance(ch, str) or len(ch) != 1:
                warnings.warn(f"Unexpected value for {h}: {ch!r}")
                ch = str(ch)[0] if ch else '?'
            if ch not in B45_SET:
                warnings.warn(f"Non-B45 char for {h}: {ch!r}")
            results[h] = ch
    return results


def main():
    client = openai.OpenAI()

    # Scan glyphs, skip row 53
    hash_to_files = {}
    hash_to_arr = {}
    for f in sorted(GLYPHS_DIR.glob('*.png')):
        col, row = map(int, f.stem.split('-'))
        if row == 53:
            continue
        arr = np.array(Image.open(f).convert('L'))
        h = ghash(arr)
        hash_to_files.setdefault(h, []).append(f)
        if h not in hash_to_arr:
            hash_to_arr[h] = arr

    print(f"{len(hash_to_arr)} unique patterns across {sum(len(v) for v in hash_to_files.values())} glyphs")

    # Auto-label blanks
    hash_to_label = {}
    needs_gpt = {}
    for h, arr in hash_to_arr.items():
        if h == 'blank':
            hash_to_label[h] = ' '
        else:
            needs_gpt[h] = arr

    print(f"  {len(hash_to_label)} blank (auto-space), {len(needs_gpt)} to send to GPT vision")

    gpt_labels = identify_glyphs_vision(needs_gpt, client)
    hash_to_label.update(gpt_labels)

    missing = [h for h in needs_gpt if h not in hash_to_label]
    if missing:
        print(f"WARNING: no label for {len(missing)} hashes: {missing}")
        for h in missing:
            hash_to_label[h] = '?'

    # Rebuild output folders
    import shutil
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    cluster_counts = {}
    for h, files in hash_to_files.items():
        ch = hash_to_label.get(h, '?')
        folder_name = folder_for(ch)
        out_dir = OUTPUT_DIR / folder_name
        out_dir.mkdir(exist_ok=True)
        for src in files:
            dst = out_dir / src.name
            dst.symlink_to(src.resolve())
        cluster_counts[ch] = cluster_counts.get(ch, 0) + len(files)

    print("\nCluster summary:")
    for ch in sorted(cluster_counts, key=lambda c: -cluster_counts[c]):
        folder = '_space_' if ch == ' ' else ch
        print(f"  {ch!r:4} ({folder_for(ch):10}) : {cluster_counts[ch]:5d} glyphs")
    print(f"\nTotal clusters: {len(cluster_counts)}")


if __name__ == '__main__':
    main()
