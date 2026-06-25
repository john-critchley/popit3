# PopIt3 Undocumented Modules - Comprehensive Analysis

## Overview

This document identifies and catalogs all undocumented features, modules, and functionality in the PopIt3 email processing system. The project has solid architecture documentation but lacks detailed documentation for several important utility and support modules.

---

## CRITICAL PRIORITY MODULES

These modules are essential for system operation and require immediate documentation.

### 1. gdata.py - GNU Database Manager Wrapper

**File**: [gdata.py](gdata.py)  
**Purpose**: Abstraction layer for GDBM (GNU Database Manager) database operations with JSON serialization support  
**Complexity**: Moderate  
**Priority**: CRITICAL  
**Lines of Code**: 156

#### What It Does
- Provides three database classes for working with GDBM files:
  - `gdata_raw`: Base class with dictionary-like access to GDBM databases
  - `gdata_simple`: UTF-8 string encoding/decoding wrapper
  - `gdata`: Full JSON serialization/deserialization for structured data storage

- Implements context manager protocol (`with` statement support)
- Handles database locking with custom `GDataLockedError` exception (indicates write lock)
- Detects `errno.EAGAIN` errors which signal database lock conflicts

#### Key Classes & Methods
- `GDataLockedError`: Exception class for database lock detection
- `gdata_raw`: 
  - `__init__(gdbm_file, mode, mask)`: Opens GDBM database with optional file permissions
  - `__enter__/__exit__`: Context manager support
  - `__getitem__/__setitem__/__delitem__`: Dictionary-like access
  - `keys()`, `items()`, `get(key, default)`: Standard dict methods
  - `__len__`: Database size
- `gdata_simple`: Extends gdata_raw with UTF-8 encoding
- `gdata`: Extends gdata_simple with automatic JSON serialization

#### Used By
- `popit3.py` - Main email sync processor
- `newparser_jobserve.py` - Job parser and AI scorer
- `job_api.py` - REST API for job queries
- `reset_all_scores.py` - Score reset utility
- `reset_recent_analysis.py` - Recent jobs reset utility
- `applications_report.py` - Application report generator
- `job_analysis_report.py` - HTML report generator
- `MyDavidLloydSchedule.py` - Gym schedule processor

#### Who Maintains It
- Used throughout codebase; changes here affect all database operations

#### Critical to Know
- **Lock Handling**: Database must be closed immediately to release locks (context manager handles this)
- **Read vs Write**: Open with mode='r' for read-only, 'w' for write, 'c' for create/update
- **JSON Storage**: All structured job data stored as JSON strings in GDBM
- **Error Recovery**: `GDataLockedError` should trigger retry logic in calling code
- **Default Database**: Most scripts use `~/.jobserve.gdbm` (configurable)

---

### 2. job_api.py - REST API & CLI for Job Data

**File**: [job_api.py](job_api.py)  
**Purpose**: Multi-interface job data query system with REST API, CLI, and WSGI support  
**Complexity**: Complex  
**Priority**: CRITICAL  
**Lines of Code**: 530

#### What It Does
Provides job data access in three ways:
1. **Command-line tool**: `python3 job_api.py [--format json|csv|yaml|xml] [--days 7] [--min-score 5]`
2. **WSGI application**: Runnable under Apache, Gunicorn via WSGI environ
3. **FastAPI application**: Modern async REST API with Uvicorn
4. **Format negotiation**: Content-Type based on Accept header

#### Key Features
- **Multiple Output Formats**: JSON, CSV, YAML, XML with consistent structure
- **Database Locking Awareness**: Detects locks, returns 503 Unavailable with Refresh header
- **Time-based Filtering**: Returns jobs from last N days (default 7)
- **Score Filtering**: Minimum score threshold (default 5)
- **HTTP Caching**: Proper cache control headers for all responses
- **Error Handling**: Structured error responses for locked/missing DB

#### Key Functions
- `load_jobs(db_path, days)`: Load job records from GDBM within date range
- `extract_job_data(gd, keys, min_score)`: Filter and extract scoring data
- `sort_jobs(gd)`: Sort job records by date
- `format_tdelta(record, now)`: Human-readable time differences (e.g., "2 days, 3 hours")
- `to_json/to_csv/to_yaml/to_xml(jobs)`: Format converters returning (output, mime_type)
- `get_content_type(accept_header)`: Parse Accept header, default to JSON
- `get_jobs_data(db_path, days, min_score)`: Module-level API returning dict with status/count/jobs
- `get_jobs_output(db_path, days, min_score, accept_header)`: Module-level API returning formatted output
- `build_success_payload(db_path, days, min_score, accept_header)`: JSON envelope builder
- `format_locked_error_response(content_type, timeout)`: 503 locked database response
- `main_cli()`: CLI interface with argparse
- `application(environ, start_response)`: WSGI entry point
- `app` (FastAPI): FastAPI application object with `/jobs` and `/health` endpoints

#### Output Schema
```json
{
  "status": "ok",
  "count": 5,
  "jobs": [
    {
      "score": 8,
      "reference": "JS-12345",
      "job_title": "Senior Python Engineer",
      "company": "Acme Ltd",
      "location": "London",
      "salary": "£85k-105k",
      "posted": "22 Jan 2026",
      "age": "2 days, 3 hours",
      "url": "https://www.jobserve.com/..."
    }
  ]
}
```

