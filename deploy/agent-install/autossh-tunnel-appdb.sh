#!/bin/bash
# SSH Tunnel using AutoSSH for Modem Agent
# Tunnel to PyPNM API (includes WebSocket) on appdb-sh.oss.local

# Configuration
JUMP_HOST="appdb-sh.oss.local"
JUMP_PORT=22
JUMP_USER="${USER}"  # Uses current user, change if needed
SSH_KEY="${HOME}/.ssh/id_rsa"

# Tunnel configuration - only PyPNM API (WebSocket runs on same port)
LOCAL_PYPNM_PORT=8000
REMOTE_PYPNM_HOST="localhost"
REMOTE_PYPNM_PORT=8000

# AutoSSH configuration
AUTOSSH_POLL=60
AUTOSSH_FIRST_POLL=30
AUTOSSH_GATETIME=0
AUTOSSH_LOGFILE="${HOME}/.autossh-pypnm.log"
AUTOSSH_PIDFILE="${HOME}/.autossh-pypnm.pid"

export AUTOSSH_POLL AUTOSSH_FIRST_POLL AUTOSSH_GATETIME AUTOSSH_LOGFILE AUTOSSH_PIDFILE

start_tunnel() {
    if [ -f "$AUTOSSH_PIDFILE" ]; then
        PID=$(cat "$AUTOSSH_PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✓ PyPNM tunnels are already running (PID: $PID)"
            echo "  AppDB API:    https://localhost:$LOCAL_APPDB_PORT/isw/api"
            echo "  PyPNM API:    http://localhost:$LOCAL_PYPNM_PORT"
            echo "  WebSocket:    ws://localhost:$LOCAL_WEBSOCKET_PORT"
            return 0
        else
            rm -f "$AUTOSSH_PIDFILE"
        fi
    fi

    echo "Starting PyPNM tunnels via autossh..."
    echo "  AppDB:     localhost:$LOCAL_APPDB_PORT -> $JUMP_HOST:$REMOTE_APPDB_PORT"
    echo "  PyPNM API: localhost:$LOCAL_PYPNM_PORT -> $JUMP_HOST:$REMOTE_PYPNM_PORT"
    echo "  WebSocket: localhost:$LOCAL_WEBSOCKET_PORT -> $JUMP_HOST:$REMOTE_WEBSOCKET_PORT"
    
    autossh -f -M 0 \
        -N \
        -L ${LOCAL_APPDB_PORT}:${REMOTE_APPDB_HOST}:${REMOTE_APPDB_PORT} \
        -L ${LOCAL_PYPNM_PORT}:${REMOTE_PYPNM_HOST}:${REMOTE_PYPNM_PORT} \
        -L ${LOCAL_WEBSOCKET_PORT}:${REMOTE_WEBSOCKET_HOST}:${REMOTE_WEBSOCKET_PORT} \
        -p ${JUMP_PORT} \
        -i "${SSH_KEY}" \
        -o "ServerAliveInterval=30" \
        -o "ServerAliveCountMax=3" \
        -o "ExitOnForwardFailure=yes" \
        -o "StrictHostKeyChecking=accept-new" \
        ${JUMP_USER}@${JUMP_HOST}

    if [ $? -eq 0 ]; then
        sleep 2
        PID=$(pgrep -f "autossh.*${LOCAL_PYPNM_PORT}:${REMOTE_PYPNM_HOST}:${REMOTE_PYPNM_PORT}")
        if [ -n "$PID" ]; then
            echo "$PID" > "$AUTOSSH_PIDFILE"
            echo "✓ PyPNM tunnels started successfully"
            echo "  AppDB API:    https://localhost:$LOCAL_APPDB_PORT/isw/api"
            echo "  PyPNM API:    http://localhost:$LOCAL_PYPNM_PORT"
            echo "  WebSocket:    ws://localhost:$LOCAL_WEBSOCKET_PORT"
            echo "  PID: $PID"
        else
            echo "✗ Failed to get tunnel PID"
            return 1
        fi
    else
        echo "✗ Failed to sPyPNM tunnels (PID: $PID)..."
            kill $PID
            sleep 1
            # Kill any remaining ssh processes
            pkill -f "ssh.*${LOCAL_PYPNM_PORT}:${REMOTE_PYPNM_HOST}:${REMOTE_PYPNM_PORT}"
            rm -f "$AUTOSSH_PIDFILE"
            echo "✓ PyPNM tunnels stopped"
        else
            echo "PyPNM tunnels not running (stale PID)"
            rm -f "$AUTOSSH_PIDFILE"
        fi
    else
        echo "PyPNM tunnels not running"
        pkill -f "autossh.*${LOCAL_PYPNM_PORT}:${REMOTE_PYPNM_HOST}:${REMOTE_PYPNM_PORT}"
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
            echo "✓ PyPNM API tunnel is running (PID: $PID)"
            echo "  localhost:$LOCAL_PYPNM_PORT -> ${JUMP_HOST}:${REMOTE_PYPNM_PORT}"
            return 0
        else
            echo "✗ PyPNM API tunnel is not running (stale PID)"
            return 1
        fi
    else
        echo "✗ PyPNM API tunnel is not running"
        return 1
    fi
}

test_tunnel() {
    echo "Testing PyPNM API tunnel..."
    if ! status_tunnel > /dev/null 2>&1; then
        echo "✗ Tunnel is not running"
        return 1
    fi
    
    if command -v curl > /dev/null 2>&1; then
        if curl -s -m 5 "http://localhost:$LOCAL_PYPNM_PORT/health" > /dev/null 2>&1; then
            echo "✓ PyPNM API tunnel is working"
            return 0
        else
            echo "✗ PyPNM API tunnel connection failed"
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
