#!/bin/bash
# =============================================================================
# PyPNM Lab Deployment Script
# =============================================================================
# This script manages the complete PyPNM lab environment deployment.
# It handles all containers with proper ordering and health checks.
#
# Usage:
#   ./lab-deploy.sh [command]
#
# Commands:
#   deploy    - Full deployment (pull, build, start all)
#   start     - Start all containers
#   stop      - Stop all containers
#   restart   - Restart all containers properly
#   status    - Show status of all containers
#   logs      - Show logs from all containers
#   pull      - Pull latest code from git
#   build     - Rebuild all images
#   fix       - Emergency fix (stop everything, rebuild, restart)
#   health    - Check health of all services
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.lab.yml"
PYPNM_REPO="/home/svdleer/docker/PyPNM"
GUI_REPO="/opt/pypnm-gui-lab"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Container names
CONTAINERS=(
    "pypnm-api"
    "pypnm-gui-lab"
    "pypnm-agent-lab"
    "eve-li-redis-lab"
)

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for container to be healthy
wait_for_healthy() {
    local container=$1
    local max_wait=${2:-60}
    local wait_time=0
    
    log_info "Waiting for $container to be healthy (max ${max_wait}s)..."
    
    while [ $wait_time -lt $max_wait ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
        
        if [ "$status" = "healthy" ]; then
            log_success "$container is healthy"
            return 0
        elif [ "$status" = "not_found" ]; then
            log_warning "$container not found, skipping health check"
            return 0
        fi
        
        sleep 2
        wait_time=$((wait_time + 2))
        echo -n "."
    done
    
    echo ""
    log_warning "$container did not become healthy within ${max_wait}s (status: $status)"
    return 1
}

# Check if container is running
is_running() {
    local container=$1
    docker ps --format '{{.Names}}' | grep -q "^${container}$"
}

# Stop all containers gracefully
stop_all() {
    log_info "Stopping all PyPNM containers..."
    
    # Stop in reverse order (agent -> gui -> api -> redis)
    for container in pypnm-agent-lab pypnm-gui-lab pypnm-api eve-li-redis-lab; do
        if is_running "$container"; then
            log_info "Stopping $container..."
            docker stop "$container" --time 10 2>/dev/null || true
        fi
    done
    
    log_success "All containers stopped"
}

# Start all containers in order
start_all() {
    log_info "Starting all PyPNM containers..."
    
    cd "$GUI_REPO"
    
    # 1. Start Redis first (no dependencies)
    log_info "Starting Redis..."
    docker compose -f docker/docker-compose.lab.yml up -d redis-lab
    sleep 2
    
    # 2. Start PyPNM API
    log_info "Starting PyPNM API..."
    docker compose -f docker/docker-compose.lab.yml up -d pypnm-api
    wait_for_healthy pypnm-api 90
    
    # 3. Start GUI Server
    log_info "Starting GUI Server..."
    docker compose -f docker/docker-compose.lab.yml up -d gui-server-lab
    wait_for_healthy pypnm-gui-lab 60
    
    # 4. Start Agent
    log_info "Starting Agent..."
    docker compose -f docker/docker-compose.lab.yml up -d agent-lab
    sleep 5
    
    # Verify agent connected
    if docker logs pypnm-agent-lab 2>&1 | tail -5 | grep -q "Authentication successful"; then
        log_success "Agent connected successfully"
    else
        log_warning "Agent may not be connected - check logs"
    fi
    
    log_success "All containers started"
}

# Pull latest code
pull_code() {
    log_info "Pulling latest code..."
    
    # Pull PyPNM
    log_info "Pulling PyPNM repository..."
    cd "$PYPNM_REPO"
    git pull
    
    # Pull PyPNMGui
    log_info "Pulling PyPNMGui repository..."
    cd "$GUI_REPO"
    git pull
    
    log_success "Code updated"
}

# Build all images
build_all() {
    log_info "Building all Docker images..."
    
    cd "$GUI_REPO"
    
    # Build PyPNM API
    log_info "Building PyPNM API..."
    docker compose -f docker/docker-compose.lab.yml build pypnm-api
    
    # Build GUI Server
    log_info "Building GUI Server..."
    CACHEBUST=$(date +%s) docker compose -f docker/docker-compose.lab.yml build gui-server-lab
    
    # Build Agent
    log_info "Building Agent..."
    docker compose -f docker/docker-compose.lab.yml build agent-lab
    
    log_success "All images built"
}

# Show status
show_status() {
    echo ""
    echo "=================================="
    echo "  PyPNM Lab Environment Status"
    echo "=================================="
    echo ""
    
    printf "%-20s %-30s %-15s\n" "CONTAINER" "IMAGE" "STATUS"
    printf "%-20s %-30s %-15s\n" "---------" "-----" "------"
    
    for container in "${CONTAINERS[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            image=$(docker inspect --format='{{.Config.Image}}' "$container" 2>/dev/null | cut -c1-28)
            status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
            health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "N/A")
            
            if [ "$status" = "running" ]; then
                if [ "$health" = "healthy" ]; then
                    status_str="${GREEN}running (healthy)${NC}"
                elif [ "$health" = "unhealthy" ]; then
                    status_str="${YELLOW}running (unhealthy)${NC}"
                else
                    status_str="${GREEN}running${NC}"
                fi
            else
                status_str="${RED}$status${NC}"
            fi
            
            printf "%-20s %-30s " "$container" "$image"
            echo -e "$status_str"
        else
            printf "%-20s %-30s " "$container" "-"
            echo -e "${RED}not found${NC}"
        fi
    done
    
    echo ""
    
    # Check API endpoints
    echo "Service Endpoints:"
    echo "  PyPNM API:  http://localhost:8000/docs"
    echo "  GUI:        http://localhost:5050"
    echo ""
    
    # Quick health check
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo -e "  PyPNM API: ${GREEN}ACCESSIBLE${NC}"
    else
        echo -e "  PyPNM API: ${RED}NOT ACCESSIBLE${NC}"
    fi
    
    if curl -s http://localhost:5050/api/health > /dev/null 2>&1; then
        echo -e "  GUI:       ${GREEN}ACCESSIBLE${NC}"
    else
        echo -e "  GUI:       ${RED}NOT ACCESSIBLE${NC}"
    fi
    
    echo ""
}

