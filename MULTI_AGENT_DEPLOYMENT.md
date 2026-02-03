# Multi-Agent Deployment Guide for Load Distribution

## Overview

PyPNM's agent architecture already supports multiple agents! The agent manager automatically:
- Routes tasks to agents with required capabilities
- Tracks agent health and availability
- Authenticates each agent independently

## Current Agent Capabilities

Each agent advertises these capabilities on connection:

### Core SNMP Operations
- `snmp_get`, `snmp_walk`, `snmp_set`, `snmp_bulk_get`

### Cable Modem Functions (cm_reachable)
- `cm_reachable` - Direct modem access
- `cm_proxy` - Proxy modem access
- `pnm_channel_info` - Modem channel statistics
- `pnm_event_log` - Modem event logs
- `pnm_ofdm_channels`, `pnm_ofdm_capture`, `pnm_ofdm_rxmer`
- `pnm_spectrum` - Spectrum analyzer
- `pnm_set_tftp` - TFTP configuration

### CMTS Functions (cmts_reachable)
- `cmts_reachable` - Direct CMTS access
- `cmts_snmp_direct` - CMTS SNMP operations
- `cmts_get_modems` - Get modems from CMTS
- `cmts_get_modem_info` - Get detailed modem info
- `cmts_command` - SSH CLI commands (if SSH enabled)
- `enrich_modems` - Enrich modem data with CMTS info
- `pnm_utsc_configure`, `pnm_utsc_start`, `pnm_utsc_stop`
- `pnm_us_rxmer_start`, `pnm_us_rxmer_status`, `pnm_us_rxmer_data`

## Scaling Strategies

### 1. Geographic Distribution
Deploy agents in different network segments:

```yaml
# Agent 1: Access network (modems)
agent-access-1:
  environment:
    - AGENT_ID=agent-access-1
    - CM_ENABLED=true          # Can reach modems
    - CMTS_ENABLED=false       # Cannot reach CMTS
    
# Agent 2: Core network (CMTS)
agent-core-1:
  environment:
    - AGENT_ID=agent-core-1
    - CM_ENABLED=false         # Cannot reach modems
    - CMTS_ENABLED=true        # Can reach CMTS
    - CMTS_SSH_ENABLED=true    # SSH to CMTS
```

### 2. Load Distribution by Function
Dedicate agents to specific operations:

```yaml
# Agent A: Spectrum analyzer (CPU intensive)
agent-spectrum-1:
  environment:
    - AGENT_ID=agent-spectrum-1
    - CM_ENABLED=true
    
# Agent B: Channel stats (frequent polling)
agent-stats-1:
  environment:
    - AGENT_ID=agent-stats-1
    - CM_ENABLED=true
    
# Agent C: CMTS operations
agent-cmts-1:
  environment:
    - AGENT_ID=agent-cmts-1
    - CMTS_ENABLED=true
```

### 3. Redundancy
Deploy multiple agents with identical capabilities:

```yaml
agent-1:
  environment:
    - AGENT_ID=agent-primary
    - CM_ENABLED=true
    - CMTS_ENABLED=true
    
agent-2:
  environment:
    - AGENT_ID=agent-backup
    - CM_ENABLED=true
    - CMTS_ENABLED=true
```

## Deployment Example: 3 Agents

Add to your docker-compose.lab.yml:

```yaml
services:
  # Agent 1: Modem operations (Access Network)
  agent-modem-1:
    build:
      context: /home/svdleer/docker/pyPNMAgent
      dockerfile: docker/Dockerfile
    container_name: pypnm-agent-modem-1
    network_mode: host
    environment:
      - AGENT_ID=agent-modem-1
      - SERVER_URL=ws://localhost:8000/api/agents/ws
      - CM_ENABLED=true
      - CMTS_ENABLED=false
    volumes:
      - agent-modem-1-config:/app/config
      - /var/lib/tftpboot:/tftpboot:ro
    restart: unless-stopped
    depends_on:
      - pypnm-api

  # Agent 2: CMTS operations (Core Network)
  agent-cmts-1:
    build:
      context: /home/svdleer/docker/pyPNMAgent
      dockerfile: docker/Dockerfile
    container_name: pypnm-agent-cmts-1
    network_mode: host
    environment:
      - AGENT_ID=agent-cmts-1
      - SERVER_URL=ws://localhost:8000/api/agents/ws
      - CM_ENABLED=false
      - CMTS_ENABLED=true
      - CMTS_SSH_ENABLED=true
      - CMTS_IP=10.10.10.1
      - CMTS_USER=admin
      - CMTS_PASSWORD=password
    volumes:
      - agent-cmts-1-config:/app/config
    restart: unless-stopped
    depends_on:
      - pypnm-api

  # Agent 3: Backup/Load balancer
  agent-backup-1:
    build:
      context: /home/svdleer/docker/pyPNMAgent
      dockerfile: docker/Dockerfile
    container_name: pypnm-agent-backup-1
    network_mode: host
    environment:
      - AGENT_ID=agent-backup-1
      - SERVER_URL=ws://localhost:8000/api/agents/ws
      - CM_ENABLED=true
      - CMTS_ENABLED=true
    volumes:
      - agent-backup-1-config:/app/config
      - /var/lib/tftpboot:/tftpboot:ro
    restart: unless-stopped
    depends_on:
      - pypnm-api

volumes:
  agent-modem-1-config:
  agent-cmts-1-config:
  agent-backup-1-config:
```

