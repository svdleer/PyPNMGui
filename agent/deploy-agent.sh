#!/bin/bash
# PyPNM Agent - Quick Deploy Script for Jump Server
# SPDX-License-Identifier: Apache-2.0
#
# This script deploys the agent to the jump server via SCP/SSH
# Usage: ./deploy-agent.sh [user@host]

set -e

# Configuration
DEFAULT_TARGET="svdleer@script3a.oss.local"
TARGET="${1:-$DEFAULT_TARGET}"
REMOTE_DIR="/home/svdleer/.pypnm-agent"
LOCAL_AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
ssh "$TARGET" "mkdir -p $REMOTE_DIR/logs"

# Copy agent files
echo -e "${YELLOW}[2/5] Copying agent files...${NC}"
scp -q "$LOCAL_AGENT_DIR/agent.py" "$TARGET:$REMOTE_DIR/"
scp -q "$LOCAL_AGENT_DIR/ssh_tunnel.py" "$TARGET:$REMOTE_DIR/" 2>/dev/null || true
scp -q "$LOCAL_AGENT_DIR/requirements.txt" "$TARGET:$REMOTE_DIR/"

# Copy config if it doesn't exist remotely
echo -e "${YELLOW}[3/5] Checking config...${NC}"
if ! ssh "$TARGET" "test -f $REMOTE_DIR/agent_config.json"; then
    # Generate config for this environment
    cat > /tmp/agent_config.json << 'EOF'
{
    "agent_id": "jump-server-script3a",
    
    "pypnm_server": {
        "url": "ws://appdb-sh.oss.local:5050/api/agents/ws",
        "auth_token": "dev-token-change-me",
        "reconnect_interval": 5
    },
    
    "pypnm_ssh_tunnel": {
        "enabled": false
    },
    
    "cmts_access": {
        "snmp_direct": true,
        "ssh_enabled": false
    },
    
    "cm_proxy": {
        "_comment": "Set to modem-server.oss.local if SNMP to modems needs to go through it",
        "host": null
    },
    
    "tftp_server": {
        "host": "tftp-server.oss.local",
        "port": 22,
        "username": "svdleer",
        "tftp_path": "/tftpboot"
    }
}
EOF
    scp -q /tmp/agent_config.json "$TARGET:$REMOTE_DIR/"
    rm /tmp/agent_config.json
    echo "  Created default config at $REMOTE_DIR/agent_config.json"
else
    echo "  Config already exists, skipping"
fi

# Install Python dependencies
echo -e "${YELLOW}[4/5] Installing Python dependencies...${NC}"
ssh "$TARGET" "cd $REMOTE_DIR && python3 -m venv venv 2>/dev/null || true && source venv/bin/activate && pip install -q --upgrade pip && pip install -q -r requirements.txt"

# Create start/stop scripts
echo -e "${YELLOW}[5/5] Creating control scripts...${NC}"

# Start script
ssh "$TARGET" "cat > $REMOTE_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
source venv/bin/activate

# Check if already running
if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "Agent already running (PID: $PID)"
        exit 0
    fi
fi

# Start agent in background
nohup python agent.py -c agent_config.json > logs/agent.log 2>&1 &
echo $! > agent.pid
echo "Agent started (PID: $!)"
echo "Log: $SCRIPT_DIR/logs/agent.log"
STARTEOF
ssh "$TARGET" "chmod +x $REMOTE_DIR/start.sh"

# Stop script
ssh "$TARGET" "cat > $REMOTE_DIR/stop.sh" << 'STOPEOF'
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
ssh "$TARGET" "chmod +x $REMOTE_DIR/stop.sh"

# Status script
ssh "$TARGET" "cat > $REMOTE_DIR/status.sh" << 'STATUSEOF'
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
ssh "$TARGET" "chmod +x $REMOTE_DIR/status.sh"

# Logs script  
ssh "$TARGET" "cat > $REMOTE_DIR/logs.sh" << 'LOGSEOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
tail -f "$SCRIPT_DIR/logs/agent.log"
LOGSEOF
ssh "$TARGET" "chmod +x $REMOTE_DIR/logs.sh"

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
