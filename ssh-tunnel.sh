#!/bin/bash
# SSH Tunnels for EVE LI Local Testing with ControlMaster
# ========================================================
# This script uses SSH ControlMaster for efficient connection multiplexing
# All tunnels share a single SSH connection that persists for 10 minutes
#
# Usage: ./ssh-tunnel.sh start|stop|status|restart|test

# ============================================================================
# Configuration - UPDATE THESE VALUES
# ============================================================================
JUMP_SERVER="svdleer@script3a.oss.local"
SSH_KEY="${HOME}/.ssh/id_rsa"
CONTROL_PATH="${HOME}/.ssh/cm-%r@%h:%p"
CONTROL_PERSIST="10m"

# Target servers (internal hosts accessible from bastion)
# Production server (runs both database and web app)
PROD_SERVER="appdb-sh.oss.local"

# PyPNM Infrastructure Servers
MODEM_SERVER="modem-server.oss.local"       # TODO: Update with actual hostname (CM Proxy for SNMP to modems)
TFTP_SERVER="tftp-server.oss.local"         # TODO: Update with actual hostname (PNM file storage)

# Remote ports
SSH_PORT="22"
WEBAPP_PORT="8502"
MODEM_SSH_PORT="22"                         # SSH port on modem server
TFTP_SSH_PORT="22"                          # SSH port on TFTP server (for SCP/SFTP)
TFTP_PORT="69"                              # TFTP UDP port (if needed)

# Local ports
LOCAL_SSH_PORT="2222"
LOCAL_WEBAPP_PORT="8080"
LOCAL_MODEM_SSH_PORT="2223"                 # Local port for modem server SSH
LOCAL_TFTP_SSH_PORT="2224"                  # Local port for TFTP server SSH

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Functions
# ============================================================================

check_control_master() {
    # Check if control master connection exists
    ssh -O check -S "$CONTROL_PATH" "$JUMP_SERVER" 2>/dev/null
    return $?
}

