# PyPNM Remote Agent Architecture

## Ownership

PyPNM owns remote-agent connections and exposes the canonical WebSocket endpoint:

```text
/api/agents/ws
```

PyPNMGui calls PyPNM over HTTP and does not accept remote-agent connections. Its `/ws/utsc/<mac>` endpoint is a separate browser-facing spectrum stream.

## Data flow

```text
Browser -> PyPNMGui -> PyPNM API -> /api/agents/ws -> pyPNMAgent -> SNMP/SSH/TFTP
```

The agent initiates the outbound WebSocket connection, which supports networks where PyPNM cannot directly reach DOCSIS equipment. PyPNM selects a connected agent by advertised capability and sends approved tasks through that connection.

## Agent configuration

Use the complete PyPNM WebSocket URL in JSON configuration:

```json
{
  "agent_id": "agent-01",
  "pypnm_server": {
    "url": "ws://pypnm-server:8000/api/agents/ws",
    "auth_token": "your-token"
  }
}
```

Equivalent environment variables:

```bash
export PYPNM_SERVER_URL=ws://pypnm-server:8000/api/agents/ws
export PYPNM_AUTH_TOKEN=your-token
export PYPNM_AGENT_ID=agent-01
```

The PyPNM server validates agent authentication with `PYPNM_AGENT_TOKEN`. Agent and server token values must match.

## Verification

Check the PyPNM agent API rather than the GUI:

```bash
curl http://pypnm-server:8000/api/agents
```

The response reports connected agents and their capabilities. For connection failures, verify the URL ends in `/api/agents/ws`, confirm network reachability to the PyPNM API port, and review PyPNM and agent logs.

## Security

Use TLS (`wss://`) through the approved reverse proxy in production, use a non-default token, restrict network access to the API, use SSH keys rather than passwords, and keep agent command capabilities minimal.