#### Used By
- Web dashboard at https://www.critchley.biz/JobAnalysis
- cron jobs for report generation
- Direct CLI queries for job data

#### Environment Variables
- `JOBSERVE_DBFILE`: Path to database (default `~/.jobserve.gdbm`)
- `JOBSERVE_DAYS`: Days to look back (default 7)
- `JOBSERVE_MIN_SCORE`: Minimum score threshold (default 5)
- `JOBSERVE_REFRESH_TIMEOUT`: Seconds before retry on lock (default 10)

#### Critical to Know
- **Lock Handling**: Returns 503 with `Refresh: 10` header when DB locked
- **FastAPI Optional**: Works without FastAPI installed (falls back to WSGI/CLI)
- **Content Negotiation**: Uses Accept header to determine response format
- **Timestamp Format**: Uses ISO format for `posted` field from record metadata
- **Error Responses**: All errors return structured JSON with status and error message

#### Deployment
- WSGI: `mod_wsgi` under Apache or Gunicorn
- CLI: Direct Python execution for cron jobs
- FastAPI: Uvicorn or similar ASGI server

---

### 3. newparser_jobserve.py - Email Parser & AI Scorer

**File**: [newparser_jobserve.py](newparser_jobserve.py)  
**Purpose**: Main email processing engine that parses JobServe emails and scores jobs using AI  
**Complexity**: Complex  
**Priority**: CRITICAL  
**Lines of Code**: 321

#### What It Does
- Parses raw email data (RFC 2822 format)
- Detects and extracts job alert/suggestion email types
- Extracts structured job data using HTML parsers (delegated to js_alert_parser, js_email)
- Scores jobs against user's CV using OpenAI GPT-4o-mini
- Stores results in GDBM database with scores and reasoning
- Implements email classification system (alert/suggestion/application/unclassified)

#### Key Functions
- `classify_job()`: Classify email into alert, suggestion, application, or unclassified
- Email parsing with RFC 2822 header extraction
- OpenAI API integration for CV-job matching
- Duplicate detection using Message-ID

#### Configuration
- Model: `gpt-4o-mini` (configurable via MODEL variable)
- CV Path: Environment variable `CV_PATH` or default `~/CV/cv_llm_optimized.md`
- OpenAI API key: Stored in `~/.openai` directory
- Cleanup frequency: Configurable (default 1 in N records checked for old dates)

#### Email Classification
1. **Job Alert**: JobServe job suggestion emails with standard format
2. **Job Suggestion**: Alternative format from JobServe
3. **Application Confirmation**: "JobServe Job Application Confirmation" emails
4. **Unclassified**: Emails that don't match above patterns

#### Scoring Logic (GPT-4o-mini)
- Uses system prompt with CV content as context
- Analyzes technical skills, experience relevance, location feasibility
- Discriminates across full 0-10 range (not grade inflation)
- Critical blockers (security clearance, visa requirements, etc.) score 0-2
- Strong fit with gaps: 7-8
- Exceptional fit: 9-10

#### Critical to Know
- **CV Management**: CV file path critical for scoring; updates require reprocessing
- **Email Headers**: Uses standard email library to parse RFC 2822
- **Structured Output**: Scores stored as JSON in `scored_job` field
- **Deletion Policy**: Jobs auto-deleted after 14 days, applications after 28 days
- **Database Format**: Records use `job_type` field for classification

---

### 4. popit3.py - POP3 Email Synchronizer

**File**: [popit3.py](popit3.py)  
**Purpose**: Main POP3 email synchronization engine with XOAUTH2 authentication  
**Complexity**: Complex  
**Priority**: CRITICAL  
**Lines of Code**: 302

#### What It Does
- Connects to Outlook.com via POP3-TLS
- Authenticates using XOAUTH2 with refresh tokens
- Synchronizes email UIDLs to detect new/deleted messages
- Downloads full email bodies (raw bytes)
- Stores emails in GDBM database (JSON with UTF-8 encoded raw email)
- Handles database locking for safe concurrent access
- Calls `process_emails.py` for post-download processing

#### Key Features
- **XOAUTH2 Authentication**: Uses refresh tokens from netrc
- **POP3-TLS**: Secure POP3 with TLS encryption
- **UIDL Tracking**: Uses Message-ID equivalents to track message state
- **Efficient Sync**: Only downloads new messages
- **Raw Email Storage**: Stores full RFC 2822 email as latin-1 encoded string
- **Database Safe**: Properly handles GDBM locking and contexts

#### Key Classes & Functions
- `Pop3TLS`: Context manager for POP3-TLS connections
  - `__enter__/__exit__`: Connection lifecycle
  - `auth_xoauth2(pop, user, access_token)`: XOAUTH2 auth method
  - `list()`: List messages with sizes
  - `retr(n)`: Retrieve message by number
  - `dele(n)`: Delete message
  - `quit()`: Close connection

