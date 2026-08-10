# PyPNM Remote Agent Integration

PyPNM owns remote-agent execution. pyPNMAgent connects to PyPNM over the canonical WebSocket endpoint and executes capability-scoped SNMP, SSH, and file operations for PyPNM.

## Architecture

```text
Browser -> PyPNMGui -> PyPNM API -> /api/agents/ws -> pyPNMAgent -> DOCSIS targets
```

- **PyPNM** owns agent authentication, connection state, task routing, timeouts, and results.
- **pyPNMAgent** initiates the WebSocket connection and advertises its capabilities.
- **PyPNMGui** is an HTTP client of PyPNM and does not expose a remote-agent endpoint.
- **`/ws/utsc/<mac>`** in PyPNMGui is a browser-facing spectrum stream and is not an agent connection.

## Canonical implementation

The current implementation is already present:

- PyPNM agent manager: `src/pypnm/api/agent/manager.py`
- PyPNM agent routes: `src/pypnm/api/routes/agents/router.py`
- Agent WebSocket: `/api/agents/ws`
- Agent runtime: `pyPNMAgent/agent.py`

Do not add a remote-agent WebSocket endpoint to PyPNMGui or create a second agent manager there.

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

Environment-based configuration uses:

```bash
export PYPNM_SERVER_URL=ws://pypnm-server:8000/api/agents/ws
export PYPNM_AGENT_ID=jump-server-01
export PYPNM_AUTH_TOKEN=your-token
```

Use `wss://` when the PyPNM API is exposed through TLS. Verify connected agents through `GET /api/agents` on PyPNM.