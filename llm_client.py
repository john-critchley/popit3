#!/usr/bin/env python3
"""
LLM Job Client - Simple client for submitting jobs to LLM server
"""

import json
import sys
import requests
import time


def submit_job(server_url, job_data):
    """Submit a job to the LLM server"""
    try:
        response = requests.post(f"{server_url}/job", json=job_data)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error submitting job: {e}")
        return None


def get_job_status(server_url, job_id):
    """Get status of a specific job"""
    try:
        response = requests.get(f"{server_url}/job/{job_id}")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error getting job status: {e}")
        return None


def list_jobs(server_url, format_type="json"):
    """List all jobs"""
    try:
        params = {'format': format_type} if format_type != 'json' else {}
        response = requests.get(f"{server_url}/list", params=params)
        response.raise_for_status()
        
        if format_type == 'json':
            return response.json()
        else:
            return response.text
    except requests.RequestException as e:
        print(f"Error listing jobs: {e}")
        return None


def main():
    server_url = "http://localhost:8080"
    
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} submit <job_data.json>")
        print(f"  {sys.argv[0]} status <job_id>")
        print(f"  {sys.argv[0]} list [text|html]")
        print(f"  {sys.argv[0]} wait <job_id>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "submit":
        if len(sys.argv) < 3:
            print("Need job data file")
            sys.exit(1)
        
        try:
            with open(sys.argv[2], 'r') as f:
                job_data = json.load(f)
        except Exception as e:
            print(f"Error loading job data: {e}")
            sys.exit(1)
        
        result = submit_job(server_url, job_data)
        if result:
            print(f"Job submitted: {result['job_id']}")
        
    elif command == "status":
        if len(sys.argv) < 3:
            print("Need job ID")
            sys.exit(1)
        
        job_id = sys.argv[2]
        result = get_job_status(server_url, job_id)
        if result:
            print(json.dumps(result, indent=2))
        
    elif command == "list":
        format_type = sys.argv[2] if len(sys.argv) > 2 else "json"
        result = list_jobs(server_url, format_type)
        if result:
            if format_type == "json":
                print(json.dumps(result, indent=2))
            else:
                print(result)
    
    elif command == "wait":
        if len(sys.argv) < 3:
            print("Need job ID")
            sys.exit(1)
        
        job_id = sys.argv[2]
        print(f"Waiting for job {job_id}...")
        
        while True:
            result = get_job_status(server_url, job_id)
            if not result:
                break
            
            status = result['status']
            print(f"Status: {status}")
            
            if status in ['completed', 'failed']:
                print("Final result:")
                print(json.dumps(result, indent=2))
                break
            
            time.sleep(5)  # Check every 5 seconds
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()