- Helper functions:
  - `read_netrc(machine)`: Load credentials from ~/.netrc
  - `parse_client_id_from_account(account)`: Extract MSAL client ID from netrc
  - `acquire_access_token_via_refresh()`: Refresh OAuth2 token
  - `get_uidl_map(pop)`: Get current message UIDL list from server
  - `fetch_message_bytes(pop, msgnum)`: Download message body
  - `del_message(pop, msgnum)`: Delete message from server

#### Configuration
- Default machine: `outlook.office365.com`
- Default port: 995 (POP3-TLS)
- Default database: `~/.email3.mail.gdbm`
- Timeout: 30 seconds
- OAuth2 authority: `https://login.microsoftonline.com/consumers`
- OAuth2 scope: `https://outlook.office.com/POP.AccessAsUser.All`

#### Email Storage Format
```json
{
  "key": "UIDL-string",
  "value": {
    "size": 2048,
    "mail": "raw RFC 2822 email as latin-1 string"
  }
}
```

#### Critical to Know
- **Netrc Format**: `machine outlook.office365.com login email@outlook.com account "MSAL:client_id" password "refresh_token"`
- **UIDL Behavior**: Not all servers support UIDL; fallback to message numbering
- **TLS Certificate**: Verifies server certificate (can be disabled with ssl context)
- **Character Encoding**: Uses latin-1 for round-trip safety with binary email data
- **Post-Download**: Calls `process_emails.do_processing()` after sync

#### Deployment
- Typically run via cron every 15-30 minutes
- Requires valid XOAUTH2 refresh token in ~/.netrc
- Requires network access to outlook.office365.com:995

---

## IMPORTANT PRIORITY MODULES

These modules are important for system functionality but less critical than above.

### 5. newparser_jobserve.py (Legacy) / jobserve_parser.py - Parser Shim

**File**: [jobserve_parser.py](jobserve_parser.py) (shim), [_newparser_jobserve.py](_newparser_jobserve.py) (legacy)  
**Purpose**: Compatibility layer; jobserve_parser.py re-exports from newparser_jobserve  
**Complexity**: Simple (shim), Complex (legacy)  
**Priority**: IMPORTANT  
**Lines of Code**: 40 (shim), 248 (legacy)

#### What It Does
- `jobserve_parser.py`: Compatibility shim that imports and re-exports everything from `newparser_jobserve.py`
- `_newparser_jobserve.py`: Legacy version with different implementation details
- Maintains backward compatibility for code importing from jobserve_parser

#### Migration Status
- Current: Uses `newparser_jobserve.py` exclusively
- Legacy `_newparser_jobserve.py` kept for reference/rollback
- Database: Using `.js_new.gdbm` (migrated)

#### Critical to Know
- **Do not edit** jobserve_parser.py directly; edit `newparser_jobserve.py` instead
- **Legacy exists** for rollback purposes only

---

### 6. process_emails.py - Email Router & Processor

**File**: [process_emails.py](process_emails.py)  
**Purpose**: Post-download email routing and processor orchestration  
**Complexity**: Moderate  
**Priority**: IMPORTANT  
**Lines of Code**: 130

#### What It Does
- Routes downloaded emails to specialized processors based on `To:` address
- Coordinates between multiple processors (job analysis, gym schedule, webdav storage)
- Manages WebDAV client connections with retry logic
- Handles encoding issues and malformed emails gracefully
- Stores processed results back to database

#### Email Routing
```
john.js@critchley.biz  → newparser_jobserve (job scoring)
john.dl@critchley.biz  → MyDavidLloydSchedule (gym bookings)
Other addresses        → mailspool (archive)
```

#### Key Features
- **WebDAV Integration**: Uploads processed data to remote server
- **Network Retry Logic**: Handles transient connection failures
- **Error Recovery**: Logs errors but continues processing
- **Character Encoding**: Handles non-ASCII in email properly

#### Configuration
- WebDAV host: `webdav.critchley.biz` (hardcoded, needs parameterization)
- WebDAV credentials: From netrc
- Mode: 'w' (overwrite existing) or 'n' (new only)

#### Used By
- Called by `popit3.py` after email sync

#### Critical to Know
- **Mode Parameter**: 'w' overwrites, 'n' creates new only
- **WebDAV Host**: Hardcoded (needs to be parameterized)
- **Error Handling**: Errors logged but processing continues

---

### 7. job_analysis_report.py - HTML Report Generator

**File**: [job_analysis_report.py](job_analysis_report.py)  
**Purpose**: Generate and deploy HTML reports of job analysis results  
**Complexity**: Complex  
**Priority**: IMPORTANT  
**Lines of Code**: 572

#### What It Does
- Loads job records from GDBM database
- Generates HTML report with three tables:
  1. Scored Jobs (main analysis)
  2. Job Applications (submitted applications)
  3. Unclassified Emails (debug information)
- Color-codes scores (green for high, red for low)
- Makes job titles clickable to original posts
- Deploys report to WebDAV server
- Handles cleanup of old records (14-day jobs, 28-day applications)

#### Report Features
- Sortable tables with score highlighting
- Time-delta formatting (e.g., "2 days ago")
- Company and location information
- Direct links to job posts
- Application dates and details
- Unclassified email debugging table

