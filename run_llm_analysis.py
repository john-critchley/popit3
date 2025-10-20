#!/usr/bin/env python3
"""
Simple LLM Analysis Runner
Uses the existing job_analysis_script.py but forces it to process all jobs that need LLM analysis
"""

import sys
import os
sys.path.append('.')
import query_jobs
from job_analysis_script import JobAnalyzer

def main():
    print("=== LLM Job Analysis Runner ===")
    
    # Configuration
    CV_PATH = "~/Downloads/cv_llm_optimized.md"
    DB_PATH = "~/.js_new.gdbm"
    MODEL_REPO = "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF"
    MODEL_FILENAME = "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    
    # Get jobs that need processing
    jobs_needing_llm = query_jobs.get_jobs_needing_llm_processing()
    print(f"Found {len(jobs_needing_llm)} jobs needing LLM processing")
    
    if not jobs_needing_llm:
        print("No jobs need LLM processing. Exiting.")
        return
    
    # Initialize analyzer
    analyzer = JobAnalyzer()
    
    try:
        # Load data
        print("Loading CV and jobs...")
        analyzer.load_cv(CV_PATH)
        analyzer.load_jobs(DB_PATH)
        
        print(f"Loaded {len(analyzer.data.get('jobs', []))} total jobs from database")
        
        # Filter to only jobs that need LLM processing
        message_ids_needing_llm = {msg_id for msg_id, _ in jobs_needing_llm}
        original_jobs = analyzer.data['jobs']
        
        # Filter jobs to only those needing LLM processing
        jobs_to_analyze = []
        for job in original_jobs:
            # Check if this job needs LLM processing
            job_msg_id = job.get('headers', {}).get('Message-ID', '')
            if job_msg_id in message_ids_needing_llm:
                jobs_to_analyze.append(job)
        
        analyzer.data['jobs'] = jobs_to_analyze
        print(f"Filtered to {len(jobs_to_analyze)} jobs that need LLM analysis")
        
        if not jobs_to_analyze:
            print("No matching jobs found for LLM analysis")
            return
        
        # Setup model and analyze
        print("Setting up LLM model...")
        analyzer.setup_model(MODEL_REPO, MODEL_FILENAME)
        
        print("Starting LLM analysis...")
        updated_from_analysis = analyzer.analyze_jobs()
        
        print("Parsing LLM responses...")
        updated_from_parsing = analyzer.parse_responses()
        
        all_updates = updated_from_analysis | updated_from_parsing
        
        print(f"Saving {len(all_updates)} job updates to database...")
        analyzer.save_results(DB_PATH, all_updates)
        
        print("Analysis summary:")
        analyzer.print_summary()
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
    
    print("ANALYSIS COMPLETE!")

if __name__ == '__main__':
    main()