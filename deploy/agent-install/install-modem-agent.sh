#!/bin/bash
# PyPNM Agent Installation Script
# For modem agent on hop-access1.ext.oss.local

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.env"

echo "=========================================="
echo "PyPNM Modem Agent Installation"
echo "=========================================="
echo "Host: ${MODEM_AGENT_HOST}"
echo "Agent ID: ${MODEM_AGENT_ID}"
echo "Installing as user: $(whoami)"
echo ""

# Check for autossh
if ! command -v autossh &> /dev/null; then
    echo "✗ autossh not found. Please install it:"
    echo "  Ubuntu/Debian: sudo apt-get install autossh"
    echo "  RHEL/CentOS: sudo yum install autossh"
    exit 1
fi

echo "✓ autossh is available"

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
    echo "Cloning pyPNMAgent..."
    if [ -d "${SCRIPT_DIR}/../../pyPNMAgent" ]; then
        cp -r "${SCRIPT_DIR}/../../pyPNMAgent" .
    else
        echo "✗ pyPNMAgent source not found"
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
  "agent_id": "${MODEM_AGENT_ID}",
  "pypnm_api_url": "${PYPNM_API_URL}",
  "websocket_url": "${PYPNM_WEBSOCKET_URL}",
  "auth_token": "${AGENT_AUTH_TOKEN}",
  "appdb": {
    "api_url": "${APPDB_API_URL}",
    "api_user": "${APPDB_API_USER}",
    "api_pass": "${APPDB_API_PASS}"
  },
  "snmp": {
    "community": "${SNMP_COMMUNITY_READ}",
    "write_community": "${SNMP_COMMUNITY_WRITE}",
    "timeout": 5,
    "retries": 3
  },
  "tftp": {
    "ipv4": "${TFTP_IPV4}",
    "ipv4_alt": "${TFTP_IPV4_ALT}",
    "path": "${TFTP_PATH}"
  }
}
EOF

# Copy autossh tunnel script
echo "Installing autossh tunnel script..."
cp "${SCRIPT_DIR}/autossh-tunnel-appdb.sh" .
chmod +x autossh-tunnel-appdb.sh

# Create systemd user services
echo "Creating systemd user services..."

# Create user systemd directory
mkdir -p ~/.config/systemd/user

# Tunnel service
cat > ~/.config/systemd/user/pypnm-tunnel.service <<EOF
[Unit]
Description=PyPNM AppDB SSH Tunnel
After=network.target

[Service]
Type=forking
WorkingDirectory=${INSTALL_DIR}/pyPNMAgent
ExecStart=${INSTALL_DIR}/pyPNMAgent/autossh-tunnel-appdb.sh start
ExecStop=${INSTALL_DIR}/pyPNMAgent/autossh-tunnel-appdb.sh stop
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

# Agent service
cat > ~/.config/systemd/user/pypnm-agent.service <<EOF
[Unit]
Description=PyPNM Modem Agent
After=network.target pypnm-tunnel.service
Requires=pypnm-tunnel.service

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
echo "2. Start the tunnel: systemctl --user start pypnm-tunnel"
echo "3. Start the agent: systemctl --user start pypnm-agent"
echo "4. Enable auto-start:"
echo "   systemctl --user enable pypnm-tunnel"
echo "   systemctl --user enable pypnm-agent"
echo ""
echo "Check status:"
echo "  systemctl --user status pypnm-tunnel"
echo "  systemctl --user status pypnm-agent"
echo ""
echo "View logs:"
echo "  journalctl --user -u pypnm-tunnel -f"
echo "  journalctl --user -u pypnm-agent -f"
echo "  tail -f ${INSTALL_DIR}/pyPNMAgent/logs/agent.log"
echo ""
