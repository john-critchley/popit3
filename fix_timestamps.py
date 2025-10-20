#!/usr/bin/env python3
"""
Utility to fix file timestamps for existing JobServe files.
This updates HTML and JSON file timestamps to match the email sent dates.
"""

import query_jobs
import os
import datetime
import glob

def fix_file_timestamps():
    """Fix timestamps on existing HTML and JSON files to match email dates."""
    
    jobs = query_jobs.get_all_jobs()
    fixed_count = 0
    error_count = 0
    
    print(f"Processing {len(jobs)} jobs to fix file timestamps...")
    
    for message_id, job_data in jobs:
        try:
            headers = job_data.get('headers', {})
            date_str = headers.get('Date')
            parsed = job_data.get('parsed', {})
            
            if not date_str:
                print(f"WARNING: No date found for {message_id}")
                continue
            
            # Parse the email date
            if isinstance(date_str, str):
                email_date = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                email_date = date_str
            
            # Convert to timestamp
            timestamp = email_date.timestamp()
            
            # Extract job details for filename matching
            job_title = parsed.get('job_title', 'Unknown')
            subject = headers.get('Subject', '')
            
            # Find matching HTML files
            html_pattern = f'html/*{message_id}*.html'
            html_files = glob.glob(html_pattern)
            
            # Find matching JSON files  
            json_pattern = f'parsed/*{message_id}*.json'
            json_files = glob.glob(json_pattern)
            
            files_updated = []
            
            # Update HTML files
            for html_file in html_files:
                try:
                    current_stat = os.stat(html_file)
                    current_time = datetime.datetime.fromtimestamp(current_stat.st_mtime)
                    
                    # Only update if timestamp is significantly different (more than 1 minute)
                    time_diff = abs((email_date.replace(tzinfo=None) - current_time).total_seconds())
                    if time_diff > 60:
                        os.utime(html_file, (timestamp, timestamp))
                        files_updated.append(os.path.basename(html_file))
                        
                except OSError as e:
                    print(f"ERROR updating {html_file}: {e}")
                    error_count += 1
            
            # Update JSON files
            for json_file in json_files:
                try:
                    current_stat = os.stat(json_file)
                    current_time = datetime.datetime.fromtimestamp(current_stat.st_mtime)
                    
                    # Only update if timestamp is significantly different
                    time_diff = abs((email_date.replace(tzinfo=None) - current_time).total_seconds())
                    if time_diff > 60:
                        os.utime(json_file, (timestamp, timestamp))
                        files_updated.append(os.path.basename(json_file))
                        
                except OSError as e:
                    print(f"ERROR updating {json_file}: {e}")
                    error_count += 1
            
            if files_updated:
                print(f"Fixed {len(files_updated)} files for {job_title} ({email_date.strftime('%Y-%m-%d %H:%M')})")
                fixed_count += len(files_updated)
                
        except Exception as e:
            print(f"ERROR processing {message_id}: {e}")
            error_count += 1
    
    print(f"\\nCompleted: {fixed_count} files updated, {error_count} errors")

def show_timestamp_mismatches():
    """Show jobs where file timestamps don't match email dates."""
    
    jobs = query_jobs.get_all_jobs()
    mismatches = []
    
    print("Checking for timestamp mismatches...")
    
    for message_id, job_data in jobs[:10]:  # Check first 10 as sample
        try:
            headers = job_data.get('headers', {})
            date_str = headers.get('Date')
            parsed = job_data.get('parsed', {})
            job_title = parsed.get('job_title', 'Unknown')
            
            if not date_str:
                continue
            
            # Parse the email date
            if isinstance(date_str, str):
                email_date = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                email_date = date_str
            
            # Find HTML files
            html_pattern = f'html/*{message_id}*.html'
            html_files = glob.glob(html_pattern)
            
            for html_file in html_files[:1]:  # Check first match
                current_stat = os.stat(html_file)
                file_time = datetime.datetime.fromtimestamp(current_stat.st_mtime)
                
                time_diff = abs((email_date.replace(tzinfo=None) - file_time).total_seconds())
                if time_diff > 60:
                    mismatches.append({
                        'job': job_title,
                        'email_date': email_date,
                        'file_time': file_time,
                        'diff_hours': time_diff / 3600,
                        'file': os.path.basename(html_file)
                    })
                    
        except Exception as e:
            continue
    
    if mismatches:
        print(f"Found {len(mismatches)} timestamp mismatches:")
        for mismatch in mismatches:
            print(f"  {mismatch['job'][:50]:<50} | Email: {mismatch['email_date'].strftime('%Y-%m-%d %H:%M')} | File: {mismatch['file_time'].strftime('%Y-%m-%d %H:%M')} | Diff: {mismatch['diff_hours']:.1f}h")
    else:
        print("No significant timestamp mismatches found in sample")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        show_timestamp_mismatches()
    else:
        print("JobServe File Timestamp Fixer")
        print("This will update HTML and JSON file timestamps to match email dates")
        print("Run with --check to see mismatches first")
        print()
        
        response = input("Continue? (y/N): ")
        if response.lower() == 'y':
            fix_file_timestamps()
        else:
            print("Cancelled")