#### Key Functions
- `format_posted_date()`: Format job posted dates
- `rec_format_tdelta()`: Human-readable time deltas
- `generate_html_table()`: Create scored jobs table
- `generate_applications_table()`: Create applications table
- `generate_unclassified_table()`: Create unclassified emails table
- `create_full_html_document()`: Combine all tables into complete HTML
- `process_job_analysis()`: Main entry point - load, filter, generate, deploy

#### Configuration
- Database: `~/.jobserve.gdbm`
- WebDAV destination: `webdav.critchley.biz` (configurable)
- Job retention: 14 days
- Application retention: 28 days
- Cleanup on generation: Auto-deletes old records

#### Deployment
- Runs via cron (typically daily)
- Outputs to: `https://www.critchley.biz/JobAnalysis/`
- Includes OpenAI reasoning when clicking scores

---

### 8. mylog.py - Logging Configuration Helper

**File**: [mylog.py](mylog.py)  
**Purpose**: Centralized logging setup with console, file, and syslog support  
**Complexity**: Simple  
**Priority**: IMPORTANT  
**Lines of Code**: 50

#### What It Does
- Provides `get_logger()` function for consistent logging setup
- Supports multiple handlers: console, file, syslog
- Configurable log levels and formats
- Prevents duplicate handlers through internal tracking

#### Function Signature
```python
def get_logger(
    name,                           # Logger name (typically __name__)
    level=logging.INFO,             # Log level
    console=True,                   # Console output
    logfile=None,                   # Optional file path
    syslog=False,                   # Optional syslog
    fmt="...",                      # Format string
    datefmt="%Y-%m-%d %H:%M:%S"   # Date format
)
```

#### Usage Example
```python
import mylog
log = mylog.get_logger(__name__, level=logging.DEBUG)
log.info("Processing email...")
```

#### Critical to Know
- **Prevents Duplicates**: Checks `log.handlers` to avoid duplicate handlers
- **Default Format**: Includes timestamp, level, logger name, message
- **Propagation**: Disables propagation to root logger (`log.propagate = False`)

---

### 9. applications_report.py - Job Applications Report

**File**: [applications_report.py](applications_report.py)  
**Purpose**: Generate report of submitted job applications  
**Complexity**: Moderate  
**Priority**: IMPORTANT  
**Lines of Code**: 118

#### What It Does
- Loads application confirmation records from database
- Generates summary report of recent applications
- Filters by date range (default 30 days)
- Shows job title, company, date applied
- Provides statistics (total applications, success metrics)

#### Function
- `generate_applications_report(days=30)`: Main entry point

#### Report Contents
- Application date and time
- Job title
- Company/agency
- Employment type
- Location
- Application count and summary

#### Critical to Know
- **Database**: Uses `~/.jobserve_applications.gdbm` OR records in main DB with `job_type: "application"`
- **Filter**: Dates within N days from today
- **Missing Data**: Graceful handling of incomplete records

---

### 10. applications_report.py - Job Applications Report

**File**: [applications_report.py](applications_report.py)  
**Purpose**: Generate report of submitted job applications  
**Complexity**: Moderate  
**Priority**: IMPORTANT  
**Lines of Code**: 118

#### What It Does
- Loads application confirmation records from database
- Generates summary report of recent applications
- Filters by date range (default 30 days)
- Shows job title, company, date applied
- Provides statistics (total applications, success metrics)

#### Function
- `generate_applications_report(days=30)`: Main entry point

#### Report Contents
- Application date and time
- Job title
- Company/agency
- Employment type
- Location
- Application count and summary

#### Critical to Know
- **Database**: Uses records with `job_type: "application"` from main DB
- **Filter**: Dates within N days from today
- **Missing Data**: Graceful handling of incomplete records

---

### 11. wsgi_dev_server.py - Development WSGI Server

**File**: [wsgi_dev_server.py](wsgi_dev_server.py)  
**Purpose**: Simple development web server for testing job_api  
**Complexity**: Simple  
**Priority**: IMPORTANT  
**Lines of Code**: 18

#### What It Does
- Starts a simple WSGI development server using `wsgiref`
- Hosts the job_api WSGI application
- Useful for local development and testing
- NOT for production (use Gunicorn or Apache)

#### Usage
```bash
python3 wsgi_dev_server.py
# Serves on http://127.0.0.1:8051
```

#### Configuration
- Host: `127.0.0.1` (localhost only)
- Port: `8051`
- WSGI app: Imported from `job_api.py`

#### Critical to Know
- **Development Only**: Not suitable for production
- **Single-threaded**: Cannot handle concurrent requests
- **Interrupts**: Graceful shutdown on Ctrl+C

---

## NICE-TO-HAVE PRIORITY MODULES

These modules provide utility functionality but are not critical to core operation.

### 12. Email Parsers - Specialized HTML Parsers

#### js_alert_parser.py - JobServe Alert Parser
**File**: [js_alert_parser.py](js_alert_parser.py)  
**Purpose**: Extract structured data from JobServe job alert HTML emails  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 245

**Function**: `parse_jobserve_alert(html_content) -> dict`

