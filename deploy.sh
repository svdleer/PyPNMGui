#!/bin/bash
# PyPNM GUI - Universal Deployment Script
# Supports local, remote, docker builds with various options

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="lab"
REMOTE_HOST="access-engineering.nl"
REMOTE_USER="svdleer"
REMOTE_PORT=65001
REMOTE_PATH="/home/svdleer/docker/PyPNMGui"
BUILD_CACHE="--build"
DOCKER_COMPOSE_FILE="docker/docker-compose.lab.yml"
ACTION=""

# Help function
show_help() {
    cat << EOF
${GREEN}PyPNM GUI Deployment Script${NC}

${YELLOW}Usage:${NC}
    $0 [OPTIONS] ACTION

${YELLOW}Actions:${NC}
    local-dev           Start local development (no docker)
    local-docker        Build and start local docker containers
    local-build         Build docker images only (local)
    remote-deploy       Deploy to remote server (git pull + docker restart)
    remote-build        Build docker images on remote server (no cache)
    remote-rebuild      Force rebuild all docker images on remote
    remote-restart      Restart remote docker containers
    remote-stop         Stop remote docker containers
    remote-logs         Show remote docker logs
    remote-status       Check remote docker status
    ssh                 SSH into remote server
    cleanup             Clean up local docker images and containers
    backup              Create backup of current deployment

${YELLOW}Options:${NC}
    -e, --env ENV       Environment: lab|prod|dev (default: lab)
    -h, --host HOST     Remote host (default: access-engineering.nl)
    -u, --user USER     Remote user (default: svdleer)
    -p, --port PORT     Remote SSH port (default: 65001)
    -r, --path PATH     Remote path (default: /home/svdleer/docker/PyPNMGui)
    --no-cache          Build docker without cache
    --cache             Build docker with cache (default)
    -f, --file FILE     Docker compose file (default: docker/docker-compose.lab.yml)
    --help              Show this help message

${YELLOW}Examples:${NC}
    # Local development
    $0 local-dev
    $0 local-docker
    $0 local-build --no-cache

    # Remote deployment
    $0 remote-deploy
    $0 remote-build --no-cache
    $0 remote-restart
    $0 remote-logs

    # Remote with custom host
    $0 -h myserver.com -u admin remote-deploy

    # Cleanup
    $0 cleanup
    $0 backup

${YELLOW}Common Workflows:${NC}
    1. Quick deploy:       $0 remote-deploy
    2. Full rebuild:       $0 remote-rebuild
    3. Check status:       $0 remote-status
    4. View logs:          $0 remote-logs
    5. Local testing:      $0 local-docker

EOF
}

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -h|--host)
            REMOTE_HOST="$2"
            shift 2
            ;;
        -u|--user)
            REMOTE_USER="$2"
            shift 2
            ;;
        -p|--port)
            REMOTE_PORT="$2"
            shift 2
            ;;
        -r|--path)
            REMOTE_PATH="$2"
            shift 2
            ;;
        --no-cache)
            BUILD_CACHE="--no-cache --build"
            shift
            ;;
        --cache)
            BUILD_CACHE="--build"
            shift
            ;;
        -f|--file)
            DOCKER_COMPOSE_FILE="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        local-dev|local-docker|local-build|remote-deploy|remote-build|remote-rebuild|remote-restart|remote-stop|remote-logs|remote-status|ssh|cleanup|backup)
            ACTION="$1"
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Check if action is provided
if [ -z "$ACTION" ]; then
    log_error "No action specified"
    show_help
    exit 1
fi

# SSH command helper
run_remote() {
    ssh -p $REMOTE_PORT ${REMOTE_USER}@${REMOTE_HOST} "$1"
}

# Local Development (no docker)
local_dev() {
    log_info "Starting local development environment..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        exit 1
    fi
    
    # Install dependencies if needed
    if [ ! -d "backend/venv" ]; then
        log_info "Creating virtual environment..."
        cd backend
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
        cd ..
    fi
    
    # Start backend
    log_info "Starting Flask backend on port 5050..."
    cd backend
    source venv/bin/activate
    export FLASK_ENV=development
    export FLASK_APP=run.py
    python run.py &
    BACKEND_PID=$!
    cd ..
    
    log_success "Backend started (PID: $BACKEND_PID)"
    log_info "Backend: http://localhost:5050"
    log_info "Press Ctrl+C to stop"
    
    wait $BACKEND_PID
}

# Local Docker
local_docker() {
    log_info "Building and starting local docker containers..."
    
    if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
        log_error "Docker compose file not found: $DOCKER_COMPOSE_FILE"
        exit 1
    fi
    
    log_info "Using docker-compose file: $DOCKER_COMPOSE_FILE"
    log_info "Build cache option: $BUILD_CACHE"
    
    docker-compose -f $DOCKER_COMPOSE_FILE up -d $BUILD_CACHE
    
    log_success "Docker containers started"
    log_info "Services:"
    docker-compose -f $DOCKER_COMPOSE_FILE ps
    
    log_info ""
    log_info "Access points:"
    log_info "  GUI:     http://localhost:5050"
    log_info "  PyPNM:   http://localhost:8000/docs"
    log_info ""
    log_info "View logs: docker-compose -f $DOCKER_COMPOSE_FILE logs -f"
}

# Local Build Only
local_build() {
    log_info "Building docker images locally..."
    
    if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
        log_error "Docker compose file not found: $DOCKER_COMPOSE_FILE"
        exit 1
    fi
    
    log_info "Build cache option: $BUILD_CACHE"
    docker-compose -f $DOCKER_COMPOSE_FILE build ${BUILD_CACHE/--build/}
    
    log_success "Docker images built"
    docker images | grep pypnm
}

