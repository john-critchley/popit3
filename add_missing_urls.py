#!/usr/bin/env python3
"""
Add Missing Job URLs Script

This script processes existing job records in the database and adds job URLs
for any records that are missing them by extracting URLs from HTML files.

Usage:
    python3 add_missing_urls.py [--force]
    
Options:
    --force    Update URLs even if they already exist
"""

import argparse
import sys
import os

# Add current directory to path for local imports
sys.path.append('.')
from jobserve_parser import reprocess_job_urls

def main():
    parser = argparse.ArgumentParser(description='Add missing job URLs to existing records')
    parser.add_argument('--force', action='store_true', 
                        help='Update URLs even if they already exist')
    
    args = parser.parse_args()
    
    print("Adding missing job URLs to existing records...")
    reprocess_job_urls(force_update=args.force)
    print("Done!")

if __name__ == '__main__':
    main()