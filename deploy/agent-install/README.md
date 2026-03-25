# PyPNM Multi-Agent Installation Package

This package contains installation scripts and configuration for deploying PyPNM agents in a multi-agent setup.

## Architecture

```
┌────────────────────────┐
│ Modem Agent            │
│ hop-access1.ext        │
│                        │
│ SSH Tunnel ────────────┼─────┐
└────────────────────────┘     │
                               │
                               ▼
                      ┌─────────────────────┐
                      │ CMTS Agent          │
                      │ appdb-sh.oss.local  │
                      │                     │
                      │ - PyPNM API         │
                      │ - AppDB access      │
                      │ - CMTS access       │
                      └─────────────────────┘
```

## Package Contents

- `config.env` - Main configuration file
- `install-cmts-agent.sh` - Installation script for CMTS agent
- `install-modem-agent.sh` - Installation script for modem agent
- `autossh-tunnel-appdb.sh` - AutoSSH tunnel script for modem agent
- `README.md` - This file

## Prerequisites

- Root or sudo access on both servers
- SSH key-based authentication set up between modem agent and CMTS server
- Python 3.7+ installed
- autossh installed (will be installed automatically if missing)

## Configuration

Edit `config.env` before installation to customize:

- Agent IDs
- API URLs
- Authentication tokens
- SNMP communities
- TFTP settings

## Installation

### 1. CMTS Agent (appdb-sh.oss.local)

```bash
# Copy package to server
scp -r agent-install/ appdb-sh.oss.local:/tmp/

# SSH to server
ssh appdb-sh.oss.local

# Run installation
cd /tmp/agent-install
sudo bash install-cmts-agent.sh
```

### 2. Modem Agent (hop-access1.ext.oss.local)

```bash
# Copy package to server
scp -r agent-install/ hop-access1.ext.oss.local:/tmp/

# SSH to server
ssh hop-access1.ext.oss.local

# Run installation
cd /tmp/agent-install
sudo bash install-modem-agent.sh
```

## Post-Installation

### Start Services

**On CMTS Agent:**
```bash
sudo systemctl start pypnm-agent
sudo systemctl enable pypnm-agent
```

**On Modem Agent:**
```bash
# Start tunnel first
sudo systemctl start pypnm-tunnel
sudo systemctl enable pypnm-tunnel

# Then start agent
sudo systemctl start pypnm-agent
sudo systemctl enable pypnm-agent
```

### Verify Status

```bash
# Check service status
sudo systemctl status pypnm-agent
sudo systemctl status pypnm-tunnel  # modem agent only

# View logs
sudo journalctl -u pypnm-agent -f
sudo journalctl -u pypnm-tunnel -f  # modem agent only

# Or check log files
sudo tail -f /opt/pypnm-agent/pyPNMAgent/logs/agent.log
```

### Test Connectivity

**On Modem Agent:**
```bash
# Test tunnel
cd /opt/pypnm-agent/pyPNMAgent
./autossh-tunnel-appdb.sh status
./autossh-tunnel-appdb.sh test

# Test AppDB access via tunnel
curl -k https://localhost:8443/isw/api
```

## Troubleshooting

### Tunnel Not Working

```bash
# Check tunnel logs
cat ~/.autossh-appdb.log

# Restart tunnel
sudo systemctl restart pypnm-tunnel

# Manual test
ssh -L 8443:localhost:443 appdb-sh.oss.local
```

### Agent Not Connecting

1. Check PyPNM API is running:
   ```bash
   curl http://appdb-sh.oss.local:8000/health
   ```

2. Check authentication token matches

3. Check firewall rules

### View Detailed Logs

```bash
# System logs
sudo journalctl -u pypnm-agent --since "1 hour ago"
sudo journalctl -u pypnm-tunnel --since "1 hour ago"

# Application logs
sudo tail -f /opt/pypnm-agent/pyPNMAgent/logs/agent.log
sudo tail -f /opt/pypnm-agent/pyPNMAgent/logs/agent.error.log
```

## Manual Operations

### Restart Agent

```bash
sudo systemctl restart pypnm-agent
```

### Restart Tunnel (Modem Agent)

```bash
sudo systemctl restart pypnm-tunnel
```

### Stop Services

```bash
sudo systemctl stop pypnm-agent
sudo systemctl stop pypnm-tunnel  # modem agent only
```

## Configuration Files

- Main config: `/opt/pypnm-agent/pyPNMAgent/agent_config.json`
- Tunnel script: `/opt/pypnm-agent/pyPNMAgent/autossh-tunnel-appdb.sh`
- Systemd services: `/etc/systemd/system/pypnm-*.service`

## Support

For issues or questions, check:
- Application logs in `/opt/pypnm-agent/pyPNMAgent/logs/`
- System logs via `journalctl -u pypnm-agent`
- Tunnel status via `./autossh-tunnel-appdb.sh status`
