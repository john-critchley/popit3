#!/usr/bin/env python3
"""
OpenAI Job Analysis Script

Analyzes JobServe job listings using OpenAI API instead of local LLM.
Provides CV-job matching scores and explanations using GPT models.
"""

import argparse
import json
import os
import sys
import re
import traceback
from datetime import datetime

# OpenAI SDK
import openai

# Job database/query helpers (shim loads TO_DELETE/query_jobs.py)
import query_jobs

"""
NOTE: This module was previously missing the OpenAIJobAnalyzer class and
had brittle regex-based score parsing. This refactor restores the class,
adds required imports, and switches to structured JSON output (score, reason)
using OpenAI Responses API to ensure reliable parsing and longer reasoning.
"""

class OpenAIJobAnalyzer:
    """Analyze JobServe jobs using OpenAI with structured JSON output."""

    def __init__(self, env_data_path: str, cv_file_path: str):
        self.env_data_path = os.path.expanduser(env_data_path or '~/.env_data')
        self.cv_file_path = cv_file_path
        self.model = None

        # Load CV content
        cv_path = os.path.expanduser(self.cv_file_path)
        with open(cv_path, 'r', encoding='utf-8') as f:
            self.cv_content = f.read()

        # Configure OpenAI client
        client_params = {}

        # Prefer environment variables for simplicity and security
        api_key = os.environ.get('OPENAI_API_KEY')
        organization = os.environ.get('OPENAI_ORG') or os.environ.get('OPENAI_ORGANIZATION')
        project = os.environ.get('OPENAI_PROJECT')
        model = os.environ.get('OPENAI_MODEL')

        # Attempt to read ~/.env_data if present for backwards compatibility
        try:
            if os.path.exists(self.env_data_path):
                # Minimal parser: expect JSON or line-based KEY=VALUE
                with open(self.env_data_path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {}
                    for line in raw.splitlines():
                        if '=' in line and not line.strip().startswith('#'):
                            k, v = line.split('=', 1)
                            data[k.strip()] = v.strip()

                api_key = api_key or data.get('api_key') or data.get('OPENAI_API_KEY')
                organization = organization or data.get('organization') or data.get('OPENAI_ORGANIZATION')
                project = project or data.get('project') or data.get('OPENAI_PROJECT')
                model = model or data.get('model') or data.get('OPENAI_MODEL')

        except Exception:
            # Non-fatal; fall back to env vars
            pass

        if not api_key:
            print("Missing OpenAI API key. Set OPENAI_API_KEY or provide in ~/.env_data")
            sys.exit(1)

        client_params['api_key'] = api_key
        if organization:
            client_params['organization'] = organization
        if project:
            client_params['project'] = project

        self.model = model or 'gpt-4o-mini'

        # Initialize client
        try:
            self.client = openai.OpenAI(**client_params)
            print(f"OpenAI client initialized with model: {self.model}")
        except Exception as e:
            print(f"Error setting up OpenAI client: {e}")
            traceback.print_exc()
            sys.exit(1)
    
    def analyze_job(self, message_id, email_data):
        """
        Analyze a single job using OpenAI API
        Returns analysis results with score and explanation
        """
        try:
            parsed = email_data.get('parsed', {})
            
            # Extract job information
            job_title = parsed.get('job_title', 'Unknown Job')
            job_description = parsed.get('description', '')
            company = parsed.get('employment_business', '')
            location = parsed.get('location', '')
            salary = parsed.get('salary', '')
            job_type = email_data.get('job_type', 'unknown')
            
            # Create comprehensive job description
            job_info = f"""
Job Title: {job_title}
Company: {company}
Location: {location}
Salary: {salary}
Type: {job_type}

Job Description:
{job_description}
            """.strip()
            
            # Create the prompt
            system_content = (
                "You are a career assistant helping with job application suitability analysis. "
                "You have expertise in matching CVs to job requirements and providing realistic assessments. "
                "You analyze technical skills, experience relevance, and overall job fit. "
                "BE DISCRIMINATING with scores - use the full 0-10 range and avoid grade inflation. "
                "Reserve high scores (8-10) for genuinely exceptional matches where the candidate clearly exceeds expectations."
            )
            
            # Load prompt from file
            try:
                with open('current_prompt.txt', 'r') as f:
                    prompt_template = f.read().strip()
            except FileNotFoundError:
                print("Warning: current_prompt.txt not found, using fallback prompt")
                prompt_template = (
                    "Analyze how well this CV matches the job description.\\n"
                    "Provide analysis and end with: Score: N (0-10)"
                )
            
            user_content = f"{prompt_template}\\n\\nJob Details:\\n{job_info}\\n\\nCV:\\n{self.cv_content}"
            
            # Call OpenAI API
            print(f"Analyzing: {job_title}")
            
            # Use Responses API with structured JSON output
            resp = self.client.responses.create(
                model=self.model,
                temperature=0.3,
                max_output_tokens=700,
                response_format={"type": "json_object"},
                input=[
                    {
                        "role": "system",
                        "content": system_content,
                    },
                    {
                        "role": "user",
                        "content": (
                            "Return a strict JSON object with keys 'score' (integer 0-10) and 'reason' (120-200 words). "
                            "Be discriminating with scores; reserve 8-10 for exceptional matches. "
                            "Explain key matches and gaps versus the CV.\n\n" + user_content
                        ),
                    },
                ],
            )

            # Extract structured output
            response_text = resp.output_text
            parsed_json = None
            try:
                parsed_json = json.loads(response_text)
            except json.JSONDecodeError:
                # Some SDK versions may return JSON directly in first item
                try:
                    first = resp.output[0].content[0].text
                    response_text = first
                    parsed_json = json.loads(first)
                except Exception:
                    parsed_json = None

            score = None
            reason = None
            if isinstance(parsed_json, dict):
                score = parsed_json.get('score')
                reason = parsed_json.get('reason')

            if score is None:
                print("Warning: Could not extract 'score' from JSON; falling back to regex")
                score_match = re.search(r"'score'\s*:\s*(\d+)|\"score\"\s*:\s*(\d+)", response_text)
                if not score_match:
                    score_match = re.search(r'Score:\s*(\d+)', response_text)
                score = int(score_match.group(1)) if score_match else None

            if score is not None:
                score = min(10, max(0, int(score)))

            # Prepare results
            analysis_results = {
                'message_id': message_id,
                'job_title': job_title,
                'company': company,
                'job_type': job_type,
                'analysis_text': reason or response_text,
                'score': score,
                'model': self.model,
                'timestamp': datetime.now().isoformat(),
                'tokens_used': getattr(resp, 'usage', None).total_tokens if getattr(resp, 'usage', None) else None,
                'api_response': resp.model_dump(mode='json')
            }
            
            print(f"✓ Score: {score}/10 - {job_title}")
            return analysis_results
            
        except Exception as e:
            print(f"Error analyzing job {message_id}: {e}")
            print("Full traceback:")
            traceback.print_exc()
            return {
                'message_id': message_id,
                'error': f"{e}",
                'traceback': traceback.format_exc(),
                'timestamp': datetime.now().isoformat()
            }
    
    def save_analysis_result(self, message_id, analysis_results):
        """Save analysis results to the job database - handles both analyzed and pre-filtered jobs"""
        try:
            # Handle pre-filtered jobs
            if analysis_results.get('pre_filtered'):
                llm_data = {
                    'status': 'skipped',
                    'processing_completed': analysis_results['timestamp'],
                    'llm_score': None,
                    'llm_explanation': f"Pre-filtered: {analysis_results['skip_reason']}",
                    'model_used': 'pre-filter',
                    'tokens_used': 0,
                    'skip_reason': analysis_results['skip_reason'],
                    'pre_filtered': True
                }
            else:
                # Handle normal analyzed jobs
                llm_data = {
                    'status': 'completed' if 'score' in analysis_results else 'failed',
                    'processing_completed': analysis_results['timestamp'],
                    'llm_score': analysis_results.get('score'),
                    'llm_explanation': analysis_results.get('analysis_text'),
                    'model_used': analysis_results.get('model'),
                    'tokens_used': analysis_results.get('tokens_used'),
                    'openai_response': analysis_results.get('api_response'),
                    'error': analysis_results.get('error'),
                    'pre_filtered': False
                }
            
            return query_jobs.update_job_llm_data(message_id, llm_data)
            
        except Exception as e:
            print(f"Error saving analysis result for {message_id}: {e}")
            print("Full traceback:")
            traceback.print_exc()
            return False
    
    def should_skip_job(self, job_title, job_description):
        """
        Determine if a job should be skipped before LLM analysis
        Based on analysis of poor matches to save API costs
        """
        title_lower = job_title.lower()
        desc_lower = job_description.lower() if job_description else ''
        
        # Exclude non-technical support roles
        exclude_patterns = [
            # Care/social work
            ('care support', ['care', 'support']),
            ('support worker', ['support', 'worker']),
            ('support assistant', ['support', 'assistant']),
            ('learning support', ['learning', 'support']),
            ('1:1 support', ['1:1', 'support']),
            
            # Education (unless technical)
            ('teacher', ['teacher', 'teaching']),
            ('school', ['school']),
            
            # Healthcare (unless health tech)
            ('nursing', ['nursing', 'nurse']),
            ('healthcare assistant', ['healthcare', 'assistant']),
            
            # Generic admin/clerical
            ('clerical', ['clerical']),
            ('receptionist', ['receptionist']),
            ('secretary', ['secretary']),
        ]
        
        # Check exclusion patterns
        for pattern_name, keywords in exclude_patterns:
            if all(keyword in title_lower for keyword in keywords):
                # But allow if it mentions technical terms
                tech_terms = ['software', 'system', 'application', 'technical', 'it ', 'data', 'analyst', 'developer', 'engineer']
                if not any(term in title_lower or term in desc_lower for term in tech_terms):
                    return True, f"Non-technical {pattern_name} role"
        
        return False, None

    def analyze_jobs_batch(self, count=None):
        """
        Analyze a batch of jobs that need LLM processing
        
        Args:
            count: Number of jobs to process (None = process all available jobs)
            
        Returns:
            Dict with processing statistics
        """
        # Get jobs that need processing
        jobs_needing_llm = query_jobs.get_jobs_needing_llm_processing()
        
        if not jobs_needing_llm:
            print("No jobs need LLM processing.")
            return {'processed': 0, 'errors': 0, 'skipped': 0}
        
        # Process all jobs if count is None, otherwise limit to count
        if count is None:
            jobs_to_process = jobs_needing_llm
            print(f"=== OpenAI Job Analysis (Processing ALL jobs) ===")
            print(f"Found {len(jobs_needing_llm)} jobs needing analysis, processing all of them")
        else:
            jobs_to_process = jobs_needing_llm[:count]
            print(f"=== OpenAI Job Analysis (Batch size: {count}) ===")
            print(f"Found {len(jobs_needing_llm)} jobs needing analysis, processing {len(jobs_to_process)}")
        
        stats = {'processed': 0, 'errors': 0, 'skipped': 0}
        
        for i, (message_id, email_data) in enumerate(jobs_to_process, 1):
            print(f"\\n[{i}/{len(jobs_to_process)}] Processing job...")
            
            try:
                # Pre-filter check
                parsed = email_data.get('parsed', {})
                job_title = parsed.get('job_title', '')
                job_description = parsed.get('description', '')
                
                should_skip, skip_reason = self.should_skip_job(job_title, job_description)
                
                if should_skip:
                    print(f"  ⏭ Skipping: {job_title}")
                    print(f"     Reason: {skip_reason}")
                    
                    # Save skip result to avoid reprocessing
                    skip_results = {
                        'message_id': message_id,
                        'job_title': job_title,
                        'skip_reason': skip_reason,
                        'timestamp': datetime.now().isoformat(),
                        'pre_filtered': True
                    }
                    
                    if self.save_analysis_result(message_id, skip_results):
                        stats['skipped'] += 1
                    else:
                        stats['errors'] += 1
                        print(f"  ✗ Failed to save skip result")
                    continue
                
                # Analyze the job
                analysis_results = self.analyze_job(message_id, email_data)
                
                # Save results
                if self.save_analysis_result(message_id, analysis_results):
                    stats['processed'] += 1
                else:
                    stats['errors'] += 1
                    print(f"  ✗ Failed to save results")
                    
            except Exception as e:
                print(f"  ✗ Error processing job: {e}")
                print("Full traceback:")
                traceback.print_exc()
                stats['errors'] += 1
        
        print(f"\\n=== Batch Analysis Complete ===")
        print(f"Processed: {stats['processed']}")
        print(f"Errors: {stats['errors']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Total cost estimate: ~${stats['processed'] * 0.01:.2f} (rough estimate)")
        print(f"Estimated savings: ~${stats['skipped'] * 0.01:.2f} from pre-filtering")
        
        return stats


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description="Analyze jobs using OpenAI API")
    parser.add_argument('--count', '-c', type=int, default=None,
                        help='Number of jobs to process (default: all available jobs)')
    parser.add_argument('--cv-file', '-f', type=str, default='cv_llm_optimized.md',
                        help='Path to CV file (default: cv_llm_optimized.md)')
    parser.add_argument('--env-data', '-e', type=str, default='~/.env_data',
                        help='Path to environment data file (default: ~/.env_data)')
    parser.add_argument('--list-jobs', '-l', action='store_true',
                        help='List jobs that need processing and exit')
    
    args = parser.parse_args()
    
    # Verify CV file exists
    cv_path = os.path.expanduser(args.cv_file)
    if not os.path.exists(cv_path) and not os.path.exists(args.cv_file):
        print(f"Error: CV file not found: {args.cv_file}")
        sys.exit(1)
    
    if args.list_jobs:
        # Just list jobs that need processing
        jobs_needing_llm = query_jobs.get_jobs_needing_llm_processing()
        print(f"Jobs needing LLM processing: {len(jobs_needing_llm)}")
        
        for i, (msg_id, data) in enumerate(jobs_needing_llm[:20]):  # Show first 20
            title = data.get('parsed', {}).get('job_title', 'No title')
            job_type = data.get('job_type', 'unknown')
            print(f"{i+1:3d}. [{job_type:10s}] {title}")
        
        if len(jobs_needing_llm) > 20:
            print(f"... and {len(jobs_needing_llm) - 20} more")
        
        sys.exit(0)
    
    # Create analyzer and process jobs
    try:
        analyzer = OpenAIJobAnalyzer(args.env_data, args.cv_file)
        stats = analyzer.analyze_jobs_batch(args.count)
        
        print(f"\\nAnalysis complete!")
        return 0 if stats['errors'] == 0 else 1
        
    except KeyboardInterrupt:
        print("\\nAnalysis interrupted by user")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())