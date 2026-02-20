#!/bin/bash
# SSH Tunnel using AutoSSH for Modem Agent
# Tunnel to appdb.oss.local via CMTS agent server (appdb-sh.oss.local)

# Configuration
JUMP_HOST="appdb-sh.oss.local"
JUMP_PORT=22
JUMP_USER="${USER}"  # Uses current user, change if needed
SSH_KEY="${HOME}/.ssh/id_rsa"

# Tunnel configuration
LOCAL_PORT=8443
REMOTE_HOST="localhost"  # appdb is on the jump host itself
REMOTE_PORT=443

# AutoSSH configuration
AUTOSSH_POLL=60
AUTOSSH_FIRST_POLL=30
AUTOSSH_GATETIME=0
AUTOSSH_LOGFILE="${HOME}/.autossh-appdb.log"
AUTOSSH_PIDFILE="${HOME}/.autossh-appdb.pid"

export AUTOSSH_POLL AUTOSSH_FIRST_POLL AUTOSSH_GATETIME AUTOSSH_LOGFILE AUTOSSH_PIDFILE

start_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ AppDB tunnel is already running (PID: $PID)"
            echo "  Access: https://localhost:$LOCAL_PORT/isw/api"
            return 0
        else
            rm -f "$AUTOSSH_PIDFILE"
        fi
    fi

    echo "Starting AppDB tunnel via autossh..."
    
    autossh -f -M 0 \
        -N \
        -L ${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT} \
        -p ${JUMP_PORT} \
        -i "${SSH_KEY}" \
        -o "ServerAliveInterval=30" \
        -o "ServerAliveCountMax=3" \
        -o "ExitOnForwardFailure=yes" \
        -o "StrictHostKeyChecking=accept-new" \
        ${JUMP_USER}@${JUMP_HOST}

    if [ $? -eq 0 ]; then
        sleep 2
        PID=$(pgrep -f "autossh.*${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}")
        if [ -n "$PID" ]; then
            echo "$PID" > "$AUTOSSH_PIDFILE"
            echo "✓ AppDB tunnel started successfully"
            echo "  Access: https://localhost:$LOCAL_PORT/isw/api"
            echo "  PID: $PID"
        else
            echo "✗ Failed to get tunnel PID"
            return 1
        fi
    else
        echo "✗ Failed to start AppDB tunnel"
        return 1
    fi
}

stop_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "Stopping AppDB tunnel (PID: $PID)..."
            kill $PID
            sleep 1
            # Kill any remaining ssh processes
            pkill -f "ssh.*${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}"
            rm -f "$AUTOSSH_PIDFILE"
            echo "✓ AppDB tunnel stopped"
        else
            echo "AppDB tunnel not running (stale PID)"
            rm -f "$AUTOSSH_PIDFILE"
        fi
    else
        echo "AppDB tunnel not running"
        pkill -f "autossh.*${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}"
    fi
}

status_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ AppDB tunnel is running (PID: $PID)"
            echo "  Local: https://localhost:$LOCAL_PORT"
            echo "  Remote: ${JUMP_HOST}:${REMOTE_PORT}"
            return 0
        else
            echo "✗ AppDB tunnel is not running (stale PID)"
            return 1
        fi
    else
        echo "✗ AppDB tunnel is not running"
        return 1
    fi
}

test_tunnel() {
    echo "Testing AppDB tunnel..."
    if ! status_tunnel > /dev/null 2>&1; then
        echo "✗ Tunnel is not running"
        return 1
    fi
    
    if command -v curl > /dev/null 2>&1; then
        if curl -s -k -m 5 "https://localhost:$LOCAL_PORT" > /dev/null 2>&1; then
            echo "✓ Tunnel is working"
            return 0
        else
            echo "✗ Tunnel is running but connection failed"
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
        exit 1
        ;;
esac
