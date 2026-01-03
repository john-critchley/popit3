#!/usr/bin/env python3
"""
Reset AI analysis for recent JobServe records.

- Loads records from the default GDBM database (~/.jobserve.gdbm).
- Finds entries with 'date' within the last ~3 days.
- Removes 'scored_job', 'score', and 'score_reason' to force re-analysis on next run.

Usage:
  python3 reset_recent_analysis.py [--db ~/.jobserve.gdbm] [--days 3]
"""
import argparse
import datetime
import os
import sys
import gdata

DEFAULT_DB = os.path.expanduser('~/.jobserve.gdbm')
DEFAULT_DAYS = 3


def parse_args():
    p = argparse.ArgumentParser(description="Reset AI analysis for recent JobServe records")
    p.add_argument('--db', default=DEFAULT_DB, help=f"Path to GDBM database (default {DEFAULT_DB})")
    p.add_argument('--days', type=int, default=DEFAULT_DAYS, help=f"Age threshold in days (default {DEFAULT_DAYS})")
    return p.parse_args()


def is_recent(rec_date_iso: str, days: int) -> bool:
    assert isinstance(rec_date_iso, str), f"rec_date_iso must be str, got {type(rec_date_iso)}"
    assert isinstance(days, int), f"days must be int, got {type(days)}"
    try:
        rec_dt = datetime.datetime.fromisoformat(rec_date_iso)
    except Exception:
        return False
    now = datetime.datetime.now(datetime.UTC)
    return (now - rec_dt) <= datetime.timedelta(days=days + 0.2)  # small cushion (~4.8 hours)


def reset_recent(db_path: str, days: int) -> int:
    assert isinstance(db_path, str), f"db_path must be str, got {type(db_path)}"
    assert isinstance(days, int), f"days must be int, got {type(days)}"
    db_path = os.path.expanduser(db_path)
    count = 0
    gd = gdata.gdata(db_path)
    try:
        for key, rec in gd.items():
            if not isinstance(rec, dict):
                continue
            d = rec.get('date')
            if not d:
                continue
            if is_recent(d, days):
                # Remove AI analysis-related fields
                changed = False
                for fld in ('scored_job', 'score', 'score_reason'):
                    if fld in rec:
                        rec.pop(fld, None)
                        changed = True
                if changed:
                    gd[key] = rec
                    count += 1
    finally:
        gd.close()
    return count


def main():
    args = parse_args()
    n = reset_recent(args.db, args.days)
    print(f"Reset analysis for {n} recent records (<= {args.days} days old).")
    return 0

if __name__ == '__main__':
    sys.exit(main())