# Remote Deploy (git pull + restart)
remote_deploy() {
    log_info "Deploying to remote: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
    
    # Git pull
    log_info "Pulling latest code..."
    run_remote "cd $REMOTE_PATH && git pull origin main"
    
    # Restart containers
    log_info "Restarting docker containers..."
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE down && docker-compose -f $DOCKER_COMPOSE_FILE up -d"
    
    log_success "Deployment complete"
    
    # Show status
    log_info "Container status:"
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE ps"
}

# Remote Build (with/without cache)
remote_build() {
    log_info "Building docker images on remote server..."
    log_info "Build cache option: $BUILD_CACHE"
    
    # Pull latest code
    log_info "Pulling latest code..."
    run_remote "cd $REMOTE_PATH && git pull origin main"
    
    # Build images
    log_info "Building images (this may take a while)..."
    if [[ "$BUILD_CACHE" == *"no-cache"* ]]; then
        run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE build --no-cache"
    else
        run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE build"
    fi
    
    log_success "Build complete"
    
    # Show images
    log_info "Docker images:"
    run_remote "docker images | grep pypnm"
}

# Remote Rebuild (force)
remote_rebuild() {
    log_info "Force rebuilding all docker images on remote..."
    
    # Stop containers
    log_info "Stopping containers..."
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE down"
    
    # Remove old images
    log_info "Removing old images..."
    run_remote "docker images | grep pypnm | awk '{print \$3}' | xargs -r docker rmi -f" || true
    
    # Pull latest code
    log_info "Pulling latest code..."
    run_remote "cd $REMOTE_PATH && git pull origin main"
    
    # Build without cache
    log_info "Building images without cache (this will take a while)..."
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE build --no-cache"
    
    # Start containers
    log_info "Starting containers..."
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE up -d"
    
    log_success "Rebuild complete"
    remote_status
}

# Remote Restart
remote_restart() {
    log_info "Restarting remote docker containers..."
    
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE restart"
    
    log_success "Containers restarted"
    remote_status
}

# Remote Stop
remote_stop() {
    log_info "Stopping remote docker containers..."
    
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE down"
    
    log_success "Containers stopped"
}

# Remote Logs
remote_logs() {
    log_info "Fetching remote docker logs..."
    log_info "Press Ctrl+C to stop"
    
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE logs --tail=100 -f"
}

# Remote Status
remote_status() {
    log_info "Checking remote docker status..."
    
    log_info "Container status:"
    run_remote "cd $REMOTE_PATH && docker-compose -f $DOCKER_COMPOSE_FILE ps"
    
    log_info ""
    log_info "Git status:"
    run_remote "cd $REMOTE_PATH && git log --oneline -3"
    
    log_info ""
    log_info "Disk usage:"
    run_remote "cd $REMOTE_PATH && du -sh ."
}

# SSH into remote
ssh_remote() {
    log_info "Connecting to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}..."
    ssh -p $REMOTE_PORT ${REMOTE_USER}@${REMOTE_HOST}
}

# Cleanup local docker
cleanup() {
    log_warning "Cleaning up local docker resources..."
    
    read -p "This will remove all PyPNM docker containers and images. Continue? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleanup cancelled"
        exit 0
    fi
    
    # Stop containers
    log_info "Stopping containers..."
    docker-compose -f $DOCKER_COMPOSE_FILE down 2>/dev/null || true
    
    # Remove containers
    log_info "Removing containers..."
    docker ps -a | grep pypnm | awk '{print $1}' | xargs -r docker rm -f 2>/dev/null || true
    
    # Remove images
    log_info "Removing images..."
    docker images | grep pypnm | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true
    
    # Remove volumes
    log_info "Removing volumes..."
    docker volume ls | grep pypnm | awk '{print $2}' | xargs -r docker volume rm 2>/dev/null || true
    
    # Docker system prune
    log_info "Pruning docker system..."
    docker system prune -f
    
    log_success "Cleanup complete"
}

# Backup current deployment
backup() {
    log_info "Creating backup..."
    
    BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p $BACKUP_DIR
    
    # Backup git state
    log_info "Backing up git state..."
    git log --oneline -5 > $BACKUP_DIR/git-commits.txt
    git status > $BACKUP_DIR/git-status.txt
    git diff > $BACKUP_DIR/git-diff.txt
    
    # Backup docker compose files
    log_info "Backing up docker configs..."
    cp -r docker/*.yml $BACKUP_DIR/ 2>/dev/null || true
    
    # Backup .env files
    cp docker/.env* $BACKUP_DIR/ 2>/dev/null || true
    
    # Create archive
    log_info "Creating archive..."
    tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR
    rm -rf $BACKUP_DIR
    
    log_success "Backup created: $BACKUP_DIR.tar.gz"
}

# Execute action
case $ACTION in
    local-dev)
        local_dev
        ;;
    local-docker)
        local_docker
        ;;
    local-build)
        local_build
        ;;
    remote-deploy)
        remote_deploy
        ;;
    remote-build)
        remote_build
        ;;
    remote-rebuild)
        remote_rebuild
        ;;
    remote-restart)
        remote_restart
        ;;
    remote-stop)
        remote_stop
        ;;
    remote-logs)
        remote_logs
        ;;
    remote-status)
        remote_status
        ;;
    ssh)
        ssh_remote
        ;;
    cleanup)
        cleanup
        ;;
    backup)
        backup
        ;;
    *)
        log_error "Unknown action: $ACTION"
        show_help
        exit 1
        ;;
esac
