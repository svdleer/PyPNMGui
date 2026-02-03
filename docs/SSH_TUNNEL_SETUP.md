# PyPNM Remote Agent - SSH-Based Architecture

## Network Overview

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                      │
│   PYPNM SERVER HOST (Docker/Kubernetes)                                              │
│   ═════════════════════════════════════                                              │
│   ┌─────────────┐         HTTP           ┌─────────────────────────────────────┐     │
│   │   Browser   │───────────────────────►│  PyPNM (FastAPI + WebSocket)       │     │
│   └─────────────┘        /docs           │  - PNM dashboards & analysis        │     │
│                                          │  - Agent endpoint: /api/agents/ws   │     │
│                                          │  - Port 8080 (default)              │     │
│                                          │  docker-compose up -d               │     │
│                                          └──────────────────▲──────────────────┘     │
│                                                             │                        │
│ ════════════════════════════════════════════════════════════│════════════════════════│
│                                                             │                        │
│   JUMP SERVER (runs as normal user)                         │ SSH Tunnel             │
│   ═════════════════════════════════                         │ (WebSocket inside)     │
│                                                             │                        │
│   ┌─────────────────────────────────────────────────────────┴──────────────────────┐ │
│   │                                                                                │ │
│   │   PyPNM Remote Agent  (~/.pypnm-agent/)                                        │ │
│   │   ├── run_background.sh start/stop/status                                      │ │
│   │   ├── agent_config.json                                                        │ │
│   │   └── logs/agent.log                                                           │ │
│   │                                                                                │ │
│   │   SSH Keys (~/.ssh/):                                                          │ │
│   │   ┌────────────────────────────────────────────────────────────────────────┐   │ │
│   │   │  id_pypnm_server ──► PyPNM Server (WebSocket tunnel)                   │   │ │
│   │   │  id_cm_proxy     ──► CM Proxy     (SNMP commands to modems)            │   │ │
│   │   │  id_cmts         ──► CMTS         (CLI commands via SSH)               │   │ │
│   │   │  id_tftp         ──► TFTP Server  (PNM file retrieval)                 │   │ │
│   │   └────────────────────────────────────────────────────────────────────────┘   │ │
│   │                                                                                │ │
│   └───────┬───────────────────┬───────────────────┬───────────────────┬────────────┘ │
│           │                   │                   │                   │              │
│           │ SSH               │ SSH               │ SSH/SNMP          │ SSH          │
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

## Quick Start

### 1. PyPNM Server (Docker)

The main PyPNM server handles the agent WebSocket connections. With remote agent
integration, add these files to your PyPNM installation:

```bash
# Copy integration files to PyPNM
cp -r pypnm_integration/transport /path/to/PyPNM/src/pypnm/
cp pypnm_integration/api/agent_router.py /path/to/PyPNM/src/pypnm/api/routers/

# Set agent token
export PYPNM_AGENT_TOKEN="your-secure-token"

# Start PyPNM
pypnm  # or docker-compose up -d
```

### 2. Agent (Jump Server)