**Returns**:
```python
{
  "job_title": "Senior Engineer",
  "location": "London, UK",
  "salary": "£85k-105k",
  "work_type": "Permanent, Full-time",
  "description": "Job description HTML content...",
  "employment_business": "Acme Agency",
  "ref": "JS-12345",
  "posted": "22 Jan 2026"
}
```

**Uses**: Custom HTML parser based on `HTMLParser` to extract structured data from email HTML

---

#### js_email.py - JobServe Email Suggestion Parser
**File**: [js_email.py](js_email.py)  
**Purpose**: Extract structured data from JobServe email suggestion HTML  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 199

**Function**: `parse_jobserve_email_part(html_part) -> dict`

**Similar structure to `js_alert_parser` but handles different email format**

**Returns**:
```python
{
  "job_title": "...",
  "location": "...",
  "salary": "...",
  "work_type": "...",
  "description": "...",
  "job_url": "...",
  ...
}
```

---

#### js_application_parser.py - JobServe Application Confirmation Parser
**File**: [js_application_parser.py](js_application_parser.py)  
**Purpose**: Extract data from JobServe application confirmation emails  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 141

**Function**: `parse_jobserve_application_confirmation(html_part) -> dict`

**Returns application confirmation details**:
```python
{
  "job_title": "...",
  "location": "...",
  "work_type": "...",
  "description": "...",
  "reference": "...",
  "posted_by": "...",
  "contact_name": "...",
  "contact_email": "...",
  "contact_phone": "..."
}
```

---

#### dl_email.py - David Lloyd Gym Schedule Parser
**File**: [dl_email.py](dl_email.py)  
**Purpose**: Extract gym class booking information from David Lloyd booking emails  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 207

**Function**: `parse_david_lloyd_email_part(html_part) -> dict`

**Detects**:
- Booking confirmations, cancellations, rescheduling
- Sports (tennis, padel, squash, badminton, pickleball, table tennis)
- Dates and time ranges
- Booking references (DL-XXXX format)

**Returns**:
```python
{
  "event_type": "booking|cancellation|update",
  "sport": "tennis",
  "date": datetime.date,
  "time_start": datetime.time,
  "time_end": datetime.time,
  "booking_ref": "DL-ABC-123",
  "location": "...",
  ...
}
```

---

#### scanmailheaders.py - Email Address Parser & Validator
**File**: [scanmailheaders.py](scanmailheaders.py)  
**Purpose**: Parse and validate email addresses with security checks  
**Complexity**: Simple  
**Priority**: Nice-to-have  
**Lines of Code**: 87

**Functions**:
- `parse_email_address(addr_string) -> (email, is_valid)`: Single email validation
- `parse_email_addresses(addr_string) -> list`: Parse comma-separated addresses

**Security Checks**:
- Length limits (max 254 characters)
- CVE-2023-27043 protection (suspicious characters)
- Header injection prevention (no CR/LF)
- Multiple @ symbol detection
- Quoted string handling

---

### 13. Utility Scripts - Database Management

#### reset_all_scores.py - Reset All Job Scores
**File**: [reset_all_scores.py](reset_all_scores.py)  
**Purpose**: Reset AI scores for all jobs to force re-analysis  
**Complexity**: Simple  
**Priority**: Nice-to-have  
**Lines of Code**: 35

**Usage**:
```bash
python3 reset_all_scores.py          # Live - resets scores
python3 reset_all_scores.py --dry-run  # Preview only
```

**What it does**: 
- Opens `~/.jobserve.gdbm`
- Finds all records with `scored_job` key
- Removes the `scored_job` field
- Records count of reset jobs

**Use Case**: When CV is updated and you want fresh scores

---

#### reset_recent_analysis.py - Reset Recent Job Scores
**File**: [reset_recent_analysis.py](reset_recent_analysis.py)  
**Purpose**: Reset AI scores only for recent jobs (default 3 days)  
**Complexity**: Simple  
**Priority**: Nice-to-have  
**Lines of Code**: 76

**Usage**:
```bash
python3 reset_recent_analysis.py              # Default: 3 days
python3 reset_recent_analysis.py --days 7    # Custom days
python3 reset_recent_analysis.py --db ~/custom.gdbm  # Custom DB
```

**Removes fields**:
- `scored_job`
- `score`
- `score_reason`

**Use Case**: Fix scoring for specific recent batch without full reset

---

### 14. MyDavidLloydSchedule.py - Gym Schedule Processor

**File**: [MyDavidLloydSchedule.py](MyDavidLloydSchedule.py)  
**Purpose**: Parse and manage David Lloyd gym class bookings  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 227

#### What It Does
- Parses gym booking confirmation/cancellation emails
- Extracts class details (sport, date, time, location)
- Generates calendar data (HTML, ICS, etc.)
- Renders HTML schedule table
- Manages booking database in GDBM
- Deploys schedule to WebDAV

#### Key Functions
- `dd(x)`: Convert dict values to ISO format datetimes
- `td(x)`: Convert ISO date strings back to datetime objects
- `aox(db, key, val, val2)`: Add new key/value list to database
- `render_events_table_html()`: Generate HTML schedule table

