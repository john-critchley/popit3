#!/usr/bin/env python3
"""
Simple LLM Job Server
A working HTTP server that processes individual job analysis requests
"""

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import tempfile

# Add current directory to path for local imports
sys.path.append('.')
import query_jobs

class SimpleJobQueue:
    """Simple thread-safe job queue"""
    
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
    
    def submit_job(self, job_data):
        """Submit a job and return job ID"""
        job_id = str(uuid.uuid4())[:8]
        job = {
            'id': job_id,
            'submitted': datetime.now().isoformat(),
            'status': 'submitted',
            'data': job_data,
            'output': None,
            'error': None
        }
        
        with self.lock:
            self.jobs[job_id] = job
        
        # Start processing in background thread
        thread = threading.Thread(target=self._process_job, args=(job_id,), daemon=True)
        thread.start()
        
        return job_id
    
    def get_job(self, job_id):
        """Get job by ID"""
        with self.lock:
            return self.jobs.get(job_id)
    
    def list_jobs(self):
        """List all jobs"""
        with self.lock:
            return list(self.jobs.values())
    
    def _process_job(self, job_id):
        """Process a single job"""
        with self.lock:
            job = self.jobs[job_id]
            job['status'] = 'running'
            job['started'] = datetime.now().isoformat()
        
        try:
            job_data = job['data']
            mode = job_data.get('mode', 'test')
            
            if mode == 'test':
                # Simple test job
                time.sleep(5)  # Simulate work
                result = {
                    'message': 'Test job completed successfully',
                    'timestamp': datetime.now().isoformat()
                }
                
            elif mode == 'analyze_individual':
                # Analyze a single job
                message_id = job_data.get('message_id')
                result = self._analyze_single_job(message_id)

    elif mode == 'analyze_batch':
                # Analyze a small batch of jobs
                count = job_data.get('count', 5)
                result = self._analyze_job_batch(count)
                
            else:
                result = {'error': f'Unknown mode: {mode}'}
            
            # Update job with results
            with self.lock:
                job = self.jobs[job_id]
                job['status'] = 'completed'
                job['completed'] = datetime.now().isoformat()
                job['output'] = result
                
        except Exception as e:
            # Mark job as failed
            with self.lock:
                job = self.jobs[job_id]
                job['status'] = 'failed'
                job['completed'] = datetime.now().isoformat()
                job['error'] = str(e)
    
    def _analyze_single_job(self, message_id):
        """Analyze a single job using the LLM"""
        try:
            # Get job from database
            job_data = query_jobs.get_job(message_id)
            if not job_data:
                return {'error': f'Job {message_id} not found'}
            
            # For now, return a mock analysis
            # TODO: Implement actual LLM analysis
            parsed = job_data.get('parsed', {})
            title = parsed.get('job_title', 'Unknown')
            
            # Simulate LLM processing time
            time.sleep(10)
            
            return {
                'message_id': message_id,
                'job_title': title,
                'llm_score': 7,
                'llm_explanation': f'Mock analysis for {title}: Good match for Python development skills.',
                'analysis_time': '10 seconds',
                'status': 'completed'
            }
            
        except Exception as e:
            return {'error': f'Analysis failed: {str(e)}'}
    
    def _analyze_job_batch(self, count):
        """Analyze a batch of jobs"""
        try:
            jobs = query_jobs.get_jobs_needing_llm_processing()[:count]
            results = []
            
            for message_id, job_data in jobs:
                parsed = job_data.get('parsed', {})
                title = parsed.get('job_title', 'Unknown')
                
                # Simulate processing
                time.sleep(2)
                
                results.append({
                    'message_id': message_id,
                    'job_title': title,
                    'llm_score': 6,
                    'status': 'analyzed'
                })
            
            return {
                'batch_size': len(results),
                'results': results,
                'total_time': f'{len(results) * 2} seconds'
            }
            
        except Exception as e:
            return {'error': f'Batch analysis failed: {str(e)}'}


class SimpleJobHandler(BaseHTTPRequestHandler):
    """Simple HTTP request handler"""
    
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
                
                job_id = self.job_queue.submit_job(job_data)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                
                response = {'job_id': job_id, 'status': 'submitted'}
                self.wfile.write(json.dumps(response, indent=2).encode())
                
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error_response = {'error': str(e)}
                self.wfile.write(json.dumps(error_response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        """Handle job status and listing"""
        path_parts = self.path.split('/')
        
        if self.path == '/list':
            # List all jobs
            jobs = self.job_queue.list_jobs()
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response = {
                'jobs': jobs,
                'count': len(jobs)
            }
            self.wfile.write(json.dumps(response, indent=2).encode())
            
        elif len(path_parts) == 3 and path_parts[1] == 'job':
            # Get specific job
            job_id = path_parts[2]
            job = self.job_queue.get_job(job_id)
            
            if job:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(job, indent=2).encode())
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error_response = {'error': 'Job not found'}
                self.wfile.write(json.dumps(error_response).encode())
        else:
            self.send_response(404)
            self.end_headers()


def create_handler(job_queue):
    """Create handler with job_queue injected"""
    def handler(*args, **kwargs):
        return SimpleJobHandler(*args, job_queue=job_queue, **kwargs)
    return handler


def main():
    """Main server function"""
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    print(f"Starting Simple LLM Job Server on port {port}")
    
    # Create job queue
    job_queue = SimpleJobQueue()
    
    # Create HTTP server
    handler_class = create_handler(job_queue)
    server = HTTPServer(('localhost', port), handler_class)
    
    print(f"Server running at http://localhost:{port}")
    print("Endpoints:")
    print("  POST /job   - Submit job")
    print("  GET  /list  - List jobs")
    print("  GET  /job/<id> - Get job status")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nShutting down...")
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
