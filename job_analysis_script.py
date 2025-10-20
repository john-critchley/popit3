#!/usr/bin/env python3
"""
Job Analysis Script - Pure Python version
Analyzes job postings against CV using LLaMA model
"""

import gdata
import time
import os
import json
import yaml
from functools import wraps

# Third-party imports
import numpy as np
import pandas as pd
import llama_cpp
import huggingface_hub


def timed_function(func):
    """Decorator that times function execution and returns (result, duration)"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        return result, end_time - start_time
    return wrapper


class JobAnalyzer:
    def __init__(self):
        self.data = {}
        self.model = None
        self.cv = None
        
    def load_cv(self, cv_path):
        """Load CV from file"""
        print(f"Loading CV from {cv_path}...")
        with open(os.path.expanduser(cv_path)) as cvfd:
            self.cv = cvfd.read()
        print(f"CV loaded ({len(self.cv)} characters)")
        
    def load_jobs(self, db_path):
        """Load jobs from gdata database"""
        print(f"Loading jobs from {db_path}...")
        with gdata.gdata(os.path.expanduser(db_path), mode="r") as gd:
            jobs = []
            for k, v in gd.items():
                # Skip metadata keys (start with 'M:' or are 8-digit dates)
                if k.startswith('M:') or (k.isdigit() and len(k) == 8):
                    continue
                # Only include entries that have parsed job data
                if isinstance(v, dict) and 'parsed' in v:
                    jobs.append(v)
            self.data['jobs'] = jobs
        print(f"Loaded {len(self.data['jobs'])} jobs")
        
    def setup_model(self, model_repo, model_filename):
        """Download and initialize the LLaMA model"""
        print(f"\nSetting up model: {model_repo}/{model_filename}")
        
        modelname = 'm_' + model_filename.replace('.gguf', '').replace('-', '').replace('.', '_')
        self.data['modelname'] = modelname
        
        print("Downloading model from HuggingFace...")
        self.data['model_path'] = huggingface_hub.hf_hub_download(
            repo_id=model_repo,
            filename=model_filename,
            local_dir="models/" + model_filename,
        )
        
        print(f"Model downloaded to: {self.data['model_path']}")
        print("Initializing model (please wait)...")
        
        self.model = llama_cpp.Llama(
            model_path=self.data['model_path'],
            n_threads=16,      # Reduced from 8
            n_ctx=8192,
            verbose=True,
        )
        
        print("Model initialized successfully!")
        
    @timed_function
    def generate_response(self, instruction, resume, subject, job_description):
        """Generate a response from the LLaMA model"""
        prompt = f"""Task: {instruction}

IMPORTANT: 
- Only mention skills explicitly stated in the resume
- Do not infer skills from related experience
- Match job requirements against actual resume content only

Resume: {resume}
Subject: {subject}
Job description: {job_description}

Output valid JSON with format:
{{"score": N, "reason": "brief explanation of skills match only"}}

