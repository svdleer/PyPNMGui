#!/bin/bash
# Forward SSH Tunnel for Server A (CMTS Agent)
# Connects to appdb-sh.oss.local to access PyPNM API (only exposed on localhost there)

# Configuration
PYPNM_SERVER="appdb-sh.oss.local"
PYPNM_SERVER_SSH_PORT=22
PYPNM_SERVER_USER="${USER}"
SSH_KEY="${HOME}/.ssh/id_rsa"

# Tunnel configuration
LOCAL_PORT=8000
REMOTE_HOST="localhost"
REMOTE_PORT=8000

# AutoSSH configuration
export AUTOSSH_POLL=60
export AUTOSSH_FIRST_POLL=30
export AUTOSSH_GATETIME=0
export AUTOSSH_LOGFILE="${HOME}/.autossh-pypnm-forward.log"
export AUTOSSH_PIDFILE="${HOME}/.autossh-pypnm-forward.pid"
export AUTOSSH_DEBUG=1

start_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ Forward tunnel to PyPNM API is already running (PID: $PID)"
            echo "  Access: http://localhost:$LOCAL_PORT"
            return 0
        else
            rm -f "$AUTOSSH_PIDFILE"
        fi
    fi

    echo "Starting forward tunnel to ${PYPNM_SERVER}..."
    echo "  localhost:$LOCAL_PORT -> ${PYPNM_SERVER}:localhost:${REMOTE_PORT}"
    
    # Use plain SSH with auto-restart via systemd
    nohup ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=accept-new \
        -L ${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT} \
        -i "${SSH_KEY}" \
        -p ${PYPNM_SERVER_SSH_PORT} \
        ${PYPNM_SERVER_USER}@${PYPNM_SERVER} \
        > "${HOME}/.ssh-forward-tunnel.log" 2>&1 &
    
    SSH_PID=$!
    echo $SSH_PID > "$AUTOSSH_PIDFILE"

    if [if ps -p $SSH_PID > /dev/null 2>&1; then
            echo "✓ Forward tunnel started successfully"
            echo "  CMTS Agent can connect to: http://localhost:$LOCAL_PORT"
            echo "  PID: $SSH_PID"
        else
            echo "✗ SSH process died immediately"
            cat "${HOME}/.ssh-forward-tunnel.log
        else
            echo "✗ Failed to get tunnel PID"
            return 1
        fi
    else
        echo "✗ Failed to start forward tunnel"
        return 1
    fi
}

stop_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "Stopping forward tunnel (PID: $PID)..."
            kill $PID
            sleep 1
            pkill -f "ssh.*${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}"
            rm -f "$AUTOSSH_PIDFILE"
            echo "✓ Forward tunnel stopped"
        else
            echo "Forward tunnel not running (stale PID)"
            rm -f "$AUTOSSH_PIDFILE"
        fi
    else
        echo "Forward tunnel not running"
        pkill -f "autossh.*${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}"
    fi
}

status_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ Forward tunnel is running (PID: $PID)"
            echo "  localhost:$LOCAL_PORT -> ${PYPNM_SERVER}:${REMOTE_PORT}"
            return 0
        else
            echo "✗ Forward tunnel is not running (stale PID)"
            return 1
        fi
    else
        echo "✗ Forward tunnel is not running"
        return 1
    fi
}

test_tunnel() {
    echo "Testing forward tunnel..."
    if ! status_tunnel > /dev/null 2>&1; then
        echo "✗ Tunnel is not running"
        return 1
    fi
    
    if command -v curl > /dev/null 2>&1; then
        if curl -s -m 5 "http://localhost:$LOCAL_PORT/health" > /dev/null 2>&1; then
            echo "✓ Forward tunnel is working"
            return 0
        else
            echo "✗ Forward tunnel connection failed"
            return 1
        fi
    else
        echo "⚠ curl not found, cannot test"
        return 0
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
    test)
        test_tunnel
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|test}"
        echo ""
        echo "This creates a forward tunnel FROM Server A TO appdb-sh"
        echo "so Server A's CMTS agent can access PyPNM API on localhost:8000"
        exit 1
        ;;
esac
