# PyPNM Remote Agent Integration

This module provides a remote agent client for PyPNM to communicate with
Jump Server agents when direct SNMP/SSH access isn't available.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                      │
│   PYPNM SERVER (Docker/Kubernetes)                                                   │
│   ════════════════════════════════                                                   │
│   ┌─────────────┐      FastAPI       ┌─────────────────────────────────────────┐     │
│   │   Browser   │───────────────────►│  PyPNM (FastAPI + WebSocket)           │     │
│   └─────────────┘    /docs           │  - PNM analysis & dashboards            │     │
│                                      │  - Agent WebSocket endpoint /ws/agent   │     │
│                                      │  - Proxies SNMP/SSH via remote agent    │     │
│                                      └──────────────────▲──────────────────────┘     │
│                                                         │                            │
│ ════════════════════════════════════════════════════════│════════════════════════════│
│                                                         │ SSH Tunnel                 │
│   JUMP SERVER                                           │ (WebSocket inside)         │
│   ═══════════                                           │                            │
│   ┌─────────────────────────────────────────────────────┴────────────────────────┐   │
│   │                                                                              │   │
│   │   PyPNM Remote Agent  (~/.pypnm-agent/)                                      │   │
│   │   ├── run_background.sh start/stop/status                                    │   │
│   │   └── Connects TO PyPNM server via WebSocket                                 │   │
│   │                                                                              │   │
│   │   Executes on behalf of PyPNM:                                               │   │
│   │   ├── SNMP commands → modems (via CM Proxy SSH)                              │   │
│   │   ├── SNMP commands → CMTS (direct)                                          │   │
│   │   ├── SSH commands → CMTS                                                    │   │
│   │   └── File retrieval → TFTP server (via SSH)                                 │   │
│   │                                                                              │   │
│   └───────┬───────────────────┬───────────────────┬───────────────────┬──────────┘   │
│           │ SSH               │ SSH               │ SNMP              │ SSH          │
│           ▼                   ▼                   ▼                   ▼              │
│   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐      │
│   │   CM Proxy    │   │ TFTP Server   │   │     CMTS      │   │     CMTS      │      │
│   │   (SNMP→CMs)  │   │  /tftpboot/   │   │  (SNMP)       │   │   (SSH)       │      │
│   └───────┬───────┘   └───────────────┘   └───────────────┘   └───────────────┘      │
│           │ SNMP                                                                     │
│           ▼                                                                          │
│   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐                          │
│   │ Cable Modem   │   │ Cable Modem   │   │ Cable Modem   │                          │
│   └───────────────┘   └───────────────┘   └───────────────┘                          │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## Integration with PyPNM

The agent integrates with PyPNM's existing architecture by providing an alternative
transport layer when the PyPNM server cannot directly reach SNMP targets.

### PyPNM Configuration

In `deploy/docker/config/system.json`, configure remote agent mode:

```json
{
    "snmp": {
        "transport": "remote_agent",
        "remote_agent": {
            "enabled": true,
            "websocket_path": "/ws/agent",
            "auth_token": "your-secure-token",
            "timeout": 30
        }
    }
}
```

### How It Works

1. **PyPNM receives API request** (e.g., GET /api/pnm/modem/{mac}/rxmer)
2. **PyPNM checks transport mode** - if `remote_agent`, routes via WebSocket
3. **Agent receives command** via WebSocket connection
4. **Agent executes SNMP** on CM Proxy or directly on CMTS
5. **Agent returns result** to PyPNM via WebSocket
6. **PyPNM processes data** and returns to client

## Files to Add to PyPNM

Copy these files into your PyPNM installation:

```
PyPNM/
├── src/pypnm/
│   └── transport/
│       ├── __init__.py
│       ├── remote_agent.py      # WebSocket client for agent communication
│       └── agent_manager.py     # Manages connected agents
└── agent/                       # Standalone agent for Jump Server
    ├── agent.py
    ├── ssh_tunnel.py
    ├── agent_config.example.json
    ├── requirements.txt
    ├── install.sh
    └── run_background.sh
```

## Quick Integration

### 1. Add WebSocket endpoint to PyPNM FastAPI

Add to your FastAPI app (e.g., in `src/pypnm/api/main.py`):

```python
from fastapi import WebSocket, WebSocketDisconnect
from pypnm.transport.agent_manager import AgentManager

agent_manager = AgentManager()

@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    await agent_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await agent_manager.handle_message(websocket, data)
    except WebSocketDisconnect:
        agent_manager.disconnect(websocket)
```

### 2. Create transport layer

Create `src/pypnm/transport/remote_agent.py`:

```python
import asyncio
from typing import Optional
from pypnm.transport.agent_manager import AgentManager

class RemoteAgentTransport:
    """Execute SNMP/SSH commands via remote agent."""
    
    def __init__(self, agent_manager: AgentManager):
        self.agent_manager = agent_manager
    
    async def snmp_get(
        self,
        target_ip: str,
        oid: str,
        community: str = "private",
        agent_id: Optional[str] = None
    ) -> dict:
        """Execute SNMP GET via remote agent."""
        agent = self.agent_manager.get_agent(agent_id)
        if not agent:
            raise RuntimeError("No agent available")
        
        result = await agent.execute({
            "command": "snmp_get",
            "params": {
                "target_ip": target_ip,
                "oid": oid,
                "community": community
            }
        })
        return result
    
    async def snmp_walk(self, target_ip: str, oid: str, **kwargs) -> dict:
        # Similar to snmp_get
        ...
```

### 3. Update SNMP executor to use transport

In your existing SNMP code, add transport selection:

```python
from pypnm.config import get_system_config

config = get_system_config()

if config.snmp.transport == "remote_agent":
    # Use remote agent
    from pypnm.transport.remote_agent import RemoteAgentTransport
    transport = RemoteAgentTransport(agent_manager)
    result = await transport.snmp_get(target_ip, oid)
else:
    # Direct SNMP (existing code)
    result = snmp_get_direct(target_ip, oid)
```

## Agent Setup on Jump Server

See the main [agent/README.md](../agent/README.md) for full setup instructions.

Quick start:
```bash
cd agent
./install.sh
nano ~/.pypnm-agent/agent_config.json  # Configure
~/.pypnm-agent/run_background.sh start
```

## Docker Integration

The PyPNM Docker container can accept agent connections. Ensure the WebSocket
endpoint is exposed:

```yaml
# docker-compose.yml
services:
  pypnm:
    image: ghcr.io/pypnmapps/pypnm:latest
    ports:
      - "8080:8080"   # FastAPI
    environment:
      - PYPNM_AGENT_ENABLED=true
      - PYPNM_AGENT_TOKEN=your-secure-token
```

The agent on Jump Server connects via SSH tunnel to this endpoint.
