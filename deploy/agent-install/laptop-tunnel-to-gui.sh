#!/bin/bash
# SSH Tunnel from Laptop to PyPNM GUI
# Run this on your laptop to access the PyPNM GUI WebSocket
#
# Architecture:
#   Laptop:5050 → script3a.oss.local → appdb-sh.oss.local:5050

# Configuration
JUMP_HOST="script3a.oss.local"
PYPNM_GUI_HOST="appdb-sh.oss.local"
PYPNM_GUI_PORT=80

LOCAL_PORT=5050
SSH_USER="svdleer"  # Change if needed

start_tunnel() {
    echo "Starting tunnel to PyPNM GUI via ${JUMP_HOST}..."
    echo "  localhost:$LOCAL_PORT -> ${JUMP_HOST} -> ${PYPNM_GUI_HOST}:${PYPNM_GUI_PORT}"
    echo ""
    echo "You may be prompted for password/2FA..."
    echo ""
    echo "Once connected:"
    echo "  PyPNM GUI: http://localhost:$LOCAL_PORT"
    echo "  WebSocket: ws://localhost:$LOCAL_PORT/ws/*"
    echo ""
    echo "Press Ctrl+C to stop the tunnel"
    echo ""
    
    # Create tunnel via jump host - interactive mode for 2FA
    # This will run in foreground until Ctrl+C
    ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -L ${LOCAL_PORT}:${PYPNM_GUI_HOST}:${PYPNM_GUI_PORT} \
        ${SSH_USER}@${JUMP_HOST}
    
    echo "Tunnel stopped"
}

stop_tunnel() {
    echo "Tunnels run in foreground mode (for 2FA support)"
    echo "Press Ctrl+C in the running terminal to stop"
    echo ""
    echo "Or kill any SSH processes manually:"
    pkill -f "ssh.*${LOCAL_PORT}:${PYPNM_GUI_HOST}:${PYPNM_GUI_PORT}"
}

status_tunnel() {
    if pgrep -f "ssh.*${LOCAL_PORT}:${PYPNM_GUI_HOST}:${PYPNM_GUI_PORT}" > /dev/null; then
        echo "✓ Tunnel appears to be running"
        ps aux | grep "ssh.*${LOCAL_PORT}:${PYPNM_GUI_HOST}:${PYPNM_GUI_PORT}" | grep -v grep
        return 0
    else
        echo "✗ Tunnel is not running"
        return 1
    fi
}

case "$1" in
    start)
        start_tunnel
        ;;
    stop)
        stop_tunnel
        ;;
    status)
        status_tunnel
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        echo ""
        echo "Creates SSH tunnel from laptop to PyPNM GUI"
        echo "  Laptop:5050 → script3a → appdb-sh:5050"
        echo ""
        echo "Note: Runs in FOREGROUND for 2FA support"
        echo "      Keep the terminal open while using PyPNM GUI"
        echo "      Press Ctrl+C to stop"
        exit 1
        ;;
esac
