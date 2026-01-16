#!/bin/bash
# SSH Tunnel for LAB Environment (access-engineering.nl)
# Tunnel local ports to remote LAB services

REMOTE_HOST="access-engineering.nl"
REMOTE_PORT=65001
REMOTE_USER="svdleer"
LOCAL_PORT=5051
REMOTE_GUI_PORT=5051
LOCAL_PYPNM_PORT=8081
REMOTE_PYPNM_PORT=8081

PIDFILE="$HOME/.ssh-tunnel-lab.pid"
LOGFILE="$HOME/.ssh-tunnel-lab.log"

start_tunnel() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "LAB tunnel is already running (PID: $PID)"
            echo "Local GUI: http://localhost:$LOCAL_PORT"
            echo "Local PyPNM: http://localhost:$LOCAL_PYPNM_PORT"
            return 0
        else
            rm -f "$PIDFILE"
        fi
    fi

    echo "Starting LAB SSH tunnel to $REMOTE_HOST:$REMOTE_PORT..."
    ssh -f -N -M -S ~/.ssh/lab-tunnel-socket \
        -L ${LOCAL_PORT}:localhost:${REMOTE_GUI_PORT} \
        -L ${LOCAL_PYPNM_PORT}:localhost:${REMOTE_PYPNM_PORT} \
        -p ${REMOTE_PORT} \
        ${REMOTE_USER}@${REMOTE_HOST} \
        > "$LOGFILE" 2>&1

    if [ $? -eq 0 ]; then
        # Get PID from socket
        ssh -S ~/.ssh/lab-tunnel-socket -O check ${REMOTE_USER}@${REMOTE_HOST} 2>&1 | \
            grep -o 'pid=[0-9]*' | cut -d= -f2 > "$PIDFILE"
        
        echo "LAB tunnel started successfully"
        echo "Access LAB GUI at: http://localhost:$LOCAL_PORT"
        echo "Access PyPNM API at: http://localhost:$LOCAL_PYPNM_PORT/docs"
        echo "PID saved to $PIDFILE"
    else
        echo "Failed to start LAB tunnel. Check $LOGFILE for details."
        return 1
    fi
}

stop_tunnel() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "Stopping LAB tunnel (PID: $PID)..."
            ssh -S ~/.ssh/lab-tunnel-socket -O exit ${REMOTE_USER}@${REMOTE_HOST} 2>/dev/null
            kill $PID 2>/dev/null
            rm -f "$PIDFILE"
            rm -f ~/.ssh/lab-tunnel-socket
            echo "LAB tunnel stopped"
        else
            echo "LAB tunnel not running"
            rm -f "$PIDFILE"
        fi
    else
        echo "LAB tunnel not running (no PID file)"
        # Clean up socket if exists
        ssh -S ~/.ssh/lab-tunnel-socket -O exit ${REMOTE_USER}@${REMOTE_HOST} 2>/dev/null
        rm -f ~/.ssh/lab-tunnel-socket
    fi
}

status_tunnel() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "LAB tunnel is running (PID: $PID)"
            echo "Local: http://localhost:$LOCAL_PORT -> Remote: localhost:$REMOTE_GUI_PORT"
            return 0
        else
            echo "LAB tunnel is not running (stale PID file)"
            return 1
        fi
    else
        echo "LAB tunnel is not running"
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
        echo "LAB Environment SSH Tunnel"
        echo "  Remote: $REMOTE_HOST:$REMOTE_PORT"
        echo "  Local:  http://localhost:$LOCAL_PORT"
        exit 1
        ;;
esac