```bash
cd agent
./install.sh

# Setup SSH keys and config
nano ~/.pypnm-agent/agent_config.json

# Start
~/.pypnm-agent/run_background.sh start
```

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                     │
│  EXAMPLE: User requests modem info for 10.1.2.3                                     │
│                                                                                     │
│  ┌──────────┐      ┌────────────┐      ┌─────────────┐      ┌──────────┐            │
│  │ Browser  │      │ GUI Server │      │   Agent     │      │ CM Proxy │            │
│  └────┬─────┘      └─────┬──────┘      └──────┬──────┘      └────┬─────┘            │
│       │                  │                    │                  │                  │
│       │  HTTP POST       │                    │                  │                  │
│       │  /api/modem/info │                    │                  │                  │
│       │─────────────────►│                    │                  │                  │
│       │                  │                    │                  │                  │
│       │                  │  WebSocket (via    │                  │                  │
│       │                  │  SSH tunnel)       │                  │                  │
│       │                  │───────────────────►│                  │                  │
│       │                  │  {cmd: snmp_get,   │                  │                  │
│       │                  │   target: 10.1.2.3}│                  │                  │
│       │                  │                    │                  │                  │
│       │                  │                    │  SSH             │                  │
│       │                  │                    │─────────────────►│                  │
│       │                  │                    │  snmpget -v2c    │                  │
│       │                  │                    │  -c private      │                  │
│       │                  │                    │  10.1.2.3 oid    │   SNMP           │
│       │                  │                    │                  │─────────►┌───────┐
│       │                  │                    │                  │          │ Modem │
│       │                  │                    │                  │◄─────────│10.1.2.3
│       │                  │                    │◄─────────────────│  result  └───────┘
│       │                  │                    │  snmp result     │                  │
│       │                  │◄───────────────────│                  │                  │
│       │                  │  {result: ...}     │                  │                  │
│       │◄─────────────────│                    │                  │                  │
│       │  JSON response   │                    │                  │                  │
│       │                  │                    │                  │                  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## SSH Keys Required

| Target | Key File | Purpose |
|--------|----------|---------|
| GUI Server | `~/.ssh/id_gui_server` | WebSocket tunnel for control |
| CM Proxy | `~/.ssh/id_cm_proxy` | SNMP commands to reach modems |
| CMTS | `~/.ssh/id_cmts` | Direct CMTS commands |
| TFTP Server | `~/.ssh/id_tftp` | Retrieve PNM data files |

## Installation (Normal User)

```bash
cd /path/to/PyPNMGui/agent
./install.sh
```

This installs to `~/.pypnm-agent/` with:
- Python virtual environment
- Agent scripts
- systemd user service

## Generate SSH Keys

```bash
# Create keys (one per target, no passphrase for automation)
ssh-keygen -t ed25519 -f ~/.ssh/id_gui_server -N '' -C "pypnm-gui"
ssh-keygen -t ed25519 -f ~/.ssh/id_cm_proxy -N '' -C "pypnm-cm-proxy"  
ssh-keygen -t ed25519 -f ~/.ssh/id_cmts -N '' -C "pypnm-cmts"
ssh-keygen -t ed25519 -f ~/.ssh/id_tftp -N '' -C "pypnm-tftp"
```

## Deploy Keys to Target Servers

```bash
# GUI Server (for WebSocket tunnel)
ssh-copy-id -i ~/.ssh/id_gui_server.pub user@gui-server.example.com

# CM Proxy (for SNMP to modems)
ssh-copy-id -i ~/.ssh/id_cm_proxy.pub user@cm-proxy.internal

# CMTS (for direct commands)
ssh-copy-id -i ~/.ssh/id_cmts.pub admin@cmts.internal

# TFTP Server (for PNM files)
ssh-copy-id -i ~/.ssh/id_tftp.pub user@tftp.internal
```

## Configuration

Edit `~/.pypnm-agent/agent_config.json`:

```json
{
    "agent_id": "jump-server-01",
    
    "gui_server": {
        "url": "ws://localhost:5050/agent",
        "auth_token": "generate-with-openssl-rand-hex-32",
        "reconnect_interval": 5
    },
    
    "gui_ssh_tunnel": {
        "_comment": "SSH tunnel to GUI Server for WebSocket",
        "enabled": true,
        "ssh_host": "gui-server.example.com",
        "ssh_port": 22,
        "ssh_user": "pnm-agent",
        "ssh_key_file": "~/.ssh/id_gui_server",
        "local_port": 5050,
        "remote_port": 5050
    },
    
    "cmts_access": {
        "_comment": "CMTS - direct SNMP and/or SSH",
        "snmp_direct": true,
        "ssh_enabled": true,
        "ssh_user": "admin",
        "ssh_key_file": "~/.ssh/id_cmts"
    },
    
    "cm_proxy": {
        "_comment": "Server with connectivity to Cable Modems",
        "host": "cm-proxy.internal",
        "port": 22,
        "username": "pnm-agent",
        "key_file": "~/.ssh/id_cm_proxy"
    },
    
    "tftp_server": {
        "_comment": "TFTP/FTP server for PNM files (via SSH)",
        "host": "tftp.internal",
        "port": 22,
        "username": "pnm-agent",
        "key_file": "~/.ssh/id_tftp",
        "tftp_path": "/tftpboot"
    }
}
```

