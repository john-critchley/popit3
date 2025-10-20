#!/usr/bin/env python3
"""
Job Analysis HTML Report Generator

Creates an HTML table report of job analysis results and deploys it to the web server.
Similar to the FindPhD notebook but for JobServe job analysis.

Usage:
    python3 job_analysis_html_report.py [--score-limit N] [--staging-dir DIR]
"""

import argparse
import sys
import os
import datetime
import io
import requests
import netrc
import re
from pathlib import Path

# Add current directory to path for local imports
sys.path.append('.')
import query_jobs
import webdav4.client

# Seaborn-style color palette
SEABORN_COLORS = {
    'excellent': '#2E8B57',    # Sea green
    'good': '#4682B4',         # Steel blue  
    'average': '#DAA520',      # Goldenrod
    'poor': '#CD5C5C',         # Indian red
    'bg_excellent': '#E6F3E6', # Light green
    'bg_good': '#E6F0FF',      # Light blue
    'bg_average': '#FFF8DC',   # Light yellow
    'bg_poor': '#FFE4E1'       # Light pink
}


def extract_job_url_from_html(html_content):
    """Extract the actual job URL from JobServe email HTML content"""
    if not html_content:
        return None
        
    # Look for the Apply button link with originalsrc attribute
    # Pattern: originalsrc="https://www.jobserve.com/jslinka.aspx?..."
    pattern = r'originalsrc=["\']https://www\.jobserve\.com/jslinka\.aspx\?[^"\']*["\']'
    match = re.search(pattern, html_content)
    
    if match:
        # Extract the URL from the originalsrc attribute
        url_match = re.search(r'originalsrc=["\']([^"\']*)["\']', match.group())
        if url_match:
            return url_match.group(1)
    
    # Fallback: look for any jobserve.com/jslinka.aspx link
    pattern2 = r'https://www\.jobserve\.com/jslinka\.aspx\?[^"\s]*'
    match2 = re.search(pattern2, html_content)
    if match2:
        return match2.group()
    
    return None


def read_netrc():
    """Read WebDAV credentials from ~/.netrc file"""
    try:
        netrc_file = netrc.netrc()
        credentials = netrc_file.authenticators('webdav.critchley.biz')
        if credentials:
            return credentials[0], credentials[2]  # username, password
        else:
            print("Error: No credentials found for webdav.critchley.biz in ~/.netrc")
            return None, None
    except Exception as e:
        print(f"Error reading ~/.netrc: {e}")
        return None, None


def get_age_color(email_date):
    """Get text color based on email age"""
    if not email_date:
        return '#999999'  # Gray for unknown dates
    
    if isinstance(email_date, str):
        try:
            email_date = datetime.datetime.strptime(email_date, '%Y%m%d')
        except ValueError:
            return '#999999'
    
    age_days = (datetime.datetime.now() - email_date).days
    
    if age_days <= 1:
        return '#2c3e50'    # Dark blue-gray (very fresh)
    elif age_days <= 3:
        return '#34495e'    # Medium blue-gray (fresh)
    elif age_days <= 7:
        return '#7f8c8d'    # Gray (week old)
    else:
        return '#bdc3c7'    # Light gray (older)


def get_original_html_content(message_id):
    """Get original HTML content from the html directory for a given message ID"""
    import os
    import glob
    
    try:
        # Look for HTML files containing this message ID
        html_dir = os.path.join(os.path.dirname(__file__), 'html')
        pattern = f"*{message_id}*.html"
        matching_files = glob.glob(os.path.join(html_dir, pattern))
        
        if matching_files:
            # Use the first matching file
            with open(matching_files[0], 'r', encoding='utf-8') as f:
                content = f.read()
                # Limit size for display (first 10KB)
                if len(content) > 10000:
                    content = content[:10000] + '\n\n... (truncated for display)'
                return content
    except Exception as e:
        return f"Error reading HTML file: {e}"
    
    return None


def get_score_colors(score):
    """Get background and text colors based on score"""
    if score is None:
        return SEABORN_COLORS['bg_poor'], SEABORN_COLORS['poor']
    elif score >= 8:
        return SEABORN_COLORS['bg_excellent'], SEABORN_COLORS['excellent']
    elif score >= 7:
        return SEABORN_COLORS['bg_good'], SEABORN_COLORS['good']
    elif score >= 6:
        return SEABORN_COLORS['bg_average'], SEABORN_COLORS['average']
    else:
        return SEABORN_COLORS['bg_poor'], SEABORN_COLORS['poor']