start_control_master() {
    echo -e "${YELLOW}Starting SSH ControlMaster connection...${NC}"
    
    # Start master connection in background
    ssh -f -N -M \
        -S "$CONTROL_PATH" \
        -o ControlPersist="$CONTROL_PERSIST" \
        -i "$SSH_KEY" \
        "$JUMP_SERVER"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ ControlMaster connection established${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed to establish ControlMaster connection${NC}"
        return 1
    fi
}

stop_control_master() {
    if check_control_master; then
        echo -e "${YELLOW}Stopping SSH ControlMaster connection...${NC}"
        ssh -O exit -S "$CONTROL_PATH" "$JUMP_SERVER" 2>/dev/null
        echo -e "${GREEN}✓ ControlMaster connection stopped${NC}"
    fi
}

start_tunnel() {
    local name=$1
    local local_port=$2
    local remote_host=$3
    local remote_port=$4
    
    # Check if port is already in use
    if lsof -Pi :$local_port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠ Port $local_port already in use, skipping $name${NC}"
        return 1
    fi
    
    # Start tunnel using existing control master, bind to 127.0.0.1
    ssh -f -N \
        -S "$CONTROL_PATH" \
        -L "127.0.0.1:${local_port}:${remote_host}:${remote_port}" \
        "$JUMP_SERVER" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $name tunnel: 127.0.0.1:$local_port -> $remote_host:$remote_port${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed to start $name tunnel${NC}"
        return 1
    fi
}

case "$1" in
  start)
    echo -e "\n${YELLOW}Starting SSH tunnels...${NC}"
    echo "================================"
    
    # Ensure control master is running
    if ! check_control_master; then
        start_control_master || exit 1
        sleep 1
    fi
    
    # Start SSH tunnel with port forwarding
    start_tunnel "SSH Access" "$LOCAL_SSH_PORT" "$PROD_SERVER" "$SSH_PORT"
    
    # Start Netshot HTTPS tunnels
    start_tunnel "Netshot HTTPS" "8443" "netshot.oss.local" "443"
    start_tunnel "Netshot MND HTTPS" "8444" "netshot.mnd.b2b.oss.local" "443"
    
    # PyPNM Infrastructure tunnels
    # Modem Server - CM Proxy for SNMP commands to cable modems
    start_tunnel "Modem Server SSH" "$LOCAL_MODEM_SSH_PORT" "$MODEM_SERVER" "$MODEM_SSH_PORT"
    
    # TFTP Server - PNM file retrieval
    start_tunnel "TFTP Server SSH" "$LOCAL_TFTP_SSH_PORT" "$TFTP_SERVER" "$TFTP_SSH_PORT"
    
    # Add local port forward through the SSH tunnel
    echo -ne "${YELLOW}✓ Web Application: localhost:${LOCAL_WEBAPP_PORT} -> appdb-sh.oss.local:${WEBAPP_PORT}${NC}"
    ssh -f -N -L ${LOCAL_WEBAPP_PORT}:localhost:${WEBAPP_PORT} -p ${LOCAL_SSH_PORT} svdleer@localhost &
    echo -e " ${GREEN}✓${NC}"
    
    echo "================================"
    echo -e "${GREEN}Tunnels started!${NC}\n"
    
    echo -e "${YELLOW}SSH to server:${NC}"
    echo "ssh -p ${LOCAL_SSH_PORT} svdleer@localhost"
    echo ""
    echo -e "${YELLOW}Access web app:${NC}"
    echo "http://localhost:${LOCAL_WEBAPP_PORT}"
    echo ""
    echo -e "${YELLOW}Access Netshot:${NC}"
    echo "https://localhost:8443"
    echo ""
    echo -e "${YELLOW}Access Netshot MND:${NC}"
    echo "https://localhost:8444"
    echo ""
    echo -e "${YELLOW}PyPNM Infrastructure:${NC}"
    echo "  Modem Server: ssh -p ${LOCAL_MODEM_SSH_PORT} user@localhost"
    echo "  TFTP Server:  ssh -p ${LOCAL_TFTP_SSH_PORT} user@localhost"
    echo ""
    ;;
    
  stop)
    echo -e "\n${YELLOW}Stopping SSH tunnels...${NC}"
    echo "================================"
    
    # Kill all SSH processes using our control socket
    pkill -f "ssh.*$CONTROL_PATH" 2>/dev/null
    
    # Stop control master
    stop_control_master
    
    # Clean up control socket if it exists
    rm -f "${CONTROL_PATH//\%*/}"* 2>/dev/null
    
    echo "================================"
    echo -e "${GREEN}All tunnels stopped!${NC}\n"
    ;;
    
  status)
    echo -e "\n${YELLOW}SSH Tunnel Status${NC}"
    echo "================================"
    
    # Check control master
    if check_control_master; then
        echo -e "${GREEN}✓ ControlMaster: Active${NC}"
        ssh -O check -S "$CONTROL_PATH" "$JUMP_SERVER" 2>&1 | head -n 1
    else
        echo -e "${RED}✗ ControlMaster: Not active${NC}"
    fi
    
    echo ""
    
    # Check tunnel ports
    if lsof -Pi :$LOCAL_SSH_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓ SSH: localhost:$LOCAL_SSH_PORT -> $PROD_SERVER:$SSH_PORT${NC}"
    else
        echo -e "${RED}✗ SSH: Not listening${NC}"
    fi
    
    if lsof -Pi :$LOCAL_WEBAPP_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Web App: localhost:$LOCAL_WEBAPP_PORT -> $PROD_SERVER:$WEBAPP_PORT${NC}"
    else
        echo -e "${RED}✗ Web App: Not listening${NC}"
    fi
    
    if lsof -Pi :$LOCAL_MODEM_SSH_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Modem Server: localhost:$LOCAL_MODEM_SSH_PORT -> $MODEM_SERVER:$MODEM_SSH_PORT${NC}"
    else
        echo -e "${RED}✗ Modem Server: Not listening${NC}"
    fi
    
    if lsof -Pi :$LOCAL_TFTP_SSH_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓ TFTP Server: localhost:$LOCAL_TFTP_SSH_PORT -> $TFTP_SERVER:$TFTP_SSH_PORT${NC}"
    else
        echo -e "${RED}✗ TFTP Server: Not listening${NC}"
    fi
    
    echo "================================"
    echo ""
    ;;
    
  test)
    echo -e "\n${YELLOW}Testing Connections...${NC}"
    echo "================================"
    
    echo -n "SSH tunnel (localhost:2222)... "
    if nc -z localhost "$LOCAL_SSH_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓ OK${NC}"
    else
        echo -e "${RED}✗ Failed${NC}"
    fi
    
    echo -n "Web App (localhost:8080)... "
    if curl -s --connect-timeout 5 "http://localhost:${LOCAL_WEBAPP_PORT}/" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ OK - Web app is accessible${NC}"
        echo -e "${BLUE}   Access at: http://localhost:${LOCAL_WEBAPP_PORT}${NC}"
    else
        echo -e "${RED}✗ Failed - Web app not accessible${NC}"
    fi
    
    echo -n "Modem Server (localhost:${LOCAL_MODEM_SSH_PORT})... "
    if nc -z localhost "$LOCAL_MODEM_SSH_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓ OK${NC}"
    else
        echo -e "${RED}✗ Failed${NC}"
    fi
    
    echo -n "TFTP Server (localhost:${LOCAL_TFTP_SSH_PORT})... "
    if nc -z localhost "$LOCAL_TFTP_SSH_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓ OK${NC}"
    else
        echo -e "${RED}✗ Failed${NC}"
    fi
    
    echo "================================"
    echo ""
    ;;
    
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
    
  *)
    echo -e "${RED}Error: Unknown command '$1'${NC}\n"
    echo "Usage: $0 {start|stop|restart|status|test}"
    echo ""
    echo "Commands:"
    echo "  start    - Start SSH tunnel using ControlMaster"
    echo "  stop     - Stop SSH tunnel and ControlMaster"
    echo "  restart  - Restart tunnel"
    echo "  status   - Show tunnel status"
    echo "  test     - Test connection through tunnel"
    exit 1
    ;;
esac
