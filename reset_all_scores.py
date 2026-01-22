#!/usr/bin/env python3
"""
Reset all job scores in the gdbm database to force re-analysis with updated CV.
"""
import dbm
import json
import sys

def reset_scores(dry_run=False):
    try:
        db = dbm.open('/home/john/.jobserve.gdbm', 'c')
    except Exception as e:
        print(f"Error opening database: {e}")
        sys.exit(1)
    
    count = 0
    reset_count = 0
    
    for key in list(db.keys()):
        count += 1
        try:
            record = json.loads(db[key])
            if 'scored_job' in record:
                del record['scored_job']
                if not dry_run:
                    db[key] = json.dumps(record)
                reset_count += 1
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Error processing key {key}: {e}")
    
    db.close()
    
    if dry_run:
        print(f"[DRY RUN] Would reset {reset_count} scores from {count} total records")
    else:
        print(f"Reset {reset_count} scores from {count} total records")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    reset_scores(dry_run)
