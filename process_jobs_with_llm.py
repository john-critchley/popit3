#!/usr/bin/env python3
"""
LLM Job Processing Script

This script:
1. Picks N jobs from the job store that need LLM processing
2. Marks them as being processed in the database
3. Submits them to the LLM server for analysis
4. Monitors job status and updates database when complete
5. Downloads and stores LLM results in the job records

Usage:
    python3 process_jobs_with_llm.py [--count N] [--cv-file path] [--server-url url]
"""

import argparse
import json
import os
import sys
import time
import traceback
import requests
import subprocess
from datetime import datetime
# Add current directory to path for local imports
sys.path.append('.')
import query_jobs
import gdata


class LLMJobProcessor:
    """Handles LLM job processing workflow"""
    
    def __init__(self, server_url="http://localhost:8080", cv_file=None):
        self.server_url = server_url
        self.cv_content = self.load_cv(cv_file or "cv_llm_optimized.md")
        
    def load_cv(self, cv_file):
        """Load CV content from file"""
        try:
            with open(cv_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: CV file not found: {cv_file}")
            sys.exit(1)
        except PermissionError:
            print(f"Error: Permission denied reading CV file: {cv_file}")
            sys.exit(1)
        except UnicodeDecodeError as e:
            print(f"Error: Cannot decode CV file {cv_file}: {e}")
            sys.exit(1)
    
    def get_jobs_for_processing(self, count):
        """
        Get jobs that need LLM processing.
        Returns list of (message_id, email_data) tuples.
        """
        jobs = query_jobs.get_jobs_needing_llm_processing()
        
        # Filter out jobs already being processed
        available_jobs = []
        for message_id, email_data in jobs:
            llm_status = email_data.get('llm_results', {}).get('status')
            if llm_status != 'processing':
                available_jobs.append((message_id, email_data))
        
        return available_jobs[:count]
    
    def mark_job_processing(self, message_id):
        """Mark job as being processed in database"""
        llm_data = {
            'status': 'processing',
            'processing_started': datetime.now().isoformat(),
            'server_job_id': None
        }
        return query_jobs.update_job_llm_data(message_id, llm_data)
    
    def create_llm_request(self, email_data):
        """
        Create LLM request payload from job email data.
        """
        parsed = email_data.get('parsed', {})
        
        # Extract job information
        job_title = parsed.get('job_title', 'Unknown Job')
        job_description = parsed.get('description', '')
        company = parsed.get('employment_business', '')
        location = parsed.get('location', '')
        salary = parsed.get('salary', '')
        
        # Create comprehensive job description
        job_info = f"""
Job Title: {job_title}
Company: {company}
Location: {location}
Salary: {salary}

Job Description:
{job_description}
        """.strip()
        
        # Create LLM prompt
        task_description = """
Please analyze how well this CV matches the job description. Your task is to:

1. Give a score from 0 to 10 (inclusive) indicating how likely this CV holder would be successful if they applied for this job.
2. Provide a detailed explanation for your score, covering:
   - Relevant skills and experience matches
   - Any gaps or concerns
   - Overall fit assessment

Score Guidelines:
- 0-2: Very poor match, significant skill gaps
- 3-4: Poor match, major concerns  
- 5-6: Average match, some relevant experience
- 7-8: Good match, strong relevant experience
- 9-10: Excellent match, ideal candidate

Please respond in JSON format with:
{
    "score": <number 0-10>,
    "explanation": "<detailed explanation>",
    "key_matches": ["<list of key matching skills/experience>"],
    "concerns": ["<list of potential concerns or gaps>"]
}
        """.strip()
        
        return {
            "task_description": task_description,
            "cv_content": self.cv_content,
            "job_description": job_info,
            "job_title": job_title,
            "message_id": email_data.get('headers', {}).get('Message-ID', '')
        }
    
    def submit_job_to_llm(self, request_data):
        """
        Submit job to LLM server.
        Returns server job ID if successful, None if failed.
        """
        try:
            response = requests.post(
                f"{self.server_url}/job",
                json=request_data,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get('job_id')
            
        except requests.exceptions.RequestException as e:
            print(f"Network error submitting job to LLM: {e}")
            return None
        except (ValueError, KeyError) as e:
            print(f"Error parsing LLM server response: {e}")
            print("Full traceback:")
            traceback.print_exc()
            return None
    
    def check_job_status(self, server_job_id):
        """
        Check job status on LLM server.
        Returns job data if complete, None if still processing or error.
        """
        try:
            response = requests.get(
                f"{self.server_url}/job/{server_job_id}",
                timeout=10
            )
            response.raise_for_status()
            
            job_data = response.json()
            if job_data.get('status') == 'completed':
                return job_data
            
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"Network error checking job status: {e}")
            return None
        except (ValueError, KeyError) as e:
            print(f"Error parsing job status response: {e}")
            print("Full traceback:")
            traceback.print_exc()
            return None
    
    def update_job_with_results(self, message_id, server_job_data):
        """Update job database record with LLM results"""
        try:
            # Extract LLM output
            output = server_job_data.get('output', '')
            
            # Try to parse JSON output
            llm_results = {}
            try:
                if output.strip():
                    # Look for JSON in the output
                    json_start = output.find('{')
                    json_end = output.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = output[json_start:json_end]
                        llm_results = json.loads(json_str)
            except json.JSONDecodeError:
                # If JSON parsing fails, store raw output
                llm_results = {'raw_output': output}
            
            # Prepare update data
            update_data = {
                'status': 'completed',
                'processing_completed': datetime.now().isoformat(),
                'server_job_id': server_job_data.get('id'),
                'llm_results': llm_results,
                'raw_output': output,
                'processing_time': server_job_data.get('completed')
            }
            
            return query_jobs.update_job_llm_data(message_id, update_data)
            
        except (OSError, ValueError, KeyError) as e:
            print(f"Error updating job {message_id} with results: {e}")
            print("Full traceback:")
            traceback.print_exc()
            return False
    
    def mark_job_failed(self, message_id, error):
        """Mark job as failed in database"""
        error_data = {
            'status': 'failed',
            'processing_completed': datetime.now().isoformat(),
            'error': error
        }
        return query_jobs.update_job_llm_data(message_id, error_data)
    
    def process_batch(self, count=5, monitor_interval=30):
        """
        Process a batch of jobs with LLM analysis.
        
        Args:
            count: Number of jobs to process
            monitor_interval: Seconds between status checks
            
        Returns:
            Dict with processing statistics
        """
        print(f"Starting LLM job processing batch (count={count})")
        
        # Get jobs for processing
        jobs = self.get_jobs_for_processing(count)
        if not jobs:
            print("No jobs available for LLM processing")
            return {'processed': 0, 'submitted': 0, 'errors': 0}
        
        print(f"Found {len(jobs)} jobs for processing")
        
        submitted_jobs = {}  # message_id -> server_job_id
        stats = {'processed': 0, 'submitted': 0, 'errors': 0}
        
        # Submit jobs to LLM server
        for message_id, email_data in jobs:
            try:
                # Mark as processing
                if not self.mark_job_processing(message_id):
                    print(f"Failed to mark job {message_id} as processing")
                    stats['errors'] += 1
                    continue
                
                # Create LLM request
                request_data = self.create_llm_request(email_data)
                
                # Submit to server
                server_job_id = self.submit_job_to_llm(request_data)
                if server_job_id:
                    submitted_jobs[message_id] = server_job_id
                    stats['submitted'] += 1
                    
                    # Update database with server job ID
                    query_jobs.update_job_llm_data(message_id, {'server_job_id': server_job_id})
                    
                    job_title = email_data.get('parsed', {}).get('job_title', 'Unknown')
                    print(f"Submitted job: {job_title} (ID: {server_job_id})")
                else:
                    self.mark_job_failed(message_id, "Failed to submit to LLM server")
                    stats['errors'] += 1
                    
            except Exception as e:
                print(f"Error processing job {message_id}: {e}")
                print("Full traceback:")
                traceback.print_exc()
                self.mark_job_failed(message_id, f"{e}")
                stats['errors'] += 1
        
        # Monitor submitted jobs
        print(f"\nMonitoring {len(submitted_jobs)} submitted jobs...")
        
        while submitted_jobs:
            # Get system load average
            try:
                uptime_result = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
                load_info = uptime_result.stdout.strip() if uptime_result.returncode == 0 else "Load info unavailable"
            except:
                load_info = "Load info unavailable"
            
            print(f"Checking status of {len(submitted_jobs)} jobs... ({load_info})")
            
            completed = []
            for message_id, server_job_id in list(submitted_jobs.items()):
                job_data = self.check_job_status(server_job_id)
                
                if job_data:
                    # Job completed
                    if self.update_job_with_results(message_id, job_data):
                        stats['processed'] += 1
                        completed.append(message_id)
                        
                        job_title = job_data.get('data', {}).get('job_title', 'Unknown')
                        print(f"Completed: {job_title}")
                    else:
                        self.mark_job_failed(message_id, "Failed to update job with results")
                        stats['errors'] += 1
                        completed.append(message_id)
            
            # Remove completed jobs
            for message_id in completed:
                del submitted_jobs[message_id]
            
            if submitted_jobs:
                print(f"Waiting {monitor_interval}s for {len(submitted_jobs)} jobs to complete... (Load: {load_info.split('load average:')[-1].strip() if 'load average:' in load_info else 'unknown'})")
                time.sleep(monitor_interval)
        
        print(f"\nBatch processing complete: {stats}")
        return stats

    def process_message_ids(self, message_ids, time_limit_seconds):
        """
        Process specific message IDs with time limit.
        
        Args:
            message_ids: List of message IDs to process
            time_limit_seconds: Maximum processing time in seconds
            
        Returns:
            Dict with processing statistics
        """
        print(f"Starting LLM job processing for {len(message_ids)} specific jobs (time limit: {time_limit_seconds//60} minutes)")
        
        start_time = time.time()
        submitted_jobs = {}  # message_id -> server_job_id
        stats = {'processed': 0, 'submitted': 0, 'errors': 0}
        
        # Process each message ID, checking time limit before starting each job
        for message_id in message_ids:
            # Check time limit before starting next job
            elapsed_time = time.time() - start_time
            if elapsed_time >= time_limit_seconds:
                print(f"Time limit reached ({elapsed_time:.1f}s >= {time_limit_seconds}s), stopping before processing {message_id}")
                break
                
            try:
                # Get job data from database
                email_data = query_jobs.get_job_by_message_id(message_id)
                if not email_data:
                    print(f"Job {message_id} not found in database")
                    stats['errors'] += 1
                    continue
                
                # Check if job already has LLM results
                if email_data.get('llm_results'):
                    print(f"Job {message_id} already has LLM results, skipping")
                    continue
                
                # Mark as processing
                if not self.mark_job_processing(message_id):
                    print(f"Failed to mark job {message_id} as processing")
                    stats['errors'] += 1
                    continue
                
                # Create LLM request
                request_data = self.create_llm_request(message_id, email_data)
                if not request_data:
                    self.mark_job_failed(message_id, "Failed to create LLM request")
                    stats['errors'] += 1
                    continue
                
                # Submit to LLM server
                server_job_id = self.submit_job_to_llm(request_data)
                if server_job_id:
                    submitted_jobs[message_id] = server_job_id
                    stats['submitted'] += 1
                    
                    job_title = request_data.get('job_title', 'Unknown')
                    print(f"Submitted: {job_title} (job_id: {server_job_id})")
                else:
                    self.mark_job_failed(message_id, "Failed to submit to LLM server")
                    stats['errors'] += 1
                    
            except Exception as e:
                print(f"Error processing job {message_id}: {e}")
                traceback.print_exc()
                self.mark_job_failed(message_id, f"Processing error: {e}")
                stats['errors'] += 1
        
        # Monitor submitted jobs until completion or time limit
        monitor_interval = 30
        while submitted_jobs:
            elapsed_time = time.time() - start_time
            if elapsed_time >= time_limit_seconds:
                print(f"Time limit reached during monitoring, stopping")
                break
                
            print(f"Monitoring {len(submitted_jobs)} jobs... (elapsed: {elapsed_time:.1f}s)")
            
            completed = []
            for message_id, server_job_id in list(submitted_jobs.items()):
                job_data = self.check_job_status(server_job_id)
                
                if job_data:
                    # Job completed
                    if self.update_job_with_results(message_id, job_data):
                        stats['processed'] += 1
                        completed.append(message_id)
                        
                        job_title = job_data.get('data', {}).get('job_title', 'Unknown')
                        print(f"Completed: {job_title}")
                    else:
                        self.mark_job_failed(message_id, "Failed to update job with results")
                        stats['errors'] += 1
                        completed.append(message_id)
            
            # Remove completed jobs
            for message_id in completed:
                del submitted_jobs[message_id]
            
            if submitted_jobs:
                time.sleep(min(monitor_interval, time_limit_seconds - elapsed_time))
        
        # Mark any remaining jobs as failed due to timeout
        for message_id in submitted_jobs:
            self.mark_job_failed(message_id, "Timeout during processing")
            stats['errors'] += 1
        
        print(f"\nMessage ID processing complete: {stats}")
        return stats


def main(argv=None, message_ids=None):
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description="Process jobs with LLM analysis")
    parser.add_argument('--count', '-c', type=int, default=5,
                        help='Number of jobs to process (default: 5)')
    parser.add_argument('--cv-file', '-f', type=str, default='cv_llm_optimized.md',
                        help='Path to CV file (default: cv_llm_optimized.md)')
    parser.add_argument('--server-url', '-s', type=str, default='http://localhost:8080',
                        help='LLM server URL (default: http://localhost:8080)')
    parser.add_argument('--monitor-interval', '-m', type=int, default=30,
                        help='Status check interval in seconds (default: 30)')
    parser.add_argument('--time-limit', '-t', type=int, default=10,
                        help='Time limit in minutes (default: 10)')
    
    args = parser.parse_args(argv)
    
    # Verify CV file exists
    if not os.path.exists(args.cv_file):
        print(f"Error: CV file '{args.cv_file}' not found")
        sys.exit(1)
    
    # Verify LLM server is accessible
    try:
        response = requests.get(f"{args.server_url}/list", timeout=5)
        response.raise_for_status()
        print(f"LLM server accessible at {args.server_url}")
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to LLM server at {args.server_url}")
        print("Is the server running?")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"Error: Timeout connecting to LLM server at {args.server_url}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: Request failed to LLM server at {args.server_url}: {e}")
        sys.exit(1)
    
    # Create processor and run batch
    processor = LLMJobProcessor(args.server_url, args.cv_file)
    
    try:
        if message_ids:
            # Check if we actually have message IDs to process
            if not message_ids:
                print("No message IDs provided for LLM processing")
                return True  # Not an error, just nothing to do
            
            # Process specific message IDs with time limit
            stats = processor.process_message_ids(message_ids, args.time_limit * 60)
        else:
            # Process batch with count limit
            stats = processor.process_batch(args.count, args.monitor_interval)
        
        print(f"\nLLM processing statistics:")
        print(f"  Jobs submitted for analysis: {stats['submitted']}")
        print(f"  Jobs completed successfully: {stats['processed']}")
        print(f"  Jobs with errors: {stats['errors']}")
        
        # Return success if any jobs were processed successfully or nothing to process
        success = stats['processed'] > 0 or stats['submitted'] == 0
        if stats['submitted'] == 0:
            print("No jobs required LLM processing")
        elif success:
            print("LLM job processing completed successfully")
        else:
            print("LLM job processing failed - no jobs completed successfully")
        return success
        
    except Exception as e:
        print(f"Unexpected error in LLM job processing: {e}")
        print("This indicates a programming bug that needs investigation:")
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)