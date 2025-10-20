#!/bin/bash
# LLM Analysis Runner with CPU Limiting
# This script runs LLM analysis with CPU limits to prevent system overload

cd /home/john/py/popit3

# Kill any existing processes
pkill -f "run_llm_analysis.py" || true
pkill -f "job_analysis_script.py" || true

echo "Starting CPU-limited LLM analysis..."
echo "Will use nice priority and limit CPU to prevent system overload"
echo "Check llm_analysis_limited.log for progress"

# Check if cpulimit is available
if command -v cpulimit >/dev/null 2>&1; then
    echo "Using cpulimit to restrict CPU usage to 80%"
    # Run with cpulimit to restrict CPU usage
    setsid nice -n 10 cpulimit -l 80 python3 run_llm_analysis.py </dev/null >llm_analysis_limited.log 2>&1 &
else
    echo "cpulimit not available, using nice priority only"
    # Run with nice priority to be less aggressive
    setsid nice -n 10 python3 run_llm_analysis.py </dev/null >llm_analysis_limited.log 2>&1 &
fi

# Get the PID for monitoring
sleep 2
PID=$(pgrep -f "run_llm_analysis.py" | head -1)

if [ -n "$PID" ]; then
    echo "LLM analysis started with PID: $PID"
    echo "Monitor with: tail -f llm_analysis_limited.log"
    echo "Check load with: uptime"
    echo "Stop with: pkill -f run_llm_analysis.py"
else
    echo "Failed to start LLM analysis process"
    exit 1
fi