# PyPNM Remote Agent Integration

This directory contains files to integrate remote agent support into PyPNM.

## Quick Integration

### 1. Copy Files to PyPNM

```bash
# From PyPNMGui directory
cp -r pypnm_integration/transport /path/to/PyPNM/src/pypnm/
cp pypnm_integration/api/agent_router.py /path/to/PyPNM/src/pypnm/api/routers/
```

### 2. Register Router in FastAPI

Edit `PyPNM/src/pypnm/api/main.py`:

```python
# Add import
from pypnm.api.routers.agent_router import router as agent_router

# Add router (after other routers)
app.include_router(agent_router)
```

### 3. Set Environment Variable

```bash
export PYPNM_AGENT_TOKEN="your-secure-token-here"
```

Or add to `docker-compose.yml`:

```yaml
services:
  pypnm:
    environment:
      - PYPNM_AGENT_TOKEN=your-secure-token-here
```

### 4. Deploy Agent on Jump Server

See [agent/](../agent/) for agent installation on Jump Server.

## Using Remote Transport in PyPNM Code

```python
from pypnm.transport import RemoteAgentTransport, get_agent_manager

# Create transport
transport = RemoteAgentTransport()

# SNMP operations (async)
result = await transport.snmp_get("10.1.2.3", "1.3.6.1.2.1.1.1.0")
result = await transport.snmp_walk("10.1.2.3", "1.3.6.1.2.1.1")

# CMTS commands
result = await transport.cmts_command("cmts.local", "show cable modem")

# PNM file retrieval
file_data = await transport.get_pnm_file("/pnm/rxmer_file.bin")
```

## API Endpoints

Once integrated, these endpoints are available:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents/ws` | WebSocket | Agent connection endpoint |
| `/api/agents/` | GET | List connected agents |
| `/api/agents/{id}` | GET | Get agent details |
| `/api/agents/{id}/ping` | POST | Ping an agent |
| `/api/agents/status/summary` | GET | Connectivity summary |

## Files

| File | Purpose | Copy To |
|------|---------|---------|
| `transport/__init__.py` | Package init | `src/pypnm/transport/` |
| `transport/agent_manager.py` | WebSocket connection manager | `src/pypnm/transport/` |
| `transport/remote_transport.py` | SNMP/SSH via agent | `src/pypnm/transport/` |
| `api/agent_router.py` | FastAPI router | `src/pypnm/api/routers/` |
