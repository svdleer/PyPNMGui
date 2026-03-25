# PyPNM GUI - Production Setup

This guide explains how to deploy PyPNM GUI in production using `docker-compose.prod.yml`.

## Components

The production stack includes:

1. **PyPNM API** - FastAPI server for PNM operations
2. **GUI Server** - Flask web interface with ISW API integration
3. **Redis** - Cache for modem data and ISW API responses
4. **Agent** - SNMP agent (runs on host, **not** in Docker)

**Important:** The agent typically runs directly on the jump server/host machine (not in Docker) for better network access to CMTS devices. See [Running Agent on Host](#running-agent-on-host) section below.

## Prerequisites

- Docker and Docker Compose installed
- Network access to:
  - CMTS devices (SNMP)
  - ISW API at `appdb.oss.local`
  - TFTP server
- PyPNM source code at `/opt/pypnm`
- pyPNMAgent source code at `/opt/pypnm-agent`

## Source Code Mounts

This setup uses **live source mounts** for development flexibility:

- **PyPNM API:** `/opt/pypnm/src/pypnm` → `/app/pypnm`
- **GUI Backend:** `../backend/app` → `/app/app`
- **GUI Frontend:** `../frontend` → `/app/frontend`
- **Agent:** `/opt/pypnm-agent/agent.py` → `/app/agent.py`

Changes to source code are reflected immediately without rebuilding containers.

## Configuration

### 1. Copy Environment File

```bash
cd /opt/pypnmgui/docker
cp .env.pypnm .env
```

### 2. Edit `.env` File

**Required changes:**

```bash
# Security - CHANGE THESE!
AGENT_AUTH_TOKEN=your-secure-token-here
SECRET_KEY=your-flask-secret-here


# Per-vendor SNMP communities (for agent)
SNMP_COMMUNITY_ARRIS=public
SNMP_COMMUNITY_CASA=public
SNMP_COMMUNITY_CISCO=public
SNMP_COMMUNITY_COMMSCOPE=public
# ISW API - Update if different
APPDB_API_URL=https://appdb.oss.local/isw/api
APPDB_API_USER=isw
APPDB_API_PASS=your-password-here

# TFTP Servers - Update for your network
TFTP_IPV4=172.16.6.101
TFTP_IPV4_ALT=127.0.0.1

# SNMP Communities - Update for your network
CMTS_COMMUNITY=public
MODEM_COMMUNITY=private
```

## Deployment

### Start Services

```bash
cd /opt/pypnmgui/docker
docker-compose -f docker-compose.prod.yml up -d
```

# Check agent connection
docker-compose -f docker-compose.prod.yml logs agent-prod | tail -20

### Check Status

```bash
docker-compose -f docker-compose.prod.yml ps
docker-compose -f docker-compose.prod.yml logs -f
```

### Health Checks


# Check agent status via API
curl http://localhost:8000/api/agents/status
```bash
# PyPNM API
curl http://localhost:8000/health

# GUI Server
curl http://localhost:5050/api/health

# Redis
docker exec eve-li-redis-prod redis-cli ping
```

## Access

- **Web GUI:** http://localhost:5050
- **PyPNM API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
via PyPNM API → Agent → SNMP
## Usage

1. Open http://localhost:5050 in your browser
2. The CMTS dropdown will be populated from ISW API automatically
3. Select a CMTS and click "Get Modems"
4. The system will query the CMTS directly via PyPNM API (no agent required)

## Data Flow

```
Frontend (Browser)
    ↓
GUI Server (Flask)
    ↓ Routes request to Agent via WebSocket
Agent (pypnm-agent-prod)
    ↓ SNMP queriesS list from ISW API
ISW API (appdb.oss.local/isw/api)
    ↓ Returns CMTS inventory
GUI Server
    ↓ User selects CMTS and clicks "Get Modems"
PyPNM API
    ↓ Direct SNMP to CMTS
CMTS Device
    ↓ Returns modem list
Redis Cache (24h TTL)
```

## Maintenance

### View Logs

```bash
# All services
docker-compose -f docker-compose.prod.yml logs -f agent-prod
docker-compose -f docker-compose.prod.yml logs -f

# Specific service
docker-compose -f docker-compose.prod.yml logs -f gui-server-prod
docker-compose -f docker-compose.prod.yml logs -f pypnm-api
```

### Restart Services

```bash
# Restart all
docker-compose -f docker-compose.prod.yml restart

# Restart specific service
docker-compose -f docker-compose.prod.yml restart gui-server-prod
```

### Clear Redis Cache

```bash
docker exec eve-li-redis-prod redis-cli FLUSHALL
```

### Update Containers
/opt/pypnm-agent
git pull

cd /opt/pypnmgui
git pull

# With source mounts, changes are live - no rebuild needed!
# Only restart containers to reload Python modules:
cd docker
docker-compose -f docker-compose.prod.yml restart

# Or rebuild if Dockerfile changed:

cd /opt/pypnmgui
git pull

# Rebuild and restart
cd docker
docker-compose -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.prod.yml up -d
```

### Stop Services
Agent not connecting

Check agent logs on the host and ensure it can reach PyPNM API:

```bash
# Check agent status via API
curl http://localhost:8000/api/agents/status

# Check agent logs on host
# If running as systemd:
sudo systemctl status pypnm-agent
sudo journalctl -u pypnm-agent -n 50

# If running in tmux:
tmux attach -t pypnm-agent

# Test WebSocket connecti on host:
```bash
# For systemd:
sudo systemctl status pypnm-agent

# For tmux:
tmux list-sessions | grep pypnm-agent

# For background process:
ps aux | grep agent.py
```

2. Verify agent token matches:
```bash
# Check GUI token
docker exec pypnm-gui-prod env | grep AGENT_AUTH_TOKEN

# Check agent token on host
cat /opt/pypnm-agent/agent_config.json | grep token
# Or check environment
echo $PYPNM_AGENT_TOKEN
```

3. Check PyPNM API logs:
```bash
docker-compose -f docker-compose.prod.yml logs pypnm-api | grep -i agent
```

4. Restart agent on host:
```bash
sudo systemctl restart pypnm-agent
# Or reconnect to tmux and restar
2. Verify agent token matches:
```bash
docker exec pypnm-gui-prod env | grep AGENT_AUTH_TOKEN
docker exec pypnm-agent-prod env | grep PYPNM_AGENT_TOKEN
```
# Restart GUI or API
docker-compose -f docker-compose.prod.yml restart gui-server-prod
docker-compose -f docker-compose.prod.yml restart pypnm-api

# Restart agent on host
sudo systemctl restart pypnm-agent
```

For Flask changes, the gunicorn worker will auto-reload if files change.

### Running Agent in Docker (Optional)

If you really need to run the agent in Docker, uncomment the `agent-prod` service in [docker-compose.prod.yml](docker-compose.prod.yml) and the agent volume definitions. This is **not recommended** for production as it may have network access limitations.
docker-compose -f docker-compose.prod.yml down -v
```

## Troubleshooting

### GUI shows "No agents connected"
# Source code changes not reflected

The containers mount source code directories, but Python needs to reload modules:

```bash
# Restart the affected service
docker-compose -f docker-compose.prod.yml restart gui-server-prod
docker-compose -f docker-compose.prod.yml restart pypnm-api
docker-compose -f docker-compose.prod.yml restart agent-prod
```

For Flask changes, the gunicorn worker will auto-reload if files change.

##
This is expected. The production setup uses PyPNM API direct SNMP mode, not agent mode.

### ISW API connection fails

1. Check network connectivity to `appdb.oss.local`:
```bash
docker exec pypnm-gui-prod curl -I https://appdb.oss.local/isw/api
```

2. Verify credentials in `.env` file

3. Check GUI logs:
```bash
docker-compose -f docker-compose.prod.yml logs gui-server-prod | grep -i "appdb\|isw"
```

### CMTS list is empty

1. Check ISW API response:
```bash
curl -u isw:password https://appdb.oss.local/isw/api/search?type=hostname&q=*
```

2. Check Flask is in production mode:
```bash
docker exec pypnm-gui-prod env | grep FLASK_ENV
# Should show: FLASK_ENV=production
```

### Redis not working

Check Redis container:
```bash
docker-compose -f docker-compose.prod.yml ps redis-prod
docker exec eve-li-redis-prod redis-cli ping
```

## Network Mode

This setup uses `network_mode: host` for all services, meaning containers share the host's network stack. This provides:

- Direct access to CMTS devices
- No port mapping needed
- Better performance

If you need isolated networking, change to bridge mode and add port mappings.

## Security Notes

1. **Change default tokens** in `.env` file
2. **Use HTTPS** in production (add nginx/traefik reverse proxy)
3. **Restrict network access** to trusted IPs only
4. **Rotate ISW API credentials** regularly
5. **Monitor logs** for unauthorized access attempts

## Support

For issues, check:
- [PyPNMGui Documentation](../README.md)
- [Docker Deployment Guide](./README.md)
- Container logs with `docker-compose logs`
