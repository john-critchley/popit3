"""
Example of how to integrate JobServe email processing with LLM analysis.
This shows the pattern for your CV matching and scoring system.
"""

import query_jobs
import datetime

def process_job_with_llm(message_id, email_data, cv_content):
    """
    Process a job with LLM to get CV matching score.
    This is just a skeleton - you'll implement the actual LLM calls.
    """
    
    # Extract job details for LLM input
    parsed = email_data.get('parsed', {})
    job_title = parsed.get('job_title', '')
    job_description = parsed.get('description', '')
    location = parsed.get('location', '')
    salary = parsed.get('salary', '')
    
    # Prepare prompt for LLM (this is just an example structure)
    prompt = f"""
    Job Title: {job_title}
    Location: {location}
    Salary: {salary}
    
    Job Description:
    {job_description}
    
    CV:
    {cv_content}
    
    Please rate this job match against the CV on a scale of 1-10 and explain why.
    Format your response as:
    SCORE: X.X
    EXPLANATION: [your explanation]
    """
    
    # TODO: Replace this with actual LLM call
    # llm_response = call_llama_llm(prompt)
    
    # Mock response for example
    llm_response = """
    SCORE: 8.5
    EXPLANATION: This is an excellent match because the candidate has strong Python experience 
    and the job requires similar technical skills. The location is also suitable.
    """
    
    # Parse LLM response
    lines = llm_response.strip().split('\n')
    score = None
    explanation = ""
    
    for line in lines:
        if line.startswith('SCORE:'):
            try:
                score = float(line.split(':', 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.startswith('EXPLANATION:'):
            explanation = line.split(':', 1)[1].strip()
    
    # Store results back to database
    llm_data = {
        'llm_score': score,
        'llm_explanation': explanation,
        'processed_date': datetime.datetime.now().isoformat(),
        'cv_version': 'v1.0',  # You might want to track CV versions
    }
    
    success = query_jobs.update_job_llm_data(message_id, llm_data)
    
    if success:
        print(f"Processed job {job_title}: Score {score}")
        return score, explanation
    else:
        print(f"Failed to update job {message_id}")
        return None, None

def process_all_pending_jobs(cv_content):
    """
    Process all jobs that haven't been analyzed by LLM yet.
    """
    pending_jobs = query_jobs.get_jobs_needing_llm_processing()
    
    print(f"Found {len(pending_jobs)} jobs needing LLM processing")
    
    for message_id, email_data in pending_jobs:
        try:
            score, explanation = process_job_with_llm(message_id, email_data, cv_content)
            
            # You could add logic here to automatically apply for high-scoring jobs
            if score and score >= 8.0:
                print(f"High score job: {email_data.get('parsed', {}).get('job_title', 'Unknown')}")
                # TODO: Generate cover letter and apply
                
        except Exception as e:
            print(f"Error processing {message_id}: {e}")

def example_usage():
    """Example of how to use the API."""
    
    # Load your CV content
    cv_content = """
    [Your CV content here - job history, skills, education, etc.]
    """
    
    # Process all pending jobs
    process_all_pending_jobs(cv_content)
    
    # Or get specific jobs
    recent_python_jobs = query_jobs.search_jobs_by_keywords(['python', 'developer'])
    print(f"Found {len(recent_python_jobs)} Python developer jobs")
    
    # Get a specific job for detailed analysis
    if recent_python_jobs:
        message_id, job_data = recent_python_jobs[0]
        job_details = query_jobs.get_job(message_id)
        print(f"Job details: {job_details.get('parsed', {}).get('job_title', 'Unknown')}")

if __name__ == '__main__':
    example_usage()