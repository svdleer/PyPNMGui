#!/bin/bash
# PyPNM Agent Installation Script
# For CMTS agent on appdb-sh.oss.local

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.env"

echo "=========================================="
echo "PyPNM CMTS Agent Installation"
echo "=========================================="
echo "Host: ${PYPNM_API_HOST}"
echo "Agent ID: ${CMTS_AGENT_ID}"
echo "Installing as user: $(whoami)"
echo ""

# Create installation directory in user home
INSTALL_DIR="${HOME}/pypnm-agent"
echo "Creating installation directory: ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Please install it:"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-pip python3-venv"
    echo "  RHEL/CentOS: sudo yum install python3 python3-pip"
    exit 1
fi

echo "✓ Python 3 is available"

# Install pyPNMAgent
if [ ! -d "pyPNMAgent" ]; then
    echo "Installing pyPNMAgent..."
    
    # Check if git is available
    if command -v git &> /dev/null; then
        echo "Cloning from git..."
        git clone https://github.com/your-org/pyPNMAgent.git || {
            echo "✗ Git clone failed. Trying local copy..."
        }
    fi
    
    # If git failed or not available, check for bundled copy
    if [ ! -d "pyPNMAgent" ] && [ -d "${SCRIPT_DIR}/pyPNMAgent" ]; then
        echo "Using bundled copy..."
        cp -r "${SCRIPT_DIR}/pyPNMAgent" .
    fi
    
    # Final check
    if [ ! -d "pyPNMAgent" ]; then
        echo "✗ pyPNMAgent source not found"
        echo "Please either:"
        echo "  1. Install git: sudo apt-get install git"
        echo "  2. Or manually copy pyPNMAgent directory here"
        exit 1
    fi
fi

cd pyPNMAgent

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Install dependencies
echo "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Copy configuration
echo "Creating agent configuration..."
cat > agent_config.json <<EOF
{
  "agent_id": "${CMTS_AGENT_ID}",
  "pypnm_server": {
    "url": "ws://localhost:8000/api/agents/ws",
    "auth_token": "${AGENT_AUTH_TOKEN}"
  },
  "cmts_access": {
    "enabled": true,
    "community": "${SNMP_COMMUNITY_READ}",
    "write_community": "${SNMP_COMMUNITY_WRITE}"
  },
  "cm_access": {
    "enabled": false
  },
  "tftp_server": {
    "tftp_path": "${TFTP_PATH}"
  }
}
EOF

# Copy forward tunnel script
echo "Installing forward tunnel script..."
cp "${SCRIPT_DIR}/create-forward-tunnel.sh" .
chmod +x create-forward-tunnel.sh

# Copy reverse tunnel script (for Server B)
echo "Installing reverse tunnel script (for Server B)..."
cp "${SCRIPT_DIR}/create-reverse-tunnel.sh" .
chmod +x create-reverse-tunnel.sh

# Create systemd user services
echo "Creating systemd user services..."

# Check if systemd user session is available
if ! systemctl --user status >/dev/null 2>&1; then
    echo "⚠ Warning: systemd user session not available"
    echo "  You may need to run this script in a login shell (not via sudo)"
    echo "  Or enable lingering: sudo loginctl enable-linger $USER"
    echo ""
    echo "For now, you can start tunnels manually:"
    echo "  ./create-forward-tunnel.sh start"
    echo "  ./create-reverse-tunnel.sh start"
    echo "  cd pyPNMAgent && ../venv/bin/python agent.py --config agent_config.json"
    echo ""
    echo "Skipping systemd service creation..."
else
    # Create user systemd directory
    mkdir -p ~/.config/systemd/user

# Forward tunnel service
cat > ~/.config/systemd/user/pypnm-forward-tunnel.service <<EOF
[Unit]
Description=PyPNM Fo pypnm-forward-tunnel.service pypnm-reverse-tunnel.service
Requires=pypnm-forward-tunnel.service pypnm-reverse-tunnel.servicerward Tunnel to API Server
After=network.target

[Service]
Type=forking
WorkingDirectory=${INSTALL_DIR}/pyPNMAgent
ExecStart=${INSTALL_DIR}/pyPNMAgent/create-forward-tunnel.sh start
ExecStop=${INSTALL_DIR}/pyPNMAgent/create-forward-tunnel.sh stop
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

# Reverse tunnel service
cat > ~/.config/systemd/user/pypnm-reverse-tunnel.service <<EOF
[Unit]
Description=PyPNM Reverse Tunnel to Server B
After=network.target

[Service]
Type=forking
WorkingDirectory=${INSTALL_DIR}/pyPNMAgent
ExecStart=${INSTALL_DIR}/pyPNMAgent/create-reverse-tunnel.sh start
ExecStop=${INSTALL_DIR}/pyPNMAgent/create-reverse-tunnel.sh stop
Restart=always
RestartSec=10

[Install]
WantedBy=default.taforward tunnel: systemctl --user start pypnm-forward-tunnel"
echo "3. Start the reverse tunnel: systemctl --user start pypnm-reverse-tunnel"
echo "4. Start the agent: systemctl --user start pypnm-agent"
echo "5. Enable auto-start:"
echo "   systemctl --user enable pypnm-forward-tunnel"
echo "   systemctl --user enable pypnm-reverse-tunnel"
echo "   systemctl --user enable pypnm-agent"
echo ""
echo "Check status:"
echo "  systemctl --user status pypnm-forward-tunnel"
echo "  systemctl --user status pypnm-reverse-tunnel"
echo "  systemctl --user status pypnm-agent"
echo ""
echo "View logs:"
echo "  journalctl --user -u pypnm-forward-tunnel -f"
echo "  journalctl --user -u pypnm-reverse-tunnel -fM CMTS Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/pyPNMAgent
ExecStart=${INSTALL_DIR}/pyPNMAgent/venv/bin/python agent.py --config agent_config.json
Restart=always
RestartSec=10
StandardOutput=append:${INSTALL_DIR}/pyPNMAgent/logs/agent.log
StandardError=append:${INSTALL_DIR}/pyPNMAgent/logs/agent.error.log

[Install]
WantedBy=default.target
EOF

# Create logs directory
mkdir -p logs

# Reload systemd user daemon
systemctl --user daemon-reload

# Enable lingering (allows user services to run at boot)
loginctl enable-linger $(whoami) 2>/dev/null || echo "Note: Could not enable lingering (may need admin to run: sudo loginctl enable-linger $(whoami))"

echo ""
echo "=========================================="
echo "✓ Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit ${INSTALL_DIR}/pyPNMAgent/agent_config.json if needed"
echo "2. Start the agent: systemctl --user start pypnm-agent"
echo "3. Enable auto-start: systemctl --user enable pypnm-agent"
echo ""
echo "Check status:"
echo "  systemctl --user status pypnm-agent"
echo ""
echo "View logs:"
echo "  journalctl --user -u pypnm-agent -f"
echo "  tail -f ${INSTALL_DIR}/pyPNMAgent/logs/agent.log"
echo ""
