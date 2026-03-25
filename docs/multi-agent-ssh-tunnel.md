# Multi-Agent Setup with Reverse SSH Tunnel

## Scenario

- **Webserver**: Runs PyPNMGui + PyPNM API (port 8000)
- **Server A**: Has CMTS network access, can SSH to Server B and Webserver
- **Server B**: Has modem network access, **cannot** initiate outbound connections (firewall)

## Constraint

Server B cannot connect to Server A or Webserver due to firewall.  
Only Server A can initiate SSH connections outward.

## Solution: Reverse Remote Port Forward

Server A SSHes into Server B and creates a reverse tunnel that exposes the PyPNM API on Server B's localhost:

```
Webserver:8000 (PyPNM API)
      ▲
      │ reverse tunnel (initiated by Server A)
      │
Server A ──SSH -R 18000:localhost:8000──▶ Server B
                                               │
                                          Agent B listens on
                                          ws://localhost:18000
                                               │
                                          SNMP → Modems (LAN only)
```

## Server A: Create the reverse tunnel

Run on Server A (persistent, one-time setup):

```bash
# Simple (manual)
ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -R 18000:localhost:8000 user@server-b

# With autossh (auto-reconnect on failure, recommended)
autossh -M 0 -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 18000:localhost:8000 user@server-b
```

### As a systemd service on Server A (`/etc/systemd/system/pypnm-tunnel-b.service`)

```ini
[Unit]
Description=PyPNM reverse tunnel to Server B
After=network.target
Wants=network-online.target

[Service]
User=pypnm
ExecStart=autossh -M 0 -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=no \
    -R 18000:localhost:8000 user@server-b
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now pypnm-tunnel-b
```

## Server B: Agent B config (`agent_config.json`)

```json
{
  "agent_id": "agent-b-modemside",
  "api_url": "ws://localhost:18000/ws/agent",
  "auth_token": "your-token-here",
  "log_level": "INFO"
}
```

Agent B connects to `localhost:18000` which tunnels through Server A back to the Webserver API.

## Server A: Agent A config (`agent_config.json`)

```json
{
  "agent_id": "agent-a-cmtsside",
  "api_url": "ws://webserver:8000/ws/agent",
  "auth_token": "your-token-here",
  "log_level": "INFO"
}
```

Agent A connects directly (it can reach the webserver).

## Requirements

- Server A needs SSH key access to Server B (no password)
- Server B's `sshd_config`: default settings are fine (`GatewayPorts no`)
  — Agent B only needs `localhost:18000`, not external access
- `autossh` installed on Server A (`apt install autossh`)

## Agent assignment in PyPNM GUI/API

Currently the API routes tasks to the first available alive agent.  
When both agents are connected, CMTS walks should go to `agent-a-cmtsside`  
and modem walks to `agent-b-modemside`.  
This per-network agent assignment can be configured in the CMTS config — to be implemented.
