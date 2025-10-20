#!/bin/bash
echo "=== JobServe Email Processing System Health Check ==="
echo "Date: $(date)"
echo

echo "1. CURRENT JOB DATABASE STATUS:"
python3 -c "
import sys
sys.path.append('.')
from query_jobs import get_all_jobs
jobs = get_all_jobs()
print(f'Total jobs in database: {len(jobs)}')

# Get recent jobs
recent = []
for msg_id, data in jobs:
    date = data.get('headers', {}).get('Date', '')
    subject = data.get('headers', {}).get('Subject', '')[:60]
    ref = data.get('jobserve_ref', 'Unknown')
    recent.append((date, ref, subject))

recent.sort(reverse=True)
print('Most recent 5 jobs:')
for date, ref, subject in recent[:5]:
    print(f'  {date}: {ref} - {subject}...')
"
echo

echo "2. RECENT CRON ACTIVITY (last 50 lines):"
tail -50 out.log | grep -E "(RC:|Processing:|job suggestion|ERROR|WARNING)" | tail -10
echo

echo "3. PROCESS LOCK STATUS:"
if [ -f /tmp/popit3.lock ]; then
    echo "⚠️  Lock file exists: /tmp/popit3.lock"
    echo "Contents: $(cat /tmp/popit3.lock 2>/dev/null || echo 'Cannot read')"
    if ps -p "$(cat /tmp/popit3.lock 2>/dev/null)" > /dev/null 2>&1; then
        echo "Process is still running"
    else
        echo "Stale lock file (process not running)"
    fi
else
    echo "✅ No lock file - system available"
fi
echo

echo "4. RECENT EMAIL PROCESSING (today's activity):"
grep "$(date +%Y-%m-%d)" out.log 2>/dev/null | wc -l | xargs echo "Lines logged today:"
echo "Recent job processing:"
grep -E "job suggestion.*Processing:" out.log 2>/dev/null | tail -5
echo

echo "5. DATABASE FILE STATUS:"
ls -la ~/.js*.gdbm* 2>/dev/null | head -3
echo

echo "6. ERROR CHECK (recent errors):"
tail -100 out.log | grep -i -E "(error|exception|traceback|fail)" | tail -5
if [ $? -ne 0 ]; then
    echo "✅ No recent errors found"
fi
echo

echo "7. SYSTEM RESOURCES:"
echo "Disk usage: $(df -h . | tail -1 | awk '{print $4}') available"
echo "Load average: $(uptime | sed 's/.*load average: //')"
echo

echo "=== SUMMARY ==="
python3 -c "
import os
from datetime import datetime, timedelta

# Check if system seems healthy
issues = []

# Check lock file
if os.path.exists('/tmp/popit3.lock'):
    issues.append('Process lock exists')

# Check recent activity
try:
    with open('out.log', 'r') as f:
        recent_lines = f.readlines()[-20:]
    
    # Look for recent RC: lines (successful completions)
    recent_completions = [line for line in recent_lines if 'RC: 0' in line]
    if not recent_completions:
        issues.append('No recent successful completions')
        
except:
    issues.append('Cannot read log file')

if issues:
    print('🔴 ISSUES FOUND:')
    for issue in issues:
        print(f'  - {issue}')
else:
    print('🟢 SYSTEM APPEARS HEALTHY')

print(f'Next cron runs at: :15 and :45 (regular), :05 and :35 (reprocess)')
"