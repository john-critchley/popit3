#!/usr/bin/env python3
"""
Job Analysis API - Extract job data in multiple formats

Can be run as:
1. Command-line tool: python3 job_api.py [options]
2. WSGI application: Served via Apache/gunicorn with environment variables
3. FastAPI application: Run with: uvicorn job_api:app --reload

Supports output formats: JSON (default), CSV, YAML, XML
Handles database locking with Refresh header and appropriate status codes.
"""

import os
import sys
import json
import csv
import io
import datetime
import argparse
import gdata
from gdata import GDataLockedError

# FastAPI imports (optional)
try:
    from fastapi import FastAPI, Header
    from fastapi.responses import Response, JSONResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def get_config_from_env():
    """Get configuration from environment variables (for WSGI)."""
    return {
        'db_path': os.environ.get('JOBSERVE_DBFILE', '~/.jobserve.gdbm'),
        'days': int(os.environ.get('JOBSERVE_DAYS', '7')),
        'min_score': int(os.environ.get('JOBSERVE_MIN_SCORE', '5')),
        'refresh_timeout': int(os.environ.get('JOBSERVE_REFRESH_TIMEOUT', '10')),
    }


def load_jobs(db_path, days=7):
    """Load jobs from the last N days from GDBM database (read-only)."""
    now = datetime.datetime.now(datetime.UTC)

    # Open database in read-only mode. If gdata detects a gdbm lock it
    # raises GDataLockedError; translate that into BlockingIOError so
    # callers can handle locking uniformly.
    try:
        gd = gdata.gdata(os.path.expanduser(db_path), mode='r')
    except GDataLockedError as e:
        raise BlockingIOError('Database locked') from e

    filtered = {}
    for k, v in gd.items():
        try:
            if 'date' in v:
                job_date = datetime.datetime.fromisoformat(v['date'])
                age = now - job_date
                if age < datetime.timedelta(days=days):
                    filtered[k] = v
        except (ValueError, TypeError, KeyError) as e:
            # Date parsing or unexpected record shape — skip this record but log a warning.
            print(f"Warning: skipping record {k!r} in {db_path}: {e}", file=sys.stderr)
            continue
    
    gd.close()
    return filtered


def sort_jobs(gd):
    """Sort job keys by score and date (ascending)."""
    keys = list(gd.keys())
    keys.sort(key=lambda k: (
        gd[k].get('score', 0),
        datetime.datetime.fromisoformat(gd[k].get('date', '2000-01-01'))
    ))
    return keys


