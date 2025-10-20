#!/bin/bash
# LLM Job Server Startup Script

PORT=${1:-8080}
HOST=${2:-localhost}

echo "Starting LLM Job Server..."
echo "Host: $HOST"
echo "Port: $PORT"
echo "Working Directory: $(pwd)"
echo

# Create output directory
mkdir -p llm_output

# Create job requests directory if it doesn't exist
mkdir -p job_requests

# Start the server
python3 llm_job_server.py $PORT