# Show logs
show_logs() {
    local container=${1:-all}
    
    if [ "$container" = "all" ]; then
        for c in "${CONTAINERS[@]}"; do
            echo "=== $c ==="
            docker logs "$c" --tail 20 2>/dev/null || echo "No logs available"
            echo ""
        done
    else
        docker logs "$container" --tail 100 -f
    fi
}

# Full deploy
full_deploy() {
    log_info "Starting full deployment..."
    
    stop_all
    pull_code
    build_all
    start_all
    
    echo ""
    show_status
    
    log_success "Deployment complete!"
}

# Restart all properly
restart_all() {
    log_info "Restarting all containers..."
    
    stop_all
    sleep 3
    start_all
    
    echo ""
    show_status
}

# Emergency fix
emergency_fix() {
    log_warning "Running emergency fix..."
    
    # Stop everything
    log_info "Force stopping all containers..."
    for container in "${CONTAINERS[@]}"; do
        docker stop "$container" 2>/dev/null || true
        docker rm "$container" 2>/dev/null || true
    done
    
    # Clean up
    log_info "Cleaning up..."
    docker system prune -f
    
    # Rebuild and start
    pull_code
    build_all
    start_all
    
    show_status
    
    log_success "Emergency fix complete"
}

# Health check
health_check() {
    echo ""
    echo "Running health checks..."
    echo ""
    
    local all_healthy=true
    
    # Check PyPNM API
    echo -n "PyPNM API (http://localhost:8000): "
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        all_healthy=false
    fi
    
    # Check GUI
    echo -n "GUI Server (http://localhost:5050): "
    if curl -s http://localhost:5050/api/health 2>&1 | grep -q "ok"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        all_healthy=false
    fi
    
    # Check Redis
    echo -n "Redis (localhost:6379): "
    if docker exec eve-li-redis-lab redis-cli ping 2>&1 | grep -q "PONG"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        all_healthy=false
    fi
    
    # Check Agent connection
    echo -n "Agent WebSocket: "
    if docker logs pypnm-agent-lab 2>&1 | tail -20 | grep -q "Authentication successful"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        all_healthy=false
    fi
    
    # Check CMTS list
    echo -n "CMTS List (LAB mode): "
    cmts_count=$(curl -s http://localhost:5050/api/cmts 2>&1 | grep -o '"count": [0-9]*' | grep -o '[0-9]*')
    if [ -n "$cmts_count" ] && [ "$cmts_count" -gt 0 ]; then
        echo -e "${GREEN}OK ($cmts_count CMTSes)${NC}"
    else
        echo -e "${RED}FAILED (no CMTSes)${NC}"
        all_healthy=false
    fi
    
    # Check PyPNM UTSC endpoint
    echo -n "PyPNM UTSC endpoint: "
    if curl -s http://localhost:8000/docs/pnm/us/spectrumAnalyzer 2>&1 | grep -q "getCapture\|discoverRfPort"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${YELLOW}PARTIAL${NC}"
    fi
    
    echo ""
    
    if $all_healthy; then
        log_success "All health checks passed!"
        return 0
    else
        log_error "Some health checks failed"
        return 1
    fi
}

# Main
case "${1:-status}" in
    deploy)
        full_deploy
        ;;
    start)
        start_all
        show_status
        ;;
    stop)
        stop_all
        ;;
    restart)
        restart_all
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "${2:-all}"
        ;;
    pull)
        pull_code
        ;;
    build)
        build_all
        ;;
    fix)
        emergency_fix
        ;;
    health)
        health_check
        ;;
    *)
        echo "Usage: $0 {deploy|start|stop|restart|status|logs|pull|build|fix|health}"
        echo ""
        echo "Commands:"
        echo "  deploy   - Full deployment (pull, build, start)"
        echo "  start    - Start all containers"
        echo "  stop     - Stop all containers"
        echo "  restart  - Restart all containers"
        echo "  status   - Show status"
        echo "  logs     - Show logs (optionally: logs <container>)"
        echo "  pull     - Pull latest code"
        echo "  build    - Rebuild images"
        echo "  fix      - Emergency fix (stop, clean, rebuild, start)"
        echo "  health   - Run health checks"
        exit 1
        ;;
esac
