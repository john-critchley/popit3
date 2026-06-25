#!/usr/bin/env python3
"""
segment.py  –  Segment a terminal screenshot into individual glyph images.

Usage:
    python3 segment.py [--image s.png] [--out glyphs] [--min-row-height 4]
                       [--col-gap-frac 0.75] [--row-gap-frac 0.05]
                       [--force-period N] [--ext png]

Steps:
  1. Find text row bands   (rows whose mean luminance > row_gap_frac * global_mean)
  2. Merge nearby bands into text lines
  3. Column segmentation: gap-based OR period-grid (--force-period)
  4. Split image into cells: one file per glyph, named X-Y.ext
"""

import argparse, json, os
import numpy as np
from PIL import Image
from collections import Counter


def find_runs(mask, min_len=1):
    runs = []
    in_run = False
    for i, v in enumerate(mask):
        if v and not in_run:
            start = i; in_run = True
        elif not v and in_run:
            if i - start >= min_len:
                runs.append((start, i - 1))
            in_run = False
    if in_run and len(mask) - start >= min_len:
        runs.append((start, len(mask) - 1))
    return runs


def grid_columns(col_signal, period):
    """Place character cell boundaries using a periodic grid aligned to signal minima.

    Returns list of (start, end) column runs, each exactly `period` columns wide,
    covering the range where text is present.
    """
    W = len(col_signal)
    # Find the phase that minimises sum of signal at boundary positions
    best_phase, best_score = 0, float('inf')
    for phase in range(period):
        positions = range(phase, W, period)
        score = sum(col_signal[p] for p in positions if p < W)
        if score < best_score:
            best_score = score
            best_phase = phase

    # Find text extent (where col_signal > some low floor)
    floor = col_signal.mean() * 0.1
    text_cols = np.where(col_signal > floor)[0]
    if len(text_cols) == 0:
        return []
    col_start = text_cols[0]
    col_end   = text_cols[-1]

    # Snap col_start to grid
    offset = (col_start - best_phase) % period
    if offset != 0:
        col_start = col_start - offset + period

    runs = []
    c = best_phase
    while c < col_start:
        c += period
    while c + period - 1 <= col_end:
        runs.append((c, c + period - 1))
        c += period

    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image',          default='s.png')
    ap.add_argument('--out',            default='glyphs')
    ap.add_argument('--ext',            default='png')
    ap.add_argument('--min-row-height', type=int,   default=4)
    ap.add_argument('--col-gap-frac',   type=float, default=0.75,
                    help='Column is a gap if signal < frac * mean-signal')
    ap.add_argument('--row-gap-frac',   type=float, default=0.05,
                    help='Row is a gap if mean-lum < frac * global-mean-lum')
    ap.add_argument('--merge-gap',      type=int,   default=3,
                    help='Merge adjacent text-row bands within this many px')
    ap.add_argument('--min-col-width',  type=int,   default=1)
    ap.add_argument('--force-period',     type=int,   default=0,
                    help='Use period-grid column segmentation with this char width (0=auto gap)')
    ap.add_argument('--force-row-period', type=int,   default=0,
                    help='Use uniform row height instead of detected text bands (0=auto)')
    ap.add_argument('--max-rows',         type=int,   default=0,
                    help='Limit to this many text rows (0=all)')
    args = ap.parse_args()

    # ---- Load image ----
    img = Image.open(args.image).convert('RGBA')
    arr = np.array(img)
    lum = arr[:, :, :3].astype(float).max(axis=2)          # (H, W)
    print(f"Image: {img.size[0]}×{img.size[1]}  lum range {lum.min():.0f}–{lum.max():.0f}  mean {lum.mean():.1f}")

    # ---- Step 1: Row segmentation ----
    row_means = lum.mean(axis=1)
    row_threshold = row_means.mean() * args.row_gap_frac
    print(f"Row gap threshold: {row_threshold:.2f}  (frac={args.row_gap_frac})")
    text_mask = row_means > row_threshold
    raw_bands = find_runs(text_mask, min_len=args.min_row_height)
    print(f"Raw text row bands (≥{args.min_row_height}px): {len(raw_bands)}")

    # ---- Step 2: Merge nearby bands ----
    if not raw_bands:
        print("No text bands found — try lowering --row-gap-frac"); return
    merged = [list(raw_bands[0])]
    for r in raw_bands[1:]:
        if r[0] - merged[-1][1] <= args.merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))
    print(f"After merging (gap≤{args.merge_gap}px): {len(merged)} text lines")
    for i, (r0, r1) in enumerate(merged[:10]):
        print(f"  Line {i:2d}: rows {r0:3d}–{r1:3d}  height={r1-r0+1}")
    if len(merged) > 10:
        print(f"  … ({len(merged)} total)")

    # Optional: replace detected bands with uniform period-grid rows
    if args.force_row_period:
        rp = args.force_row_period
        # Use first detected band's start as phase
        phase = merged[0][0]
        uniform = []
        r = phase
        while r + rp - 1 < lum.shape[0]:
            uniform.append([r, r + rp - 1])
            r += rp
        n = args.max_rows if args.max_rows else len(merged)
        merged = uniform[:n]
        print(f"Using uniform row period={rp}: {len(merged)} rows of height {rp}")
        for i, (r0, r1) in enumerate(merged[:5]):
            print(f"  Line {i:2d}: rows {r0:3d}–{r1:3d}")

    # ---- Step 3: Column segmentation ----
    W = lum.shape[1]
    col_signal = np.zeros(W)
    for r0, r1 in merged:
        line_lum = lum[r0:r1+1, :]
        line_mean = line_lum.mean(axis=0)
        lmax = line_mean.max()
        if lmax > 0:
            col_signal += line_mean / lmax
    col_signal /= len(merged)

    print(f"\nCol signal range: {col_signal.min():.3f} – {col_signal.max():.3f}  mean {col_signal.mean():.3f}")

    # ACF period estimate
    sig = col_signal - col_signal.mean()
    acf = np.real(np.fft.ifft(np.fft.fft(sig) * np.conj(np.fft.fft(sig))))
    acf /= acf[0]
    peaks = [i for i in range(3, 30) if acf[i] > acf[i-1] and acf[i] > acf[i+1]]
    acf_period = peaks[0] if peaks else 0
    print(f"ACF period estimate: {peaks[:5]} (acf values: {[f'{acf[p]:.3f}' for p in peaks[:5]]})")

    if args.force_period:
        period = args.force_period
        print(f"\nUsing period-grid segmentation with period={period}")
        char_col_runs = grid_columns(col_signal, period)
        gap_col_runs  = []
        print(f"Character column runs: {len(char_col_runs)}")
    else:
        col_threshold = col_signal.mean() * args.col_gap_frac
        print(f"Col gap threshold: {col_threshold:.4f}  (frac={args.col_gap_frac})")
        gap_mask = col_signal < col_threshold
        char_col_runs = find_runs(~gap_mask, min_len=args.min_col_width)
        gap_col_runs  = find_runs( gap_mask, min_len=1)
        print(f"Character column runs: {len(char_col_runs)}")
        print(f"Gap column runs:       {len(gap_col_runs)}")

    widths = [e - s + 1 for s, e in char_col_runs]
    print(f"Char column widths: {Counter(widths).most_common(15)}")

    # ---- Step 4: Extract and save cells ----
    os.makedirs(args.out, exist_ok=True)
    n_glyphs = 0
    for row_idx, (r0, r1) in enumerate(merged):
        for col_idx, (c0, c1) in enumerate(char_col_runs):
            cell = arr[r0:r1+1, c0:c1+1, :]      # RGBA crop
            cell_img = Image.fromarray(cell.astype(np.uint8), 'RGBA')
            fname = f"{col_idx}-{row_idx}.{args.ext}"
            cell_img.save(os.path.join(args.out, fname))
            n_glyphs += 1

    print(f"\nSaved {n_glyphs} glyph images to '{args.out}/'")
    print(f"Grid: {len(char_col_runs)} columns × {len(merged)} rows")

    # Save grid metadata
    meta = {
        'text_lines': merged,
        'char_col_runs': char_col_runs,
        'gap_col_runs': gap_col_runs,
        'n_cols': len(char_col_runs),
        'n_rows': len(merged),
    }
    with open('grid_meta.json', 'w') as f:
        json.dump(meta, f, indent=2)
    print("Saved grid_meta.json")


if __name__ == '__main__':
    main()
