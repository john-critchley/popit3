#!/usr/bin/env python3
"""
Job Analysis Report Generator

This module processes job application data from a GDBM database,
generates an HTML report, and deploys it via WebDAV.
"""

import os
import io
import datetime
import numpy as np
import requests
import netrc
import re
import webdav4.client

import gdata

def rec_format_tdelta(rtd, now):
    """Format time delta between now and record date in human-readable format."""
    td = now - datetime.datetime.fromisoformat(rtd['date'])
    total_seconds = int(td.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, minutes = divmod(rem // 60, 60)
    
    if days:
        return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
    elif hours:
        return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"


def load_recent_jobs(db_path, days=7):
    """Load jobs from the last N days from GDBM database."""
    gd = gdata.gdata(os.path.expanduser(db_path))
    filtered = {
        k: v for k, v in gd.items() 
        if 'date' in v and 
        datetime.datetime.fromisoformat(v['date']) - datetime.datetime.now(datetime.UTC) 
        < datetime.timedelta(days=days)
    }
    return filtered


def sort_jobs(gd):
    """Sort job keys by score and date."""
    keys = list(gd.keys())
    # Sort by: score (ascending), then date (ascending)
    keys.sort(key=lambda k: (
        gd[k].get('score', 0),
        datetime.datetime.fromisoformat(gd[k]['date'])  # Ascending order
    ))
    return keys


def generate_html_table(gd, keys, min_score=5):
    """Generate HTML table with job listings and toggleable details."""
    now = datetime.datetime.now(datetime.UTC)
    
    rec_to_row = [
        ('Score', lambda r: str(r.get('score', ''))),
        ('Reference', lambda r: str(r['parsed_job'].get('ref', '-')) if 'parsed_job' in r else '-'),
        ('Job Title', lambda r: r['parsed_job']['job_title'] if 'parsed_job' in r and 'job_title' in r['parsed_job'] else '-'),
        ('Company', lambda r: r['parsed_job']['employment_business'] if 'parsed_job' in r and 'employment_business' in r['parsed_job'] else '-'),
        ('age', lambda r: rec_format_tdelta(r, now)),
        ('Location', lambda r: r['parsed_job']['location'] if 'parsed_job' in r and 'location' in r['parsed_job'] else '-'),
        ('Salary', lambda r: r['parsed_job']['salary'] if 'parsed_job' in r and 'salary' in r['parsed_job'] else '-'),
        ('Summary', lambda r: '-'),
        ('Email', lambda r: '-'),
        ('Date', lambda r: datetime.datetime.fromisoformat(r['date']).strftime('%D')),
        ('Link', lambda r: '<a href="' + r['parsed_job']['job_url'] + '"> Job</a>' if 'parsed_job' in r and 'job_url' in r['parsed_job'] else '-')
    ]
    
    html_table = '''
<style>
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background-color: #555; color: white; }
    tr.job_row { cursor: pointer; }
    tr.job_row:hover { opacity: 0.8; }
    
    /* Floating overlay for reason text */
    .reason-overlay {
        position: fixed;
        top: 10%;
        left: 50%;
        transform: translateX(-50%);
        width: 90%;
        max-width: 400px;
        max-height: 80vh;
        background: white;
        border: 2px solid #333;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        z-index: 1000;
        overflow-y: auto;
        padding: 16px;
        font-size: 16px;
        line-height: 1.4;
        display: none;
    }
    
    /* Show overlay when target is active */
    .reason-overlay:target {
        display: block;
    }
    
    /* Job row anchor targets */
    .job-anchor {
        position: relative;
    }
    
    /* Mobile responsive */
    @media (max-width: 600px) {
        .reason-overlay {
            width: 95%;
            max-width: none;
            left: 2.5%;
            transform: none;
            font-size: 18px;
        }
    }
    
    /* Style for the score cell as a clickable button */
    .job_score_col {
        cursor: pointer;
        position: relative;
    }
    
    .job_score_col a {
        display: block;
        width: 100%;
        height: 100%;
        text-decoration: none;
        color: inherit;
        cursor: pointer;
    }
    
    /* Close button styling */
    .close-overlay {
        position: absolute;
        top: 8px;
        right: 12px;
        font-size: 20px;
        font-weight: bold;
        color: #666;
        cursor: pointer;
        line-height: 1;
        text-decoration: none;
    }
    
    .close-overlay:hover {
        color: #000;
    }
    
    /* Mobile responsive */
    @media (max-width: 600px) {
        .reason-overlay {
            width: 95%;
            max-width: none;
            left: 2.5%;
            transform: none;
            font-size: 18px;
        }
    }
</style>
<table><thead><tr>'''
    
    for k in rec_to_row:
        if k[0] != 'Link':
            html_table += f'<th>{k[0]}</th>\n'
    for k in rec_to_row:
        if k[0] == 'Link':
            html_table += f'<th>{k[0]}</th>\n'
    
    html_table += '</tr></thead>\n<tbody>'
    
    # Score to color mapping (10=purple, 9=blue, 8=green, 7=yellow, 6=orange, 5=red)
    score_colors = {
        10: '#d1c4e9',  # Light purple (lilac)
        9:  '#b3e5fc',  # Light blue
        8:  '#c8e6c9',  # Light green
        7:  '#fff9c4',  # Light yellow
        6:  '#ffecb3',  # Light orange
        5:  '#ffcdd2',  # Light red
    }
    
    import markdown
    for idx, key in enumerate(keys):
        rec = gd[key]
        if rec.get('score', 99) < min_score:
            continue

        # Set background color based on score
        score = rec.get('score', 0)
        bg_color = score_colors.get(score, '#ffffff')  # Default to white

        html_table += f'<tr class="job_row job-anchor" id="job-{idx}" data-row="{idx}" style="background-color: {bg_color};">'
        for col_idx, (k, t) in enumerate(rec_to_row):
            value = t(rec) if callable(t) else t
            if k == 'Score':
                # Create link that scrolls to job row and shows floating overlay
                html_table += f'<td class="job_score_col"><a href="#job-{idx}">{value}</a></td>'
            elif k == 'Link':
                html_table += f'<td class="job_link_col">{value}</td>'
            else:
                html_table += f'<td>{value}</td>'
        html_table += '</tr>\n'

        # Show only the 'reason' field from structured LLM output if present
        analysis = rec.get("scored_job", "")
        from html import escape
        import json
        reason_text = None
        if analysis.strip():
            try:
                parsed = json.loads(analysis)
                if isinstance(parsed, dict) and 'reason' in parsed:
                    reason_text = str(parsed['reason'])
            except json.JSONDecodeError:
                # Not JSON; fall back to rendering full analysis text
                reason_text = None
        analysis_html = markdown.markdown(reason_text if reason_text else analysis)

        # Create floating overlay that appears when job row is targeted
        html_table += f'''
        <div class="reason-overlay" id="reason-{idx}">
            <a href="#" class="close-overlay">&times;</a>
            <div style="margin-top: 20px;">{analysis_html}</div>
        </div>
        '''
    
    html_table += '</tbody></table>'
    
    # Add JavaScript to show overlay when job row is targeted
    html_table += '''
<script>
// Show reason overlay when job row is in URL hash
function checkHash() {
    var hash = window.location.hash;
    if (hash.startsWith('#job-')) {
        // Hide all overlays
        document.querySelectorAll('.reason-overlay').forEach(function(overlay) {
            overlay.style.display = 'none';
        });
        
        // Show corresponding overlay
        var jobNum = hash.replace('#job-', '');
        var overlay = document.getElementById('reason-' + jobNum);
        if (overlay) {
            overlay.style.display = 'block';
        }
    }
}

// Check on page load and hash change
window.addEventListener('load', checkHash);
window.addEventListener('hashchange', checkHash);

// Close overlay functionality
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('close-overlay')) {
        e.preventDefault();
        document.querySelectorAll('.reason-overlay').forEach(function(overlay) {
            overlay.style.display = 'none';
        });
        // Remove hash to prevent issues
        history.replaceState(null, null, window.location.pathname);
    }
});
</script>'''
    
    return html_table


def generate_unclassified_table(gd):
    """Generate HTML table for unclassified emails (datetime order, newest last)."""
    now = datetime.datetime.now(datetime.UTC)
    
    # Filter for unclassified entries
    unclassified = {k: v for k, v in gd.items() if 'unclassified' in v}
    
    if not unclassified:
        return ''
    
    # Sort by date ascending (newest last)
    sorted_keys = sorted(
        unclassified.keys(),
        key=lambda k: datetime.datetime.fromisoformat(unclassified[k].get('date', '2000-01-01'))
    )
    
    html_table = '''
<h2>Unclassified Emails</h2>
<table border="1">
<thead><tr>
    <th>DateTime</th>
    <th>Subject</th>
</tr></thead>
<tbody>
'''
    
    for key in sorted_keys:
        rec = unclassified[key]
        date_str = datetime.datetime.fromisoformat(rec.get('date', '2000-01-01')).strftime('%Y-%m-%d %H:%M:%S')
        subject = rec.get('subject', 'No Subject')
        html_table += f'<tr><td>{date_str}</td><td>{subject}</td></tr>\n'
    
    html_table += '</tbody></table>\n'
    return html_table


def generate_applications_table(gd):
    """Generate HTML table for job applications (datetime order, newest last)."""
    now = datetime.datetime.now(datetime.UTC)
    
    # Load applications from separate applications database
    app_db_path = os.path.expanduser('~/.jobserve_applications.gdbm')
    applications = {}
    
    if os.path.exists(app_db_path):
        try:
            app_gd = gdata.gdata(app_db_path, mode='r')
            applications = dict(app_gd.items())
            app_gd.close()
        except Exception as e:
            print(f"Warning: Could not read applications database: {e}")
    
    if not applications:
        return ''
    
    # Sort by date ascending (newest last)
    sorted_keys = sorted(
        applications.keys(),
        key=lambda k: datetime.datetime.fromisoformat(applications[k].get('date', '2000-01-01'))
    )
    
    html_table = '''
<h2>Job Applications</h2>
<table border="1">
<thead><tr>
    <th>DateTime</th>
    <th>Subject</th>
</tr></thead>
<tbody>
'''
    
    for key in sorted_keys:
        rec = applications[key]
        date_str = datetime.datetime.fromisoformat(rec.get('date', '2000-01-01')).strftime('%Y-%m-%d %H:%M:%S')
        subject = rec.get('subject', 'No Subject')
        html_table += f'<tr><td>{date_str}</td><td>{subject}</td></tr>\n'
    
    html_table += '</tbody></table>\n'
    return html_table


def create_full_html_document(table_html, applications_html='', unclassified_html=''):
    """Wrap the table HTML in a complete HTML document."""
    now = datetime.datetime.now(datetime.UTC)
    date_str = now.strftime('%Y-%m-%d %H:%M:%S UTC')
    
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Analysis Report</title>
</head>
<body>
    <h1>Job Analysis Report</h1>
    <p>Generated: {date_str}</p>
    <p><a href="/JobAnalysis">Load latest analysis</a></p>
    {table_html}
    {applications_html}
    {unclassified_html}
</body>
</html>'''


def deploy_html_to_webdav(html_content, host):
    """Deploy HTML content to WebDAV server and return deploy status."""
    try:
        user, account, password = netrc.netrc().authenticators(host)
    except (FileNotFoundError, TypeError) as e:
        raise ValueError(f"No credentials found in ~/.netrc for host '{host}': {e}")
    
    client = webdav4.client.Client(f'https://{host}', auth=(user, password))

    now = datetime.datetime.now(datetime.UTC)
    date_time_representation = now.strftime('%Y%m%d_%H%M%S')

    file_loc = f'JobAnalysis/jobanalysis-{date_time_representation}.html'
    deploy_url = f'https://www.critchley.biz/deploy/{file_loc}'

    html_bytesio = io.BytesIO(html_content.encode('utf-8'))
    html_bytesio.seek(0)

    client.upload_fileobj(html_bytesio, f"staging/{file_loc}", overwrite=True)

    # --- Cleanup: keep only the last 5 jobanalysis-*.html files ---
    # List all files in the JobAnalysis directory (filenames only)
    files = client.ls('staging/JobAnalysis/', detail=False)
    job_files = [f for f in files if re.match(r"jobanalysis-\\d{8}_\\d{6}\\.html$", f)]
    # Sort by filename (date in name, descending)
    job_files_sorted = sorted(job_files, reverse=True)
    # Keep only the most recent 5
    for old_file in job_files_sorted[5:]:
        full_path = f'staging/JobAnalysis/{old_file}'
        print(f"Deleting old report: {full_path}")
        client.remove(full_path)

    resp = requests.get(deploy_url)
    print('Deployed:', resp.ok)

    return resp.ok


def process_job_analysis(db_path='~/.jobserve.gdbm', days=7, min_score=5, 
                        host='webdav.critchley.biz', deploy=True):
    """
    Main API function to process job analysis and optionally deploy.
    
    Args:
        db_path: Path to GDBM database
        days: Number of days back to include jobs
        min_score: Minimum score threshold for jobs
        host: WebDAV host (credentials read from ~/.netrc)
        deploy: Whether to deploy to WebDAV
    
    Returns:
        list: List of email UIDs to be deleted (jobs older than 14 days, applications older than 28 days)
    """
    gd = gdata.gdata(os.path.expanduser(db_path))
    now = datetime.datetime.now(datetime.UTC)
    uids_to_delete = []
    
    # Find and delete jobs older than 14 days, applications older than 28 days
    for key in list(gd.keys()):
        try:
            record = gd[key]
            if 'date' in record:
                job_date = datetime.datetime.fromisoformat(record['date'])
                age = now - job_date
                
                # Delete applications after 28 days
                if record.get('job_type') == 'application' and age > datetime.timedelta(days=28):
                    msg_id = key if isinstance(key, str) else key.decode()
                    uids_to_delete.append(msg_id)
                    print(f"Deleting old application: {msg_id} (age: {age.days} days)")
                    del gd[key]
                # Delete jobs after 14 days
                elif age > datetime.timedelta(days=14):
                    msg_id = key if isinstance(key, str) else key.decode()
                    uids_to_delete.append(msg_id)
                    print(f"Deleting old job: {msg_id} (age: {age.days} days)")
                    del gd[key]
        except Exception as e:
            print(f"Error processing key {key}: {e}")
    
    gd.close()
    
    # Reload without deleted jobs
    gd = load_recent_jobs(db_path, days=days)
    
    # Filter out unclassified and applications from the jobs list
    classified_jobs = {k: v for k, v in gd.items() 
                       if 'unclassified' not in v and v.get('job_type') != 'application'}
    keys = sort_jobs(classified_jobs)
    
    table_html = generate_html_table(classified_jobs, keys, min_score=min_score)
    applications_html = generate_applications_table(gd)
    unclassified_html = generate_unclassified_table(gd)
    full_html = create_full_html_document(table_html, applications_html, unclassified_html)
    
    # Save HTML locally for debugging (always save when not deploying)
    if not deploy:
        output_file = 'job_analysis_report_debug.html'
        with open(output_file, 'w') as f:
            f.write(full_html)
        print(f"HTML report saved to: {output_file}")
    
    if deploy:
        try:
            deploy_html_to_webdav(full_html, host)
        except ValueError as e:
            print(f"Warning: Could not deploy - {e}")
            return uids_to_delete
    
    return uids_to_delete


def main():
    """Command-line entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate and deploy job analysis report')
    parser.add_argument('--db-path', default='~/.jobserve.gdbm', 
                       help='Path to GDBM database')
    parser.add_argument('--days', type=int, default=7, 
                       help='Number of days back to include')
    parser.add_argument('--min-score', type=int, default=5, 
                       help='Minimum score threshold')
    parser.add_argument('--no-deploy', action='store_true', 
                       help='Skip WebDAV deployment')
    
    args = parser.parse_args()
    
    uids_to_delete = process_job_analysis(
        db_path=args.db_path,
        days=args.days,
        min_score=args.min_score,
        deploy=not args.no_deploy
    )
    print(f"Email UIDs to delete: {uids_to_delete}")

if __name__ == '__main__':
    main()
