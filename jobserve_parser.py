import gdata
import os
import email
import email.utils
import email.header
import datetime
import random
import traceback
import json
import re

import js_email
from process_lock import retry_gdbm_operation, is_gdbm_locked_error
import analyze_jobs_openai

home = os.environ['HOME']

# TODO: Consider integrating JobServe RSS feeds for better real-time job flow
# RSS feeds provide structured data without email parsing overhead
# URL: https://www.jobserve.com/gb/en/can/savedsearches/rss
# Benefits: Real-time updates, no Message-ID parsing, configurable frequency
# Integration: Use feedparser library, RSS GUID as primary key like Message-ID

# Configuration: How often to check for old dates (1 in N chance)
OLD_DATE_CLEANUP_FREQUENCY = 5  # Change this to run cleanup less/more often

# Database configuration
DATABASE_FILENAME = '.js_new.gdbm'  # Using the migrated database


def extract_job_url_from_html(html_content):
    """Extract the actual job URL from JobServe email HTML content"""
    if not html_content:
        return None
        
    # Look for Outlook safelinks first (they're also valid and work)
    safelink_pattern = r'https://[^"]*\.safelinks\.protection\.outlook\.com/[^"]*'
    safelink_match = re.search(safelink_pattern, html_content)
    if safelink_match:
        return safelink_match.group()
    
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


def reprocess_job_urls(force_update=False):
    """
    Reprocess existing job records to extract and store job URLs.
    
    Args:
        force_update: If True, update URLs even if they already exist
    """
    print("Reprocessing job records to extract URLs...")
    
    database_path = os.path.expanduser(f'~/{DATABASE_FILENAME}')
    if not os.path.exists(database_path):
        print(f"Database not found: {database_path}")
        return
    
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    with gdata.gdata(gdbm_file=database_path, mode="w") as db:
        # Get all message IDs
        all_keys = list(db.keys())
        print(f"Found {len(all_keys)} records in database")
        
        for msg_id in all_keys:
            if msg_id.startswith('_'):  # Skip metadata keys
                continue
                
            try:
                email_data = db[msg_id]
                
                # Skip if URL already exists and not forcing update
                if not force_update and email_data.get('job_url'):
                    skipped_count += 1
                    continue
                
                # Find corresponding HTML file
                html_file_found = False
                html_dir = 'html'
                
                if os.path.exists(html_dir):
                    # Clean message ID for filename matching
                    clean_msg_id = msg_id.replace('<', '').replace('>', '')
                    
                    for filename in os.listdir(html_dir):
                        if clean_msg_id in filename and filename.endswith('.html'):
                            html_path = os.path.join(html_dir, filename)
                            
                            try:
                                with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    html_content = f.read()
                                    
                                job_url = extract_job_url_from_html(html_content)
                                
                                if job_url:
                                    # Update the record with the job URL
                                    email_data['job_url'] = job_url
                                    db[msg_id] = email_data
                                    updated_count += 1
                                    print(f"Updated {msg_id}: {job_url[:80]}...")
                                    html_file_found = True
                                    break
                                    
                            except (OSError, UnicodeDecodeError) as e:
                                print(f"Error reading HTML file {html_path}: {e}")
                                error_count += 1
                
                if not html_file_found:
                    print(f"No HTML file found for: {msg_id}")
                    
            except (OSError, KeyError, ValueError) as e:
                print(f"Error processing {msg_id}: {e}")
                error_count += 1
    
    print(f"\nReprocessing complete:")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors: {error_count}")



def decode_header_value(header_value):
    """Decode RFC 2047 encoded header values"""
    if not header_value:
        return ""
    
    decoded_parts = email.header.decode_header(header_value)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or 'utf-8', errors='replace'))
        else:
            result.append(part)
    return ''.join(result)

