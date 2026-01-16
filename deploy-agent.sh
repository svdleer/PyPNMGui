#!/bin/bash
# Manual agent restart script for script3a
# Copy updated agent.py and restart the service

echo "Copying agent.py to script3a..."
scp -o ControlPath=~/.ssh/cm-%r@%h:%p agent/agent.py svdleer@script3a.oss.local:~/agent.py

echo ""
echo "Agent code updated. To restart the agent service:"
echo "  1. SSH to script3a: ssh script3a.oss.local"
echo "  2. Restart service: sudo systemctl restart pypnm-agent"
echo "  3. Check status: sudo systemctl status pypnm-agent"
echo ""
echo "Or ask the user with sudo access to restart it."