def generate_job_analysis_html(job_data, title="Job Analysis Report", score_limit=6, staging_dir="JobAnalysis", days_limit=7):
    """Generate full HTML document for job analysis results"""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #2c3e50;
            text-align: center;
        }}
        h2 {{
            color: #34495e;
            text-align: center;
        }}
        .reload-link {{
            text-align: center;
            border: 3px solid #202020;
            background-color: #e0e0e0;
            margin: 16px;
            padding: 10px;
            text-decoration: none;
            color: black;
            display: block;
        }}
        .reload-link:hover {{
            background-color: #d0d0d0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        th {{
            background-color: #2c3e50;
            color: white;
            padding: 12px 8px;
            text-align: left;
            font-weight: bold;
        }}
        td {{
            padding: 8px;
            border-bottom: 1px solid #ddd;
        }}
        tr:hover {{
            background-color: #f8f9fa;
        }}
        .score-cell {{
            text-align: center;
            font-weight: bold;
            font-size: 18px;
        }}
        .job-title {{
            font-weight: bold;
            max-width: 300px;
        }}
        .company {{
            color: #7f8c8d;
            font-style: italic;
        }}
        .analysis {{
            max-width: 400px;
            font-size: 0.9em;
            line-height: 1.4;
        }}
        .date {{
            font-size: 0.9em;
            color: #666;
        }}
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .summary {{
            text-align: center;
            margin: 20px 0;
            padding: 15px;
            background-color: #ecf0f1;
            border-radius: 5px;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <h2>Updated: {datetime.datetime.now().strftime("%Y %B %d %H:%M:%S")}</h2>
    
    <a href="https://www.critchley.biz/{staging_dir}" class="reload-link">
        Load Latest Analysis
    </a>
    
    <div class="summary">
        <strong>Last {days_limit} days:</strong> {len([j for j in job_data if j['score'] is not None])} jobs analyzed | 
        <strong>Showing scores ≥ {score_limit}/10</strong> | 
        <strong>High-quality matches (8-10/10):</strong> {len([j for j in job_data if j['score'] and j['score'] >= 8])}
    </div>
    
    <table>
        <tr>
            <th>Score</th>
            <th>Job Title</th>
            <th>Company</th>
            <th>Location</th>
            <th>Salary</th>
            <th>Analysis Summary</th>
            <th>Email Date</th>
            <th>Link</th>
        </tr>
"""

    # Filter and add data rows
    now = datetime.datetime.now()
    for job in job_data:
        score = job.get('score')
        if score is None or score < score_limit:
            continue
            
        # Get colors based on score and age
        bg_color, score_color = get_score_colors(score)
        age_color = get_age_color(job.get('email_date'))

        html += f'<tr style="background-color: {bg_color};">\n'
        
        # Score cell
        html += f'<td class="score-cell" style="color: {score_color};">{score}/10</td>\n'
        
        # Job title
        job_title = job.get('job_title', 'Unknown Job')
        html += f'<td class="job-title" style="color: {age_color};">{job_title}</td>\n'
        
        # Company
        company = job.get('company', 'Not specified')
        html += f'<td class="company" style="color: {age_color};">{company}</td>\n'
        
        # Location
        location = job.get('location', 'Not specified')
        html += f'<td style="color: {age_color};">{location}</td>\n'
        
        # Salary
        salary = job.get('salary', 'Not specified')
        html += f'<td style="color: {age_color};">{salary}</td>\n'
        
        # Analysis summary (first 200 chars)
        analysis = job.get('analysis', 'No analysis available')
        if len(analysis) > 200:
            analysis = analysis[:200] + '...'
        html += f'<td class="analysis" style="color: {age_color};">{analysis}</td>\n'
        
        # Email date
        email_date = job.get('email_date', 'Unknown')
        if isinstance(email_date, datetime.datetime):
            email_date_str = email_date.strftime('%Y-%m-%d')
        else:
            email_date_str = str(email_date)
        html += f'<td class="date" style="color: {age_color};">{email_date_str}</td>\n'
        
        # Link to actual job posting
        job_url = job.get('job_url', '')
        if job_url and not job_url.startswith('#'):
            html += f'<td><a href="{job_url}" target="_blank" style="color: {score_color};">View Job</a></td>\n'
        else:
            message_id = job.get('message_id', '')
            html += f'<td><span style="color: #999;" title="{message_id}">No Link</span></td>\n'
        
        html += '</tr>\n'

    html += """
    </table>
    
    <div style="margin-top: 30px; text-align: center; color: #7f8c8d; font-size: 0.9em;">
        Generated by Job Analysis System | 
        Scores: 10=Perfect, 9=Excellent, 8=Strong, 7=Good, 6=Average, 5-1=Poor
    </div>
</body>
</html>
"""

    return html


def get_job_analysis_data(days_limit=7):
    """Extract job analysis data from the database, filtered to recent jobs"""
    all_jobs = query_jobs.get_all_jobs()
    job_data = []
    
    # Calculate cutoff date
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_limit)
    
    for message_id, email_data in all_jobs:
        if 'llm_results' not in email_data or not email_data['llm_results']:
            continue
            
        llm_data = email_data['llm_results']
        parsed = email_data.get('parsed', {})
        
        # Parse email date
        email_date = None
        date_str = email_data.get('headers', {}).get('Date', '')
        if date_str:
            try:
                email_date = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00').replace('+01:00', ''))
                email_date = email_date.replace(tzinfo=None)
            except:
                pass
        
        # Skip jobs older than the cutoff
        if email_date and email_date < cutoff_date:
            continue
        
        # Get job URL from email data (stored during processing)
        job_url = email_data.get('job_url')
        
        # Fallback to parsed data if not in main data
        if not job_url:
            job_url = parsed.get('job_url') or parsed.get('url')
        
        job_record = {
            'message_id': message_id,
            'score': llm_data.get('llm_score'),
            'job_title': parsed.get('job_title', 'Unknown Job'),
            'company': parsed.get('employment_business', 'Not specified'),
            'location': parsed.get('location', 'Not specified'),  
            'salary': parsed.get('salary', 'Not specified'),
            'analysis': llm_data.get('llm_explanation', 'No analysis available'),
            'email_date': email_date,
            'job_url': job_url,
            'model_used': llm_data.get('model_used', 'Unknown'),
            'processing_date': llm_data.get('processing_completed', 'Unknown')
        }
        
        job_data.append(job_record)
    
    # Sort by score (highest first), then by email date (newest first)
    job_data.sort(key=lambda x: (
        -(x['score'] or 0),
        -(x['email_date'].timestamp() if x['email_date'] else 0)
    ))
    
    return job_data


def deploy_to_webserver(html_content, staging_dir='JobAnalysis', webdav_machine='webdav.critchley.biz'):
    """Deploy HTML content to webserver using WebDAV"""
    try:
        # Read WebDAV credentials from ~/.netrc
        login, password = read_netrc()
        if not login or not password:
            print("Failed to read WebDAV credentials")
            return False
        print(f"Using WebDAV credentials for {webdav_machine} (user: {login})")
            
        # Create WebDAV client with timeout settings
        client = webdav4.client.Client(
            base_url=f'https://{webdav_machine}/staging',
            auth=(login, password),
            timeout=30.0  # 30 second timeout
        )
        
        # Generate filename with timestamp 
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'{staging_dir}-{timestamp}.html'
        staging_path = f'{staging_dir}/{filename}'
        
        # Convert HTML to bytes and upload
        html_bytes = html_content.encode('utf-8')
        html_bytesio = io.BytesIO(html_bytes)
        html_bytesio.seek(0)
        
        # Create the staging directory if it doesn't exist
        try:
            print(f"Creating staging directory: {staging_dir}...")
            client.mkdir(staging_dir)
            print(f"Created staging directory: {staging_dir}")
        except Exception as e:
            # Directory might already exist, that's okay
            print(f"Directory creation: {e} (likely already exists)")
            pass
        
        print(f"Uploading to staging/{staging_path}...")
        try:
            client.upload_fileobj(html_bytesio, staging_path, overwrite=True)
            print(f"Upload completed successfully")
        except Exception as e:
            print(f"Upload failed: {e}")
            raise
        
        # Deploy to production using the deployment API (2-step process)
        # Step 1: Create the directory
        dir_deploy_url = f'http://www.critchley.biz/deploy/{staging_dir}/'
        print(f"Creating directory via: {dir_deploy_url}")
        
        dir_response = requests.get(dir_deploy_url)
        if not dir_response.ok:
            print(f"Directory creation failed: {dir_response.status_code}")
            print(dir_response.text)
            return False
            
        # Step 2: Deploy the file
        deploy_url = f'http://www.critchley.biz/deploy/{staging_path}'
        print(f"Deploying file via: {deploy_url}")
        
        response = requests.get(deploy_url)
        if response.ok:
            production_url = f'https://www.critchley.biz/{staging_path}'
            print(f"Successfully deployed!")
            print(f"View at: {production_url}")
            return production_url
        else:
            print(f"File deployment failed: {response.status_code}")
            print(response.text)
            return False
        
    except Exception as e:
        print(f"Error deploying to webserver: {e}")
        return False


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description="Generate and deploy job analysis HTML report")
    parser.add_argument('--score-limit', '-s', type=int, default=6,
                        help='Minimum score to include in report (default: 6)')
    parser.add_argument('--staging-dir', '-d', type=str, default='JobAnalysis',
                        help='Staging directory name (default: JobAnalysis)')
    parser.add_argument('--local-only', '-l', action='store_true',
                        help='Generate HTML file locally only, do not deploy')
    parser.add_argument('--webdav-machine', '-w', type=str, default='webdav.critchley.biz',
                        help='WebDAV machine name from ~/.netrc (default: webdav.critchley.biz)')
    
    args = parser.parse_args()
    
    print("Extracting job analysis data...")
    job_data = get_job_analysis_data()
    
    if not job_data:
        print("No job analysis data found!")
        return 1
    
    print(f"Found {len(job_data)} analyzed jobs")
    
    # Generate HTML report
    print("Generating HTML report...")
    html_content = generate_job_analysis_html(
        job_data, 
        title="JobServe Analysis Report",
        score_limit=args.score_limit,
        staging_dir=args.staging_dir
    )
    
    # Save locally
    local_filename = f"job_analysis_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    with open(local_filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Local file saved: {local_filename}")
    
    # Deploy to webserver unless local-only mode
    if not args.local_only:
        print("\nDeploying to webserver...")
        result = deploy_to_webserver(html_content, args.staging_dir, args.webdav_machine)
        if result:
            print(f"Report successfully deployed and available at: {result}")
        else:
            print("Deployment failed, but local file is available")
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())