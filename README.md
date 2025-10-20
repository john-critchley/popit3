# PopIt3 - Job Analysis and Email Processing System

A Python-based system for parsing job emails from Jobserve, analyzing them with LLM, and generating HTML reports.

## Features

- **Email Processing**: Parse job emails from various sources (Jobserve, etc.)
- **LLM Analysis**: Analyze job descriptions using OpenAI/LLM APIs for relevance scoring
- **HTML Reports**: Generate professional HTML reports with color-coded job analysis
- **WebDAV Deployment**: Automatically deploy reports to web servers
- **Database Storage**: GDBM-based storage for job data and analysis results

## Main Components

### Core Scripts
- `popit3.py` - Main email processing and job extraction
- `extract_job_analysis.py` - Extract and display job analysis data
- `job_analysis_html_report.py` - Generate HTML reports and deploy to web
- `process_emails.py` - Email processing utilities
- `mailspool.py` - Email spool management

### LLM Integration
- `llm_client.py` - LLM client interface
- `process_jobs_with_llm.py` - Job analysis with LLM
- `run_llm_analysis.py` - Batch job analysis runner
- `analyze_jobs_openai.py` - OpenAI-specific job analysis

### Parsers
- `jobserve_parser.py` - Jobserve email parser
- `js_email.py` - Job email utilities
- `scanmailheaders.py` - Email header analysis

### Utilities
- `MyJobserveJobs.py` - Jobserve job management
- `query_jobs.py` - Job database queries
- `migrate_database.py` - Database migration utilities

## Usage

### Generate HTML Report
```bash
python3 job_analysis_html_report.py
```

Options:
- `--score-limit` / `-s`: Minimum score to include (default: 6)
- `--local-only` / `-l`: Generate locally only, don't deploy
- `--staging-dir` / `-d`: Staging directory name

### Extract Job Analysis
```bash
python3 extract_job_analysis.py
```

### Process Emails
```bash
python3 popit3.py
```

## Configuration

The system uses several configuration methods:
- `~/.netrc` for WebDAV credentials
- Environment variables for API keys
- Command-line arguments for runtime options

## Dependencies

- Python 3.x
- webdav4 (for WebDAV deployment)
- requests (for HTTP operations)
- OpenAI API libraries (for LLM analysis)
- Standard Python libraries (email, gdbm, etc.)

## Output

- HTML reports with color-coded job analysis
- Local file storage in GDBM format
- Web deployment to staging/production servers
- Log files for debugging and monitoring