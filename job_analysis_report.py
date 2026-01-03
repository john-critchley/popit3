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
    tr.scored_job_row { display: none; }
    tr.scored_job_row td { background: #f8f8f8; font-family: monospace; }
    tr.job_row { cursor: pointer; }
    tr.job_row:hover { opacity: 0.8; }
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

        html_table += f'<tr class="job_row" data-row="{idx}" style="background-color: {bg_color};">'
        for col_idx, (k, t) in enumerate(rec_to_row):
            value = t(rec) if callable(t) else t
            if k == 'Score':
                html_table += f'<td class="job_score_col" style="cursor:pointer;">{value}</td>'
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
        # Always wrap in a div for word wrapping
        analysis_html = f'<div style="white-space: pre-wrap; word-break: break-word;">{analysis_html}</div>'

        html_table += f'<tr class="scored_job_row" id="scored_job_{idx}">'
        html_table += f'<td colspan="{len(rec_to_row)}">{analysis_html}</td></tr>\n'
    
    html_table += '</tbody></table>'
    
    html_table += '''
<script>
// Only expand/collapse when clicking the Score column
document.querySelectorAll('tr.job_row').forEach(function(row) {
    var idx = row.getAttribute('data-row');
    var scoreCell = row.querySelector('td.job_score_col');
    if (scoreCell) {
        scoreCell.addEventListener('click', function(event) {
            var scoredRow = document.getElementById('scored_job_' + idx);
            if (scoredRow.style.display === 'table-row') {
                scoredRow.style.display = 'none';
            } else {
                document.querySelectorAll('tr.scored_job_row').forEach(function(r) { 
                    r.style.display = 'none'; 
                });
                scoredRow.style.display = 'table-row';
            }
            event.stopPropagation();
        });
    }
});
</script>
'''
    return html_table


def create_full_html_document(table_html):
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
        list: List of email UIDs to be deleted (empty in current implementation)
    """
    gd = load_recent_jobs(db_path, days=days)
    keys = sort_jobs(gd)
    
    table_html = generate_html_table(gd, keys, min_score=min_score)
    full_html = create_full_html_document(table_html)
    
    if deploy:
        try:
            deploy_html_to_webdav(full_html, host)
        except ValueError as e:
            print(f"Warning: Could not deploy - {e}")
            return []
    
    return []


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