#### Database Schema
Stores bookings indexed by date:
```python
{
  "2026-01-22": [
    ["msg_id_1", {booking_details}],
    ["msg_id_2", {booking_details}],
  ]
}
```

#### Outputs
- HTML schedule to WebDAV for web display
- ICS calendar file (if supported)
- Local SQLite database of bookings

---

### 15. mailspool.py - Email Storage Manager

**File**: [mailspool.py](mailspool.py)  
**Purpose**: Store emails in Maildir format (local and WebDAV)  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 123

#### What It Does
- Stores emails in Maildir format (standard for Unix mail)
- Supports local filesystem storage
- Supports WebDAV remote storage
- Handles compression (optional)
- Generates RFC-compliant filenames

#### Key Classes
- `MailSpool`:
  - `__init__(maildir_path, webdav_client=None, delete=True)`
  - `store_messages(messages)`: Store parsed email objects
  - `_generate_filename()`: RFC 3501 compliant filenames
  - `_store_local()`: Write to local Maildir
  - `_store_webdav_from_file()`: Upload to WebDAV
  - `_store_webdav_from_memory()`: Upload without local storage

#### Maildir Structure
```
maildir/
├── new/     # New messages
├── cur/     # Current (read) messages
└── tmp/     # Temporary (being written)
```

#### Filename Format
`{timestamp}.{hostname}:2,{flags}`

---

### 16. query_jobs.py - Job Query Compatibility Shim

**File**: [query_jobs.py](query_jobs.py)  
**Purpose**: Compatibility layer for legacy job query code  
**Complexity**: Simple  
**Priority**: Nice-to-have  
**Lines of Code**: 145 (includes legacy code)

#### What It Does
- Acts as shim that imports code from `TO_DELETE/query_jobs.py`
- Provides helper functions:
  - `get_job(message_id)`: Get single job by ID
  - `get_all_jobs()`: Get all jobs with parsed_job data
  - `get_jobs_by_jobserve_ref()`: Get jobs by reference number

#### Critical to Know
- **Shim Pattern**: Loads legacy code from TO_DELETE folder at runtime
- **Purpose**: Backward compatibility during transition
- **Should Replace**: With direct calls to gdata and filtering

---

### 17. tmp_cleanup.py - Temporary File Cleanup Scheduler

**File**: [tmp_cleanup.py](tmp_cleanup.py)  
**Purpose**: Schedule automatic deletion of temporary files via `at` command  
**Complexity**: Simple  
**Priority**: Nice-to-have  
**Lines of Code**: 70

#### What It Does
- Schedules deletion of temporary files using Unix `at` command
- Safety checks: Only files starting with `tmp_` can be deleted
- Converts relative paths to absolute paths
- Validates cleanup environment

#### Key Function
```python
def schedule_tmp_cleanup(
    paths: Union[str, Sequence[str]],
    when: str = "17:00 tomorrow",
    allow_missing: bool = False
) -> Optional[str]
```

#### Configuration
- `POPIT3_DISABLE_AT_CLEANUP`: Environment variable to disable cleanup
- Requires `at` daemon running

#### Safety Features
- Filename validation (must start with `tmp_`)
- Path resolution (absolute paths only)
- Graceful degradation (returns None if `at` unavailable)

---

### 18. get_pop_refresh_token.py - OAuth2 Token Manager

**File**: [get_pop_refresh_token.py](get_pop_refresh_token.py)  
**Purpose**: Obtain and refresh OAuth2 tokens for POP3 access  
**Complexity**: Moderate  
**Priority**: Nice-to-have  
**Lines of Code**: 105

#### What It Does
- Initiates OAuth2 device flow for user authentication
- Supports web-based authorization redirect
- Acquires tokens using authorization codes
- Manages token lifecycle

#### Key Class
- `TokenManager`:
  - `__init__(client_id, user, authority, scope)`
  - `get_device_flow_url_and_code()`: Start device flow
  - `get_auth_url(redirect_uri)`: Get web auth URL
  - `acquire_token_by_auth_code()`: Acquire token from code

#### Configuration
- Default authority: `https://login.microsoftonline.com/consumers`
- Default scope: `https://outlook.office.com/POP.AccessAsUser.All`

#### Used By
- Initial setup of XOAUTH2 tokens for popit3.py

---

### 19. analyze_jobs_openai.py - Alternative OpenAI Analyzer

**File**: [analyze_jobs_openai.py](analyze_jobs_openai.py)  
**Purpose**: Alternative OpenAI job analyzer with structured JSON output  
**Complexity**: Complex  
**Priority**: Nice-to-have  
**Lines of Code**: 447

#### What It Does
- Analyzes jobs against CV using OpenAI API
- Uses structured JSON responses instead of regex parsing
- Provides longer, detailed reasoning
- Intended as replacement for inline scoring in newparser_jobserve

#### Key Class
- `OpenAIJobAnalyzer`:
  - `__init__(env_data_path, cv_file_path)`
  - CV loading and API key management
  - Score analysis with structured output

