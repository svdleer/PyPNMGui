# PyPNM Docker Deployment

## Quick Start - PyPNM with Remote Agent Support

```bash
cd docker

# Copy and configure environment
cp .env.pypnm .env
nano .env  # Set PYPNM_AGENT_TOKEN

# Start PyPNM server
docker-compose -f docker-compose.pypnm.yml up -d

# View logs
docker-compose -f docker-compose.pypnm.yml logs -f

# Check health
curl http://localhost:8080/api/health

# Check agent connectivity
curl http://localhost:8080/api/agents/status/summary
```

PyPNM available at `http://localhost:8080`
- Swagger UI: `http://localhost:8080/docs`
- Agent endpoint: `ws://localhost:8080/api/agents/ws`

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   YOUR SERVER (Docker Host)                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  docker-compose.pypnm.yml                                           │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │  pypnm (container)                                          │    │   │
│   │  │  - FastAPI server (PyPNM)                                   │    │   │
│   │  │  - PNM dashboards & analysis                                │    │   │
│   │  │  - Agent WebSocket endpoint /api/agents/ws                  │    │   │
│   │  │  - Port 8080                                                │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                              ▲                                              │
│                              │ WebSocket (via SSH tunnel)                   │
│                              │                                              │
├──────────────────────────────┼──────────────────────────────────────────────┤
│                              │                                              │
│   JUMP SERVER                │                                              │
│   ┌──────────────────────────┴──────────────────────────────────────────┐   │
│   │  PyPNM Remote Agent                                                 │   │
│   │  (runs directly on Jump Server, or in Docker)                       │   │
│   │                                                                     │   │
│   │  Option A: Direct install (recommended for production)              │   │
│   │    ~/.pypnm-agent/run_background.sh start                           │   │
│   │                                                                     │   │
│   │  Option B: Docker                                                   │   │
│   │    docker-compose -f docker-compose.agent.yml up -d                 │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Deployment Options

### PyPNM Server Only

```bash
docker-compose -f docker-compose.pypnm.yml up -d
```

### Full Stack (Server + Agent for testing)

```bash
docker-compose -f docker-compose.full.yml up -d
```

## Agent Deployment Options

### Option A: Direct Install on Jump Server (Recommended)

Best for production - agent runs directly on Jump Server with SSH keys:

```bash
# On Jump Server
cd /path/to/PyPNMGui/agent
./install.sh

# Configure
nano ~/.pypnm-agent/agent_config.json

# Start
~/.pypnm-agent/run_background.sh start
```

See [SSH_TUNNEL_SETUP.md](../docs/SSH_TUNNEL_SETUP.md) for full instructions.

### Option B: Agent in Docker

If you prefer Docker on Jump Server:

```bash
# On Jump Server
mkdir -p pypnm-agent/{agent-config,agent-ssh,agent-logs}
cd pypnm-agent

# Copy compose file
cp /path/to/docker-compose.agent.yml ./docker-compose.yml

# Create config
cat > agent-config/agent_config.json << 'EOF'
{
    "agent_id": "jump-docker-01",
    "pypnm_server": {
        "url": "ws://localhost:8080/api/agents/ws",
        "auth_token": "your-token-here",
        "reconnect_interval": 5
    },
    "pypnm_ssh_tunnel": {
        "enabled": true,
        "ssh_host": "pypnm-server.example.com",
        "ssh_port": 22,
        "ssh_user": "pypnm",
        "ssh_key_file": "/home/pypnm/.ssh/id_pypnm_server",
        "local_port": 8080,
        "remote_port": 8080
    },
    "cm_proxy": {
        "host": "cm-proxy.internal",
        "port": 22,
        "username": "pypnm",
        "key_file": "/home/pypnm/.ssh/id_cm_proxy"
    }
}
EOF

# Add SSH keys (copy your existing keys)
cp ~/.ssh/id_pypnm_server* agent-ssh/
cp ~/.ssh/id_cm_proxy* agent-ssh/
chmod 600 agent-ssh/*

# Start
docker-compose up -d

# View logs
docker-compose logs -f
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYPNM_AGENT_TOKEN` | Token agents use to authenticate | (required) |
| `PYPNM_PORT` | PyPNM server port | 8080 |
| `PYPNM_VERSION` | PyPNM Docker image version | latest |
| `LOG_LEVEL` | Logging level | INFO |

## Volumes

| Volume | Purpose |
|--------|---------|
| `pypnm-data` | Database and persistent data |
| `pypnm-logs` | Application logs |

## Production Deployment

### With Nginx Reverse Proxy

```nginx
upstream pypnm {
    server 127.0.0.1:8080;
}

server {
    listen 443 ssl http2;
    server_name pypnm.example.com;

    ssl_certificate /etc/ssl/certs/pypnm.crt;
    ssl_certificate_key /etc/ssl/private/pypnm.key;

    location / {
        proxy_pass http://pypnm;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # Agent WebSocket endpoint
    location /api/agents/ws {
        proxy_pass http://pypnm;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

### With Traefik

Add labels to `docker-compose.pypnm.yml`:

```yaml
services:
  pypnm:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.pypnm.rule=Host(`pypnm.example.com`)"
      - "traefik.http.routers.pypnm.tls=true"
      - "traefik.http.services.pypnm.loadbalancer.server.port=8080"
```

## Troubleshooting

### Check PyPNM Server
```bash
docker-compose -f docker-compose.pypnm.yml logs pypnm
docker-compose -f docker-compose.pypnm.yml exec pypnm curl localhost:8080/api/health
```

### Check Connected Agents
```bash
curl http://localhost:8080/api/agents/
curl http://localhost:8080/api/agents/status/summary
```

### View Agent Logs
```bash
docker-compose -f docker-compose.pypnm.yml exec pypnm cat /app/logs/pypnm.log | grep agent
```

### Rebuild After Code Changes
```bash
docker-compose -f docker-compose.pypnm.yml build --no-cache
docker-compose -f docker-compose.pypnm.yml up -d
```

## Docker Files Reference

| File | Description |
|------|-------------|
| `docker-compose.pypnm.yml` | PyPNM server with agent support |
| `docker-compose.agent.yml` | Standalone agent for Jump Server |
| `docker-compose.full.yml` | Full stack (server + agent) for testing |
| `Dockerfile.pypnm-agent` | PyPNM with agent integration |
| `Dockerfile.agent` | Remote agent image |
| `.env.pypnm` | Environment template |
