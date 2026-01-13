# PyPNM Web GUI - Network Architecture

## Overview

This document describes the network architecture for deploying PyPNM Web GUI in environments with restricted network access.

## Network Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│    ZONE A: User Network                                                     │
│    ┌──────────────────┐                                                     │
│    │   User Browser   │                                                     │
│    └────────┬─────────┘                                                     │
│             │ HTTPS                                                         │
│             ▼                                                               │
│    ┌──────────────────┐                                                     │
│    │  GUI/App Server  │  ◄── Flask + WebSocket Server                       │
│    │  (PyPNM Web GUI) │      Cannot access Jump Server                      │
│    └────────▲─────────┘                                                     │
│             │                                                               │
├─────────────┼───────────────────────────────────────────────────────────────┤
│             │ WebSocket (Reverse Connection)                                │
│             │ Jump Server CONNECTS TO GUI Server                            │
│             │                                                               │
│    ZONE B: Management Network                                               │
│    ┌────────┴─────────┐                                                     │
│    │   Jump Server    │  ◄── PyPNM Agent (connects OUT to GUI)              │
│    │   (Agent)        │      Can access: CMTS, TFTP, SSH Proxy              │
│    └────────┬─────────┘                                                     │
│             │                                                               │
│    ┌────────┼────────────────────────┐                                      │
│    │        │                        │                                      │
│    ▼        ▼                        ▼                                      │
│ ┌──────┐ ┌──────────┐          ┌───────────┐                                │
│ │ CMTS │ │TFTP/FTP  │          │SSH Proxy  │                                │
│ │      │ │ Server   │          │ Server    │                                │
│ └──────┘ └──────────┘          └─────┬─────┘                                │
│                                      │ SSH                                  │
├──────────────────────────────────────┼──────────────────────────────────────┤
│                                      │                                      │
│    ZONE C: CPE Network               ▼                                      │
│                              ┌───────────────┐                              │
│                              │ Cable Modems  │                              │
│                              │ (SNMP Target) │                              │
│                              └───────────────┘                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. GUI/Application Server (Zone A)
- **Role**: Serves web interface, manages WebSocket connections from agents
- **Technology**: Flask + Flask-SocketIO
- **Network**: Can be accessed by users, cannot initiate connections to Zone B

### 2. Jump Server Agent (Zone B)
- **Role**: Executes SNMP/SSH commands on behalf of GUI Server
- **Technology**: Python agent with WebSocket client
- **Network**: 
  - Connects OUT to GUI Server (reverse tunnel)
  - Can access CMTS systems directly
  - Can SSH to SNMP Proxy Server
  - Can access TFTP/FTP servers

### 3. SSH Proxy Server (Zone B)
- **Role**: Bridge to reach cable modems
- **Technology**: SSH server with SNMP tools installed
- **Network**: Can reach cable modems in Zone C

### 4. SNMP Proxy Options

#### Option A: SSH Command Execution
Agent SSHs to proxy server and executes SNMP commands there.

#### Option B: SSH Port Forwarding
Agent creates SSH tunnel to proxy server, forwarding SNMP port (161/UDP).

#### Option C: SOCKS Proxy via SSH
Agent creates SOCKS proxy via SSH, routes SNMP through it.

## Data Flow

### SNMP Request Flow (e.g., Get Modem Info)

```
1. User clicks "Get Info" in browser
   │
   ▼
2. Browser sends HTTP POST to /api/modem/<mac>/system-info
   │
   ▼
3. GUI Server receives request, creates task
   │
   ▼
4. GUI Server sends task via WebSocket to connected Agent
   │
   ▼
5. Agent on Jump Server receives task
   │
   ▼
6. Agent SSHs to SNMP Proxy Server
   │
   ▼
7. Agent executes: ssh proxy "snmpget -v2c -c private <modem_ip> sysDescr.0"
   │
   ▼
8. SNMP Proxy sends SNMP request to Cable Modem
   │
   ▼
9. Response flows back through SSH → Agent → WebSocket → GUI → Browser
```

### PNM File Retrieval Flow

```
1. User requests PNM file
   │
   ▼
2. GUI Server sends file request to Agent
   │
   ▼
3. Agent connects to TFTP/FTP server
   │
   ▼
4. Agent retrieves file
   │
   ▼
5. Agent sends file content via WebSocket to GUI Server
   │
   ▼
6. GUI Server stores/serves file to user
```

## Configuration

### GUI Server Configuration (config.py)

```python
# Agent WebSocket settings
AGENT_WEBSOCKET_PORT = 5051
AGENT_AUTH_TOKEN = "secure-token-here"

# Expected agents
REGISTERED_AGENTS = {
    "jump-server-01": {
        "name": "Primary Jump Server",
        "capabilities": ["snmp", "ssh", "tftp"]
    }
}
```

### Jump Server Agent Configuration (agent_config.json)

```json
{
    "agent_id": "jump-server-01",
    "gui_server": {
        "url": "ws://gui-server.example.com:5051",
        "auth_token": "secure-token-here",
        "reconnect_interval": 5
    },
    "ssh_proxy": {
        "host": "snmp-proxy.internal",
        "port": 22,
        "username": "pnm-agent",
        "key_file": "/home/agent/.ssh/id_rsa"
    },
    "tftp_server": {
        "host": "tftp.internal",
        "port": 69
    },
    "cmts_access": {
        "direct": true
    }
}
```

## Security Considerations

1. **WebSocket Authentication**: Agent must authenticate with token
2. **SSH Key Management**: Use SSH keys, not passwords
3. **Command Whitelisting**: Agent only executes approved commands
4. **Rate Limiting**: Prevent command flooding
5. **Audit Logging**: Log all commands executed by agent

## Deployment

### On GUI Server
```bash
# Install dependencies
pip install flask-socketio python-socketio

# Start server with WebSocket support
python run.py
```

### On Jump Server
```bash
# Install agent
pip install websocket-client paramiko

# Configure agent
cp agent_config.example.json agent_config.json
# Edit configuration...

# Start agent (as service)
python agent.py
```

## Fallback Options

If WebSocket is blocked:

### Option 1: HTTP Long Polling
Agent polls GUI server every N seconds for pending tasks.

### Option 2: Reverse SSH Tunnel
```bash
# On Jump Server, create reverse tunnel to GUI Server
ssh -R 5051:localhost:5051 gui-server.example.com
```

### Option 3: Message Queue
Use RabbitMQ/Redis accessible from both servers.