#### Differences from newparser_jobserve
- **Structured Output**: Uses JSON responses API for reliable parsing
- **Longer Reasoning**: More detailed explanations
- **Standalone**: Can be run independently
- **CV Management**: Separate CV file path support

#### Note
Module documentation notes previous missing `OpenAIJobAnalyzer` class that has been restored.

---

### 20. Test Suite - Quality Assurance

**Test Files**: All in [tests/](tests/) directory

#### conftest.py - Pytest Fixtures
**Purpose**: Shared pytest fixtures for test sessions  
**Key Fixture**: `wsgi_server` - Session-scoped WSGI server in background thread

#### test_module_api.py - Module API Tests
**Purpose**: Test `get_jobs_data()` and `get_jobs_output()` functions  
**Coverage**: 
- Return types and structure
- Count/filtering validation
- Error handling (locked DB)
- High score filtering

#### test_wsgi_integration.py - WSGI HTTP Tests
**Purpose**: Test HTTP interface via WSGI  
**Coverage**:
- JSON responses
- CSV formatting
- HTTP headers and status codes
- Content-Type negotiation

#### test_fastapi_integration.py - FastAPI Tests
**Purpose**: Test FastAPI interface (if available)  
**Coverage**:
- Similar to WSGI tests
- FastAPI-specific request/response handling
- Status codes and headers

#### test_db_locking.py - Database Lock Handling
**Purpose**: Test behavior when database is locked  
**Coverage**:
- Lock detection
- 503 Unavailable responses
- Refresh header values
- CLI error handling

#### test_cli_output.py - CLI Interface Tests
**Purpose**: Test command-line interface  
**Coverage**:
- JSON output formatting
- CSV output formatting
- Exit codes
- Parameter passing

#### test_format_mappings.py - Format Conversion Tests
**Purpose**: Test output format conversions  
**Coverage**:
- Format mapping validation
- Content-Type negotiation
- Default format fallback
- MIME type correctness

---

## SUMMARY & DOCUMENTATION GAPS

### Currently Documented (in existing docs)
✅ Main architecture and data flow (README.md)
✅ Job analysis processor with AI scoring (README.md)
✅ Email routing and filters (README.md)
✅ Database schema (README.md)
✅ Gym schedule parsing (README.md)
✅ Deployment and operations (README.md, deployment.md)
✅ Development history (DEVELOPMENT_NOTES.md)
✅ Email classification system (DEVELOPMENT_NOTES.md)

### Missing Documentation (by priority)

#### CRITICAL - Core System Modules
1. **gdata.py** - Database abstraction layer
   - Locking behavior and error handling
   - JSON serialization details
   - Mode parameters and usage
   
2. **job_api.py** - REST API system
   - All endpoints and parameters
   - Output formats and schemas
   - Deployment options (WSGI, FastAPI, CLI)
   - Environment variables
   - Error handling and lock recovery
   
3. **newparser_jobserve.py** - Email parser and scorer
   - Email classification logic
   - AI scoring criteria and thresholds
   - Score field storage format
   - Cleanup policies (14-day jobs, 28-day applications)
   
4. **popit3.py** - POP3 synchronization
   - XOAUTH2 token setup
   - Netrc format for credentials
   - UIDL tracking and sync strategy
   - Email storage format (latin-1 encoding)
   - POP3-TLS configuration

#### IMPORTANT - Supporting Systems
5. **process_emails.py** - Email routing and orchestration
6. **job_analysis_report.py** - HTML report generation
7. **mylog.py** - Logging configuration
8. **applications_report.py** - Application tracking
9. **wsgi_dev_server.py** - Development server
10. **Email parsers** - All four HTML parsers (js_alert_parser, js_email, js_application_parser, dl_email)

#### NICE-TO-HAVE - Utilities
11. **reset_all_scores.py** - Full score reset
12. **reset_recent_analysis.py** - Recent score reset
13. **MyDavidLloydSchedule.py** - Gym schedule processor
14. **mailspool.py** - Maildir storage
15. **query_jobs.py** - Query compatibility shim
16. **tmp_cleanup.py** - Cleanup scheduler
17. **get_pop_refresh_token.py** - OAuth2 token manager
18. **analyze_jobs_openai.py** - Alternative analyzer
19. **Test suite** - Test infrastructure and coverage

---

## DOCUMENTATION EFFORT ESTIMATE

### By Priority Level

#### CRITICAL (4 modules) - ~16 hours
- gdata.py: 2-3 hours (database mechanics, locking, modes)
- job_api.py: 4-5 hours (endpoints, formats, deployment, caching)
- newparser_jobserve.py: 4-5 hours (parsing, classification, scoring)
- popit3.py: 4-5 hours (XOAUTH2, netrc, sync, storage)

**Total**: ~16 hours  
**Effort**: High - Complex systems with many integration points

#### IMPORTANT (6 modules) - ~12 hours
- process_emails.py: 2 hours (routing, WebDAV, error handling)
- job_analysis_report.py: 2-3 hours (report generation, cleanup, deployment)
- mylog.py: 0.5-1 hour (simple logging wrapper)
- applications_report.py: 1-2 hours (report generation)
- wsgi_dev_server.py: 0.5 hour (trivial)
- Email parsers (4 files): 3-4 hours (HTML parsing, regex patterns)