def extract_headers(msg):
    """
    Extract relevant headers from email message.
    Excludes: envelope From, X-* headers, Received, DKIM-Signature
    Decodes encoded headers and handles multi-value headers as lists.
    """
    headers = {}
    skip_headers = {'DKIM-Signature', 'Received'}
    
    for key, value in msg.items():
        # Skip unwanted headers
        if key.startswith('X-') or key in skip_headers:
            continue
            
        # Decode the header value
        decoded_value = decode_header_value(value)
        
        # Special handling for Date header
        if key == 'Date':
            try:
                decoded_value = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError) as e:
                print(f"ERROR: Could not parse date '{value}': {e}")
                # Return None to signal parsing failure
                return None
        
        # Handle multiple occurrences of same header
        if key in headers:
            # Convert to list if not already
            if not isinstance(headers[key], list):
                headers[key] = [headers[key]]
            headers[key].append(decoded_value)
        else:
            headers[key] = decoded_value
    
    return headers

def get_date_key(sent_datetime):
    """Convert datetime to YYYYMMDD format for date set keys"""
    if isinstance(sent_datetime, datetime.datetime):
        return sent_datetime.strftime('%Y%m%d')
    return None

def serialize_datetime(obj):
    """Convert datetime objects to ISO strings for JSON storage"""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_datetime(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_datetime(item) for item in obj]
    return obj

def load_metadata_set(db, key):
    """Load a metadata set from gdata, return empty set if not exists"""
    try:
        value = db[key]
        if isinstance(value, list):
            return set(value)
        return set()
    except KeyError:
        return set()

def save_metadata_set(db, key, value_set):
    """Save a metadata set to gdata, delete key if empty"""
    if value_set:
        db[key] = list(value_set)
    else:
        try:
            del db[key]
        except KeyError:
            pass

def cleanup_old_emails(db, cutoff_date, broken_out, parsed, deleted):
    """
    Clean up emails older than cutoff_date that are in both broken_out and parsed.
    Returns list of UIDLs to delete.
    """
    to_delete = []
    cutoff_key = cutoff_date.strftime('%Y%m%d')
    
    # Find all date keys older than cutoff
    all_keys = db.keys()
    date_keys = [k for k in all_keys if k.isdigit() and len(k) == 8 and k < cutoff_key]
    
    if not date_keys:
        return to_delete
    
    print(f"Found {len(date_keys)} date sets older than {cutoff_key}")
    
    for date_key in date_keys:
        date_set = load_metadata_set(db, date_key)
        message_ids_to_remove = []
        
        for message_id in date_set:
            # Check if in both broken_out and parsed
            if message_id in broken_out and message_id in parsed:
                try:
                    email_data = db[message_id]
                    uidl = email_data.get('UIDL')
                    js_ref = email_data.get('jobserve_ref', 'unknown')
                    
                    if uidl:
                        print(f"CLEANUP: Marking for deletion: {message_id} (JS ref={js_ref}, UIDL={uidl}, date={date_key})")
                        to_delete.append(uidl)
                        deleted.add(message_id)
                        broken_out.discard(message_id)
                        parsed.discard(message_id)
                        message_ids_to_remove.append(message_id)
                except KeyError:
                    print(f"Warning: {message_id} in date set but not in database")
                    message_ids_to_remove.append(message_id)
        
        # Remove cleaned message IDs from date set
        for message_id in message_ids_to_remove:
            date_set.discard(message_id)
        
        save_metadata_set(db, date_key, date_set)
    
    return to_delete

