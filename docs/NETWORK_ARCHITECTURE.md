# PyPNM Network Architecture

## Overview

PyPNMGui, PyPNM, and pyPNMAgent have separate network responsibilities:

```text
User browser -> PyPNMGui -> PyPNM API -> /api/agents/ws -> pyPNMAgent
                                                        -> CMTS / modems / file servers
```

- **PyPNMGui** serves the browser UI and proxies application requests to PyPNM.
- **PyPNM** owns PNM orchestration, analysis, persistence, and remote-agent connections.
- **pyPNMAgent** runs where DOCSIS targets are reachable and initiates an outbound WebSocket connection to PyPNM.
- **`/ws/utsc/<mac>`** is a browser-facing GUI spectrum stream, not an agent endpoint.

## Restricted-network topology

The agent can run in a management zone that can reach CMTS, modem, TFTP, or FTP networks. Only outbound reachability from the agent to the PyPNM API is required. When that route is unavailable, use an approved SSH tunnel carrying the same `/api/agents/ws` endpoint.

## Request flow

```text
1. Browser sends an authenticated request to PyPNMGui.
2. PyPNMGui calls the corresponding PyPNM HTTP API.
3. PyPNM selects an agent by advertised capability.
4. PyPNM sends the task over /api/agents/ws.
5. The agent performs the approved operation and returns its result.
6. PyPNM processes the result and PyPNMGui renders it.
```

PNM file catalog and retrieval operations follow the same ownership path; the GUI does not directly command remote agents.

## Agent configuration

```json
{
  "agent_id": "jump-server-01",
  "pypnm_server": {
    "url": "ws://pypnm-server:8000/api/agents/ws",
    "auth_token": "your-token"
  }
}
```

Use `wss://` behind TLS. Keep agent/server tokens aligned, restrict API reachability, advertise only required capabilities, use separate SSH keys per target, and avoid exposing SNMP or file services outside their management zones.
