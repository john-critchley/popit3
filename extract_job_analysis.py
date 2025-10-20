#!/usr/bin/env python3
"""
Extract Job Analysis Results

Extracts all job analysis results from the database into a readable text report.
Shows job details, LLM scores, analysis text, and statistics by model used.

Usage:
    python3 extract_job_analysis.py [--output filename.txt]
"""

import argparse
import sys
import os
from datetime import datetime

# Add current directory to path for local imports
sys.path.append('.')
import query_jobs


def extract_job_analysis_results(output_file=None, sort_by_score=False):
    """Extract all job analysis results and print to stdout"""
    
    # Get all jobs and filter for those with LLM results
    all_jobs = query_jobs.get_all_jobs()
    jobs_with_llm = []
    
    for message_id, email_data in all_jobs:
        if 'llm_results' in email_data and email_data['llm_results']:
            jobs_with_llm.append((message_id, email_data, email_data['llm_results']))
    
    if not jobs_with_llm:
        try:
            print('No jobs found with LLM results')
        except BrokenPipeError:
            pass
        return None
    
    # Group by model used for statistics
    model_counts = {}
    score_by_model = {}
    
    for _, _, llm_data in jobs_with_llm:
        model = llm_data.get('model_used', 'unknown')
        model_counts[model] = model_counts.get(model, 0) + 1
        
        # Track scores by model
        score = llm_data.get('llm_score')
        if score is not None:
            if model not in score_by_model:
                score_by_model[model] = []
            score_by_model[model].append(score)
    
    # Print the report to stdout with pipe handling
    def safe_print(*args, **kwargs):
        try:
            print(*args, **kwargs)
        except BrokenPipeError:
            # Exit gracefully when pipe is closed (e.g., head command)
            sys.exit(0)
    
    safe_print('JOB ANALYSIS RESULTS REPORT\n')
    safe_print(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    safe_print(f'Total jobs analyzed: {len(jobs_with_llm)}\n')
    
    # Statistics by model
    safe_print('ANALYSIS BY MODEL:\n')
    for model, count in sorted(model_counts.items(), key=lambda x: x[0] or 'zzz'):
        safe_print(f'  {model}: {count} jobs', end='')
        if model in score_by_model:
            scores = score_by_model[model]
            avg_score = sum(scores) / len(scores)
            safe_print(f' (avg score: {avg_score:.1f})')
        else:
            safe_print()
    safe_print('\n')
    
    # Sort jobs - by score if requested, otherwise by email date (newest first)
    if sort_by_score:
        # Sort by score (highest first), then by title
        jobs_sorted = sorted(jobs_with_llm, 
                           key=lambda x: (-(x[2].get('llm_score') or 0), 
                                        x[1].get('parsed', {}).get('job_title', '')))
    else:
        # Sort by email date (newest first), using message_id as fallback
        def get_email_date(job_tuple):
            _, job_data, _ = job_tuple
            date_str = job_data.get('headers', {}).get('Date', '')
            # Return date string for sorting (ISO format sorts correctly)
            return date_str or '1900-01-01'
        
        jobs_sorted = sorted(jobs_with_llm, key=get_email_date, reverse=True)
    
    # Individual job details
    for i, (message_id, job_data, llm_data) in enumerate(jobs_sorted, 1):
        safe_print(f'JOB #{i}: {message_id}\n')
        
        # Job details
        parsed = job_data.get('parsed', {})
        job_title = parsed.get('job_title', 'Unknown Job')
        company = parsed.get('employment_business', 'Unknown Company')
        location = parsed.get('location', 'Unknown Location')
        salary = parsed.get('salary', 'Not specified')
        job_type = job_data.get('job_type', 'unknown')
        
        safe_print(f'Title: {job_title}')
        safe_print(f'Company: {company}')
        safe_print(f'Location: {location}')
        safe_print(f'Salary: {salary}')
        safe_print(f'Type: {job_type}\n')
        
        # LLM analysis details
        safe_print(f'ANALYSIS DETAILS:')
        safe_print(f'Status: {llm_data.get("status", "unknown")}')
        safe_print(f'Model Used: {llm_data.get("model_used", "unknown")}')
        
        score = llm_data.get("llm_score", "N/A")
        if score == "N/A":
            safe_print(f'Score: {score}')
        else:
            safe_print(f'Score: {score}/10')
        
        safe_print(f'Processing Date: {llm_data.get("processing_completed", "unknown")}')
        
        if llm_data.get('tokens_used'):
            safe_print(f'Tokens Used: {llm_data["tokens_used"]}')
        
        safe_print(f'\nANALYSIS TEXT:\n')
        explanation = llm_data.get('llm_explanation', 'No explanation available')
        safe_print(f'{explanation}\n')
        
        if llm_data.get('error'):
            safe_print(f'ERROR: {llm_data["error"]}\n')
        
        # Add separation between jobs (except for the last one)
        if i < len(jobs_sorted):
            safe_print()
    
    return len(jobs_with_llm)


def reset_jobs_by_model(target_model='gpt-4o-mini'):
    """Reset jobs processed with models other than the target model"""
    
    print(f'Resetting jobs processed with models other than {target_model}...')
    
    # Get all jobs and find those with LLM results from other models
    all_jobs = query_jobs.get_all_jobs()
    jobs_to_reset = []
    
    for message_id, email_data in all_jobs:
        if 'llm_results' in email_data and email_data['llm_results']:
            llm_data = email_data['llm_results']
            model_used = llm_data.get('model_used', 'unknown')
            
            # Reset if processed with different model or unknown/None model
            if model_used != target_model:
                jobs_to_reset.append((message_id, email_data, model_used))
    
    if not jobs_to_reset:
        print(f'No jobs need resetting - all are already processed with {target_model}')
        return 0
    
    print(f'Found {len(jobs_to_reset)} jobs processed with older models:')
    
    # Show what we're about to reset
    model_reset_counts = {}
    for message_id, email_data, model_used in jobs_to_reset:
        model_reset_counts[model_used] = model_reset_counts.get(model_used, 0) + 1
    
    for model, count in sorted(model_reset_counts.items(), key=lambda x: x[0] or 'zzz'):
        print(f'  {model}: {count} jobs')
    
    # Confirm reset
    response = input(f'\nReset these {len(jobs_to_reset)} jobs for reprocessing with {target_model}? (y/N): ')
    if response.lower() != 'y':
        print('Reset cancelled')
        return 0
    
    print(f'Resetting jobs...')
    
    reset_count = 0
    with query_jobs.get_database(mode='w') as db:
        for message_id, email_data, model_used in jobs_to_reset:
            try:
                # Remove LLM results to mark for reprocessing
                if 'llm_results' in email_data:
                    del email_data['llm_results']
                
                # Save back to database
                db[message_id] = email_data
                reset_count += 1
                
            except Exception as e:
                print(f'Error resetting {message_id}: {e}')
    
    print(f'✅ Successfully reset {reset_count} jobs')
    print(f'These jobs will now be re-processed with {target_model}')
    
    # Check how many jobs now need processing
    jobs_needing_processing = query_jobs.get_jobs_needing_llm_processing()
    print(f'Total jobs now needing LLM processing: {len(jobs_needing_processing)}')
    
    return reset_count


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description="Extract job analysis results to text file")
    parser.add_argument('--output', '-o', type=str, 
                        help='Output filename (default: auto-generated with timestamp)')
    parser.add_argument('--reset', '-r', action='store_true',
                        help='Reset jobs processed with older models for reprocessing')
    parser.add_argument('--target-model', '-m', type=str, default='gpt-4o-mini',
                        help='Target model for reset operation (default: gpt-4o-mini)')
    parser.add_argument('--sort-by-score', '-s', action='store_true',
                        help='Sort results by score (highest first) instead of by email date')
    
    args = parser.parse_args()
    
    if args.reset:
        # Reset jobs processed with older models
        reset_jobs_by_model(args.target_model)
    else:
        # Extract analysis results to stdout
        job_count = extract_job_analysis_results(args.output, sort_by_score=args.sort_by_score)
        if job_count is None:
            return 1


if __name__ == '__main__':
    main()