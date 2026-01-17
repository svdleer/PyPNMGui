#!/bin/bash
# Deploy GUI with PyPNM plot directory mounted

cd /opt/pypnm-gui-lab/docker
docker compose build gui-server

docker rm -f pypnm-gui-lab

# Run with PyPNM data volume mounted
docker run -d \
  --name pypnm-gui-lab \
  -p 5051:5050 \
  --network docker_pypnm-net \
  --network compose_default \
  -v compose_pypnm_data:/pypnm-data:ro \
  -e REDIS_HOST=redis-lab \
  -e REDIS_PORT=6379 \
  -e AGENT_HOST=agent-lab \
  -e AGENT_PORT=50051 \
  -e PYPNM_BASE_URL=http://pypnm-api:8000 \
  -e PYPNM_MODE=lab \
  -e FLASK_ENV=lab \
  docker-gui-server

echo "GUI deployed with PyPNM plot directory mounted"
