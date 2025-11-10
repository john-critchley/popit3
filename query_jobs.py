
# Compatibility shim for query_jobs
import os
shim_path = os.path.join(os.path.dirname(__file__), 'TO_DELETE', 'query_jobs.py')
with open(shim_path, 'r') as f:
    code = f.read()
exec(code, globals())

def get_job(message_id):
    """
    Get a specific job by Message-ID.
    Returns email_data dict or None if not found.
    """
    with get_database() as db:
        try:
            return db[message_id]
        except KeyError:
            return None

def get_all_jobs():
    """
    Get all job emails from the database.
    Returns list of (message_id, email_data) tuples.
    """
    results = []
    with get_database() as db:
        for key in db.keys():
            # Skip metadata keys
            if key.startswith('M:') or (key.isdigit() and len(key) == 8):
                continue
            
            try:
                email_data = db[key]
                # Only return entries that have job data
                if 'parsed' in email_data:
                    results.append((key, email_data))
            except (KeyError, TypeError):
                continue
    
    return results

def get_jobs_by_jobserve_ref(jobserve_ref):
    """
    Get all emails for a specific JobServe reference.
    Returns list of (message_id, email_data) tuples.
    """
    results = []
    with get_database() as db:
        for key in db.keys():
            # Skip metadata keys
            if key.startswith('M:') or (key.isdigit() and len(key) == 8):
                continue
            
            try:
                email_data = db[key]
                if email_data.get('jobserve_ref') == jobserve_ref:
                    results.append((key, email_data))
            except (KeyError, TypeError):
                continue
    
    return results

def update_job_llm_data(message_id, llm_data):
    """
    Update job record with LLM processing results.
    
    Args:
        message_id: Message-ID of the job email
        llm_data: Dict containing LLM results, e.g.:
                 {
                     'llm_score': 8.5,
                     'llm_explanation': 'Good match because...',
                     'cv_match': True,
                     'processed_date': '2025-10-17T14:30:00'
                 }
    
    Returns:
        True if successful, False if job not found
    """
    with get_database(mode='w') as db:
        try:
            email_data = db[message_id]
            
            # Add LLM data to the record
            if 'llm_results' not in email_data:
                email_data['llm_results'] = {}
            
            email_data['llm_results'].update(llm_data)
            
            # Save back to database
            db[message_id] = email_data
            return True
            
        except KeyError:
            return False

def get_jobs_needing_llm_processing():
    """
    Get jobs that haven't been processed by LLM yet.
    Returns list of (message_id, email_data) tuples.
    """
    results = []
    with get_database() as db:
        for key in db.keys():
            # Skip metadata keys
            if key.startswith('M:') or (key.isdigit() and len(key) == 8):
                continue
            
            try:
                email_data = db[key]
                # Only return entries that have job data but no LLM results
                if 'parsed' in email_data and 'llm_results' not in email_data:
                    results.append((key, email_data))
            except (KeyError, TypeError):
                continue
    
    return results

def search_jobs_by_keywords(keywords):
    """
    Search jobs by keywords in title, description, or location.
    Args:
        keywords: list of strings to search for
    Returns list of (message_id, email_data) tuples.
    """
    results = []
    all_jobs = get_all_jobs()
    
    for message_id, email_data in all_jobs:
        try:
            parsed = email_data.get('parsed', {})
            searchable_text = ' '.join([
                parsed.get('job_title', ''),
                parsed.get('description', ''),
                parsed.get('location', ''),
                parsed.get('employment_business', ''),
            ]).lower()
            
            # Check if any keyword matches
            if any(keyword.lower() in searchable_text for keyword in keywords):
                results.append((message_id, email_data))
        except (TypeError, AttributeError):
            continue
    
    return results