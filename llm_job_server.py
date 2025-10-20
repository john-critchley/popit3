#!/usr/bin/env python3
"""
LLM Job Server - Lightweight HTTP server for running LLM analysis jobs
Prevents terminal/screen issues by running jobs completely detached
"""

import json
import os
import sys
import time
import uuid
import subprocess
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import queue
import signal


class JobQueue:
    """Thread-safe job queue manager"""
    
    def __init__(self):
        self.jobs = {}
        self.queue = queue.Queue()
        self.current_job = None
        self.worker_thread = None
        self.lock = threading.Lock()
        
    def submit_job(self, job_data):
        """Submit a new LLM job"""
        job_id = str(uuid.uuid4())[:8]  # Short ID
        job = {
            'id': job_id,
            'submitted': datetime.now().isoformat(),
            'status': 'queued',
            'data': job_data,
            'output': None,
            'error': None,
            'started': None,
            'completed': None
        }
        
        with self.lock:
            self.jobs[job_id] = job
            self.queue.put(job_id)
        
        # Start worker if not running
        self._ensure_worker_running()
        
        return job_id
    
    def get_job(self, job_id):
        """Get job by ID"""
        with self.lock:
            return self.jobs.get(job_id, None)
    
    def list_jobs(self):
        """List all jobs (running, queued, recent completed)"""
        with self.lock:
            # Get queue position for queued jobs
            queue_list = list(self.queue.queue)
            
            jobs_list = []
            for job in self.jobs.values():
                job_info = job.copy()
                if job['status'] == 'queued' and job['id'] in queue_list:
                    job_info['queue_position'] = queue_list.index(job['id']) + 1
                jobs_list.append(job_info)
            
            # Sort by submission time (newest first)
            jobs_list.sort(key=lambda x: x['submitted'], reverse=True)
            
            return {
                'current_job': self.current_job,
                'queue_size': self.queue.qsize(),
                'jobs': jobs_list[:20]  # Limit to 20 most recent
            }
    
    def _ensure_worker_running(self):
        """Start worker thread if not running"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
    
    def _worker_loop(self):
        """Worker thread that processes jobs"""
        while True:
            try:
                # Get next job (blocks if queue empty)
                job_id = self.queue.get(timeout=60)  # 1 minute timeout
                
                with self.lock:
                    if job_id not in self.jobs:
                        continue
                    
                    job = self.jobs[job_id]
                    job['status'] = 'running'
                    job['started'] = datetime.now().isoformat()
                    self.current_job = job_id
                
                print(f"Starting LLM job {job_id}")
                
                # Run the LLM job completely detached
                success = self._run_llm_job(job_id, job)
                
                with self.lock:
                    if success:
                        job['status'] = 'completed'
                    else:
                        job['status'] = 'failed'
                    
                    job['completed'] = datetime.now().isoformat()
                    self.current_job = None
                
                print(f"Completed LLM job {job_id}: {job['status']}")
                
            except queue.Empty:
                # Timeout - continue loop
                continue
            except Exception as e:
                print(f"Worker error: {e}")
                with self.lock:
                    if self.current_job:
                        job = self.jobs.get(self.current_job)
                        if job:
                            job['status'] = 'failed'
                            job['error'] = str(e)
                            job['completed'] = datetime.now().isoformat()
                        self.current_job = None
    
    def _run_llm_job(self, job_id, job):
        """Run LLM job completely detached from terminal"""
        try:
            # Create output directory
            output_dir = f"llm_output/{job_id}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Get job data for processing options
            job_data = job.get('data', {})
            mode = job_data.get('mode', 'analyze_new')  # analyze_new, analyze_all, or analyze_refs
            
            # Prepare command based on mode
            if mode == 'analyze_all':
                # Run full analysis (your existing script)
                cmd = [sys.executable, 'job_analysis_script.py']
            elif mode == 'analyze_refs' and 'message_ids' in job_data:
                # Create a wrapper script to analyze specific jobs
                wrapper_script = self._create_analysis_wrapper(output_dir, job_data['message_ids'])
                cmd = [sys.executable, wrapper_script]
            else:
                # Default: analyze new jobs only (modify existing script for this mode)
                wrapper_script = self._create_new_jobs_wrapper(output_dir)
                cmd = [sys.executable, wrapper_script]
            
            # Run completely detached - no stdin/stdout/stderr
            with open(f"{output_dir}/stdout.log", 'w') as stdout_file, \
                 open(f"{output_dir}/stderr.log", 'w') as stderr_file:
                
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    start_new_session=True,  # Detach from terminal completely
                )
                
                # Wait for completion
                return_code = process.wait()
                
                # Read results from stdout log
                job['return_code'] = return_code
                
                try:
                    with open(f"{output_dir}/stdout.log", 'r') as f:
                        stdout_content = f.read()
                        job['output'] = {
                            'stdout': stdout_content,
                            'analysis_summary': self._parse_analysis_output(stdout_content)
                        }
                except Exception as e:
                    job['output'] = {'error': f"Could not read output: {e}"}
                
                if return_code != 0:
                    # Read error log
                    try:
                        with open(f"{output_dir}/stderr.log", 'r') as f:
                            stderr_content = f.read()
                            job['error'] = stderr_content[-1000:]  # Last 1000 chars
                    except:
                        job['error'] = f"LLM process failed with code {return_code}"
                    return False
                
                return True
                
        except Exception as e:
            job['error'] = f"Failed to start LLM process: {e}"
            return False
    
    def _create_analysis_wrapper(self, output_dir, message_ids):
        """Create wrapper script for analyzing specific message IDs"""
        wrapper_path = os.path.join(output_dir, 'analyze_specific.py')
        wrapper_code = f'''#!/usr/bin/env python3
import sys
import os
sys.path.append('{os.path.dirname(os.path.abspath(__file__))}')

# Import your existing analyzer
from job_analysis_script import JobAnalyzer

def main():
    print("Analyzing specific jobs: {message_ids}")
    
    analyzer = JobAnalyzer()
    
    # Load CV and jobs
    analyzer.load_cv("~/Downloads/cv_llm_optimized.md")
    analyzer.load_jobs("~/.js_new.gdbm")
    
    # Filter to only specified message IDs
    target_refs = {message_ids}
    original_jobs = analyzer.data['jobs']
    analyzer.data['jobs'] = [job for job in original_jobs 
                            if job.get('parsed', {{}}).get('ref') in target_refs]
    
    print(f"Found {{len(analyzer.data['jobs'])}} matching jobs to analyze")
    
    if analyzer.data['jobs']:
        # Setup model and analyze
        analyzer.setup_model("bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", 
                           "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf")
        
        updated_from_analysis = analyzer.analyze_jobs()
        updated_from_parsing = analyzer.parse_responses()
        all_updates = updated_from_analysis | updated_from_parsing
        
        analyzer.save_results("~/.js_new.gdbm", all_updates)
        analyzer.print_summary()
    else:
        print("No matching jobs found")
    
    print("Analysis completed!")

if __name__ == "__main__":
    main()
'''
        
        with open(wrapper_path, 'w') as f:
            f.write(wrapper_code)
        
        return wrapper_path
    
    def _create_new_jobs_wrapper(self, output_dir):
        """Create wrapper script for analyzing only new/unanalyzed jobs"""
        wrapper_path = os.path.join(output_dir, 'analyze_new.py')
        wrapper_code = f'''#!/usr/bin/env python3
import sys
import os
sys.path.append('{os.path.dirname(os.path.abspath(__file__))}')

from job_analysis_script import JobAnalyzer

def main():
    print("Analyzing new jobs only...")
    
    analyzer = JobAnalyzer()
    
    # Load CV and jobs  
    analyzer.load_cv("~/Downloads/cv_llm_optimized.md")
    analyzer.load_jobs("~/.js_new.gdbm")
    
    # Setup model info to check what's already analyzed
    model_repo = "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF"
    model_filename = "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    modelname = 'm_' + model_filename.replace('.gguf', '').replace('-', '').replace('.', '_')
    analyzer.data['modelname'] = modelname
    
    # Filter to only unanalyzed jobs
    original_jobs = analyzer.data['jobs']
    unanalyzed_jobs = []
    
    for job in original_jobs:
        if modelname not in job or 'score' not in job.get(modelname, {{}}):
            unanalyzed_jobs.append(job)
    
    analyzer.data['jobs'] = unanalyzed_jobs
    
    print(f"Found {{len(unanalyzed_jobs)}} unanalyzed jobs")
    
    if unanalyzed_jobs:
        # Setup model and analyze
        analyzer.setup_model(model_repo, model_filename)
        
        updated_from_analysis = analyzer.analyze_jobs()
        updated_from_parsing = analyzer.parse_responses()
        all_updates = updated_from_analysis | updated_from_parsing
        
        analyzer.save_results("~/.js_new.gdbm", all_updates)
        analyzer.print_summary()
    else:
        print("No new jobs to analyze")
    
    print("Analysis completed!")

if __name__ == "__main__":
    main()
'''
        
        with open(wrapper_path, 'w') as f:
            f.write(wrapper_code)
        
        return wrapper_path
    
    def _parse_analysis_output(self, stdout_content):
        """Parse analysis output for summary info"""
        summary = {
            'jobs_analyzed': 0,
            'high_scoring_jobs': [],
            'completion_status': 'unknown'
        }
        
        lines = stdout_content.split('\n')
        
        for line in lines:
            if 'new jobs analyzed' in line:
                try:
                    summary['jobs_analyzed'] = int(line.split()[0])
                except:
                    pass
            elif '▄' in line and '/10' in line:
                # Parse score line: "  REF123: ▄▄▄▄▄▄▄▄ (8/10)"
                try:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        score_part = parts[1].strip()
                        if '(' in score_part and '/10' in score_part:
                            score_text = score_part.split('(')[1].split('/')[0]
                            score = int(score_text)
                            if score >= 8:
                                ref = parts[0].strip()
                                summary['high_scoring_jobs'].append({
                                    'ref': ref,
                                    'score': score
                                })
                except:
                    pass
            elif 'ANALYSIS COMPLETE' in line:
                summary['completion_status'] = 'completed'
        
        return summary


class LLMJobHandler(BaseHTTPRequestHandler):
    """HTTP request handler for LLM job server"""
    
    def __init__(self, *args, job_queue=None, **kwargs):
        self.job_queue = job_queue
        super().__init__(*args, **kwargs)
    
    def do_POST(self):
        """Handle job submission"""
        if self.path == '/job':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                job_data = json.loads(post_data.decode('utf-8'))
                
                # Validate job data
                if not isinstance(job_data, dict):
                    self._send_error(400, "Job data must be JSON object")
                    return
                
                # Submit job
                job_id = self.job_queue.submit_job(job_data)
                
                # Return job ID
                self._send_json({'job_id': job_id, 'status': 'submitted'})
                
            except json.JSONDecodeError:
                self._send_error(400, "Invalid JSON")
            except Exception as e:
                self._send_error(500, f"Server error: {e}")
        else:
            self._send_error(404, "Not found")
    
    def do_GET(self):
        """Handle status requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        try:
            if path == '/list':
                # List jobs
                jobs = self.job_queue.list_jobs()
                
                # Check for format parameter
                query = parse_qs(parsed.query)
                format_type = query.get('format', ['json'])[0]
                
                if format_type == 'html':
                    self._send_html_list(jobs)
                elif format_type == 'text':
                    self._send_text_list(jobs)
                else:
                    self._send_json(jobs)
                    
            elif path.startswith('/job/'):
                # Get specific job
                job_id = path.split('/')[-1]
                job = self.job_queue.get_job(job_id)
                
                if job is None:
                    self._send_error(404, f"Job {job_id} not found")
                    return
                
                self._send_json(job)
                
            else:
                self._send_error(404, "Not found")
                
        except Exception as e:
            self._send_error(500, f"Server error: {e}")
    
    def _send_json(self, data):
        """Send JSON response"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))
    
    def _send_html_list(self, jobs):
        """Send HTML formatted job list"""
        html = f"""
        <html><head><title>LLM Job Queue</title></head><body>
        <h1>LLM Job Server Status</h1>
        <p>Current job: {jobs['current_job'] or 'None'}</p>
        <p>Queue size: {jobs['queue_size']}</p>
        <h2>Jobs:</h2>
        <table border="1">
        <tr><th>ID</th><th>Status</th><th>Submitted</th><th>Queue Pos</th><th>Started</th><th>Completed</th></tr>
        """
        
        for job in jobs['jobs']:
            queue_pos = job.get('queue_position', '')
            started = job.get('started', '') or ''
            completed = job.get('completed', '') or ''
            html += f"""
            <tr>
                <td><a href="/job/{job['id']}">{job['id']}</a></td>
                <td>{job['status']}</td>
                <td>{job['submitted']}</td>
                <td>{queue_pos}</td>
                <td>{started}</td>
                <td>{completed}</td>
            </tr>
            """
        
        html += "</table></body></html>"
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _send_text_list(self, jobs):
        """Send plain text job list"""
        text = f"LLM Job Server Status\n"
        text += f"Current job: {jobs['current_job'] or 'None'}\n"
        text += f"Queue size: {jobs['queue_size']}\n\n"
        text += "Jobs:\n"
        text += f"{'ID':<10} {'Status':<10} {'Submitted':<20} {'Queue':<5}\n"
        text += "-" * 50 + "\n"
        
        for job in jobs['jobs']:
            queue_pos = str(job.get('queue_position', ''))
            text += f"{job['id']:<10} {job['status']:<10} {job['submitted'][:19]:<20} {queue_pos:<5}\n"
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))
    
    def _send_error(self, code, message):
        """Send error response"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        error = {'error': message}
        self.wfile.write(json.dumps(error).encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to control logging"""
        print(f"{self.address_string()} - {format % args}")


def create_handler(job_queue):
    """Create handler with job_queue injected"""
    def handler(*args, **kwargs):
        return LLMJobHandler(*args, job_queue=job_queue, **kwargs)
    return handler


def main():
    """Main server function"""
    host = 'localhost'
    port = 8080
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    print(f"Starting LLM Job Server on {host}:{port}")
    
    # Create job queue
    job_queue = JobQueue()
    
    # Create HTTP server
    handler_class = create_handler(job_queue)
    server = HTTPServer((host, port), handler_class)
    
    # Handle shutdown gracefully
    def signal_handler(signum, frame):
        print("\nShutting down server...")
        server.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"Server running at http://{host}:{port}")
    print("Endpoints:")
    print("  POST /job           - Submit LLM job (JSON data)")
    print("  GET  /list          - List jobs (add ?format=html or ?format=text)")
    print("  GET  /job/<id>      - Get specific job")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()