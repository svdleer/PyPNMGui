#!/bin/bash
set -e
REMOTE_HOST="localhost"
REMOTE_PORT="2222"
REMOTE_USER="svdleer"
REMOTE_DEPLOY_DIR="/opt/pypnm-gui"

build_images() {
    echo "Syncing code..."
    rsync -avz --delete -e "ssh -p ${REMOTE_PORT}" --exclude='venv' --exclude='__pycache__' --exclude='.git' ./ ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DEPLOY_DIR}/
    echo "Building on remote with proxy (cache-busted)..."
    ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST} "cd /opt/pypnm-gui && docker build --build-arg CACHEBUST=\$(date +%s) --build-arg HTTP_PROXY=http://proxy.ext.oss.local:8080 --build-arg HTTPS_PROXY=http://proxy.ext.oss.local:8080 --build-arg http_proxy=http://proxy.ext.oss.local:8080 --build-arg https_proxy=http://proxy.ext.oss.local:8080 -f docker/Dockerfile.server -t pypnm-gui:latest . && docker build --build-arg HTTP_PROXY=http://proxy.ext.oss.local:8080 --build-arg HTTPS_PROXY=http://proxy.ext.oss.local:8080 --build-arg http_proxy=http://proxy.ext.oss.local:8080 --build-arg https_proxy=http://proxy.ext.oss.local:8080 -f docker/Dockerfile.agent -t pypnm-gui-agent:latest ."
}

deploy() {
    ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST} "cd /opt/pypnm-gui/docker && docker-compose down || true && docker-compose up -d && docker-compose ps"
}

case "$1" in
    build) build_images ;;
    deploy) deploy ;;
    all) build_images && deploy ;;
    *) echo "Usage: $0 {build|deploy|all}"; exit 1 ;;
esac