def process_js_mails(segregated_js_emails):
    """
    Process JobServe emails and store to gdata database.
    Returns list of UIDLs that can be deleted from mail server.
    Uses extended locking and retry logic for database safety.
    """
    gdbm_path = os.path.join(home, DATABASE_FILENAME)
    
    def _process_with_extended_lock():
        """Internal function that holds the database lock for the entire operation"""
        to_delete_uidls = []
        newly_processed_message_ids = []  # Track new jobs for LLM processing

        with gdata.gdata(gdbm_path) as db:
            # Load metadata sets
            broken_out = load_metadata_set(db, 'M:broken_out')
            parsed = load_metadata_set(db, 'M:parsed')
            deleted = load_metadata_set(db, 'M:deleted')

            # Process each email while DB is open
            for uidl, msg in segregated_js_emails:
                # Convert UIDL to int if it's bytes
                if isinstance(uidl, bytes):
                    uidl = int(uidl.decode('ascii'))
                elif isinstance(uidl, str):
                    uidl = int(uidl)

                msg_id = msg['Message-ID']
                print(f'\nProcessing: {msg_id}')

                subject = msg.get('Subject', '')
                decoded_subject = decode_header_value(subject)
                print(f'Subject: {decoded_subject}')

                # Determine job type and filter for JobServe job emails
                job_type = None
                if 'job suggestion' in decoded_subject.lower():
                    job_type = 'suggestion'
                    print(f"Processing JOB SUGGESTION: {decoded_subject}")
                elif 'job alert' in decoded_subject.lower():
                    job_type = 'alert'
                    print(f"Processing JOB ALERT: {decoded_subject}")
                else:
                    print(f"Skipping non-job email: {decoded_subject}")
                    continue

                # Extract and process headers
                headers = extract_headers(msg)

                # If date parsing failed, headers will be None
                if headers is None:
                    print("ERROR: Failed to parse Date header, cannot process this email properly")
                    continue  # Skip to next email - can't store without valid date

                sent_date = headers.get('Date')

                if sent_date:
                    print(f'Date: {sent_date}')
                else:
                    print("Warning: No Date header found")

                # Save HTML and parse
                parsed_job = None
                html_saved = False

                for part in msg.walk():
                    if part.is_multipart():
                        continue

                    if part.get_content_type() == "text/html":
                        # Save HTML file
                        fn = '.'.join([decode_header_value(msg.get(h, '')) 
                                      for h in ['Subject', 'Message-ID']] + [str(uidl), 'html'])
                        fn = 'html' + os.sep + '_'.join(fn.split(os.sep))

                        try:
                            payload = part.get_payload(decode=True)
                            print(f"Save HTML to: {fn}")

                            os.makedirs('html', exist_ok=True)
                            with open(fn, 'wb') as fd:
                                fd.write(payload)

                            if sent_date and isinstance(sent_date, datetime.datetime):
                                mod_timestamp = sent_date.timestamp()
                                os.utime(fn, (mod_timestamp, mod_timestamp))

                            html_saved = True
                        except (OSError, IOError, UnicodeDecodeError) as e:
                            print(f"ERROR: Failed to save HTML file: {e}")
                            traceback.print_exc()
                            continue

                        # Parse the email
                        try:
                            charset = part.get_content_charset() or 'utf-8'
                            html_content = payload.decode(charset)
                            parsed_job = js_email.parse_jobserve_email_part(html_content)
                            print(f"Parsed job: {parsed_job.get('job_title', 'Unknown')}")

                            # Extract job URL from HTML
                            job_url = extract_job_url_from_html(html_content)
                            if job_url:
                                print(f"Extracted job URL: {job_url[:80]}...")

                            # Save parsed JSON
                            base_fn = '.'.join([decode_header_value(msg.get(h, '')) 
                                               for h in ['Subject', 'Message-ID']] + [str(uidl)])
                            base_fn = '_'.join(base_fn.split(os.sep))
                            parsed_fn = 'parsed' + os.sep + base_fn + '.json'

                            os.makedirs('parsed', exist_ok=True)
                            with open(parsed_fn, 'w', encoding='utf-8') as fd:
                                json.dump(serialize_datetime(parsed_job), fd, indent=2, ensure_ascii=False)

                            if sent_date and isinstance(sent_date, datetime.datetime):
                                os.utime(parsed_fn, (mod_timestamp, mod_timestamp))

                        except (UnicodeDecodeError, KeyError, AttributeError, ValueError) as e:
                            print(f"ERROR: Failed to parse email: {e}")
                            traceback.print_exc()
                            parsed_job = None
                            job_url = None

                        break  # Only process first HTML part

                if not html_saved:
                    print("Warning: No HTML part found in email")
                    continue

                # Get JobServe ref for metadata/indexing
                js_ref = parsed_job.get('ref') if parsed_job else None

                # Use Message-ID as primary key (guaranteed unique by RFC 5322)
                primary_key = msg_id

                # Prepare data to store - gdata class handles JSON serialization
                email_data = {
                    'headers': serialize_datetime(headers),
                    'UIDL': uidl,
                    'jobserve_ref': js_ref,  # Store JobServe ref as metadata
                    'job_type': job_type,    # Track whether this is 'suggestion' or 'alert'
                }
                
                # Add job URL if extracted during current processing
                if job_url:
                    email_data['job_url'] = job_url

                if parsed_job:
                    email_data['parsed'] = serialize_datetime(parsed_job)

                # Check for existing entry (should be rare with Message-ID as key)
                try:
                    existing_data = db[primary_key]
                    existing_uidl = existing_data.get('UIDL')
                    existing_job_type = existing_data.get('job_type')

                    # If already processed with same UIDL and job_type present, skip reprocessing
                    if existing_uidl == uidl and existing_job_type is not None:
                        print(f"WARNING: Duplicate processing of same email (Message-ID={primary_key}) - already has job_type '{existing_job_type}'")
                        continue
                    else:
                        # Either different UIDL (rare) or missing job_type (older entry) - allow update
                        print(f"INFO: Reprocessing/Updating existing entry (existing_uidl={existing_uidl}, existing_job_type={existing_job_type})")
                except KeyError:
                    # No existing entry, this is normal
                    pass

                # Check if job URL is missing and try to extract it from HTML file
                if 'job_url' not in email_data or not email_data['job_url']:
                    print("Job URL missing, attempting to extract from HTML file...")
                    
                    # Find corresponding HTML file
                    html_dir = 'html'
                    if os.path.exists(html_dir):
                        clean_msg_id = primary_key.replace('<', '').replace('>', '')
                        
                        for filename in os.listdir(html_dir):
                            if clean_msg_id in filename and filename.endswith('.html'):
                                html_path = os.path.join(html_dir, filename)
                                
                                try:
                                    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        html_content = f.read()
                                        
                                    extracted_url = extract_job_url_from_html(html_content)
                                    
                                    if extracted_url:
                                        email_data['job_url'] = extracted_url
                                        print(f"Extracted job URL: {extracted_url[:80]}...")
                                    else:
                                        print("No job URL found in HTML file")
                                    break
                                        
                                except Exception as e:
                                    print(f"Error reading HTML file {html_path}: {e}")
                    else:
                        print("HTML directory not found")

                # Store to gdata (it handles JSON serialization automatically)
                try:
                    db[primary_key] = email_data
                    print(f"Stored to gdata with key: {primary_key}")
                    if js_ref:
                        print(f"  JobServe ref: {js_ref}")
                    if email_data.get('job_url'):
                        print(f"  Job URL: {email_data['job_url'][:50]}...")
                    
                    # Track newly processed job for LLM analysis
                    newly_processed_message_ids.append(primary_key)
                    
                except (OSError, IOError, KeyError) as e:
                    print(f"ERROR: Failed to store to gdata: {e}")
                    traceback.print_exc()
                    continue

                # Update metadata sets - use Message-ID for tracking
                broken_out.add(primary_key)
                if parsed_job:
                    parsed.add(primary_key)

                # Add to date set
                if sent_date and isinstance(sent_date, datetime.datetime):
                    date_key = get_date_key(sent_date)
                    if date_key:
                        date_set = load_metadata_set(db, date_key)
                        date_set.add(primary_key)
                        save_metadata_set(db, date_key, date_set)

        # All metadata operations need a fresh DB context to avoid GDBM iterator conflicts
        week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
        week_ago_key = week_ago.strftime('%Y%m%d')
        
        print(f"\nPerforming cleanup operations in fresh DB context...")
        
        # Open a fresh database context for all metadata operations
        with gdata.gdata(gdbm_path) as cleanup_db:
            # Reload and update metadata sets in cleanup context  
            cleanup_broken_out = load_metadata_set(cleanup_db, 'M:broken_out')
            cleanup_parsed = load_metadata_set(cleanup_db, 'M:parsed')
            cleanup_deleted = load_metadata_set(cleanup_db, 'M:deleted')
            
            # Add newly processed items to metadata sets
            cleanup_broken_out.update(broken_out)
            cleanup_parsed.update(parsed)
            cleanup_deleted.update(deleted)
            
            # Save updated metadata sets first
            save_metadata_set(cleanup_db, 'M:broken_out', cleanup_broken_out)
            save_metadata_set(cleanup_db, 'M:parsed', cleanup_parsed) 
            save_metadata_set(cleanup_db, 'M:deleted', cleanup_deleted)
            
            print(f"Checking for emails from {week_ago_key} to clean up...")
            try:
                week_ago_uidls = cleanup_old_emails(cleanup_db, week_ago, cleanup_broken_out, cleanup_parsed, cleanup_deleted)
                to_delete_uidls.extend(week_ago_uidls)
                print(f"Added {len(week_ago_uidls)} UIDLs from week cleanup to deletion list")
            except Exception as e:
                print(f"WARNING: cleanup_old_emails failed: {e}")
                traceback.print_exc()

            # Occasionally check for even older dates
            if random.randint(0, OLD_DATE_CLEANUP_FREQUENCY - 1) < 2:
                print(f"Performing occasional cleanup of dates older than {week_ago_key}...")
                older_date = week_ago - datetime.timedelta(days=1)
                try:
                    older_uidls = cleanup_old_emails(cleanup_db, older_date, cleanup_broken_out, cleanup_parsed, cleanup_deleted)
                    to_delete_uidls.extend(older_uidls)
                    print(f"Added {len(older_uidls)} UIDLs from older cleanup to deletion list")
                except Exception as e:
                    print(f"WARNING: older cleanup failed: {e}")
                    traceback.print_exc()

            # Save final metadata sets after cleanup
            save_metadata_set(cleanup_db, 'M:broken_out', cleanup_broken_out)
            save_metadata_set(cleanup_db, 'M:parsed', cleanup_parsed)
            save_metadata_set(cleanup_db, 'M:deleted', cleanup_deleted)

        print(f"\nProcessing complete. {len(to_delete_uidls)} emails marked for deletion.")
        return to_delete_uidls, newly_processed_message_ids    # Return both UIDLs and new message IDs
    
    try:
        to_delete_uidls, newly_processed_message_ids = retry_gdbm_operation(_process_with_extended_lock, max_timeout=300)  # 5 minutes
        print("to_delete_uidls:", *to_delete_uidls)
        
        # Process newly downloaded jobs with LLM analysis if any (outside database lock)
        if newly_processed_message_ids:
            print(f"\nStarting LLM analysis for {len(newly_processed_message_ids)} newly processed JobServe jobs...")
            try:
                # Call LLM processor with the newly processed message IDs
                success = analyze_jobs_openai.main(argv=[], message_ids=newly_processed_message_ids)
                if success:
                    print("JobServe LLM analysis completed successfully")
                else:
                    print("JobServe LLM analysis completed with errors")
            except (OSError, ConnectionError, TimeoutError, ValueError) as e:
                print(f"JobServe LLM analysis failed: {e}")
                traceback.print_exc()
        else:
            print("No new JobServe jobs require LLM analysis in this batch")
        
        return to_delete_uidls
    except OSError as e:
        if is_gdbm_locked_error(e):
            print(f"INFO: Database locked after 5 minutes - another process likely running: {e}")
            print("Following design philosophy: next cron run will handle any missed emails.")
            return []  # Return empty list so email server doesn't delete emails
        else:
            # Re-raise other OSErrors - these indicate real problems (file permissions, disk space, etc.)
            raise
