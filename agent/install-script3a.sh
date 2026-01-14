#!/bin/bash
# PyPNM Agent - Install Script for script3a.oss.local
# Uses existing venv at ~/python/venv
#
# Usage:
#   1. Copy agent files to script3a
#   2. Run: ./install-script3a.sh

set -e

VENV_DIR="${HOME}/python/venv"
INSTALL_DIR="${HOME}/.pypnm-agent"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Proxy configuration for pip
export http_proxy="http://proxy.ext.oss.local:8080"
export https_proxy="http://proxy.ext.oss.local:8080"
export HTTP_PROXY="http://proxy.ext.oss.local:8080"
export HTTPS_PROXY="http://proxy.ext.oss.local:8080"

echo "=========================================="
echo "  PyPNM Agent Install for script3a"
echo "=========================================="
echo ""
echo "Using venv: $VENV_DIR"
echo "Install to: $INSTALL_DIR"
echo "Proxy: $http_proxy"
echo ""

# Check venv exists
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "ERROR: venv not found at $VENV_DIR"
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR/logs"

# Copy agent files
cp "$SCRIPT_DIR/agent.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/ssh_tunnel.py" ] && cp "$SCRIPT_DIR/ssh_tunnel.py" "$INSTALL_DIR/"

# Install dependencies in venv
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q websocket-client

# Create config if not exists
if [ ! -f "$INSTALL_DIR/agent_config.json" ]; then
    cat > "$INSTALL_DIR/agent_config.json" << 'EOF'
{
    "agent_id": "jump-server-script3a",
    
    "pypnm_server": {
        "_comment": "Connect via SSH tunnel to appdb.oss.local",
        "url": "ws://127.0.0.1:5050/ws/agent",
        "auth_token": "dev-token-change-me",
        "reconnect_interval": 5
    },
    
    "pypnm_ssh_tunnel": {
        "_comment": "SSH tunnel to appdb-sh.oss.local for WebSocket + Redis",
        "enabled": true,
        "ssh_host": "appdb-sh.oss.local",
        "ssh_port": 22,
        "ssh_user": "svdleer",
        "local_port": 5050,
        "remote_port": 5050
    },
    
    "cmts_access": {
        "snmp_direct": true,
        "ssh_enabled": false
    },
    
    "cm_proxy": {
        "_comment": "Jump host to reach cable modems for SNMP (disabled for now)",
        "host": null,
        "port": 22,
        "username": "svdleer"
    },
    
    "redis": {
        "_comment": "Redis on appdb - accessible via SSH tunnel (localhost:6379)",
        "host": "127.0.0.1",
        "port": 6379,
        "ttl": 300
    },
    
    "tftp_server": {
        "host": null,
        "tftp_path": "/tftpboot"
    }
}
EOF
    chmod 600 "$INSTALL_DIR/agent_config.json"
    echo "Created config: $INSTALL_DIR/agent_config.json"
fi

# Create start script (agent handles its own SSH tunnel, we add Redis tunnel)
cat > "$INSTALL_DIR/start.sh" << EOF
#!/bin/bash
cd "\$(dirname "\$0")"
VENV="$VENV_DIR"

# Check if already running
if [ -f agent.pid ] && kill -0 \$(cat agent.pid) 2>/dev/null; then
    echo "Agent already running (PID: \$(cat agent.pid))"
    exit 0
fi

# Start Redis SSH tunnel (port 6379) if not already running
if ! pgrep -f "ssh.*6379:localhost:6379.*appdb-sh" > /dev/null 2>&1; then
    echo "Starting Redis SSH tunnel to appdb-sh.oss.local..."
    ssh -f -N -L 6379:localhost:6379 svdleer@appdb-sh.oss.local -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes 2>/dev/null
    sleep 1
    if pgrep -f "ssh.*6379:localhost:6379.*appdb-sh" > /dev/null 2>&1; then
        echo "Redis tunnel established (localhost:6379)"
    else
        echo "WARNING: Redis tunnel failed (caching disabled)"
    fi
fi

# Start agent (it will create its own WebSocket SSH tunnel based on config)
nohup "\$VENV/bin/python" agent.py -c agent_config.json > logs/agent.log 2>&1 &
echo \$! > agent.pid
echo "Agent started (PID: \$!)"
echo "Logs: \$(pwd)/logs/agent.log"
EOF
chmod +x "$INSTALL_DIR/start.sh"

# Create stop script
cat > "$INSTALL_DIR/stop.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "Stopping PyPNM Agent..."

# Stop by PID file if exists
if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Sending SIGTERM to agent (PID: $PID)..."
        kill -TERM $PID 2>/dev/null
        sleep 2
        if ps -p $PID > /dev/null 2>&1; then
            echo "Force killing agent..."
            kill -9 $PID 2>/dev/null
        fi
    fi
    rm -f agent.pid
else
    # Fallback: find by process name
    AGENT_PID=$(pgrep -f "python.*agent.py" 2>/dev/null)
    if [ -n "$AGENT_PID" ]; then
        echo "Sending SIGTERM to agent (PID: $AGENT_PID)..."
        kill -TERM $AGENT_PID 2>/dev/null
        sleep 2
        if ps -p $AGENT_PID > /dev/null 2>&1; then
            kill -9 $AGENT_PID 2>/dev/null
        fi
    fi
fi

# Kill SSH tunnels started by agent
pkill -f "ssh.*-L.*5050" 2>/dev/null
pkill -f "ssh.*6379:localhost:6379.*appdb-sh" 2>/dev/null
pkill -f "ssh.*appdb" 2>/dev/null

echo "Agent stopped"
EOF
chmod +x "$INSTALL_DIR/stop.sh"

# Create status script
cat > "$INSTALL_DIR/status.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -f agent.pid ] && kill -0 $(cat agent.pid) 2>/dev/null; then
    echo "Agent RUNNING (PID: $(cat agent.pid))"
    pgrep -f "ssh.*6379:localhost:6379.*appdb-sh" > /dev/null && echo "Redis tunnel: ACTIVE" || echo "Redis tunnel: DOWN"
    echo "---"
    tail -10 logs/agent.log 2>/dev/null
else
    echo "Agent STOPPED"
fi
EOF
chmod +x "$INSTALL_DIR/status.sh"

# Create run script (foreground for debug)
cat > "$INSTALL_DIR/run.sh" << EOF
#!/bin/bash
cd "\$(dirname "\$0")"
"$VENV_DIR/bin/python" agent.py -c agent_config.json -v
EOF
chmod +x "$INSTALL_DIR/run.sh"

echo ""
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  cd $INSTALL_DIR"
echo "  ./start.sh    - Start agent"
echo "  ./stop.sh     - Stop agent"
echo "  ./status.sh   - Check status"
echo "  ./run.sh      - Run in foreground (debug)"
echo ""
echo "Config: $INSTALL_DIR/agent_config.json"
echo ""