## Agent Selection Logic

The agent manager uses **first-match** selection:

```python
# PyPNM automatically selects agent with required capability
agent = agent_manager.get_agent_for_capability('snmp_get')
```

### Future Enhancement: Smart Selection

You can enhance the agent manager to implement:

1. **Round-robin load balancing**:
```python
def get_agent_for_capability_rr(self, capability: str) -> Optional[ConnectedAgent]:
    """Get agent using round-robin."""
    candidates = [a for a in self.agents.values() 
                  if a.authenticated and capability in a.capabilities]
    if not candidates:
        return None
    # Track selection index per capability
    idx = self._selection_index.get(capability, 0)
    agent = candidates[idx % len(candidates)]
    self._selection_index[capability] = idx + 1
    return agent
```

2. **Least-busy selection**:
```python
def get_agent_for_capability_lb(self, capability: str) -> Optional[ConnectedAgent]:
    """Get least busy agent."""
    candidates = [a for a in self.agents.values() 
                  if a.authenticated and capability in a.capabilities]
    if not candidates:
        return None
    # Return agent with fewest active tasks
    return min(candidates, key=lambda a: a.active_tasks)
```

3. **Geographic affinity**:
```python
def get_agent_for_modem(self, modem_ip: str) -> Optional[ConnectedAgent]:
    """Get agent based on network proximity."""
    # Route to agent in same subnet
    for agent in self.agents.values():
        if agent.authenticated and 'cm_reachable' in agent.capabilities:
            if is_same_subnet(modem_ip, agent.network_segment):
                return agent
    # Fallback to any cm_reachable agent
    return self.get_agent_for_capability('cm_reachable')
```

## Monitoring Multiple Agents

Check connected agents via PyPNM API:

```bash
curl http://localhost:8000/api/agents
```

Response:
```json
{
  "agents": [
    {
      "agent_id": "agent-modem-1",
      "capabilities": ["snmp_get", "cm_reachable", "pnm_spectrum"],
      "authenticated": true,
      "last_seen": 1738575600
    },
    {
      "agent_id": "agent-cmts-1",
      "capabilities": ["snmp_get", "cmts_reachable", "cmts_command"],
      "authenticated": true,
      "last_seen": 1738575598
    }
  ]
}
```

## Network Architecture with Multiple Agents

```
                     ┌──────────────┐
                     │   PyPNM API  │
                     │  Port 8000   │
                     └───────┬──────┘
                             │ WebSocket
          ┌──────────────────┼──────────────────┐
          │                  │                  │
    ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
    │  Agent 1  │     │  Agent 2  │     │  Agent 3  │
    │  Modem    │     │   CMTS    │     │  Backup   │
    └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
          │                 │                   │
    ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
    │  Modems   │     │   CMTS    │     │ Both/Any  │
    │ 10.x.x.x  │     │ 172.x.x.x │     │           │
    └───────────┘     └───────────┘     └───────────┘
```

## Benefits of Multi-Agent Architecture

✅ **Load Distribution**: Spread SNMP operations across multiple agents
✅ **Network Segmentation**: Agents in different VLANs/subnets
✅ **Redundancy**: Automatic failover if agent disconnects
✅ **Specialization**: Dedicate agents to specific tasks
✅ **Scalability**: Add agents as load increases
✅ **Geographic Distribution**: Agents near target devices reduce latency

## Quick Start: Add 2 More Agents

1. Copy existing agent config:
```bash
cp agent_config.json agent_modem_config.json
cp agent_config.json agent_cmts_config.json
```

2. Update agent IDs:
```json
// agent_modem_config.json
{
  "agent_id": "agent-modem-1",
  "cm_enabled": true,
  "cmts_enabled": false
}

// agent_cmts_config.json
{
  "agent_id": "agent-cmts-1", 
  "cm_enabled": false,
  "cmts_enabled": true
}
```

3. Start agents:
```bash
python agent.py --config agent_modem_config.json &
python agent.py --config agent_cmts_config.json &
```

4. Verify:
```bash
curl http://localhost:8000/api/agents | jq
```

You should see 3 agents connected!

## Next Steps

- Implement round-robin load balancing in agent manager
- Add agent health metrics (response time, success rate)
- Create agent dashboard in GUI
- Add agent affinity rules (route specific IPs to specific agents)
- Implement agent priority/weight for selection
