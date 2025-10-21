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
import gdata
import openai
from datetime import datetime
# Add current directory to path for local imports
sys.path.append('.')
import query_jobs


class OpenAIJobAnalyzer:
    """Handles job analysis using OpenAI API"""
    
    def __init__(self, env_data_path="~/.env_data", cv_file="cv_llm_optimized.md"):
        self.env_data_path = os.path.expanduser(env_data_path)
        self.cv_content = self.load_cv(cv_file)
        self.client = None
        self.model = None
        self._setup_openai_client()
        
    def load_cv(self, cv_file):
        """Load CV content from file"""
        cv_path = os.path.expanduser(cv_file)
        if not os.path.exists(cv_path):
            # Try relative to current directory
            cv_path = cv_file
        
        try:
            with open(cv_path, 'r', encoding='utf-8') as f:
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
    
    def _setup_openai_client(self):
        """Setup OpenAI client using environment data"""
        try:
            print(f"Loading environment data from: {self.env_data_path}")
            
            # Try to access the environment data with proper error handling
            try:
                environ_gd = gdata.gdata(self.env_data_path, mode='r')
            except FileNotFoundError:
                print(f"Error: Environment data file not found: {self.env_data_path}")
                print("Make sure ~/.env_data exists and contains your OpenAI API credentials")
                sys.exit(1)
            except PermissionError:
                print(f"Error: Permission denied accessing: {self.env_data_path}")
                sys.exit(1)
            
            try:
                # Use JobServe-specific credentials if available, otherwise fall back to defaults
                if 'jobserve_api_key' in environ_gd:
                    client_params = {
                        'api_key': environ_gd['jobserve_api_key'],
                        'project': environ_gd.get('jobserve_project')
                    }
                    self.model = environ_gd.get('jobserve_model', 'gpt-4o-mini')
                    print(f"Using JobServe project: {environ_gd.get('jobserve_project')}")
                    print(f"Using JobServe model: {self.model}")
                else:
                    # Fallback to default credentials
                    required_keys = ['api_key']
                    optional_keys = ['organization', 'project', 'model']
                    
                    # Check for required keys
                    missing_keys = [key for key in required_keys if key not in environ_gd]
                    if missing_keys:
                        print(f"Missing required keys in {self.env_data_path}: {missing_keys}")
                        print("Please set up your OpenAI API credentials first.")
                        environ_gd.close()
                        sys.exit(1)
                    
                    # Setup client parameters
                    client_params = {'api_key': environ_gd['api_key']}
                    
                    # Add optional parameters if available
                    for key in optional_keys:
                        if key in environ_gd:
                            if key == 'model':
                                self.model = environ_gd[key]
                            else:
                                client_params[key] = environ_gd[key]
                
                # Add organization if available
                if 'organization' in environ_gd:
                    client_params['organization'] = environ_gd['organization']
                
                # Close the gdata file
                environ_gd.close()
                
            except KeyError as e:
                environ_gd.close()
                print(f"Missing required key in environment data: {e}")
                sys.exit(1)
            except Exception as e:
                environ_gd.close()
                print(f"Error reading environment data: {e}")
                traceback.print_exc()
                sys.exit(1)
            
            # Use default model if not specified  
            if not self.model:
                self.model = "gpt-4o-mini"  # Much better than gpt-3.5-turbo for structured tasks
            
            # Create OpenAI client
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
            
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}
                ],
                model=self.model,
                temperature=0.3  # Lower temperature for more consistent scoring
            )
            
            # Extract response
            response_text = chat_completion.choices[0].message.content
            
            # Debug: Print end of response to see score format
            print(f"Response ending: ...{response_text[-100:]}")
            
            # Extract score using regex - try multiple patterns
            score_match = re.search(r'Score:\s*(\d+)', response_text)
            if not score_match:
                # Try alternative patterns
                score_match = re.search(r'score:\s*(\d+)', response_text, re.IGNORECASE)
            if not score_match:
                score_match = re.search(r'(\d+)/10', response_text)
            
            score = int(score_match.group(1)) if score_match else None
            
            if score is None:
                print(f"Warning: Could not extract score from response")
                print(f"Last 200 chars: {response_text[-200:]}")
            else:
                print(f"Extracted score: {score}")
            
            if score is not None:
                score = min(10, max(0, score))  # Clamp to 0-10 range
            
            # Prepare results
            analysis_results = {
                'message_id': message_id,
                'job_title': job_title,
                'company': company,
                'job_type': job_type,
                'analysis_text': response_text,
                'score': score,
                'model': self.model,
                'timestamp': datetime.now().isoformat(),
                'tokens_used': chat_completion.usage.total_tokens if chat_completion.usage else None,
                'api_response': chat_completion.model_dump(mode='json')
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