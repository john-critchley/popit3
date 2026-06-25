#!/usr/bin/env python3
"""
rs_decode.py — Decode Reed-Solomon Base45 from stdin (OCR output).
Usage: echo "OCR_BASE45_STRING" | python rs_decode.py [nsym] | bzip2 -d
       python rs_decode.py [nsym] < ocr_output.txt | bzip2 -d
  nsym must match what was used in rs_encode.py (default 32).
"""
import sys, struct, os

# ── Base45 (RFC 9285) ────────────────────────────────────────────────────

B45_ALPHA = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
B45_MAP   = {c: i for i, c in enumerate(B45_ALPHA)}

def b45_decode(text: str) -> bytes:
    # Strip anything not in the alphabet (whitespace, OCR noise)
    clean = [c for c in text.upper() if c in B45_MAP]
    out = bytearray()
    i = 0
    while i < len(clean):
        if i + 2 < len(clean):         # 3 chars → 2 bytes
            a = B45_MAP[clean[i]]
            b = B45_MAP[clean[i + 1]]
            c = B45_MAP[clean[i + 2]]
            n = a + b * 45 + c * 45 * 45
            if n > 0xFFFF:
                raise ValueError(f'Base45 value out of range at pos {i}: {n}')
            out.append(n >> 8)
            out.append(n & 0xFF)
            i += 3
        elif i + 1 < len(clean):       # 2 chars → 1 byte (trailing odd)
            a = B45_MAP[clean[i]]
            b = B45_MAP[clean[i + 1]]
            n = a + b * 45
            if n > 0xFF:
                raise ValueError(f'Base45 trailing value out of range at pos {i}: {n}')
            out.append(n)
            i += 2
        else:
            raise ValueError(f'Base45 input has odd single trailing character at pos {i}')
    return bytes(out)

# ── GF(2^8) ────────────────────────────────────────────────────────────

_EXP = [0] * 512
_LOG = [0] * 256

def _init_gf():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11d
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]

_init_gf()

def gmul(a, b):
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]

def gdiv(a, b):
    if b == 0: raise ZeroDivisionError
    return 0 if a == 0 else _EXP[(_LOG[a] - _LOG[b]) % 255]

def gpow(x, n):
    return _EXP[(_LOG[x] * n) % 255] if x else 0

def ginv(x):
    return _EXP[255 - _LOG[x]]

def padd(p, q):
    r = bytearray(max(len(p), len(q)))
    for i, v in enumerate(p): r[i + len(r) - len(p)] ^= v
    for i, v in enumerate(q): r[i + len(r) - len(q)] ^= v
    return r

def pscale(p, x):
    return bytearray(gmul(c, x) for c in p)

def pmul(p, q):
    r = bytearray(len(p) + len(q) - 1)
    for i, a in enumerate(p):
        if a:
            for j, b in enumerate(q):
                r[i + j] ^= gmul(a, b)
    return r

def peval(p, x):
    y = p[0]
    for c in p[1:]:
        y = gmul(y, x) ^ c
    return y

def syndromes(msg, nsym):
    return [peval(msg, gpow(2, i)) for i in range(nsym)]

def berlekamp_massey(synd, nsym):
    """
    Berlekamp-Massey in LOW-DEGREE-FIRST internally.
    Returns sigma in HIGH-DEGREE-FIRST: [sigma_t, ..., sigma_1, 1].
    """
    def ldf_add(a, b):
        r = bytearray(max(len(a), len(b)))
        for i, v in enumerate(a): r[i] ^= v
        for i, v in enumerate(b): r[i] ^= v
        return r
    def ldf_shift(p, m): return bytearray(m) + bytearray(p)
    def ldf_scale(p, x): return bytearray(gmul(c, x) for c in p)

    C = bytearray([1])
    B = bytearray([1])
    L = 0
    m = 1
    b = 1

    for n in range(nsym):
        d = synd[n]
        for j in range(1, L + 1):
            if j < len(C):
                d ^= gmul(C[j], synd[n - j])
        if d == 0:
            m += 1
        elif 2 * L <= n:
            T = bytearray(C)
            C = ldf_add(C, ldf_shift(ldf_scale(B, gdiv(d, b)), m))
            L, B, b, m = n + 1 - L, T, d, 1
        else:
            C = ldf_add(C, ldf_shift(ldf_scale(B, gdiv(d, b)), m))
            m += 1

    return bytearray(reversed(C))