**Total**: ~12 hours  
**Effort**: Medium - Some complex, some simple

#### NICE-TO-HAVE (9+ modules) - ~8 hours
- Utility scripts: 2-3 hours (reset_all_scores, reset_recent_analysis, tmp_cleanup)
- MyDavidLloydSchedule.py: 2 hours
- mailspool.py: 1-2 hours
- Query/OAuth modules: 1-2 hours
- analyze_jobs_openai.py: 1 hour
- Test suite: 1-2 hours

**Total**: ~8 hours  
**Effort**: Low - Mostly straightforward utilities

#### GRAND TOTAL: ~36 hours
- **High Priority (CRITICAL+IMPORTANT)**: 28 hours
- **Low Priority (NICE-TO-HAVE)**: 8 hours

---

## RECOMMENDATIONS

### Phase 1 (Immediate)
Document the 4 CRITICAL modules first:
1. gdata.py - Foundation for all data operations
2. popit3.py - Core email sync engine
3. newparser_jobserve.py - Core job processing
4. job_api.py - Primary user-facing interface

Estimated: 16 hours  
Impact: Covers all essential system components

### Phase 2 (Important)
Document the 6 IMPORTANT modules:
- process_emails.py, job_analysis_report.py, email parsers, etc.

Estimated: 12 hours  
Impact: Completes main operational flow

### Phase 3 (Nice-to-have)
Document utilities as needed:
- Cleanup scripts, OAuth token management, test infrastructure

Estimated: 8 hours  
Impact: Better maintainability and extension

### Documentation Format Suggestion
- **API Modules** (gdata, job_api): Full API documentation with examples
- **Processing Modules** (popit3, newparser_jobserve): Algorithm/flow documentation
- **Utility Modules**: Simple docstrings + usage examples
- **Test Infrastructure**: Test plan and coverage matrix

### Missing Tools in Codebase
- **Configuration Management**: `webdav.critchley.biz` hardcoded in multiple files
- **API Documentation Tool**: Consider OpenAPI/Swagger for job_api
- **Database Migration Tool**: No versioning system for schema changes
- **Monitoring/Alerting**: No built-in health checks or alerts
- **Audit Logging**: Limited logging of data access/modifications

---

## APPENDIX: FILE REFERENCE TABLE

| File | Type | Lines | Priority | Status |
|------|------|-------|----------|--------|
| gdata.py | Core | 156 | CRITICAL | Undocumented |
| job_api.py | API | 530 | CRITICAL | Undocumented |
| newparser_jobserve.py | Processing | 321 | CRITICAL | Undocumented |
| popit3.py | Sync | 302 | CRITICAL | Undocumented |
| process_emails.py | Router | 130 | IMPORTANT | Undocumented |
| job_analysis_report.py | Report | 572 | IMPORTANT | Undocumented |
| js_alert_parser.py | Parser | 245 | IMPORTANT | Undocumented |
| js_email.py | Parser | 199 | IMPORTANT | Undocumented |
| js_application_parser.py | Parser | 141 | IMPORTANT | Undocumented |
| dl_email.py | Parser | 207 | IMPORTANT | Undocumented |
| mylog.py | Utility | 50 | IMPORTANT | Undocumented |
| applications_report.py | Report | 118 | IMPORTANT | Undocumented |
| wsgi_dev_server.py | Server | 18 | IMPORTANT | Undocumented |
| MyDavidLloydSchedule.py | Processor | 227 | Nice-to-have | Undocumented |
| mailspool.py | Storage | 123 | Nice-to-have | Undocumented |
| reset_all_scores.py | Utility | 35 | Nice-to-have | Undocumented |
| reset_recent_analysis.py | Utility | 76 | Nice-to-have | Undocumented |
| query_jobs.py | Compat | 145 | Nice-to-have | Undocumented |
| tmp_cleanup.py | Utility | 70 | Nice-to-have | Undocumented |
| get_pop_refresh_token.py | OAuth | 105 | Nice-to-have | Undocumented |
| analyze_jobs_openai.py | Analyzer | 447 | Nice-to-have | Undocumented |
| jobserve_parser.py | Compat | 40 | Nice-to-have | Undocumented |
| _newparser_jobserve.py | Legacy | 248 | Nice-to-have | Undocumented |
| scanmailheaders.py | Parser | 87 | Nice-to-have | Undocumented |

---

## CONCLUSION

The PopIt3 codebase has solid architecture documentation but lacks comprehensive module-level documentation for 23 Python files. The 4 CRITICAL modules (gdata, job_api, newparser_jobserve, popit3) are the foundation and should be documented first (~16 hours). The 6 IMPORTANT modules cover the operational pipeline (~12 hours). The remaining 13 NICE-TO-HAVE modules provide supporting functionality (~8 hours).

Total estimated documentation effort: **~36 hours** for complete coverage.

The system is well-architected with clear separation of concerns. Documentation should focus on:
1. Internal interfaces and contracts
2. Database schemas and storage formats
3. Configuration and environment variables
4. Error handling and recovery mechanisms
5. Deployment and operational procedures
6. Integration points between modules

