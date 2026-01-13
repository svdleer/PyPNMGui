#!/bin/bash
# PyPNM Web GUI - Start with Agent Support
# SPDX-License-Identifier: Apache-2.0

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Set environment variables for agent mode
export ENABLE_AGENT_WEBSOCKET=true
export AGENT_AUTH_TOKEN="${AGENT_AUTH_TOKEN:-change-this-token}"
export DATA_MODE=agent

# Change to backend directory
cd "$SCRIPT_DIR/backend"

# Start Flask application with SocketIO
echo "=============================================="
echo "  PyPNM Web GUI - Agent Mode"
echo "=============================================="
echo ""
echo "WebSocket endpoint for agents: ws://0.0.0.0:5050/agent"
echo "Web interface: http://127.0.0.1:5050"
echo ""
echo "Configure your agent with:"
echo "  URL: ws://<this-server-ip>:5050/agent"
echo "  Token: $AGENT_AUTH_TOKEN"
echo ""
python run.py