def chien_search(sigma, n):
    t = len(sigma) - 1
    pos = []
    for i in range(255):
        if peval(sigma, gpow(2, i)) == 0:
            p = (i + n - 1) % 255
            if p < n:
                pos.append(p)
    return pos if len(pos) == t else None

def forney(sigma, synd_list, pos, n):
    nsym = len(synd_list)
    t = len(sigma) - 1
    S_hdgf = bytearray(reversed(synd_list))
    product = pmul(S_hdgf, sigma)
    omega = bytearray(product[-nsym:]) if len(product) >= nsym else bytearray(product)

    mags = []
    for p in pos:
        i = n - 1 - p
        X     = gpow(2, i)
        X_inv = ginv(X)
        omega_val = peval(omega, X_inv)
        sigma_prime_val = 0
        for k in range(1, t + 1, 2):
            coef = sigma[t - k]
            sigma_prime_val ^= gmul(coef, gpow(X_inv, k - 1))
        if sigma_prime_val == 0:
            raise ValueError(f'Forney: singular at position {p}')
        mags.append(gdiv(gmul(X, omega_val), sigma_prime_val))
    return mags

def rs_correct_block(block, nsym):
    msg  = bytearray(block)
    n    = len(msg)
    synd = syndromes(msg, nsym)
    if all(s == 0 for s in synd):
        return bytes(msg[:-nsym])
    sigma = berlekamp_massey(synd, nsym)
    t = len(sigma) - 1
    if t > nsym // 2:
        raise ValueError(f'Too many errors: detected {t}, capacity {nsym//2}')
    pos = chien_search(sigma, n)
    if pos is None:
        raise ValueError('Chien search failed — uncorrectable (too many errors?)')
    mags = forney(sigma, synd, pos, n)
    for p, mag in zip(pos, mags):
        msg[p] ^= mag
    if any(s != 0 for s in syndromes(msg, nsym)):
        raise ValueError('Correction failed — syndromes non-zero after fix')
    return bytes(msg[:-nsym])

MAGIC = b'\xd3\x52\x53\xec'
DEFAULT_NSYM = 32

def decode(raw_bytes, nsym=DEFAULT_NSYM):
    block_size = 255
    if len(raw_bytes) % block_size != 0:
        pad = block_size - (len(raw_bytes) % block_size)
        raw_bytes = raw_bytes + bytes(pad)
    corrected = bytearray()
    for i in range(len(raw_bytes) // block_size):
        block = raw_bytes[i * block_size : (i + 1) * block_size]
        try:
            corrected += rs_correct_block(block, nsym)
        except ValueError as e:
            sys.stderr.write(f'Block {i}: UNCORRECTABLE — {e}\n')
            corrected += block[:-nsym]
    return bytes(corrected)

def main():
    nsym = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_NSYM
    if not (2 <= nsym <= 120 and nsym % 2 == 0):
        sys.exit('nsym must be even, 2-120')
    text = sys.stdin.read()
    sys.stderr.write(f'Read {len(text)} chars from stdin\n')
    try:
        raw = b45_decode(text)
    except Exception as e:
        sys.exit(f'Base45 decode failed: {e}')
    sys.stderr.write(f'Base45-decoded to {len(raw)} bytes, RS-decoding with nsym={nsym}...\n')
    payload = decode(raw, nsym)
    if len(payload) < 9:
        sys.exit('Decoded payload too short')
    magic = payload[:4]
    if magic != MAGIC:
        sys.stderr.write(f'WARNING: magic mismatch {magic.hex()} != {MAGIC.hex()}\n')
    stored_nsym = payload[4]
    data_len = struct.unpack('>I', payload[5:9])[0]
    if stored_nsym != nsym:
        sys.stderr.write(f'WARNING: encoded with nsym={stored_nsym}, decoding with nsym={nsym}\n')
    data = payload[9 : 9 + data_len]
    if len(data) < data_len:
        sys.stderr.write(f'WARNING: expected {data_len} bytes, got {len(data)}\n')
    sys.stderr.write(f'Recovered {len(data)} bytes (expected {data_len})\n')
    os.write(1, data)    # write binary to stdout without .buffer

if __name__ == '__main__':
    main()
