#!/bin/bash
# PyPNM Agent - Quick Deploy Script for Jump Server
# SPDX-License-Identifier: Apache-2.0
#
# This script deploys the agent to the jump server via SCP/SSH
# Usage: ./deploy-agent.sh [user@host] [ssh-port]

set -e

# Configuration - Via SSH tunnel on port 2222
DEFAULT_TARGET="svdleer@localhost"
DEFAULT_SSH_PORT="2222"
TARGET="${1:-$DEFAULT_TARGET}"
SSH_PORT="${2:-$DEFAULT_SSH_PORT}"
REMOTE_DIR="/home/svdleer/.pypnm-agent"
LOCAL_AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"

# SSH/SCP options
SSH_OPTS="-p $SSH_PORT"
SCP_OPTS="-P $SSH_PORT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=========================================="
echo "  PyPNM Agent Deployment"
echo -e "==========================================${NC}"
echo ""
echo "Target: $TARGET"
echo "Remote Dir: $REMOTE_DIR"
echo ""

# Check if agent files exist
if [ ! -f "$LOCAL_AGENT_DIR/agent.py" ]; then
    echo -e "${RED}ERROR: agent.py not found in $LOCAL_AGENT_DIR${NC}"
    exit 1
fi

# Create remote directory
echo -e "${YELLOW}[1/5] Creating remote directory...${NC}"
ssh $SSH_OPTS "$TARGET" "mkdir -p $REMOTE_DIR/logs"

# Copy agent files
echo -e "${YELLOW}[2/5] Copying agent files...${NC}"
scp -q $SCP_OPTS "$LOCAL_AGENT_DIR/agent.py" "$TARGET:$REMOTE_DIR/"
scp -q $SCP_OPTS "$LOCAL_AGENT_DIR/ssh_tunnel.py" "$TARGET:$REMOTE_DIR/" 2>/dev/null || true
scp -q $SCP_OPTS "$LOCAL_AGENT_DIR/requirements.txt" "$TARGET:$REMOTE_DIR/"

# Copy config if it doesn't exist remotely
echo -e "${YELLOW}[3/5] Checking config...${NC}"
if ! ssh $SSH_OPTS "$TARGET" "test -f $REMOTE_DIR/agent_config.json"; then
    # Generate config for this environment
    cat > /tmp/agent_config.json << 'EOF'
{
    "agent_id": "jump-server-appdb",
    
    "pypnm_server": {
        "_comment": "Connect to local GUI server running in Docker",
        "url": "ws://localhost:5050/api/agents/ws",
        "auth_token": "dev-token-change-me",
        "reconnect_interval": 5
    },
    
    "pypnm_ssh_tunnel": {
        "enabled": false
    },
    
    "cmts_access": {
        "_comment": "Direct SNMP access to CMTS devices",
        "snmp_direct": true,
        "ssh_enabled": false
    },
    
    "cm_proxy": {
        "_comment": "Not needed - direct SNMP access from this server",
        "host": null
    },
    
    "tftp_server": {
        "_comment": "TFTP server for PNM file retrieval",
        "host": null,
        "tftp_path": "/tftpboot"
    }
}
EOF
    scp -q $SCP_OPTS /tmp/agent_config.json "$TARGET:$REMOTE_DIR/"
    rm /tmp/agent_config.json
    echo "  Created default config at $REMOTE_DIR/agent_config.json"
else
    echo "  Config already exists, skipping"
fi

# Install Python dependencies (try system Python first, then venv)
echo -e "${YELLOW}[4/5] Checking Python dependencies...${NC}"
# Check if websocket-client is available system-wide
if ssh $SSH_OPTS "$TARGET" "python3 -c 'import websocket' 2>/dev/null"; then
    echo "  Using system Python (websocket-client already installed)"
    # Create a simple wrapper that uses system Python
    ssh $SSH_OPTS "$TARGET" "mkdir -p $REMOTE_DIR/venv/bin && ln -sf /usr/bin/python3 $REMOTE_DIR/venv/bin/python"
else
    echo "  Creating venv and installing dependencies..."
    ssh $SSH_OPTS "$TARGET" "cd $REMOTE_DIR && python3 -m venv venv 2>/dev/null || true && source venv/bin/activate && pip install -q --upgrade pip && pip install -q -r requirements.txt"
fi

# Create start/stop scripts
echo -e "${YELLOW}[5/5] Creating control scripts...${NC}"

# Start script
ssh $SSH_OPTS "$TARGET" "cat > $REMOTE_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Use venv if it exists and has activate, otherwise use system Python
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

# Check if already running
if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "Agent already running (PID: $PID)"
        exit 0
    fi
fi

# Start agent in background
nohup python3 agent.py -c agent_config.json > logs/agent.log 2>&1 &
echo $! > agent.pid
echo "Agent started (PID: $!)"
echo "Log: $SCRIPT_DIR/logs/agent.log"
STARTEOF
ssh $SSH_OPTS "$TARGET" "chmod +x $REMOTE_DIR/start.sh"

# Stop script
ssh $SSH_OPTS "$TARGET" "cat > $REMOTE_DIR/stop.sh" << 'STOPEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Agent stopped (PID: $PID)"
    else
        echo "Agent not running"
    fi
    rm -f agent.pid
else
    echo "No PID file found"
fi
STOPEOF
ssh $SSH_OPTS "$TARGET" "chmod +x $REMOTE_DIR/stop.sh"

# Status script
ssh $SSH_OPTS "$TARGET" "cat > $REMOTE_DIR/status.sh" << 'STATUSEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "Agent is RUNNING (PID: $PID)"
        echo ""
        echo "Recent log:"
        tail -10 logs/agent.log
        exit 0
    fi
fi
echo "Agent is STOPPED"
STATUSEOF
ssh $SSH_OPTS "$TARGET" "chmod +x $REMOTE_DIR/status.sh"

# Logs script  
ssh $SSH_OPTS "$TARGET" "cat > $REMOTE_DIR/logs.sh" << 'LOGSEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
tail -f "$SCRIPT_DIR/logs/agent.log"
LOGSEOF
ssh $SSH_OPTS "$TARGET" "chmod +x $REMOTE_DIR/logs.sh"

echo ""
echo -e "${GREEN}=========================================="
echo "  Deployment Complete!"
echo -e "==========================================${NC}"
echo ""
echo "Agent installed to: $TARGET:$REMOTE_DIR"
echo ""
echo "Commands (run on $TARGET):"
echo "  cd $REMOTE_DIR"
echo "  ./start.sh    - Start agent in background"
echo "  ./stop.sh     - Stop agent"
echo "  ./status.sh   - Check agent status"
echo "  ./logs.sh     - Tail agent logs"
echo ""
echo "Or run manually:"
echo "  source venv/bin/activate"
echo "  python agent.py -c agent_config.json -v"
echo ""
echo -e "${YELLOW}NOTE: Edit $REMOTE_DIR/agent_config.json to configure:${NC}"
echo "  - PyPNM server URL (currently: appdb-sh.oss.local:5050)"
echo "  - Authentication token"
echo "  - CMTS SNMP community strings"
