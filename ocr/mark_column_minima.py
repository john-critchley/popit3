#!/usr/bin/env python3
"""Mark likely character boundary columns by fitting stride+offset to minima.

The script:
1) Builds a vertical darkness profile (sum down each column)
2) Smooths the profile
3) Searches (stride, offset) pairs globally
4) For each predicted boundary, snaps to nearest local minimum in a window
5) Draws red vertical lines at snapped minima and saves overlay

Usage:
  python3 ocr/mark_column_minima.py \
    --image tmp/rs_note_encoded_line_inv_wide_1x_tight.png \
    --out   tmp/rs_note_encoded_line_inv_wide_1x_marked_red_fit.png
"""

import argparse
import math
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw


def local_minima_indices(y: np.ndarray) -> np.ndarray:
    """Return indices i where y[i] is a strict/flat local minimum."""
    if y.size < 3:
        return np.array([], dtype=int)
    left = y[:-2]
    mid = y[1:-1]
    right = y[2:]
    mask = (mid <= left) & (mid <= right) & ((mid < left) | (mid < right))
    return np.where(mask)[0] + 1


def smooth_signal(x: np.ndarray, kernel: int) -> np.ndarray:
    k = max(1, int(kernel))
    if k == 1:
        return x.copy()
    filt = np.ones(k, dtype=np.float32) / float(k)
    return np.convolve(x, filt, mode="same")


def get_text_bounds(sig: np.ndarray, frac: float) -> Tuple[int, int]:
    th = max(1.0, float(sig.max()) * frac)
    active = np.where(sig > th)[0]
    if active.size == 0:
        return 0, sig.size - 1
    return int(active[0]), int(active[-1])


def fit_stride_offset(sig: np.ndarray, x0: int, x1: int, stride_min: int, stride_max: int) -> Tuple[int, int, List[int], float]:
    """Fit stride and offset, allowing non-zero offset independent from stride.

    For each predicted boundary x = offset + k*stride, we snap to nearest local
    minimum within +/- window and score by profile value + shift penalty.
    """
    best = None
    best_score = float("inf")

    for stride in range(stride_min, stride_max + 1):
        window = max(2, int(round(stride * 0.5)))
        for offset in range(stride):
            # Keep boundaries inside text extents.
            ks = np.arange(math.floor((x0 - offset) / stride), math.ceil((x1 - offset) / stride) + 1)
            preds = offset + ks * stride
            preds = preds[(preds >= x0) & (preds <= x1)]
            if preds.size < 20:
                continue

            snapped: List[int] = []
            score = 0.0
            ok = True
            for p in preds:
                lo = p - window
                hi = p + window
                lo = max(0, lo)
                hi = min(sig.size - 1, hi)
                if lo > hi:
                    ok = False
                    break

                # Pick the lowest-profile column in the window,
                # then tie-break toward the predicted boundary.
                win_idx = np.arange(lo, hi + 1)
                vals = sig[win_idx]
                best_local = np.min(vals)
                c2 = win_idx[vals == best_local]
                q = int(c2[np.argmin(np.abs(c2 - p))])
                snapped.append(q)

                shift = abs(q - p) / float(window)
                score += float(sig[q]) + 0.8 * shift

            if not ok:
                continue

            # Penalize collapsed/duplicate boundaries heavily.
            uniq = len(set(snapped))
            if uniq != len(snapped):
                score += 1000.0 * (len(snapped) - uniq)

            score /= float(len(snapped))
            if score < best_score:
                best_score = score
                best = (stride, offset, snapped, score)

    if best is None:
        raise RuntimeError("Failed to fit stride/offset against minima")
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--smooth", type=int, default=5, help="Smoothing kernel size")
    ap.add_argument("--active-frac", type=float, default=0.06, help="Text extent threshold as profile fraction")
    ap.add_argument("--stride-min", type=int, default=8)
    ap.add_argument("--stride-max", type=int, default=18)
    args = ap.parse_args()

    gray = Image.open(args.image).convert("L")
    arr = np.array(gray, dtype=np.float32)

    # Darkness profile: lower means likely inter-character white gaps.
    dark = 255.0 - arr
    col_profile = dark.sum(axis=0)
    sig = smooth_signal(col_profile, args.smooth)

    x0, x1 = get_text_bounds(sig, args.active_frac)
    stride, offset, cuts, score = fit_stride_offset(sig, x0, x1, args.stride_min, args.stride_max)

    rgb = Image.open(args.image).convert("RGB")
    dr = ImageDraw.Draw(rgb)

    for x in cuts:
        dr.line([(x, 0), (x, rgb.height - 1)], fill=(255, 0, 0), width=1)

    # Green text extent markers for context.
    dr.line([(x0, 0), (x0, rgb.height - 1)], fill=(0, 200, 0), width=1)
    dr.line([(x1, 0), (x1, rgb.height - 1)], fill=(0, 200, 0), width=1)

    rgb.save(args.out)

    print("saved", args.out)
    print("text_bounds", (x0, x1))
    print("best_stride", stride, "best_offset", offset, "n_cuts", len(cuts), "score", round(score, 3))


if __name__ == "__main__":
    main()