JSON:"""

        response = self.model(
            prompt=prompt,
            max_tokens=256,
            temperature=0.01,
            top_p=0.9,
            repeat_penalty=1.1,
            top_k=40,
            stop=['END', '---'],
            echo=False,
            seed=42,
        )

        response_text = response["choices"][0]["text"].strip()
        return response_text
    
    def analyze_jobs(self):
        """Analyze all jobs that haven't been analyzed yet"""
        modelname = self.data['modelname']
        updated = set()
        
        instruction = "Would I have a good chance applying to this job? Give me a score 1 to 10; be honest."
        
        total_jobs = len(self.data['jobs'])
        analyzed = 0
        
        for idx, details in enumerate(self.data['jobs'], 1):
            # Ensure the model field exists
            if modelname not in details:
                details[modelname] = {}
            
            # Skip if already analyzed
            if 'resp' in details[modelname]:
                print(f"[{idx}/{total_jobs}] {details['parsed']['ref']} already analyzed")
                continue
                print("but still processing")
            
            print(f"\n[{idx}/{total_jobs}] Analyzing {details['parsed']['ref']}...")
            print(f"  Subject: {details['headers']['Subject'][:60]}...")
            
            try:
                resp, duration = self.generate_response(
                    instruction,
                    self.cv,
                    details['headers']['Subject'],
                    details['parsed']['description']
                )
                
                details[modelname]['resp'] = resp
                updated.add(details['parsed']['ref'])
                analyzed += 1
                
                print(f"  Response time: {duration:.2f}s")
                print(f"  Response: {resp}...")
                
            except Exception as e:
                print(f"  ERROR: {e}")
                continue
        
        print(f"\n{analyzed} new jobs analyzed")
        return updated
    
    def parse_responses(self):
        """Parse JSON responses and extract scores"""
        modelname = self.data['modelname']
        updated = set()
        dec = json.JSONDecoder(strict=False)
        
        print("\nParsing responses...")
        
        for details in self.data['jobs']:
            if modelname not in details or 'resp' not in details[modelname]:
                continue
                
            if 'score' in details[modelname]:
                continue  # Already parsed
            
            try:
                j, offset = dec.raw_decode(details[modelname]['resp'])
                details[modelname]['score'] = int(j['score'])
                details[modelname]['analysis'] = details[modelname]['resp'][offset:].strip()
                
                # Visual score indicator
                bar = '▄' * details[modelname]['score']
                print(f"  {details['parsed']['ref']}: {bar} ({details[modelname]['score']}/10)")
                
                updated.add(details['parsed']['ref'])
                
            except json.JSONDecodeError as e:
                print(f"  ERROR parsing {details['parsed']['ref']}: {e}")
                print(f"    Response was: {details[modelname]['resp'][:100]}...")
                continue
        
        return updated
    
    def save_results(self, db_path, updated_refs):
        """Save updated results back to database"""
        if not updated_refs:
            print("\nNo updates to save")
            return
        
        print(f"\nSaving {len(updated_refs)} updated jobs to database...")
        
        with gdata.gdata(os.path.expanduser(db_path)) as gd:
            for details in self.data['jobs']:
                if details['parsed']['ref'] in updated_refs:
                    gd[details['parsed']['ref']] = details
        
        print("Results saved!")
    
    def print_summary(self):
        """Print summary of all analyzed jobs"""
        modelname = self.data['modelname']
        
        print("SUMMARY OF JOB MATCHES")
        
        scored_jobs = []
        for details in self.data['jobs']:
            if modelname in details and 'score' in details[modelname]:
                scored_jobs.append({
                    'ref': details['parsed']['ref'],
                    'subject': details['headers']['Subject'],
                    'score': details[modelname]['score'],
                    'reason': details[modelname].get('analysis', 'N/A')
                })
        
        # Sort by score (highest first)
        scored_jobs.sort(key=lambda x: x['score'], reverse=True)
        
        for job in scored_jobs:
            bar = '▄' * job['score']
            print(f"\n{job['ref']}: {bar} ({job['score']}/10)")
            print(f"  {job['subject'][:70]}")
            if job['reason']:
                print(f"  → {job['reason'][:100]}...")


def main():
    print("JOB ANALYSIS SCRIPT")
    
    # Configuration
    CV_PATH = "~/Downloads/cv_llm_optimized.md"
    DB_PATH = "~/.js_new.gdbm"
    
    MODEL_REPO, MODEL_FILENAME = (
#    "MoMonir/Meta-Llama-3-8B-Instruct-GGUF", "meta-llama-3-8b-instruct.Q5_K_M.gguf"

    # Qwen2.5-1.5B-Instruct (currently using)
    #"Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"

    #"bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf"

    #"bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf"

    "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    )
    
    # Initialize analyzer
    analyzer = JobAnalyzer()
    
    try:
        # Load data
        analyzer.load_cv(CV_PATH)
        analyzer.load_jobs(DB_PATH)
        
        # Setup model
        analyzer.setup_model(MODEL_REPO, MODEL_FILENAME)
        
        # Analyze jobs
        updated_from_analysis = analyzer.analyze_jobs()
        
        # Parse responses
        updated_from_parsing = analyzer.parse_responses()
        
        # Combine all updates
        all_updates = updated_from_analysis | updated_from_parsing
        
        # Save results
        analyzer.save_results(DB_PATH, all_updates)
        
        # Print summary
        analyzer.print_summary()
        
        print("ANALYSIS COMPLETE!")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Saving partial results...")
        if 'all_updates' in locals():
            analyzer.save_results(DB_PATH, all_updates)
        print("Exiting.")
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