def format_tdelta(record, now):
    """Format time delta between now and record date."""
    td = now - datetime.datetime.fromisoformat(record.get('date', now.isoformat()))
    total_seconds = int(td.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, minutes = divmod(rem // 60, 60)
    
    if days:
        return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
    elif hours:
        return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"


def extract_job_data(gd, keys, min_score=5):
    """Extract job records matching criteria (excluding unclassified and applications)."""
    now = datetime.datetime.now(datetime.UTC)
    jobs = []
    
    for key in keys:
        record = gd[key]
        
        # Filter out unclassified and applications
        if 'unclassified' in record or record.get('job_type') == 'application':
            continue
        
        # Only include scored jobs
        if 'scored_job' not in record:
            continue
        
        score = record.get('score', 0)
        if score < min_score:
            continue
        
        msg_id = key if isinstance(key, str) else key.decode()
        
        job_data = {
            'message_id': msg_id,
            'score': score,
            'reference': record.get('parsed_job', {}).get('ref', '-'),
            'job_title': record.get('parsed_job', {}).get('job_title', '-'),
            'company': record.get('parsed_job', {}).get('employment_business', '-'),
            'age': format_tdelta(record, now),
            'location': record.get('parsed_job', {}).get('location', '-'),
            'salary': record.get('parsed_job', {}).get('salary', '-'),
            'date': record.get('date', ''),
            'job_url': record.get('parsed_job', {}).get('job_url', '-'),
        }
        jobs.append(job_data)
    
    return jobs


def to_json(jobs):
    """Convert jobs to JSON format."""
    return json.dumps({'status': 'ok', 'count': len(jobs), 'jobs': jobs}, indent=2)


def to_csv(jobs):
    """Convert jobs to CSV format."""
    if not jobs:
        return "status,count\nok,0\n"
    
    output = io.StringIO()
    fieldnames = ['score', 'reference', 'job_title', 'company', 'age', 'location', 'salary', 'date', 'job_url']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    for job in jobs:
        row = {k: v for k, v in job.items() if k in fieldnames}
        writer.writerow(row)
    
    return output.getvalue()


def to_yaml(jobs):
    """Convert jobs to YAML format."""
    try:
        import yaml
        return yaml.dump({'status': 'ok', 'count': len(jobs), 'jobs': jobs}, default_flow_style=False)
    except ImportError:
        raise ValueError("YAML format requires PyYAML package")


def to_xml(jobs):
    """Convert jobs to XML format."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.Element('response')
        status = ET.SubElement(root, 'status')
        status.text = 'ok'
        count = ET.SubElement(root, 'count')
        count.text = str(len(jobs))
        jobs_elem = ET.SubElement(root, 'jobs')
        
        for job in jobs:
            job_elem = ET.SubElement(jobs_elem, 'job')
            for key, value in job.items():
                elem = ET.SubElement(job_elem, key)
                elem.text = str(value)
        
        return ET.tostring(root, encoding='unicode')
    except ImportError:
        raise ValueError("XML format requires xml package")


def get_content_type(accept_header):
    """Determine content type from Accept header."""
    if not accept_header:
        return 'application/json'
    
    accept_lower = accept_header.lower()

    # Use the ACCEPT_MATCHERS list (module-level) to map Accept header fragments
    # to canonical content types. Order matters: first match wins.
    for needle, ctype in ACCEPT_MATCHERS:
        if needle in accept_lower:
            return ctype

    return 'application/json'


# Module-level formatter registry: map content type -> (formatter_function, mime_type)
FORMATTERS = {
    'text/csv': (to_csv, 'text/csv; charset=utf-8'),
    'application/yaml': (to_yaml, 'application/yaml; charset=utf-8'),
    'application/xml': (to_xml, 'application/xml; charset=utf-8'),
    'application/json': (to_json, 'application/json; charset=utf-8'),
}

# CLI-friendly mapping from short names to content types
CLI_FORMAT_MAP = {
    'json': 'application/json',
    'csv': 'text/csv',
    'yaml': 'application/yaml',
    'xml': 'application/xml',
}

# Accept-header matchers: (substring, canonical content-type)
ACCEPT_MATCHERS = [
    ('text/csv', 'text/csv'),
    ('application/x-yaml', 'application/yaml'),
    ('application/yaml', 'application/yaml'),
    ('application/xml', 'application/xml'),
    ('text/xml', 'application/xml'),
]


def format_output(jobs, content_type):
    """Format jobs based on content type."""
    formatter, mime = FORMATTERS.get(content_type, FORMATTERS['application/json'])
    return formatter(jobs), mime


def load_and_extract_jobs(db_path, days, min_score):
    """Helper to load jobs from DB, sort them, and apply score filter."""
    gd = load_jobs(db_path, days=days)
    keys = sort_jobs(gd)
    return extract_job_data(gd, keys, min_score=min_score)


def format_locked_error_response(content_type_str, timeout, url='/jobs'):
    """Build body, content type, and headers for a DB-locked response."""
    if content_type_str == 'text/csv':
        error_body = f"status,error\nlocked,Database locked - retry in {timeout}s\n"
        content_type = 'text/csv; charset=utf-8'
    elif content_type_str == 'application/yaml':
        error_body = f"status: locked\nerror: Database locked - retry in {timeout}s\n"
        content_type = 'application/yaml; charset=utf-8'
    elif content_type_str == 'application/xml':
        error_body = (
            '<?xml version="1.0"?><response><status>locked</status>'
            f'<error>Database locked - retry in {timeout}s</error></response>'
        )
        content_type = 'application/xml; charset=utf-8'
    else:
        error_body = json.dumps(
            {
                'status': 'locked',
                'error': f'Database locked - retry in {timeout}s',
            },
            indent=2,
        )
        content_type = 'application/json; charset=utf-8'

    headers = {
        'Refresh': f'{timeout}; url={url}',
        'Retry-After': str(timeout),
    }

    return error_body, content_type, headers


# ============================================================================
# Module-level API (for use as a Python library)
# ============================================================================


def get_jobs_data(
    db_path: str = '~/.jobserve.gdbm',
    days: int = 7,
    min_score: int = 5,
) -> dict:
    """Return job data as a dictionary.

    This is the primary programmatic interface for using job_api as a module.
    Returns a dict with keys: 'status', 'count', 'jobs'.

    Args:
        db_path: Path to the GDBM database file.
        days: Number of days back to include.
        min_score: Minimum score threshold for jobs.

    Returns:
        dict: {'status': 'ok', 'count': <int>, 'jobs': [<job_dict>, ...]}

    Raises:
        BlockingIOError: If the database is locked.
    """
    jobs = load_and_extract_jobs(db_path, days, min_score)
    return {'status': 'ok', 'count': len(jobs), 'jobs': jobs}


def get_jobs_output(
    db_path: str = '~/.jobserve.gdbm',
    days: int = 7,
    min_score: int = 5,
    format: str = 'json',
) -> str:
    """Return job data as a formatted string.

    Convenience wrapper that serializes job data to JSON, CSV, YAML, or XML.

    Args:
        db_path: Path to the GDBM database file.
        days: Number of days back to include.
        min_score: Minimum score threshold for jobs.
        format: Output format ('json', 'csv', 'yaml', 'xml').

    Returns:
        str: Formatted output string.

    Raises:
        BlockingIOError: If the database is locked.
        ValueError: If format is not recognized or YAML is unavailable.
    """
    data = get_jobs_data(db_path, days, min_score)
    content_type = CLI_FORMAT_MAP.get(format, 'application/json')
    formatter, _ = FORMATTERS.get(content_type, FORMATTERS['application/json'])
    return formatter(data['jobs'])


def build_success_payload(db_path, days, min_score, accept_header):
    """Framework-agnostic success helper.

    Loads jobs, negotiates content type from an Accept header, and formats
    the response body and MIME type. WSGI and FastAPI wrap this in their
    respective response types.
    """
    data = get_jobs_data(db_path, days, min_score)
    content_type_str = get_content_type(accept_header)
    output, content_type = format_output(data['jobs'], content_type_str)
    return output, content_type


# ============================================================================
# CLI Entry Point
# ============================================================================

def main_cli():
    """Command-line interface."""
    parser = argparse.ArgumentParser(description='Extract job analysis data in multiple formats')
    parser.add_argument('--db-path', default='~/.jobserve.gdbm', help='Path to GDBM database')
    parser.add_argument('--days', type=int, default=7, help='Number of days back to include')
    parser.add_argument('--min-score', type=int, default=5, help='Minimum score threshold')
    parser.add_argument('--format', choices=['json', 'csv', 'yaml', 'xml'], default='json', 
                       help='Output format (default: json)')
    
    args = parser.parse_args()
    
    try:
        output = get_jobs_output(
            db_path=args.db_path,
            days=args.days,
            min_score=args.min_score,
            format=args.format,
        )
        print(output)
        return 0
        
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}), file=sys.stderr)
        return 1


# ============================================================================
# WSGI Entry Point
# ============================================================================

def application(environ, start_response):
    """WSGI application for Apache/gunicorn."""
    config = get_config_from_env()
    
    try:
        # Framework-agnostic success path
        accept_header = environ.get('HTTP_ACCEPT', '')
        output, content_type = build_success_payload(
            config['db_path'], config['days'], config['min_score'], accept_header
        )
        
        status = '200 OK'
        response_headers = [
            ('Content-Type', content_type),
            ('Content-Length', str(len(output))),
        ]
        start_response(status, response_headers)
        return [output.encode('utf-8')]
        
    except BlockingIOError:
        # Database is locked
        timeout = config['refresh_timeout']
        current_url = environ.get('REQUEST_URI', '/')
        
        # Determine requested format for error response
        accept_header = environ.get('HTTP_ACCEPT', '')
        content_type_str = get_content_type(accept_header)
        
        error_body, content_type, hdrs = format_locked_error_response(
            content_type_str, timeout, current_url
        )
        
        status = '503 Service Unavailable'
        response_headers = [
            ('Content-Type', content_type),
            ('Content-Length', str(len(error_body))),
            ('Refresh', hdrs['Refresh']),
            ('Retry-After', hdrs['Retry-After']),
        ]
        start_response(status, response_headers)
        return [error_body.encode('utf-8')]
        
    except Exception as e:
        # General error
        error_msg = str(e)
        error_body = json.dumps({'status': 'error', 'error': error_msg}, indent=2)
        
        status = '500 Internal Server Error'
        response_headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(error_body))),
        ]
        start_response(status, response_headers)
        return [error_body.encode('utf-8')]



# ============================================================================
# FastAPI Entry Point
# ============================================================================

if HAS_FASTAPI:
    app = FastAPI(title='Job Analysis API', description='Extract job data in multiple formats')
    # Allow all Host headers (useful when serving via dynamic DNS or external testing).
    # Starlette's TrustedHostMiddleware normally restricts Host header values; explicitly
    # add it with allowed_hosts=["*"] so requests with arbitrary Host headers are accepted.
    try:
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    except ImportError:
        # If starlette isn't available, continue without the middleware.
        pass
    
    @app.get('/jobs')
    def get_jobs(
        accept: str = Header(default='application/json'),
        days: int = 7,
        min_score: int = 5,
    ):
        """Get jobs in requested format."""
        config = get_config_from_env()
        config['days'] = days
        config['min_score'] = min_score
        
        try:
            # Framework-agnostic success path
            output, content_type = build_success_payload(
                config['db_path'], config['days'], config['min_score'], accept
            )

            return Response(content=output, media_type=content_type)
            
        except BlockingIOError:
            # Database is locked
            timeout = config['refresh_timeout']
            
            content_type_str = get_content_type(accept)
            error_body, content_type, headers = format_locked_error_response(
                content_type_str, timeout, url='/jobs'
            )

            return Response(
                content=error_body,
                status_code=503,
                media_type=content_type,
                headers=headers,
            )
            
        except Exception as e:
            # General error
            error_msg = str(e)
            return JSONResponse(
                status_code=500,
                content={'status': 'error', 'error': error_msg}
            )
    
    # NOTE: format-specific endpoints removed — use Accept header with `/jobs`.
    # The server will negotiate output format based on the client's Accept header.
    
    @app.get('/health')
    def health_check():
        """Health check endpoint."""
        return {'status': 'ok', 'api': 'job_api'}

if __name__ == '__main__':
    sys.exit(main_cli())
