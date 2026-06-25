#!/usr/bin/env python3
"""
Extract named email fixtures from the live mail gdbm for use in tests.

Run from popit3/ directory:
    python3 tests/save_fixtures.py

Reads ~/.email3.mail.gdbm and writes .eml files to tests/fixtures/.
Safe to re-run; existing files are overwritten.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import email as emaillib
import gdata

DBFILE = os.path.expanduser('~/.email3.mail.gdbm')
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')

# uidl -> output filename, description
TARGETS = {
    '181426': ('dl_booking_bodypump.eml',     'Normal class booking (BODYPUMP)'),
    '181377': ('dl_cancellation.eml',          'Class cancellation confirmation'),
    '179040': ('dl_pt_session.eml',            'Personal Training session (FT- ref, single time)'),
    '179007': ('dl_payment_receipt.eml',       'Payment receipt — should be ignored by parser'),
    '155162': ('dl_stages_workout_summary.eml','StagesStudio workout summary — should be ignored'),
}

def _norm(v):
    i = 0
    while i < len(v) and int(v[i]) > 0x7f:
        i += 1
    return v[i:]

def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    with gdata.gdata_raw(gdbm_file=DBFILE) as db:
        for uidl_s, (filename, description) in TARGETS.items():
            key = uidl_s.encode()
            if key not in db:
                print(f'SKIP {uidl_s}: not in db')
                continue
            raw = _norm(db[key])
            msg = emaillib.message_from_bytes(raw)
            out = os.path.join(FIXTURES_DIR, filename)
            with open(out, 'wb') as f:
                f.write(raw)
            print(f'OK   {uidl_s} -> fixtures/{filename}  ({description})')

if __name__ == '__main__':
    main()
