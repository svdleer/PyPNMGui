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
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Create installation directory
INSTALL_DIR="/opt/pypnm-agent"
echo "Creating installation directory: ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Installing..."
    if command -v apt-get &> /dev/null; then
        apt-get install -y python3 python3-pip python3-venv
    elif command -v yum &> /dev/null; then
        yum install -y python3 python3-pip
    fi
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
  "agent_id": "${CMTS_AGENT_ID}",
  "pypnm_api_url": "${PYPNM_API_URL}",
  "websocket_url": "${PYPNM_WEBSOCKET_URL}",
  "auth_token": "${AGENT_AUTH_TOKEN}",
  "appdb": {
    "api_url": "https://appdb.oss.local/isw/api",
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

# Create systemd service (no tunnel needed for CMTS agent)
echo "Creating systemd service..."

cat > /etc/systemd/system/pypnm-agent.service <<EOF
[Unit]
Description=PyPNM CMTS Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}/pyPNMAgent
ExecStart=${INSTALL_DIR}/pyPNMAgent/venv/bin/python agent.py --config agent_config.json
Restart=always
RestartSec=10
StandardOutput=append:${INSTALL_DIR}/pyPNMAgent/logs/agent.log
StandardError=append:${INSTALL_DIR}/pyPNMAgent/logs/agent.error.log

[Install]
WantedBy=multi-user.target
EOF

# Create logs directory
mkdir -p logs

# Reload systemd
systemctl daemon-reload

echo ""
echo "=========================================="
echo "✓ Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit ${INSTALL_DIR}/pyPNMAgent/agent_config.json if needed"
echo "2. Start the agent: systemctl start pypnm-agent"
echo "3. Enable auto-start: systemctl enable pypnm-agent"
echo ""
echo "Check status:"
echo "  systemctl status pypnm-agent"
echo ""
echo "View logs:"
echo "  journalctl -u pypnm-agent -f"
echo "  tail -f ${INSTALL_DIR}/pyPNMAgent/logs/agent.log"
echo ""
