#!/bin/bash
# Reverse SSH Tunnel Script for Server A (CMTS Agent)
# Creates reverse tunnel TO Server B (Modem Agent) so it can reach PyPNM API
# Run this on Server A

# Configuration
PYPNM_SERVER="appdb-sh.oss.local"  # PyPNM API + GUI server
PYPNM_PORT=8000

MODEM_AGENT_SERVER="hop-access1.ext.oss.local"  # Server B (destination)
MODEM_AGENT_USER="${USER}"  # SSH user for Server B
MODEM_AGENT_SSH_KEY="${HOME}/.ssh/id_rsa"

# Reverse tunnel configuration
REMOTE_PORT=18000  # Port on Server B that will forward back to PyPNM API

# AutoSSH configuration
AUTOSSH_POLL=60
AUTOSSH_FIRST_POLL=30
AUTOSSH_GATETIME=0
AUTOSSH_LOGFILE="${HOME}/.autossh-reverse-modem.log"
AUTOSSH_PIDFILE="${HOME}/.autossh-reverse-modem.pid"

export AUTOSSH_POLL AUTOSSH_FIRST_POLL AUTOSSH_GATETIME AUTOSSH_LOGFILE AUTOSSH_PIDFILE

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
    echo "  ${PYPNM_SERVER}:${PYPNM_PORT} <- Server A <- Server B:localhost:${REMOTE_PORT}"
    
    autossh -f -M 0 \
        -N \
        -R ${REMOTE_PORT}:${PYPNM_SERVER}:${PYPNM_PORT} \
        -i "${MODEM_AGENT_SSH_KEY}" \
        -o "ServerAliveInterval=30" \
        -o "ServerAliveCountMax=3" \
        -o "ExitOnForwardFailure=yes" \
        -o "StrictHostKeyChecking=accept-new" \
        ${MODEM_AGENT_USER}@${MODEM_AGENT_SERVER}

    if [ $? -eq 0 ]; then
        sleep 2
        PID=$(pgrep -f "autossh.*${REMOTE_PORT}:${PYPNM_SERVER}:${PYPNM_PORT}")
        if [ -n "$PID" ]; then
            echo "$PID" > "$AUTOSSH_PIDFILE"
            echo "✓ Reverse tunnel created successfully"
            echo "  Server B can now connect to: http://localhost:$REMOTE_PORT"
            echo "  (This tunnels back to ${PYPNM_SERVER}:${PYPNM_PORT})"
            echo "  PID: $PID"
        else
            echo "✗ Failed to get tunnel PID"
            return 1
        fi
    else
        echo "✗ Failed to create reverse tunnel"
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
            pkill -f "ssh.*${REMOTE_PORT}:${PYPNM_SERVER}:${PYPNM_PORT}"
            rm -f "$AUTOSSH_PIDFILE"
            echo "✓ Reverse tunnel stopped"
        else
            echo "Reverse tunnel not running (stale PID)"
            rm -f "$AUTOSSH_PIDFILE"
        fi
    else
        echo "Reverse tunnel not running"
        pkill -f "autossh.*${REMOTE_PORT}:${PYPNM_SERVER}:${PYPNM_PORT}"
    fi
}

status_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ Reverse tunnel is running (PID: $PID)"
            echo "  Server B: localhost:$REMOTE_PORT -> ${PYPNM_SERVER}:${PYPNM_PORT}"
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
