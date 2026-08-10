# PyPNM Agent SSH Tunnel Setup

Use an SSH tunnel only when pyPNMAgent cannot directly reach the PyPNM API. The tunnel carries the canonical PyPNM agent WebSocket; it does not connect to PyPNMGui.

## Flow

```text
pyPNMAgent -> local tunnel port -> SSH -> PyPNM API port -> /api/agents/ws
```

PyPNM remains the owner of authentication, task routing, and agent state.

## Agent-managed tunnel

Current `agent_config.json` structure:

```json
{
  "agent_id": "jump-server-01",
  "pypnm_server": {
    "url": "ws://127.0.0.1:18000/api/agents/ws",
    "auth_token": "your-token"
  },
  "pypnm_ssh_tunnel": {
    "enabled": true,
    "ssh_host": "pypnm-server.example.com",
    "ssh_port": 22,
    "ssh_user": "pypnm-agent",
    "ssh_key_file": "~/.ssh/id_pypnm_server",
    "local_port": 18000,
    "remote_port": 8000
  }
}
```

The configured WebSocket URL must use the local tunnel port and end in `/api/agents/ws`.

## Manual equivalent

```bash
ssh -N -L 18000:127.0.0.1:8000 \
  -i ~/.ssh/id_pypnm_server pypnm-agent@pypnm-server.example.com
```

Then configure `PYPNM_SERVER_URL=ws://127.0.0.1:18000/api/agents/ws`.

## Verification

```bash
ssh -v -i ~/.ssh/id_pypnm_server pypnm-agent@pypnm-server.example.com 'echo connected'
curl http://127.0.0.1:18000/api/agents
journalctl --user -u pypnm-agent --since '10 minutes ago'
```

Use a dedicated restricted SSH key, verify host keys, keep private-key permissions at `0600`, and do not expose the local forwarding port externally. For a reverse tunnel serving an isolated peer agent, see `multi-agent-ssh-tunnel.md`.