## Test Connections

```bash
# Test each SSH connection
ssh -i ~/.ssh/id_gui_server user@gui-server 'echo "GUI: OK"'
ssh -i ~/.ssh/id_cm_proxy user@cm-proxy 'which snmpget && echo "CM Proxy: OK"'
ssh -i ~/.ssh/id_cmts admin@cmts 'show version | head -1'
ssh -i ~/.ssh/id_tftp user@tftp 'ls /tftpboot | head -5'
```

## Run Agent

### Manual (for testing)
```bash
~/.pypnm-agent/start.sh -v
```

### As systemd user service
```bash
systemctl --user daemon-reload
systemctl --user enable pypnm-agent
systemctl --user start pypnm-agent
systemctl --user status pypnm-agent

# View logs
journalctl --user -u pypnm-agent -f
```

## How It Works

### 1. WebSocket via SSH Tunnel

Agent creates SSH tunnel to GUI Server, then connects WebSocket through it:

```
Agent → SSH tunnel (local:5050 → GUI:5050) → WebSocket connection
```

### 2. SNMP to Modems via CM Proxy

Agent SSHs to CM Proxy server and executes SNMP commands there:

```
Agent → SSH → CM Proxy → snmpget → Modem
```

Example command executed on CM Proxy:
```bash
snmpget -v2c -c private 10.1.2.3 1.3.6.1.2.1.1.1.0
```

### 3. CMTS Commands via SSH

Agent SSHs directly to CMTS for CLI commands:

```
Agent → SSH → CMTS → execute command → return output
```

### 4. PNM Files via TFTP SSH

Agent SSHs to TFTP server and reads files directly:

```
Agent → SSH → TFTP Server → cat /tftpboot/pnm/file.bin → return content
```

## Data Flow Example

```
User clicks "Get Modem Info" in browser
         │
         ▼
Browser → HTTP POST → GUI Server
         │
         ▼
GUI Server → WebSocket message → SSH Tunnel → Agent
         │
         ▼
Agent → SSH → CM Proxy: "snmpget -v2c -c private 10.1.2.3 sysDescr.0"
         │
         ▼
CM Proxy → SNMP UDP → Modem 10.1.2.3
         │
         ▼
Response: Modem → CM Proxy → SSH → Agent → WebSocket → GUI → Browser
```

## Security Best Practices

1. **Separate keys per target** - Easier to revoke if compromised
2. **No passphrase for automation** - But secure the key files
3. **Key file permissions**: `chmod 600 ~/.ssh/id_*`
4. **Consider command restrictions** on target servers:
   ```bash
   # In ~/.ssh/authorized_keys on CM Proxy:
   command="/usr/bin/snmpget $SSH_ORIGINAL_COMMAND",no-port-forwarding ssh-ed25519 AAA... pypnm
   ```
5. **Generate strong auth token**:
   ```bash
   openssl rand -hex 32
   ```

## Troubleshooting

### Agent won't start
```bash
# Check config syntax
python3 -c "import json; json.load(open('agent_config.json'))"

# Run verbose
~/.pypnm-agent/start.sh -v
```

### SSH connection fails
```bash
# Test with verbose
ssh -v -i ~/.ssh/id_cm_proxy user@cm-proxy 'echo test'

# Check key permissions
ls -la ~/.ssh/id_*
```

### WebSocket tunnel not working
```bash
# Check if local port is listening
ss -tlnp | grep 5050

# Test SSH tunnel manually
ssh -N -L 5050:localhost:5050 -i ~/.ssh/id_gui_server user@gui-server
```

### View service logs
```bash
journalctl --user -u pypnm-agent --since "10 minutes ago"
```
