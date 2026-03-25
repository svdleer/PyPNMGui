# PyPNM Proxy/Agent Architecture

## The Problem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ┌─────────────┐                           ┌─────────────┐                 │
│   │   GUI       │ ──────── ╳ ──────────────►│   Jump      │                 │
│   │   Server    │   CANNOT CONNECT          │   Server    │                 │
│   └─────────────┘                           └──────┬──────┘                 │
│         ▲                                          │                        │
│         │                                          │ CAN CONNECT            │
│         │ CAN CONNECT                              ▼                        │
│         │                                   ┌─────────────┐                 │
│         └───────────────────────────────────│   SSH       │                 │
│                                             │   Proxy     │                 │
│                                             └──────┬──────┘                 │
│                                                    │                        │
│                                                    ▼                        │
│                                             ┌─────────────┐                 │
│                                             │   Cable     │                 │
│                                             │   Modems    │                 │
│                                             └─────────────┘                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## The Solution: Reverse WebSocket Connection

Since the **Jump Server CAN connect to the GUI Server**, we flip the connection:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ┌─────────────┐     WebSocket      ┌─────────────┐                        │
│   │   GUI       │◄───────────────────│   Jump      │                        │
│   │   Server    │    (Agent          │   Server    │                        │
│   │   (Flask +  │     connects       │   (Agent)   │                        │
│   │   SocketIO) │     TO server)     └──────┬──────┘                        │
│   └─────────────┘                           │                               │
│                                             │ SSH                           │
│                                             ▼                               │
│                                      ┌─────────────┐                        │
│                                      │   SSH       │                        │
│                                      │   Proxy     │                        │
│                                      └──────┬──────┘                        │
│                                             │ SNMP                          │
│                                             ▼                               │
│                                      ┌─────────────┐                        │
│                                      │   Cable     │                        │
│                                      │   Modems    │                        │
│                                      └─────────────┘                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. GUI Server (Flask + SocketIO)
- Serves web interface
- Accepts WebSocket connections from agents
- Sends SNMP commands through agents
- Receives results and displays to users

### 2. Jump Server Agent (Python)
- Connects OUT to GUI Server via WebSocket
- Maintains persistent connection
- Executes SNMP commands (locally or via SSH proxy)
- Returns results through WebSocket

### 3. SSH Proxy (Optional)
- Reached by agent via SSH
- Has direct network access to cable modems
- Agent executes SNMP commands there

## Data Flow Example

```
User clicks "Get System Info"
         │
         ▼
Browser ──► GUI Server ──► WebSocket ──► Agent ──► SSH ──► SNMP ──► Modem
                                                                      │
User sees result                                                      │
         ▲                                                            │
         │                                                            │
Browser ◄── GUI Server ◄── WebSocket ◄── Agent ◄── SSH ◄── SNMP ◄────┘
```

## Quick Start

### On GUI Server:

```bash
# Install dependencies
cd /path/to/PyPNMGui
source venv/bin/activate
pip install -r backend/requirements.txt

# Start with agent support
./start_with_agent.sh

# Or manually:
export ENABLE_AGENT_WEBSOCKET=true
export AGENT_AUTH_TOKEN=your-secure-token
cd backend && python run.py
```

### On Jump Server:

```bash
# Install agent
pip install websocket-client paramiko

# Configure
cd /path/to/agent
cp agent_config.example.json agent_config.json
# Edit agent_config.json with your settings

# Start agent
python agent.py -c agent_config.json

# Or with environment variables:
export PYPNM_GUI_URL=ws://gui-server:5050/agent
export PYPNM_AUTH_TOKEN=your-secure-token
export PYPNM_SSH_PROXY_HOST=ssh-proxy.internal
python agent.py
```

## Configuration

### GUI Server Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_AGENT_WEBSOCKET` | `false` | Enable agent WebSocket support |
| `AGENT_AUTH_TOKEN` | `dev-token` | Token for agent authentication |
| `DATA_MODE` | `mock` | `mock`, `agent`, or `direct` |
| `PORT` | `5050` | HTTP/WebSocket port |

### Agent Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYPNM_GUI_URL` | `ws://localhost:5051` | GUI Server WebSocket URL |
| `PYPNM_AUTH_TOKEN` | `dev-token` | Authentication token |
| `PYPNM_AGENT_ID` | `agent-01` | Unique agent identifier |
| `PYPNM_SSH_PROXY_HOST` | - | SSH proxy hostname |
| `PYPNM_SSH_PROXY_USER` | - | SSH proxy username |
| `PYPNM_SSH_PROXY_KEY` | - | Path to SSH key file |

## Security Considerations

1. **Use strong tokens** - Change default tokens in production
2. **Use TLS** - Put behind nginx with SSL for production
3. **Firewall rules** - Only allow Jump Server IPs to WebSocket port
4. **SSH key authentication** - Never use passwords for SSH proxy
5. **Command whitelisting** - Agent only executes approved SNMP commands

## Alternative: Polling Mode

If WebSocket is blocked, use HTTP polling:

```bash
# On Jump Server
export PYPNM_POLL_MODE=true
export PYPNM_POLL_INTERVAL=5  # seconds
python agent.py
```

Agent polls `GET /api/agent/tasks` and posts results to `POST /api/agent/results`.
