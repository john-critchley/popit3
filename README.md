# PopIt3 - Intelligent Job Application Pipeline

An automated system that transforms job alert emails into actionable insights, using AI to match opportunities against your CV and generate scored, web-deployed reports.

##  Key Features

- **Automated Email Processing**: POP3/OAuth2 integration for Outlook/Hotmail
- **Multi-Source Support**: JobServe alerts, David Lloyd bookings, and extensible for other sources
- **AI-Powered Analysis**: OpenAI GPT integration for CV-job matching (0-10 scoring)
- **Smart Storage**: GDBM-based with Message-ID keying to handle duplicate JobServe references
- **Web Deployment**: Automated HTML report generation with WebDAV deployment
- **Visual Reports**: Color-coded job matches with expandable details
- **Process Safety**: Lock files and retry logic for robust operation

##  Quick Start

### Prerequisites

- Python 3.8+
- OpenAI API key
- Outlook/Hotmail account with POP3 enabled
- WebDAV server (optional, for web deployment)

### Installation
```bash
# Clone the repository
git clone https://github.com/yourusername/popit3.git
cd popit3

# Install dependencies
pip install -r requirements.txt

# Set up credentials
cp .netrc.example ~/.netrc
chmod 600 ~/.netrc
# Edit ~/.netrc with your credentials

# Set up OpenAI API
python3 -c "import gdata; db = gdata.gdata('~/.env_data'); db['api_key'] = 'your-openai-key'; db.close()"
```

### Basic Usage
```bash
# Process new emails
./popit3.py

# Generate and deploy HTML report
python3 job_analysis_html_report.py

# Query job database
python3 query_jobs.py list
python3 query_jobs.py search python "machine learning"

# Extract analysis results
python3 extract_job_analysis.py --sort-by-score
```

##  Architecture
```
Email Sources  POP3 Fetcher  Parser  Database  LLM Analyzer  Report Generator  Web
                                                                  
  Outlook       popit3.py    js_email   GDBM      OpenAI API    HTML/WebDAV
```

##  Configuration

### Email Setup (`.netrc`)
```
machine outlook.office365.com
  login your-email@hotmail.com
  account MSAL:your-client-id
  password your-refresh-token

machine webdav.critchley.biz
  login webdav-user
  password webdav-password
```

### OpenAI Configuration
```python
# Set up in ~/.env_data
{
  "api_key": "sk-...",
  "model": "gpt-4o-mini",
  "organization": "org-..." (optional),
  "project": "proj-..." (optional)
}
```

##  Project Structure
```
popit3/
 Core Processing
    popit3.py              # Main email fetcher
    process_emails.py      # Email router/processor
    process_lock.py        # Concurrency control
 Parsers
    jobserve_parser.py     # JobServe email parser
    js_email.py            # JobServe HTML extractor
    dl_email.py            # David Lloyd parser
 Analysis
    analyze_jobs_openai.py # OpenAI job analyzer
    query_jobs.py          # Database queries
    extract_job_analysis.py # Results extractor
 Reporting
    job_analysis_html_report.py # HTML generator
    mailspool.py           # Email archiving
 Utilities
     gdata.py               # GDBM wrapper (external)
     scanmailheaders.py     # Email security
```

##  Report Features

- **Color-Coded Scores**: 
  -  8-10: Excellent match
  -  7: Good match
  -  6: Average match
  -  <6: Poor match
- **Expandable Details**: Click scores to see full analysis
- **Job Age Indicators**: Visual freshness by color intensity
- **Direct Links**: Apply buttons and analysis pages

##  Automation

### Cron Setup
```bash
# Process emails every 30 minutes
*/30 * * * * cd /path/to/popit3 && ./popit3.py >> out.log 2>&1

# Generate reports daily at 9 AM
0 9 * * * cd /path/to/popit3 && python3 job_analysis_html_report.py
```

##  Troubleshooting

- **Database Locked**: Check `/tmp/popit3.lock` and remove if stale
- **OAuth Issues**: Regenerate token with `get_pop_refresh_token.py`
- **LLM Failures**: Check API quota and model availability
- **WebDAV Errors**: Verify credentials in `~/.netrc`

##  Performance

- Processes ~50 emails/minute
- LLM analysis: ~3 seconds/job (with GPT-4o-mini)
- HTML generation: <1 second for 100 jobs
- Typical database: 500-1000 jobs stored

##  Contributing

Contributions welcome! Key areas for enhancement:
- Additional email sources (LinkedIn, Indeed)
- Alternative LLM providers (Anthropic, local models)
- Enhanced scoring algorithms
- Mobile-responsive reports

##  License

MIT License - See LICENSE file

##  Acknowledgments

- Uses `gdata` for GDBM wrapper functionality
- OpenAI for GPT models
- JobServe for job listings
