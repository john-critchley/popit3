#!/usr/bin/env python3
"""Generate a report of job applications from JobServe confirmation emails."""

if __name__ != "__main__": print("Module:", __name__)

import gdata
import os
import datetime
from box import Box
import argparse


def generate_applications_report(days=30):
    """Generate a report of recent job applications.
    
    Args:
        days: Number of days to look back (default 30)
    """
    app_gdbm_path = os.path.expanduser('~/.jobserve_applications.gdbm')
    
    if not os.path.exists(app_gdbm_path):
        print(f"No applications database found at {app_gdbm_path}")
        print("Run popit3.py to process application confirmation emails first.")
        return
    
    app_gd = gdata.gdata(app_gdbm_path)
    
    print(f"\n{'='*80}")
    print(f"JOB APPLICATIONS REPORT")
    print(f"{'='*80}\n")
    
    # Collect and sort applications
    applications = []
    cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    
    for msg_id, data in app_gd.items():
        rec = Box(data)
        
        if 'date' in rec:
            app_date = datetime.datetime.fromisoformat(rec.date)
            
            if app_date >= cutoff_date:
                applications.append((app_date, msg_id, rec))
    
    app_gd.close()
    
    # Sort by date (newest first)
    applications.sort(key=lambda x: x[0], reverse=True)
    
    if not applications:
        print(f"No applications found in the last {days} days.\n")
        return
    
    print(f"Found {len(applications)} application(s) in the last {days} days:\n")
    
    for app_date, msg_id, rec in applications:
        parsed = rec.get('parsed_application', {})
        
        print(f"{'─'*80}")
        print(f"Applied: {app_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"Reference: {parsed.get('reference', 'N/A')}")
        print(f"Job Title: {parsed.get('job_title', 'N/A')}")
        print(f"Location: {parsed.get('location', 'N/A')}")
        print(f"Work Type: {parsed.get('work_type', 'N/A')}")
        print(f"Posted By: {parsed.get('posted_by', 'N/A')}")
        
        if parsed.get('contact_name'):
            print(f"Contact: {parsed['contact_name']}")
        if parsed.get('contact_email'):
            print(f"  Email: {parsed['contact_email']}")
        if parsed.get('contact_phone'):
            print(f"  Phone: {parsed['contact_phone']}")
        
        # Show snippet of description
        if parsed.get('description'):
            desc = parsed['description']
            if len(desc) > 200:
                desc = desc[:200] + "..."
            print(f"Description: {desc}")
        
        print()
    
    print(f"{'='*80}\n")
    
    # Summary by week
    print("Applications by Week:")
    print(f"{'─'*40}")
    
    weekly = {}
    for app_date, _, _ in applications:
        week_start = app_date - datetime.timedelta(days=app_date.weekday())
        week_key = week_start.strftime('%Y-%m-%d')
        weekly[week_key] = weekly.get(week_key, 0) + 1
    
    for week in sorted(weekly.keys(), reverse=True):
        print(f"  Week of {week}: {weekly[week]} application(s)")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Generate report of job applications'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days to look back (default: 30)'
    )
    
    args = parser.parse_args()
    generate_applications_report(days=args.days)


if __name__ == "__main__":
    main()
