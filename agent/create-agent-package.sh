#!/bin/bash
# PyPNM Agent - Manual Install Package Creator
# Creates a tar.gz that can be copied to the jump server
#
# Usage: ./create-agent-package.sh
#        scp pypnm-agent.tar.gz user@script3a.oss.local:~
#        ssh user@script3a.oss.local "tar -xzf pypnm-agent.tar.gz && cd pypnm-agent && ./install.sh"

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_DIR="/tmp/pypnm-agent-package"
OUTPUT_FILE="${SCRIPT_DIR}/pypnm-agent.tar.gz"

echo "=========================================="
echo "  Creating PyPNM Agent Package"
echo "=========================================="

# Clean up
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

# Copy agent files
cp "$SCRIPT_DIR/agent.py" "$PACKAGE_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$PACKAGE_DIR/"
[ -f "$SCRIPT_DIR/ssh_tunnel.py" ] && cp "$SCRIPT_DIR/ssh_tunnel.py" "$PACKAGE_DIR/"

# Create config template for script3a -> appdb connection
cat > "$PACKAGE_DIR/agent_config.json" << 'EOF'
{
    "agent_id": "jump-server-script3a",
    
    "pypnm_server": {
        "_comment": "Connect to PyPNM GUI on appdb.oss.local via direct connection",
        "url": "ws://appdb.oss.local:5050/socket.io/?EIO=4&transport=websocket",
        "auth_token": "dev-token-change-me",
        "reconnect_interval": 5
    },
    
    "pypnm_ssh_tunnel": {
        "_comment": "SSH tunnel if needed (usually not, appdb is reachable)",
        "enabled": false
    },
    
    "cmts_access": {
        "_comment": "Direct SNMP access to CMTS from jump server",
        "snmp_direct": true,
        "ssh_enabled": false
    },
    
    "cm_proxy": {
        "_comment": "Not needed - direct SNMP from jump server",
        "host": null
    },
    
    "tftp_server": {
        "_comment": "TFTP server for PNM files (configure if needed)",
        "host": null,
        "tftp_path": "/tftpboot"
    }
}
EOF

# Create install script
cat > "$PACKAGE_DIR/install.sh" << 'INSTALL_EOF'
#!/bin/bash
# PyPNM Agent - Install Script for Jump Server
set -e

INSTALL_DIR="${HOME}/.pypnm-agent"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing PyPNM Agent to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR/logs"
cp "$SCRIPT_DIR/agent.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/ssh_tunnel.py" ] && cp "$SCRIPT_DIR/ssh_tunnel.py" "$INSTALL_DIR/"

# Only copy config if not exists
if [ ! -f "$INSTALL_DIR/agent_config.json" ]; then
    cp "$SCRIPT_DIR/agent_config.json" "$INSTALL_DIR/"
    chmod 600 "$INSTALL_DIR/agent_config.json"
    echo "Created config: $INSTALL_DIR/agent_config.json"
fi

# Create start script
cat > "$INSTALL_DIR/start.sh" << 'START_EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -f agent.pid ] && kill -0 $(cat agent.pid) 2>/dev/null; then
    echo "Agent already running (PID: $(cat agent.pid))"
    exit 0
fi
nohup python3 agent.py -c agent_config.json > logs/agent.log 2>&1 &
echo $! > agent.pid
echo "Agent started (PID: $!)"
echo "Logs: $(pwd)/logs/agent.log"
START_EOF
chmod +x "$INSTALL_DIR/start.sh"

# Create stop script
cat > "$INSTALL_DIR/stop.sh" << 'STOP_EOF'
#!/bin/bash
cd "$(dirname "$0")"
[ -f agent.pid ] && kill $(cat agent.pid) 2>/dev/null && rm agent.pid && echo "Agent stopped" || echo "Agent not running"
STOP_EOF
chmod +x "$INSTALL_DIR/stop.sh"

# Create status script
cat > "$INSTALL_DIR/status.sh" << 'STATUS_EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -f agent.pid ] && kill -0 $(cat agent.pid) 2>/dev/null; then
    echo "Agent RUNNING (PID: $(cat agent.pid))"
    tail -5 logs/agent.log 2>/dev/null
else
    echo "Agent STOPPED"
fi
STATUS_EOF
chmod +x "$INSTALL_DIR/status.sh"

# Create run-foreground script (for debugging)
cat > "$INSTALL_DIR/run.sh" << 'RUN_EOF'
#!/bin/bash
cd "$(dirname "$0")"
python3 agent.py -c agent_config.json -v
RUN_EOF
chmod +x "$INSTALL_DIR/run.sh"

echo ""
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo ""
echo "Agent installed to: $INSTALL_DIR"
echo ""
echo "IMPORTANT: Edit config before starting:"
echo "  vi $INSTALL_DIR/agent_config.json"
echo ""
echo "  - Set pypnm_server.url to: ws://appdb.oss.local:5050/socket.io/?EIO=4&transport=websocket"
echo "  - Set auth_token to match the server"
echo ""
echo "Commands:"
echo "  cd $INSTALL_DIR"
echo "  ./start.sh    - Start agent in background"
echo "  ./stop.sh     - Stop agent"
echo "  ./status.sh   - Check status"
echo "  ./run.sh      - Run in foreground (debug)"
echo ""
INSTALL_EOF
chmod +x "$PACKAGE_DIR/install.sh"

# Create the tar.gz
cd /tmp
tar -czf "$OUTPUT_FILE" pypnm-agent-package --transform 's/pypnm-agent-package/pypnm-agent/'

echo ""
echo "Package created: $OUTPUT_FILE"
echo ""
echo "To deploy to script3a.oss.local:"
echo "  1. scp $OUTPUT_FILE user@script3a.oss.local:~"
echo "  2. ssh user@script3a.oss.local"
echo "  3. tar -xzf pypnm-agent.tar.gz"
echo "  4. cd pypnm-agent && ./install.sh"
echo "  5. Edit ~/.pypnm-agent/agent_config.json"
echo "  6. cd ~/.pypnm-agent && ./start.sh"
echo ""

# Cleanup
rm -rf "$PACKAGE_DIR"
