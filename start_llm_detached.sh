#!/bin/bash
# LLM Analysis Runner with Proper Detachment
# This script ensures the LLM runs completely detached from the terminal

cd /home/john/py/popit3

# Kill any existing processes
pkill -f "run_llm_analysis.py" || true
pkill -f "job_analysis_script.py" || true

echo "Starting LLM analysis with proper detachment..."
echo "Process will run completely isolated from terminal"
echo "Check llm_analysis_detached.log for progress"

# Run with setsid to create new session, completely detached
setsid python3 run_llm_analysis.py </dev/null >llm_analysis_detached.log 2>&1 &

# Get the PID for monitoring
sleep 1
PID=$(pgrep -f "run_llm_analysis.py" | head -1)

if [ -n "$PID" ]; then
    echo "LLM analysis started successfully with PID: $PID"
    echo "Monitor with: tail -f llm_analysis_detached.log"
    echo "Check load with: uptime"
else
    echo "Failed to start LLM analysis process"
    exit 1
fi