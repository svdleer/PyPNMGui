#!/bin/bash
# PyPNM Agent - Install from Git Clone
# Clone repo on script3a and run agent directly
#
# Usage on script3a:
#   git clone https://github.com/svdleer/PyPNMGui.git
#   cd PyPNMGui/agent
#   ./install-from-git.sh

set -e

VENV_DIR="${HOME}/python/venv"
INSTALL_DIR="${HOME}/.pypnm-agent"
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Proxy configuration for pip
export http_proxy="http://proxy.ext.oss.local:8080"
export https_proxy="http://proxy.ext.oss.local:8080"
export HTTP_PROXY="http://proxy.ext.oss.local:8080"
export HTTPS_PROXY="http://proxy.ext.oss.local:8080"

echo "=========================================="
echo "  PyPNM Agent Install from Git"
echo "=========================================="
echo ""
echo "Agent source: $AGENT_DIR"
echo "Install to:   $INSTALL_DIR"
echo "Using venv:   $VENV_DIR"
echo ""

# Check venv exists
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "ERROR: venv not found at $VENV_DIR"
    echo "Create with: python3 -m venv $VENV_DIR"
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR/logs"

# Symlink agent.py instead of copying (for easy updates)
ln -sf "$AGENT_DIR/agent.py" "$INSTALL_DIR/agent.py"
ln -sf "$AGENT_DIR/ssh_tunnel.py" "$INSTALL_DIR/ssh_tunnel.py" 2>/dev/null || true

# Copy requirements (not symlink)
cp "$AGENT_DIR/requirements.txt" "$INSTALL_DIR/"

# Install dependencies in venv
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$AGENT_DIR/requirements.txt"

# Create config if not exists
if [ ! -f "$INSTALL_DIR/agent_config.json" ]; then
    cat > "$INSTALL_DIR/agent_config.json" << 'EOF'
{
    "agent_id": "jump-server-script3a",
    
    "pypnm_server": {
        "url": "ws://127.0.0.1:5050/ws/agent",
        "auth_token": "dev-token-change-me",
        "reconnect_interval": 5
    },
    
    "ssh_tunnel": {
        "enabled": true,
        "ssh_host": "appdb-sh.oss.local",
        "ssh_port": 22,
        "ssh_user": "svdleer",
        "ssh_key_file": "~/.ssh/id_rsa",
        "local_port": 5050,
        "remote_port": 5050
    },
    
    "cmts": {
        "snmp_direct": true,
        "ssh_enabled": true
    },
    
    "cm_proxy": {
        "host": "hop-access.oss.local",
        "port": 22,
        "username": "svdleer",
        "key_file": "~/.ssh/id_rsa"
    },
    
    "equalizer": {
        "host": "hop-access.oss.local",
        "port": 22,
        "username": "svdleer",
        "key_file": "~/.ssh/id_rsa"
    }
}
EOF
    echo "Created config: $INSTALL_DIR/agent_config.json"
fi

# Create start script
cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
VENV="${HOME}/python/venv"
LOGFILE="logs/agent.log"

if pgrep -f "agent.py" > /dev/null 2>&1; then
    echo "Agent already running"
    exit 0
fi

echo "Starting PyPNM Agent..."
nohup "$VENV/bin/python" agent.py --config agent_config.json >> "$LOGFILE" 2>&1 &
echo "Agent started (PID: $!)"
echo "Log: $LOGFILE"
EOF
chmod +x "$INSTALL_DIR/start.sh"

# Create stop script
cat > "$INSTALL_DIR/stop.sh" << 'EOF'
#!/bin/bash
echo "Stopping PyPNM Agent..."
pkill -f "agent.py" 2>/dev/null || echo "Agent not running"
EOF
chmod +x "$INSTALL_DIR/stop.sh"

# Create update script
cat > "$INSTALL_DIR/update.sh" << EOF
#!/bin/bash
# Update agent from git
cd "$AGENT_DIR/.."
git pull
cd "$AGENT_DIR"
"$VENV_DIR/bin/pip" install -q -r requirements.txt
cd "$INSTALL_DIR"
./stop.sh
sleep 1
./start.sh
echo "Agent updated and restarted"
EOF
chmod +x "$INSTALL_DIR/update.sh"

echo ""
echo "=========================================="
echo "  Installation complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  Start:  cd $INSTALL_DIR && ./start.sh"
echo "  Stop:   cd $INSTALL_DIR && ./stop.sh"
echo "  Update: cd $INSTALL_DIR && ./update.sh"
echo "  Logs:   tail -f $INSTALL_DIR/logs/agent.log"
echo ""
echo "To update agent after git pull:"
echo "  cd $INSTALL_DIR && ./update.sh"
echo ""
