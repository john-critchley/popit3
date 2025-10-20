#!/bin/bash
# LLM Analysis Runner with SSH isolation
# This completely isolates the process by running it over SSH

echo "Starting LLM analysis via SSH for complete isolation..."

# Kill any existing processes
pkill -f "run_llm_analysis.py" || true
pkill -f "job_analysis_script.py" || true

# Create a script to run over SSH
cat > /tmp/run_llm_remote.sh << 'EOF'
#!/bin/bash
cd /home/john/py/popit3
nice -n 19 python3 run_llm_analysis.py > llm_analysis_ssh.log 2>&1
echo "LLM analysis completed at $(date)" >> llm_analysis_ssh.log
EOF

chmod +x /tmp/run_llm_remote.sh

# Run the analysis via SSH to localhost for complete isolation
ssh -o StrictHostKeyChecking=no localhost 'bash /tmp/run_llm_remote.sh' &

SSH_PID=$!
echo "Started LLM analysis via SSH (PID: $SSH_PID)"
echo "Process is completely isolated from this terminal session"
echo "Monitor with: tail -f llm_analysis_ssh.log"
echo "Check with: ssh localhost 'ps aux | grep run_llm_analysis'"

# Clean up the temp script after a moment
sleep 2
rm -f /tmp/run_llm_remote.sh

echo "SSH session initiated. LLM should be running isolated."