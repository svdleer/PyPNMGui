#!/bin/bash
# Reverse SSH Tunnel Script for Server A (CMTS Agent)
# Creates reverse tunnel TO Server B (Modem Agent) so it can reach PyPNM API
# Run this on Server A

# Configuration
PYPNM_SERVER="appdb-sh.oss.local"  # PyPNM API + GUI server (for display only)
LOCAL_FORWARD_HOST="127.0.0.1"  # Forward tunnel endpoint on this server
LOCAL_FORWARD_PORT=8000

MODEM_AGENT_SERVER="hop-access1.ext.oss.local"  # Server B (destination)
MODEM_AGENT_USER="${USER}"  # SSH user for Server B
MODEM_AGENT_SSH_KEY="${HOME}/.ssh/id_rsa"

# Reverse tunnel configuration
REMOTE_PORT=18000  # Port on Server B that will forward back to PyPNM API

# AutoSSH configuration
export AUTOSSH_POLL=60
export AUTOSSH_FIRST_POLL=30
export AUTOSSH_GATETIME=0
export AUTOSSH_LOGFILE="${HOME}/.autossh-reverse-modem.log"
export AUTOSSH_PIDFILE="${HOME}/.autossh-reverse-modem.pid"
export AUTOSSH_DEBUG=1

start_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ Reverse tunnel to Server B is already running (PID: $PID)"
            echo "  Server B can access PyPNM API at: http://localhost:$REMOTE_PORT"
            return 0
        else
            rm -f "$AUTOSSH_PIDFILE"
        fi
    fi

    echo "Starting reverse tunnel to Server B (${MODEM_AGENT_SERVER})..."
    echo "  localhost:${LOCAL_FORWARD_PORT} (forward tunnel) <- Server B:localhost:${REMOTE_PORT}"
    
    # Use plain SSH with auto-restart via systemd instead of autossh
    # This is more reliable for reverse tunnels
    nohup ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=accept-new \
        -R ${REMOTE_PORT}:${LOCAL_FORWARD_HOST}:${LOCAL_FORWARD_PORT} \
        -i "${MODEM_AGENT_SSH_KEY}" \
        -p 22 \
        ${MODEM_AGENT_USER}@${MODEM_AGENT_SERVER} \
        > "${HOME}/.ssh-reverse-tunnel.log" 2>&1 &
    
    SSH_PID=$!
    echo $SSH_PID > "$AUTOSSH_PIDFILE"
    
    sleep 2
    if ps -p $SSH_PID > /dev/null 2>&1; then
        echo "✓ Reverse tunnel created successfully"
        echo "  Server B can now connect to: http://localhost:$REMOTE_PORT"
        echo "  (This tunnels back to localhost:${LOCAL_FORWARD_PORT})"
        echo "  PID: $SSH_PID"
    else
        echo "✗ SSH process died immediately"
        cat "${HOME}/.ssh-reverse-tunnel.log"
        return 1
    fi
}

stop_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "Stopping reverse tunnel (PID: $PID)..."
            kill $PID
            sleep 1
            pkill -f "ssh.*${REMOTE_PORT}:${LOCAL_FORWARD_HOST}:${LOCAL_FORWARD_PORT}"
            rm -f "$AUTOSSH_PIDFILE"
            echo "✓ Reverse tunnel stopped"
        else
            echo "Reverse tunnel not running (stale PID)"
            rm -f "$AUTOSSH_PIDFILE"
        fi
    else
        echo "Reverse tunnel not running"
        pkill -f "autossh.*${REMOTE_PORT}:${LOCAL_FORWARD_HOST}:${LOCAL_FORWARD_PORT}"
    fi
}

status_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ Reverse tunnel is running (PID: $PID)"
            echo "  Server B: localhost:$REMOTE_PORT -> Server A:localhost:${LOCAL_FORWARD_PORT}"
            return 0
        else
            echo "✗ Reverse tunnel is not running (stale PID)"
            return 1
        fi
    else
        echo "✗ Reverse tunnel is not running"
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
    restart)
        stop_tunnel
        sleep 2
        start_tunnel
        ;;
    status)
        status_tunnel
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        echo ""
        echo "This creates a reverse SSH tunnel FROM Server A TO Server B"
        echo "so that Server B's modem agent can reach the PyPNM API."
        exit 1
        ;;
esac
