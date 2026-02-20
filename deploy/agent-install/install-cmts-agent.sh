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
  "pypnm_api_url": "http://localhost:8000",
  "auth_token": "${AGENT_AUTH_TOKEN}",
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

# Create systemd user service (no tunnel needed for CMTS agent)
echo "Creating systemd user service..."

# Create user systemd directory
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/pypnm-agent.service <<EOF
[Unit]
Description=PyPNM CMTS Agent
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
