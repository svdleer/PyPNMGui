# PyPNM Remote Agent Integration

## Summary

This PR adds remote agent support to PyPNM, enabling SNMP/SSH operations through
a Jump Server when PyPNM cannot directly reach cable modems or CMTS systems.

## Problem

In many production environments, the PyPNM server cannot directly reach:
- Cable modems (SNMP access requires being on specific network segments)
- CMTS systems (may require VPN or jump host access)
- TFTP servers (PNM files stored on isolated network)

## Solution

A lightweight WebSocket-based agent that:
1. Runs on a Jump Server with network access to target devices
2. Connects TO PyPNM (outbound connection, no inbound firewall rules needed)
3. Executes SNMP/SSH commands on behalf of PyPNM
4. Returns results via WebSocket

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PyPNM Server (FastAPI)                                         │
│  ├── /api/agents/ws      ← Agent WebSocket endpoint (NEW)       │
│  └── /api/agents/        ← Agent management API (NEW)           │
│                              ▲                                  │
│                              │ WebSocket                        │
├──────────────────────────────┼──────────────────────────────────┤
│  Jump Server                 │                                  │
│  └── PyPNM Remote Agent ─────┘                                  │
│      └── Executes: SNMP GET/WALK/SET, SSH commands, TFTP fetch  │
└─────────────────────────────────────────────────────────────────┘
```

## Files Added

### Server-side (PyPNM)

| File | Description |
|------|-------------|
| `src/pypnm/transport/__init__.py` | Transport layer package |
| `src/pypnm/transport/agent_manager.py` | WebSocket connection manager |
| `src/pypnm/transport/remote_transport.py` | SNMP/SSH via remote agent |
| `src/pypnm/api/routers/agent_router.py` | FastAPI router for `/api/agents/` |

### Agent (Jump Server)

| File | Description |
|------|-------------|
| `agent/agent.py` | Main agent with command handlers |
| `agent/ssh_tunnel.py` | SSH tunnel manager |
| `agent/requirements.txt` | Python dependencies |
| `agent/install.sh` | User-mode installer |
| `agent/run_background.sh` | Background process manager |
| `agent/agent_config.example.json` | Configuration template |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents/ws` | WebSocket | Agent connection endpoint |
| `/api/agents/` | GET | List connected agents |
| `/api/agents/{id}` | GET | Get agent details |
| `/api/agents/{id}/ping` | POST | Ping an agent |
| `/api/agents/status/summary` | GET | Connectivity summary |

## Agent Commands

| Command | Description |
|---------|-------------|
| `snmp_get` | SNMP GET operation |
| `snmp_walk` | SNMP WALK operation |
| `snmp_set` | SNMP SET operation |
| `snmp_bulk_get` | Multiple SNMP GETs |
| `cmts_command` | Execute SSH command on CMTS |
| `tftp_get` | Retrieve file from TFTP server |
| `execute_pnm` | Trigger PNM measurement |
| `ping` | Network reachability test |

## Configuration

### PyPNM Server

```bash
export PYPNM_AGENT_TOKEN="your-secure-token"
```

### Agent (agent_config.json)

```json
{
    "agent_id": "jump-server-01",
    "pypnm_server": {
        "url": "ws://pypnm-server:8080/api/agents/ws",
        "auth_token": "your-secure-token"
    },
    "cm_proxy": {
        "host": "cm-proxy.internal",
        "username": "pypnm",
        "key_file": "~/.ssh/id_cm_proxy"
    }
}
```

## Usage in PyPNM Code

```python
from pypnm.transport import RemoteAgentTransport

transport = RemoteAgentTransport()

# SNMP via remote agent
result = await transport.snmp_get("10.1.2.3", "1.3.6.1.2.1.1.1.0")

# CMTS command via remote agent  
result = await transport.cmts_command("cmts.local", "show cable modem")
```

## Installation

### Server

```python
# In src/pypnm/api/main.py
from pypnm.api.routers.agent_router import router as agent_router
app.include_router(agent_router)
```

### Agent

```bash
cd agent
./install.sh
~/.pypnm-agent/run_background.sh start
```

## Testing

```bash
# Check agent connectivity
curl http://localhost:8080/api/agents/status/summary

# List connected agents
curl http://localhost:8080/api/agents/
```

## Security

- Token-based authentication between agent and server
- All agent connections are outbound (no inbound firewall rules needed)
- SSH key-based authentication for SNMP proxy and CMTS access
- Agent runs as non-root user

## Backward Compatibility

This is an additive change. Existing direct SNMP operations continue to work.
Remote agent transport is only used when configured.
