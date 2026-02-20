#!/bin/bash
# Master Setup Script for PyPNM Multi-Agent Architecture
# Run this on Server A (CMTS Agent Server)
#
# This script sets up:
# 1. Forward tunnel to PyPNM API (appdb-sh.oss.local)
# 2. Reverse tunnel to Modem Agent (hop-access1.ext.oss.local)
# 3. Verifies connectivity

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "PyPNM Multi-Agent Tunnel Setup"
echo "========================================"
echo ""
echo "Architecture:"
echo "  PyPNM API (appdb-sh.oss.local:8000)"
echo "       ↑                     ↓"
echo "  Forward Tunnel      Reverse Tunnel"
echo "       ↑                     ↓"
echo "  Server A (CMTS)    →  Server B (Modem)"
echo "  (This server)         (hop-access1)"
echo ""

# Configuration
PYPNM_SERVER="appdb-sh.oss.local"
MODEM_AGENT_SERVER="hop-access1.ext.oss.local"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Start Forward Tunnel (Server A → PyPNM API)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Starting Forward Tunnel to PyPNM API"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "${SCRIPT_DIR}/create-forward-tunnel.sh" ]; then
    echo -e "${RED}✗ create-forward-tunnel.sh not found!${NC}"
    exit 1
fi

${SCRIPT_DIR}/create-forward-tunnel.sh stop 2>/dev/null || true
sleep 2
${SCRIPT_DIR}/create-forward-tunnel.sh start

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Forward tunnel started${NC}"
else
    echo -e "${RED}✗ Failed to start forward tunnel${NC}"
    exit 1
fi

# Wait and test
echo ""
echo "Testing forward tunnel..."
sleep 3

if curl -s -m 5 http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Forward tunnel is working - can reach PyPNM API${NC}"
else
    echo -e "${YELLOW}⚠ Warning: Cannot reach PyPNM API through forward tunnel${NC}"
    echo "  This may be normal if PyPNM API is not running yet."
fi

echo ""

# Step 2: Start Reverse Tunnel (Server A → Server B)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Starting Reverse Tunnel to Modem Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "${SCRIPT_DIR}/create-reverse-tunnel.sh" ]; then
    echo -e "${RED}✗ create-reverse-tunnel.sh not found!${NC}"
    exit 1
fi

echo "Testing SSH connection to ${MODEM_AGENT_SERVER}..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes ${MODEM_AGENT_SERVER} exit 2>/dev/null; then
    echo -e "${RED}✗ Cannot SSH to ${MODEM_AGENT_SERVER}${NC}"
    echo "  Make sure:"
    echo "  1. SSH key is set up: ssh-copy-id ${MODEM_AGENT_SERVER}"
    echo "  2. Server is reachable: ping ${MODEM_AGENT_SERVER}"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection to ${MODEM_AGENT_SERVER} works${NC}"
echo ""

${SCRIPT_DIR}/create-reverse-tunnel.sh stop 2>/dev/null || true
sleep 2
${SCRIPT_DIR}/create-reverse-tunnel.sh start

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Reverse tunnel created${NC}"
else
    echo -e "${RED}✗ Failed to create reverse tunnel${NC}"
    exit 1
fi

echo ""

# Step 3: Verify Modem Agent can reach PyPNM API
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Verifying Modem Agent Connectivity"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

sleep 3

echo "Testing if ${MODEM_AGENT_SERVER} can reach PyPNM API via reverse tunnel..."
if ssh ${MODEM_AGENT_SERVER} "curl -s -m 5 http://localhost:18000/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SUCCESS! Modem agent can reach PyPNM API via reverse tunnel${NC}"
else
    echo -e "${YELLOW}⚠ Warning: Cannot verify connectivity from modem agent${NC}"
    echo "  This may be normal if PyPNM API is not running yet."
    echo "  Or curl might not be installed on ${MODEM_AGENT_SERVER}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Tunnel Status:"
echo "  Forward Tunnel:  localhost:8000 → ${PYPNM_SERVER}:8000"
echo "  Reverse Tunnel:  ${MODEM_AGENT_SERVER}:localhost:18000 → localhost:8000"
echo ""
echo "Next Steps:"
echo "  1. On this server (Server A/CMTS):"
echo "     systemctl --user start pypnm-agent"
echo ""
echo "  2. On ${MODEM_AGENT_SERVER}:"
echo "     systemctl --user start pypnm-agent"
echo ""
echo "Monitor tunnels:"
echo "  ./create-forward-tunnel.sh status"
echo "  ./create-reverse-tunnel.sh status"
echo ""
echo "To enable auto-start on boot:"
echo "  systemctl --user enable pypnm-forward-tunnel"
echo "  systemctl --user enable pypnm-reverse-tunnel"
echo "  systemctl --user enable pypnm-agent"
echo ""
